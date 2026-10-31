"""Candidate generation: banyak strategi murah, high recall, lalu filter.

Prinsip: JANGAN minta LLM "carikan klip terbaik" dari seluruh transkrip.
Hasilkan 30-50 kandidat dengan sinyal murah, saring ke ~15, baru LLM menilai.
Lihat docs/PIPELINE.md tahap 4.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .lib import text as T

DEFAULT_MIN_DUR = 20.0
DEFAULT_MAX_DUR = 60.0
DEFAULT_TOP_N = 15


# ---------------------------------------------------------------------------
# Span helper
# ---------------------------------------------------------------------------


def span(atoms: list[dict[str, Any]], i: int, j: int) -> dict[str, Any]:
    """Ambil rentang atom [i, j] inklusif."""
    i = max(0, min(i, len(atoms) - 1))
    j = max(i, min(j, len(atoms) - 1))
    chunk = atoms[i : j + 1]
    text = " ".join(str(a["text"]) for a in chunk).strip()
    start = float(chunk[0]["start"])
    end = float(chunk[-1]["end"])
    return {
        "atom_start": i,
        "atom_end": j,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
        "text": text,
        "words": sum(int(a["words"]) for a in chunk),
        "speaker": chunk[0].get("speaker"),
        "ends_sentence": bool(chunk[-1].get("ends_sentence")),
    }


# ---------------------------------------------------------------------------
# TF-IDF kosinus (tanpa numpy)
# ---------------------------------------------------------------------------


def _tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    n = len(docs) or 1
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))

    vecs: list[dict[str, float]] = []
    for d in docs:
        tf = Counter(d)
        total = sum(tf.values()) or 1
        vec: dict[str, float] = {}
        for term, count in tf.items():
            idf = math.log((n + 1) / (df[term] + 1)) + 1.0
            vec[term] = (count / total) * idf
        vecs.append(vec)
    return vecs


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = a.keys() & b.keys()
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / len(values)
    return m, var ** 0.5


# ---------------------------------------------------------------------------
# Strategi
# ---------------------------------------------------------------------------


def _strategy_sliding(
    atoms: list[dict[str, Any]], min_dur: float, max_dur: float
) -> list[dict[str, Any]]:
    out = []
    n = len(atoms)
    for i in range(n):
        j = i
        while j < n:
            dur = float(atoms[j]["end"]) - float(atoms[i]["start"])
            if dur > max_dur:
                break
            if dur >= min_dur and bool(atoms[j].get("ends_sentence")):
                out.append({**span(atoms, i, j), "strategy": "sliding"})
            j += 1
    return out


def _strategy_qa(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    n = len(atoms)
    for i, atom in enumerate(atoms):
        if not atom.get("is_question"):
            continue
        j = min(n - 1, i + 4)
        out.append({**span(atoms, i, j), "strategy": "qa"})
    return out


def _strategy_payoff(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    n = len(atoms)
    for i, atom in enumerate(atoms):
        text = str(atom["text"])
        if not (T.has_digit(text) or T.has_point_marker(text)):
            continue
        out.append({**span(atoms, max(0, i - 2), min(n - 1, i + 3)), "strategy": "payoff"})
    return out


def _strategy_topic_shift(
    atoms: list[dict[str, Any]], min_dur: float, max_dur: float
) -> list[dict[str, Any]]:
    if len(atoms) < 4:
        return []
    docs = [T.word_tokens(str(a["text"])) for a in atoms]
    vecs = _tfidf(docs)
    sims = [_cosine(vecs[i - 1], vecs[i]) for i in range(1, len(vecs))]
    if not sims:
        return []
    m, s = _mean_std(sims)
    threshold = m - 0.5 * s

    boundaries = [0]
    for k, sim in enumerate(sims, start=1):
        if sim <= threshold:
            boundaries.append(k)
    boundaries.append(len(atoms))

    out = []
    for b in range(len(boundaries) - 1):
        i, j = boundaries[b], boundaries[b + 1] - 1
        if j <= i:
            continue
        dur = float(atoms[j]["end"]) - float(atoms[i]["start"])
        if dur < min_dur:
            j = min(len(atoms) - 1, j + 3)
            dur = float(atoms[j]["end"]) - float(atoms[i]["start"])
        if min_dur <= dur <= max_dur:
            out.append({**span(atoms, i, j), "strategy": "topic_shift"})
    return out


def _strategy_energy(
    atoms: list[dict[str, Any]], rms: list[tuple[float, float]] | None
) -> list[dict[str, Any]]:
    if not rms:
        return []
    levels = []
    for atom in atoms:
        vals = [db for t, db in rms if float(atom["start"]) <= t < float(atom["end"])]
        levels.append(sum(vals) / len(vals) if vals else -60.0)
    m, s = _mean_std(levels)
    if s == 0:
        return []
    n = len(atoms)
    out = []
    for i, level in enumerate(levels):
        if level >= m + 0.5 * s:
            out.append({**span(atoms, max(0, i - 1), min(n - 1, i + 3)), "strategy": "energy"})
    return out


# ---------------------------------------------------------------------------
# Filter + skor murah
# ---------------------------------------------------------------------------


def _hook_latency(c: dict[str, Any], atoms: list[dict[str, Any]]) -> float:
    base = float(c["start"])
    for atom in atoms[int(c["atom_start"]) : int(c["atom_end"]) + 1]:
        text = str(atom["text"])
        if atom.get("is_question") or T.has_digit(text) or T.has_point_marker(text):
            return max(0.0, float(atom["start"]) - base)
    return float(c["duration"])


def _cheap_score(c: dict[str, Any], atoms: list[dict[str, Any]]) -> float:
    dur = float(c["duration"]) or 1.0
    words = int(c["words"])
    wpm = words / (dur / 60.0)
    fillers = T.count_fillers(str(c["text"]))
    filler_ratio = fillers / max(1, words)
    hook = _hook_latency(c, atoms)

    score = 0.0
    score += 25.0 * max(0.0, 1.0 - abs(wpm - 160.0) / 160.0)
    score += 20.0 * max(0.0, 1.0 - filler_ratio / 0.10)
    score += 25.0 * max(0.0, 1.0 - hook / 3.0)
    score += 10.0 * min(T.count_numbers(str(c["text"])) / 3.0, 1.0)
    score += 10.0 if not T.starts_with_hanging_conjunction(str(c["text"])) else 0.0
    score += 10.0 * min(T.type_token_ratio(str(c["text"])) / 0.55, 1.0)
    return round(score, 3)


def _passes(c: dict[str, Any], min_dur: float, max_dur: float) -> bool:
    dur = float(c["duration"])
    if not (min_dur <= dur <= max_dur):
        return False
    words = int(c["words"])
    if words < 30:
        return False
    # minimal ~72 wpm supaya bukan potongan sepi
    if words / (dur / 60.0) < 72:
        return False
    if T.starts_with_hanging_conjunction(str(c["text"])):
        return False
    return True


def generate(
    atoms: list[dict[str, Any]],
    top_n: int = DEFAULT_TOP_N,
    min_dur: float = DEFAULT_MIN_DUR,
    max_dur: float = DEFAULT_MAX_DUR,
    rms: list[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    """Hasilkan kandidat, saring, kembalikan top_n terurut skor murah."""
    if not atoms:
        return []

    raw: list[dict[str, Any]] = []
    raw += _strategy_sliding(atoms, min_dur, max_dur)
    raw += _strategy_qa(atoms)
    raw += _strategy_payoff(atoms)
    raw += _strategy_topic_shift(atoms, min_dur, max_dur)
    raw += _strategy_energy(atoms, rms)

    # dedupe by rentang atom, strategi digabung
    by_range: dict[tuple[int, int], dict[str, Any]] = {}
    for c in raw:
        key = (int(c["atom_start"]), int(c["atom_end"]))
        if key in by_range:
            prev = by_range[key]
            strategies = set(str(prev["strategy"]).split("+"))
            strategies.add(str(c["strategy"]))
            prev["strategy"] = "+".join(sorted(strategies))
        else:
            by_range[key] = dict(c)

    filtered = [c for c in by_range.values() if _passes(c, min_dur, max_dur)]
    if not filtered:
        return []

    for c in filtered:
        c["cheap_score"] = _cheap_score(c, atoms)
    filtered.sort(key=lambda c: (-c["cheap_score"], c["atom_start"]))

    # buang kandidat yang tumpang tindih >60% dengan yang sudah dipilih,
    # supaya 15 kandidat mewakili bagian video yang berbeda
    selected: list[dict[str, Any]] = []
    for c in filtered:
        if len(selected) >= top_n:
            break
        if any(_overlap_ratio(c, s) > 0.60 for s in selected):
            continue
        selected.append(c)

    for i, c in enumerate(selected):
        c["id"] = i
    return selected


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    a0, a1 = float(a["start"]), float(a["end"])
    b0, b1 = float(b["start"]), float(b["end"])
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 0.0
    return inter / union
