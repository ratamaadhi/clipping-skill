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
from . import faces
from . import motion
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
    edl: dict[str, Any],
    clip: dict[str, Any],
    ass_rel: str | None = None,
    fontsdir: str | None = None,
    motion_filters: list[str] | None = None,
    fps: float = 30.0,
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
        track = reframe.get("bias_track") or []
        if track:
            # crop bergerak mengikuti wajah; x dievaluasi per frame oleh ffmpeg
            expr = faces.crop_expression(
                [(float(t), float(b)) for t, b in track],
                cw,
                int(src["width"]) - cw,
            )
            parts.append(f"crop={cw}:{ch}:x='{expr}':y={y}")
        else:
            parts.append(f"crop={cw}:{ch}:{x}:{y}")
    parts.append(f"scale={TARGET_W}:{TARGET_H}:flags=lanczos")
    parts.append("setsar=1")

    # Normalisasi fps SEBELUM motion. zoompan memakai d=1, jadi kalau input 25fps
    # dibiarkan, 25 frame masuk -> 25 frame keluar tapi ditimestamppi 30fps:
    # video jadi 0,83x lebih cepat dan audio desync.
    if motion_filters:
        parts.append(f"fps={fps:g}")

    # motion graphics SEBELUM caption, supaya caption selalu di lapisan teratas
    parts.extend(motion_filters or [])

    # PENGAMAN, bukan perbaikan bug. zoompan menulis timestamp sendiri
    # (indeks/fps) sehingga secara teori bisa melenceng dari grid fps dan
    # memicu pembuangan frame saat konversi CFR. Pada pengujian dengan tiga
    # klip nyata, keluaran tanpa baris ini juga bersih (0 celah, 0 duplikat),
    # jadi manfaatnya belum terbukti — biayanya nyaris nol, dijaga sebagai
    # jaring pengaman. Periksa dengan `python3 -m scripts.verify` sebelum
    # menyimpulkan ada frame hilang.
    if any(f.startswith("zoompan") for f in (motion_filters or [])):
        parts.append(f"setpts=N/({fps:g}*TB)")

    if ass_rel:
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

    segs = clip.get("segments") or []
    if not segs:
        raise RenderError(f"{clip['id']}: tidak punya segments")
    first_start = min(float(s["src_start"]) for s in segs)
    last_end = max(float(s["src_end"]) for s in segs)
    duration = sum(float(s["src_end"]) - float(s["src_start"]) for s in segs)
    if duration <= 0:
        raise RenderError(f"{clip['id']}: durasi <= 0")

    # Offset relatif terhadap titik seek (-ss), karena trim menghitung dari situ.
    rel: list[tuple[float, float]] = [
        (float(s["src_start"]) - first_start, float(s["src_end"]) - first_start)
        for s in segs
    ]

    cap_dir = wd / CAP_DIR
    cap_dir.mkdir(parents=True, exist_ok=True)
    ass_path = cap_dir / f"{clip['id']}.ass"
    cap_mod.write_ass(clip.get("captions", []), ass_path)
    ass_rel = f"{CAP_DIR}/{clip['id']}.ass"

    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    fps = float(edl["output"].get("fps", 30.0))
    show_progress = bool(clip.get("progress", True)) and duration > 0

    # --- motion graphics tier-1 ---
    zoom = motion.zoompan_filter(clip.get("punch") or [], fps, TARGET_W, TARGET_H)
    base_motion: list[str] = []
    if zoom:
        base_motion.append(zoom)
    if show_progress:
        base_motion.append(motion.progress_track_filter())

    base = _vf_chain(edl, clip, None, None, base_motion, fps)

    parts: list[str] = []
    if len(rel) == 1:
        parts.append(f"[0:v]{base}[vcat]")
    else:
        labels: list[str] = []
        for i, (a, b) in enumerate(rel):
            parts.append(
                f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[sv{i}]"
            )
            labels.append(f"[sv{i}]")
        parts.append("".join(labels) + f"concat=n={len(rel)}:v=1:a=0[svcat]")
        parts.append(f"[svcat]{base}[vcat]")

    last = "vcat"
    if show_progress:
        parts.append(motion.progress_fill_source(duration, fps, TARGET_W))
        parts.append(f"[{last}][bar]{motion.progress_fill_overlay(duration)}[v1]")
        last = "v1"
    panels = motion.overlay_filters(clip.get("overlays") or [])
    if panels:
        parts.append(f"[{last}]" + ",".join(panels) + "[v2]")
        last = "v2"
    sub = f"subtitles={ass_rel}" + (f":fontsdir={fontsdir}" if fontsdir else "")
    parts.append(f"[{last}]{sub}[v]")

    punch = clip.get("punch") or []
    sfx_events = [
        {"t": float(p["t"]), "kind": "hit" if i % 2 else "whoosh"}
        for i, p in enumerate(punch)
        if i > 0
    ]
    sfx_path = (
        motion.write_sfx_wav(wd / "sfx" / f"{clip['id']}.wav", sfx_events, duration)
        if sfx_events
        else None
    )

    has_audio = bool(edl["source"].get("audio_rate"))
    target_i = float(edl["output"].get("loudness_lufs", -14.0))
    target_tp = float(edl["output"].get("true_peak_db", -1.0))

    if has_audio:
        if len(rel) == 1:
            parts.append(f"[0:a]loudnorm=I={target_i:g}:TP={target_tp:g}:LRA=11[a0]")
        else:
            alabels: list[str] = []
            for i, (a, b) in enumerate(rel):
                parts.append(
                    f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[sa{i}]"
                )
                alabels.append(f"[sa{i}]")
            parts.append(
                "".join(alabels) + f"concat=n={len(rel)}:v=0:a=1[acat]"
            )
            parts.append(f"[acat]loudnorm=I={target_i:g}:TP={target_tp:g}:LRA=11[a0]")
        if sfx_path:
            parts.append("[1:a]volume=1.0[s1]")
            parts.append(
                "[a0][s1]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.95[a]"
            )
        else:
            parts.append("[a0]anull[a]")

    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-y",
        "-ss",
        f"{first_start:.3f}",
        "-t",
        f"{last_end - first_start:.3f}",
        "-i",
        str(src_path),
    ]
    if sfx_path:
        cmd += ["-i", str(sfx_path)]

    cmd += ["-filter_complex", ";".join(p for p in parts if p)]
    cmd += ["-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
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
        f"{fps:g}",
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
