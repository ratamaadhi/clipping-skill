"""Render: EDL -> mp4. Renderer TIDAK punya logika kreatif (docs/DECISIONS.md D-001).

Urutan filter:
  crop (reframe) -> scale 1080x1920 -> setsar -> subtitles (libass)
Audio: loudnorm sekali jalan ke -14 LUFS.

Catatan seek: `-ss` diletakkan SEBELUM `-i`. Dengan re-encode ini akurat dan cepat.
Output dipaksa CFR (`-fps_mode cfr`) supaya durasi caption tidak melayang.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from . import captions as cap_mod
from .lib import jsonio

TARGET_W, TARGET_H = 1080, 1920
TARGET_AR = TARGET_W / TARGET_H

EDL = "edl.json"
OUT_DIR = "out"
CAP_DIR = "captions"


class RenderError(RuntimeError):
    pass


def crop_params(
    src_w: int,
    src_h: int,
    bias_x: float = 0.0,
    bias_y: float = 0.0,
    target_ar: float = TARGET_AR,
) -> tuple[int, int, int, int]:
    """Hitung crop 9:16. bias 0 = tengah, +1 = kanan/bawah, -1 = kiri/atas."""
    if src_w <= 0 or src_h <= 0:
        raise RenderError("dimensi sumber tidak valid")

    src_ar = src_w / src_h
    if src_ar > target_ar:
        ch = src_h
        cw = int(round(ch * target_ar / 2.0)) * 2
    else:
        cw = src_w
        ch = int(round(cw / target_ar / 2.0)) * 2

    cw = min(cw, src_w)
    ch = min(ch, src_h)

    free_x = src_w - cw
    free_y = src_h - ch
    x = int(round(free_x / 2.0 * (1.0 + max(-1.0, min(1.0, bias_x)))))
    y = int(round(free_y / 2.0 * (1.0 + max(-1.0, min(1.0, bias_y)))))
    x = max(0, min(x, free_x))
    y = max(0, min(y, free_y))
    return cw, ch, x, y


def _vf_chain(
    edl: dict[str, Any], clip: dict[str, Any], ass_rel: str, fontsdir: str | None
) -> str:
    src = edl["source"]
    reframe = clip.get("reframe", {}) or {}
    cw, ch, x, y = crop_params(
        int(src["width"]),
        int(src["height"]),
        float(reframe.get("bias_x", 0.0)),
        float(reframe.get("bias_y", 0.0)),
    )

    parts: list[str] = []
    if (cw, ch) != (int(src["width"]), int(src["height"])):
        parts.append(f"crop={cw}:{ch}:{x}:{y}")
    parts.append(f"scale={TARGET_W}:{TARGET_H}:flags=lanczos")
    parts.append("setsar=1")

    sub = f"subtitles={ass_rel}"
    if fontsdir:
        sub += f":fontsdir={fontsdir}"
    parts.append(sub)
    return ",".join(parts)


def render_clip(
    edl: dict[str, Any],
    clip: dict[str, Any],
    work_dir: str | Path,
    out_path: str | Path,
    crf: int = 20,
    preset: str = "veryfast",
    fontsdir: str | None = None,
) -> Path:
    wd = Path(work_dir)
    src_path = Path(str(edl["source"]["path"])).expanduser()
    if not src_path.is_absolute():
        src_path = (wd / src_path).resolve()
    if not src_path.exists():
        raise RenderError(f"sumber tidak ada: {src_path}")

    seg = clip["segments"][0]
    start = float(seg["src_start"])
    duration = float(seg["src_end"]) - start
    if duration <= 0:
        raise RenderError(f"{clip['id']}: durasi <= 0")

    cap_dir = wd / CAP_DIR
    cap_dir.mkdir(parents=True, exist_ok=True)
    ass_path = cap_dir / f"{clip['id']}.ass"
    cap_mod.write_ass(clip.get("captions", []), ass_path)
    ass_rel = f"{CAP_DIR}/{clip['id']}.ass"

    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(src_path),
        "-vf",
        _vf_chain(edl, clip, ass_rel, fontsdir),
    ]

    has_audio = bool(edl["source"].get("audio_rate"))
    if has_audio:
        target_i = float(edl["output"].get("loudness_lufs", -14.0))
        target_tp = float(edl["output"].get("true_peak_db", -1.0))
        cmd += [
            "-af",
            f"loudnorm=I={target_i:g}:TP={target_tp:g}:LRA=11",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
        ]
    else:
        cmd += ["-an"]

    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-fps_mode",
        "cfr",
        "-r",
        "30",
        "-movflags",
        "+faststart",
        str(out),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", cwd=str(wd))
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1200:]
        raise RenderError(f"ffmpeg gagal untuk {clip['id']}:\n{tail}")
    return out


def render_all(
    work_dir: str | Path,
    top: int | None = None,
    crf: int = 20,
    preset: str = "veryfast",
    fontsdir: str | None = None,
) -> list[Path]:
    wd = Path(work_dir).expanduser().resolve()
    edl = jsonio.read_json(wd / EDL)
    clips = edl["clips"][: top] if top else edl["clips"]

    out_dir = wd / OUT_DIR
    results: list[Path] = []
    for clip in clips:
        results.append(
            render_clip(
                edl,
                clip,
                wd,
                out_dir / f"{clip['id']}.mp4",
                crf=crf,
                preset=preset,
                fontsdir=fontsdir,
            )
        )
    return results
