"""Bangun EDL — artefak pusat (docs/DECISIONS.md D-001).

Aturan timing yang wajib dijaga:
  * `segments[].src_start/src_end`  -> waktu SUMBER (absolut)
  * `captions[].start/end`          -> waktu OUTPUT (relatif awal klip)
  * `captions[].src_start`          -> jejak balik ke sumber, untuk debug drift

Di v0 setiap klip hanya satu segmen kontinu, jadi mapping-nya cuma pengurangan.
Saat multi-segment masuk (v1), mapping harus piecewise-linear — lihat docs/PIPELINE.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import captions as cap_mod
from .lib import jsonio

# Caption yang terlalu singkat tidak terbaca; yang berjeda terlalu jauh terlihat
# berkedip. Dua ambang ini merapikan ritme tanpa membuat teks menggantung.
MIN_CAP_DUR = 0.45
HOLD_MAX_GAP = 0.55
HOLD_MARGIN = 0.04


def _smooth_captions(captions: list[dict[str, Any]], clip_dur: float) -> None:
    """Rapikan durasi caption in-place.

    1. durasi minimum supaya sempat dibaca
    2. isi gap kecil ke caption berikutnya supaya tidak flicker
    """
    n = len(captions)
    for i, cap in enumerate(captions):
        limit = (
            captions[i + 1]["start"] - HOLD_MARGIN if i + 1 < n else clip_dur
        )
        start = float(cap["start"])
        end = float(cap["end"])
        if limit <= start:
            continue

        if end - start < MIN_CAP_DUR:
            end = min(start + MIN_CAP_DUR, limit)
        if 0.0 <= limit - end <= HOLD_MAX_GAP:
            end = limit
        cap["end"] = round(min(max(end, start + 0.08), clip_dur), 3)


def _clip_from_item(
    item: dict[str, Any],
    atoms: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    a0 = int(item["atom_start"])
    a1 = int(item["atom_end"])
    w0 = int(atoms[a0]["word_start"])
    w1 = int(atoms[a1]["word_end"])

    clip_start = float(atoms[a0]["start"])
    clip_end = float(atoms[a1]["end"])
    clip_dur = max(0.0, clip_end - clip_start)

    clip_words = words[w0 : w1 + 1]
    phrases = cap_mod.group_words(clip_words)

    captions: list[dict[str, Any]] = []
    for ph in phrases:
        start = round(max(0.0, float(ph["start"]) - clip_start), 3)
        end = round(min(clip_dur, max(0.0, float(ph["end"]) - clip_start)), 3)
        if end <= start:
            continue
        cap: dict[str, Any] = {
            "start": start,
            "end": end,
            "text": str(ph["text"]),
            "src_start": round(float(ph["start"]), 3),
        }
        em_idx = cap_mod.pick_emphasis(ph)
        if em_idx is not None:
            from .lib.text import clean as _clean

            cap["emphasis"] = _clean(str(ph["words"][em_idx]["w"]))
        captions.append(cap)

    _smooth_captions(captions, clip_dur)

    return {
        "id": f"clip_{int(item['rank']):02d}",
        "score": {
            "axes": {k: float(v) for k, v in item["axes"].items()},
            "base": float(item["base"]),
            "penalty": float(item["penalty"]),
            "final": float(item["final"]),
            "percentile": float(item["percentile"]),
            "weakest_axis": str(item["weakest_axis"]),
            "fix_suggestion": str(item["fix_suggestion"]),
        },
        "segments": [
            {
                "src_start": round(clip_start, 3),
                "src_end": round(clip_end, 3),
                "speed": 1.0,
                "out_start": 0.0,
            }
        ],
        "captions": captions,
        "reframe": {"mode": "center", "bias_x": 0.0, "bias_y": 0.0},
        "overlays": [],
    }


def build(work_dir: str | Path, top_n: int = 5) -> dict[str, Any]:
    wd = Path(work_dir)
    meta = jsonio.read_json(wd / "meta.json")
    transcript = jsonio.read_json(wd / "transcript.json")
    atoms = jsonio.read_json(wd / "atoms.json")
    scored = jsonio.read_json(wd / "scored.json")

    ranked = scored.get("scored", [])[: max(1, top_n)]
    if not ranked:
        raise ValueError("scored.json tidak punya kandidat")

    clips = [
        _clip_from_item(item, atoms, transcript["words"]) for item in ranked
    ]

    edl = {
        "version": "0.1.0",
        "source": {
            "path": meta.get("mezzanine") or meta["source"],
            "duration": round(float(meta["duration"]), 3),
            "fps": round(float(meta["fps"]), 6),
            "width": int(meta["width"]),
            "height": int(meta["height"]),
            "audio_rate": int(meta.get("audio_rate") or 48000),
            "loudness_lufs": meta.get("loudness_lufs"),
        },
        "output": {
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "loudness_lufs": -14.0,
            "true_peak_db": -1.0,
        },
        "clips": clips,
    }
    return edl


def write(work_dir: str | Path, edl: dict[str, Any]) -> Path:
    return jsonio.write_json(Path(work_dir) / "edl.json", edl)


def write_report(work_dir: str | Path, scored: dict[str, Any], edl: dict[str, Any]) -> Path:
    from .score import report as score_report

    body = score_report(scored, top=len(edl["clips"]))
    lines = [body, "", "## Peta klip → file", "", "| klip | sumber | durasi | skor |", "|---|---|---|---|"]
    for clip in edl["clips"]:
        seg = clip["segments"][0]
        lines.append(
            f"| `{clip['id']}` | {seg['src_start']}s → {seg['src_end']}s | "
            f"{round(seg['src_end'] - seg['src_start'], 2)}s | {clip['score']['final']} |"
        )
    lines.append("")
    path = Path(work_dir) / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
