"""Segmentasi transkrip menjadi *atom* — unit kalimat yang jadi satuan kandidat klip.

Boundary ditentukan oleh tiga sinyal:
  1. tanda baca akhir kalimat
  2. jeda antar kata >= pause (default 400ms)
  3. discourse marker Indonesia (lihat lib/text.py)

Kenapa atom penting: LLM hanya boleh memilih `atom_id`, bukan timestamp
(docs/DECISIONS.md D-002). Jadi kualitas atom menentukan kualitas seluruh pipeline.
"""

from __future__ import annotations

from typing import Any

from .lib import text as T

DEFAULTS = {
    "min_words": 3,
    "max_words": 70,
    "pause": 0.40,
    "marker_pause": T.MARKER_PAUSE,
}


def _atom(idx: int, idxs: list[int], words: list[dict[str, Any]]) -> dict[str, Any]:
    ws = [words[i] for i in idxs]
    text = " ".join(str(w.get("w", "")).strip() for w in ws).strip()
    return {
        "id": idx,
        "start": round(float(ws[0]["start"]), 3),
        "end": round(float(ws[-1]["end"]), 3),
        "text": text,
        "word_start": idxs[0],
        "word_end": idxs[-1],
        "words": len(idxs),
        "speaker": ws[0].get("speaker"),
        "is_question": T.is_question(text),
        "ends_sentence": T.is_sentence_end(str(ws[-1].get("w", ""))),
        "gap_before": 0.0,
    }


def _is_boundary(words: list[dict[str, Any]], i: int, cfg: dict[str, Any]) -> bool:
    cur = words[i]
    if T.is_sentence_end(str(cur.get("w", ""))):
        return True
    if i + 1 >= len(words):
        return True

    nxt = words[i + 1]
    gap = float(nxt["start"]) - float(cur["end"])

    if gap >= cfg["pause"]:
        return True

    nxt_word = T.clean(str(nxt.get("w", "")))
    if nxt_word in T.STRONG_MARKERS:
        return True
    if nxt_word in T.WEAK_MARKERS and gap >= cfg["marker_pause"]:
        return True
    return False


def _merge_short(atoms: list[dict[str, Any]], min_words: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for atom in atoms:
        if out and atom["words"] < min_words:
            prev = out[-1]
            prev["text"] = f"{prev['text']} {atom['text']}".strip()
            prev["end"] = atom["end"]
            prev["word_end"] = atom["word_end"]
            prev["words"] += atom["words"]
            prev["ends_sentence"] = atom["ends_sentence"]
            prev["is_question"] = T.is_question(prev["text"])
        else:
            out.append(dict(atom))
    return out


def _split_long(
    atom: dict[str, Any], words: list[dict[str, Any]], max_words: int
) -> list[dict[str, Any]]:
    if atom["words"] <= max_words:
        return [atom]

    idxs = list(range(atom["word_start"], atom["word_end"] + 1))
    pieces: list[list[int]] = []
    cur: list[int] = []
    for pos, wi in enumerate(idxs):
        cur.append(wi)
        if len(cur) >= max_words and pos + 1 < len(idxs):
            # potong di jeda terbesar dalam 15 kata terakhir
            best_cut, best_gap = len(cur) - 1, -1.0
            for k in range(max(1, len(cur) - 15), len(cur)):
                gap = float(words[cur[k]]["start"]) - float(words[cur[k - 1]]["end"])
                if gap > best_gap:
                    best_gap, best_cut = gap, k
            pieces.append(cur[:best_cut])
            cur = cur[best_cut:]
    if cur:
        pieces.append(cur)

    out = []
    for piece in pieces:
        if not piece:
            continue
        piece_atom = _atom(0, piece, words)
        piece_atom["ends_sentence"] = T.is_sentence_end(
            str(words[piece[-1]].get("w", ""))
        )
        out.append(piece_atom)
    return out


def build_atoms(words: list[dict[str, Any]], **overrides: Any) -> list[dict[str, Any]]:
    """Bangun atom dari daftar kata ber-timestamp.

    `words` harus punya field: i, w, start, end (speaker opsional).
    """
    if not words:
        return []

    cfg = {**DEFAULTS, **overrides}
    raw: list[dict[str, Any]] = []
    cur: list[int] = []

    for i in range(len(words)):
        cur.append(i)
        if _is_boundary(words, i, cfg):
            raw.append(_atom(0, cur, words))
            cur = []
    if cur:
        raw.append(_atom(0, cur, words))

    merged = _merge_short(raw, int(cfg["min_words"]))

    split: list[dict[str, Any]] = []
    for atom in merged:
        split.extend(_split_long(atom, words, int(cfg["max_words"])))

    for i, atom in enumerate(split):
        atom["id"] = i
        if i == 0:
            atom["gap_before"] = round(float(atom["start"]), 3)
        else:
            atom["gap_before"] = round(
                float(atom["start"]) - float(split[i - 1]["end"]), 3
            )

    return split


def load_atoms(transcript: dict[str, Any], **overrides: Any) -> list[dict[str, Any]]:
    return build_atoms(transcript.get("words", []), **overrides)


def total_words(atoms: list[dict[str, Any]]) -> int:
    return sum(int(a["words"]) for a in atoms)
