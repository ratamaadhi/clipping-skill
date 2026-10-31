"""Fitur deterministik per kandidat.

Dua kelompok:
  * teks  — murah, tanpa audio, selalu tersedia
  * audio — butuh rms_series dari lib/audio.py (opsional)

Fitur ini dipakai dua kali:
  1. prefilter kandidat sebelum LLM (lihat candidates._cheap_score)
  2. sebagai fitur tambahan saat kalibrasi model nanti (v2)
"""

from __future__ import annotations

from typing import Any

from .lib import text as T
from .lib.audio import silence_ratio as _silence_ratio
from .lib.audio import stats as _stats

# Target WPM untuk short Bahasa Indonesia.
WPM_IDEAL = 160.0
WPM_MIN = 72.0


def hook_latency(c: dict[str, Any], atoms: list[dict[str, Any]]) -> float:
    """Detik dari awal klip sampai sinyal "ada poin" pertama."""
    base = float(c["start"])
    for atom in atoms[int(c["atom_start"]) : int(c["atom_end"]) + 1]:
        text = str(atom["text"])
        if atom.get("is_question") or T.has_digit(text) or T.has_point_marker(text):
            return round(max(0.0, float(atom["start"]) - base), 3)
    return round(float(c["duration"]), 3)


def extract(
    c: dict[str, Any],
    atoms: list[dict[str, Any]],
    rms: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    text = str(c["text"])
    dur = float(c["duration"]) or 1.0
    words = int(c["words"]) or 1

    chunk = atoms[int(c["atom_start"]) : int(c["atom_end"]) + 1]
    atom_word_counts = [int(a["words"]) for a in chunk]
    _, len_std = _stats([float(x) for x in atom_word_counts])

    fillers = T.count_fillers(text)
    numbers = T.count_numbers(text)

    feats: dict[str, Any] = {
        "words": words,
        "duration": round(dur, 3),
        "wpm": round(words / (dur / 60.0), 2),
        "atom_count": len(chunk),
        "filler_count": fillers,
        "filler_ratio": round(fillers / words, 4),
        "particle_count": T.count_particles(text),
        "question_count": sum(1 for a in chunk if a.get("is_question")),
        "number_count": numbers,
        "number_density": round(numbers / words * 100.0, 3),
        "hook_latency": hook_latency(c, atoms),
        "starts_with_conjunction": T.starts_with_hanging_conjunction(text),
        "ends_mid_thought": not bool(chunk[-1].get("ends_sentence")),
        "type_token_ratio": round(T.type_token_ratio(text), 4),
        "avg_atom_words": round(sum(atom_word_counts) / max(1, len(atom_word_counts)), 2),
        "sentence_len_std": round(len_std, 3),
    }

    # WPM penalty relatif terhadap target
    feats["wpm_score"] = round(max(0.0, 1.0 - abs(feats["wpm"] - WPM_IDEAL) / WPM_IDEAL), 4)

    if rms:
        window = [
            db for t, db in rms if float(c["start"]) <= t < float(c["end"])
        ]
        if window:
            mean_db, std_db = _stats(window)
            feats["rms_mean_db"] = round(mean_db, 2)
            feats["rms_std_db"] = round(std_db, 2)
            feats["silence_ratio"] = round(_silence_ratio([(0.0, d) for d in window]), 4)
            # delivery datar = kurang menarik; std rendah dinilai rendah
            feats["prosody_score"] = round(min(std_db / 6.0, 1.0), 4)

    return feats


def attach(
    candidates: list[dict[str, Any]],
    atoms: list[dict[str, Any]],
    rms: list[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    for c in candidates:
        c["features"] = extract(c, atoms, rms)
    return candidates
