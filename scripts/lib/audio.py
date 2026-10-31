"""Probe dan analisis audio via ffmpeg.

Sengaja TIDAK memakai numpy/librosa — lihat docs/DECISIONS.md D-004.
Semua angka diambil dari filter ffmpeg dan di-parse dari stdout/stderr.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for binary in (FFMPEG, FFPROBE):
        if shutil.which(binary) is None:
            raise FFmpegError(
                f"{binary} tidak ditemukan di PATH. Pasang ffmpeg >= 6.0 dulu."
            )


def _run(cmd: list[str], capture_stdout: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        capture_output=capture_stdout,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-800:]
        raise FFmpegError(f"gagal: {' '.join(cmd[:6])} ...\n{tail}")
    return proc


def _fraction(value: str | None, default: float = 30.0) -> float:
    if not value:
        return default
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            n, d = float(num), float(den)
            return n / d if d else default
        except ValueError:
            return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class MediaInfo:
    path: str
    duration: float
    fps: float
    width: int
    height: int
    has_audio: bool
    audio_rate: int = 48000
    rotation: int = 0

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "duration": round(self.duration, 3),
            "fps": round(self.fps, 6),
            "width": self.width,
            "height": self.height,
            "has_audio": self.has_audio,
            "audio_rate": self.audio_rate,
            "rotation": self.rotation,
        }


def probe(path: str) -> MediaInfo:
    proc = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
    )
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise FFmpegError(f"tidak ada stream video di {path}")

    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rotation = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                rotation = 0

    duration = 0.0
    try:
        duration = float(fmt.get("duration") or video.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    return MediaInfo(
        path=path,
        duration=duration,
        fps=_fraction(video.get("r_frame_rate") or video.get("avg_frame_rate")),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_audio=audio is not None,
        audio_rate=int(audio.get("sample_rate") or 48000) if audio else 0,
        rotation=rotation,
    )


def extract_audio(src: str, dst: str, rate: int = 48000, mono: bool = False) -> str:
    """Ekstrak audio ke WAV PCM. Normalisasi sample rate di sini, bukan nanti."""
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-y", "-i", src, "-vn"]
    if mono:
        cmd += ["-ac", "1"]
    cmd += ["-ar", str(rate), "-c:a", "pcm_s16le", dst]
    _run(cmd)
    return dst


def to_mezzanine(src: str, dst: str, fps: float = 30.0) -> str:
    """Transkode ke CFR + H.264 mezzanine. VFR dari rekaman HP wajib dipaksa CFR."""
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        src,
        "-vf",
        f"fps={fps:g},scale='trunc(iw/2)*2':'trunc(ih/2)*2'",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        dst,
    ]
    _run(cmd)
    return dst


_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


@dataclass
class Loudness:
    input_i: float | None = None
    input_tp: float | None = None
    input_lra: float | None = None
    input_thresh: float | None = None
    raw: dict = field(default_factory=dict)


def measure_loudness(path: str, limit: float | None = None) -> Loudness:
    """Loudness terintegrasi (LUFS) via filter loudnorm.

    `limit` (detik) membatasi analisis ke bagian awal saja — cukup representatif
    dan jauh lebih cepat untuk file panjang.
    """
    cmd = [FFMPEG, "-hide_banner", "-nostats"]
    if limit:
        cmd += ["-t", f"{float(limit):g}"]
    cmd += [
        "-i",
        path,
        "-af",
        "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    blob = proc.stderr or ""
    matches = _LOUDNORM_JSON.findall(blob)
    if not matches:
        return Loudness()
    try:
        raw = json.loads(matches[-1])
    except json.JSONDecodeError:
        return Loudness()

    def _num(key: str) -> float | None:
        try:
            v = float(raw.get(key, "nan"))
        except (TypeError, ValueError):
            return None
        return None if v != v else v

    return Loudness(
        input_i=_num("input_i"),
        input_tp=_num("input_tp"),
        input_lra=_num("input_lra"),
        input_thresh=_num("input_thresh"),
        raw=raw,
    )


_PTS_RE = re.compile(r"pts_time:([0-9.]+)")
_RMS_RE = re.compile(r"RMS_level=(-?[0-9.]+|-inf)")


def rms_series(path: str, frame_ms: int = 100, rate: int = 48000) -> list[tuple[float, float]]:
    """RMS per frame dalam dB, satu titik tiap `frame_ms`.

    Memaksa ukuran frame audio supaya jumlah sampel deterministik,
    bukan bergantung pada buffer internal ffmpeg.
    """
    n = max(1, int(rate * frame_ms / 1000))
    filt = (
        f"asetnsamples=n={n},"
        "astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af", filt, "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = proc.stdout or ""
    if not out.strip():
        return []

    series: list[tuple[float, float]] = []
    t = 0.0
    for line in out.splitlines():
        m = _PTS_RE.search(line)
        if m:
            try:
                t = float(m.group(1))
            except ValueError:
                pass
            continue
        m = _RMS_RE.search(line)
        if m:
            val = m.group(1)
            db = float("-100.0") if val == "-inf" else float(val)
            series.append((t, db))
    return series


def silence_ratio(series: list[tuple[float, float]], threshold_db: float = -40.0) -> float:
    if not series:
        return 0.0
    silent = sum(1 for _, db in series if db < threshold_db)
    return silent / len(series)


def stats(values: list[float]) -> tuple[float, float]:
    """(mean, stdev) tanpa numpy."""
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return mean, var ** 0.5
