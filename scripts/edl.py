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
from . import motion
from .lib import jsonio

# Caption yang terlalu singkat tidak terbaca; yang berjeda terlalu jauh terlihat
# berkedip. Dua ambang ini merapikan ritme tanpa membuat teks menggantung.
MIN_CAP_DUR = 0.62
HOLD_MAX_GAP = 0.55
HOLD_MARGIN = 0.04
MAX_CAP_DUR = 2.0   # jangan tahan satu frasa lebih lama dari ini

# Multi-segment: jeda lebih panjang dari ini dibuang dari klip, bukan ditampilkan.
DEAD_AIR_GAP = 0.45
MIN_SEG_DUR = 0.6


def plan_segments(
    spans: list[tuple[float, float]],
    clip_start: float,
    clip_end: float,
    max_gap: float = DEAD_AIR_GAP,
    min_seg: float = MIN_SEG_DUR,
) -> list[dict[str, Any]]:
    """Pecah rentang klip jadi segmen-segmen tanpa jeda > max_gap.

    `spans` = rentang bicara dalam waktu SUMBER. Jeda di antaranya dibuang,
    jadi output lebih padat daripada inputnya.
    """
    clean: list[list[float]] = []
    for s, e in sorted((float(a), float(b)) for a, b in spans):
        s = max(s, clip_start)
        e = min(e, clip_end)
        if e - s <= 1e-6:
            continue
        if clean and s - clean[-1][1] <= max_gap:
            clean[-1][1] = max(clean[-1][1], e)
        else:
            clean.append([s, e])

    if not clean:
        return [
            {
                "src_start": round(clip_start, 3),
                "src_end": round(clip_end, 3),
                "speed": 1.0,
                "out_start": 0.0,
            }
        ]

    # Segmen yang terlalu pendek dibuang: menampilkan 0,1 detik lebih buruk
    # daripada melewatinya, dan menggabungkannya akan mengembalikan jeda.
    kept = [pair for pair in clean if pair[1] - pair[0] >= min_seg] or [clean[0]]

    segments: list[dict[str, Any]] = []
    out = 0.0
    for s, e in kept:
        segments.append(
            {
                "src_start": round(s, 3),
                "src_end": round(e, 3),
                "speed": 1.0,
                "out_start": round(out, 3),
            }
        )
        out += e - s
    return segments


def map_time(segments: list[dict[str, Any]], t: float) -> float | None:
    """Waktu sumber -> waktu output. None kalau jatuh di jeda yang dibuang."""
    for seg in segments:
        s = float(seg["src_start"])
        e = float(seg["src_end"])
        if s - 1e-6 <= t <= e + 1e-6:
            return round(float(seg["out_start"]) + (t - s), 3)
    return None


def map_interval(
    segments: list[dict[str, Any]], start: float, end: float
) -> tuple[float, float] | None:
    """Petakan rentang; dipotong di batas segmen, None kalau seluruhnya di jeda."""
    outs: list[tuple[float, float]] = []
    for seg in segments:
        s = float(seg["src_start"])
        e = float(seg["src_end"])
        lo = max(start, s)
        hi = min(end, e)
        if hi - lo <= 1e-6:
            continue
        base = float(seg["out_start"])
        outs.append((base + (lo - s), base + (hi - s)))
    if not outs:
        return None
    return (round(min(o[0] for o in outs), 3), round(max(o[1] for o in outs), 3))


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
        # Timestamp kata dari ASR kadang melar; jangan biarkan satu frasa nangkring.
        # Tapi jangan sampai memotongnya menciptakan celah kedip ke caption berikutnya.
        capped = min(end, start + MAX_CAP_DUR)
        if 0.0 <= limit - capped <= 0.15:
            capped = limit
        end = capped
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

    # Jeda panjang dibuang: klip jadi beberapa segmen, bukan satu rentang utuh.
    spans = [(float(p["start"]), float(p["end"])) for p in phrases]
    segments = plan_segments(spans, clip_start, clip_end)
    out_dur = round(
        sum(float(s["src_end"]) - float(s["src_start"]) for s in segments), 3
    )

    captions: list[dict[str, Any]] = []
    for ph in phrases:
        mapped = map_interval(segments, float(ph["start"]), float(ph["end"]))
        if mapped is None:
            continue  # seluruh frasa jatuh di jeda yang dibuang
        start, end = mapped
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

    _smooth_captions(captions, out_dur)

    # --- motion graphics tier-1 (tidak mengubah timing) ---
    boundaries: list[float] = []
    for i in range(a0 + 1, a1 + 1):
        mapped_b = map_time(segments, float(atoms[i]["start"]))
        if mapped_b is not None:
            boundaries.append(round(mapped_b, 3))
    punch = motion.punch_schedule(boundaries, out_dur)

    overlays: list[dict[str, Any]] = []
    vs = motion.detect_vs(str(item["text"])[:400])
    if vs and out_dur >= 6.0:
        overlays.append(
            {
                "type": "vs",
                "start": 0.6,
                "end": 3.6,
                "left": vs[0],
                "right": vs[1],
            }
        )

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
        "segments": segments,
        "captions": captions,
        "reframe": {"mode": "center", "bias_x": 0.0, "bias_y": 0.0},
        "punch": punch,
        "progress": True,
        "overlays": overlays,
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
