"""Ingest: normalisasi sumber ke mezzanine CFR + audio siap analisis.

Kenapa mezzanine: rekaman HP dan screen recording sering VFR. Kalau VFR masuk ke
renderer, caption dan audio bergeser tanpa pola. Paksa CFR sekali di depan
(docs/DECISIONS.md, lihat juga docs/PIPELINE.md bagian timing drift).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .lib import audio as A
from .lib import jsonio

MEZZANINE = "mezzanine.mp4"
AUDIO48 = "audio48.wav"
AUDIO16 = "audio16.wav"
META = "meta.json"


def run(
    src: str | Path,
    work_dir: str | Path,
    fps: float = 30.0,
    force: bool = False,
    loudness_limit: float = 180.0,
) -> dict[str, Any]:
    A.require_ffmpeg()

    src_path = Path(src).expanduser().resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"file tidak ada: {src_path}")

    wd = Path(work_dir).expanduser().resolve()
    wd.mkdir(parents=True, exist_ok=True)

    digest = jsonio.sha256_file(src_path)
    meta_path = wd / META
    if meta_path.exists() and not force:
        cached = jsonio.read_json(meta_path)
        if cached.get("source_sha256") == digest:
            return cached

    info = A.probe(str(src_path))

    mezz = wd / MEZZANINE
    A.to_mezzanine(str(src_path), str(mezz), fps=fps)

    a48 = wd / AUDIO48
    a16 = wd / AUDIO16
    if info.has_audio:
        A.extract_audio(str(mezz), str(a48), rate=48000, mono=False)
        A.extract_audio(str(mezz), str(a16), rate=16000, mono=True)
        loud = A.measure_loudness(str(a48), limit=loudness_limit)
        lufs = loud.input_i
    else:
        loud = A.Loudness()
        lufs = None

    mezz_info = A.probe(str(mezz))
    meta = {
        "version": "0.1.0",
        "source": str(src_path),
        "source_sha256": digest,
        "duration": round(mezz_info.duration, 3),
        "fps": round(mezz_info.fps, 6),
        "width": mezz_info.width,
        "height": mezz_info.height,
        "has_audio": info.has_audio,
        "audio_rate": mezz_info.audio_rate or 48000,
        "loudness_lufs": round(lufs, 2) if lufs is not None else None,
        "loudness_lra": round(loud.input_lra, 2) if loud.input_lra is not None else None,
        "mezzanine": str(mezz),
        "audio48": str(a48) if info.has_audio else None,
        "audio16": str(a16) if info.has_audio else None,
        "language": None,
        "clip_count": None,
    }
    jsonio.write_json(meta_path, meta)
    return meta
