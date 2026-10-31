#!/usr/bin/env python3
"""Runner benchmark whisper.cpp: ukur peak RSS + waktu, catat ke JSON.

Kenapa ada: angka benchmark cepat basi — model baru, mesin baru, thread berbeda.
Script ini membuat pengukuran ulang jadi satu perintah, dan hasilnya menumpuk
di satu file JSON sehingga perbandingan antar waktu tetap apples-to-apples.

Contoh:

    python3 benchmarks/bench.py \
        --model ~/models/ggml-large-v3-turbo-q5_0.bin \
        --audio ~/bench/a130.wav \
        --threads 4 --language id

Butuh: whisper-cli ter-build, ffprobe, /usr/bin/time (GNU time).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_OUT = Path(__file__).resolve().parent / "results.json"

_RE_MEM = re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)")
_RE_ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(.*?\):\s*([\d:.]+)")
_RE_CPU = re.compile(r"Percent of CPU this job got:\s*(\d+)%")
_RE_TOTAL = re.compile(r"whisper_print_timings:\s+total time\s*=\s*([\d.]+)\s*ms")
_RE_ENCODE = re.compile(
    r"whisper_print_timings:\s+encode time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*runs\s*\(\s*([\d.]+)\s*ms per run"
)
_RE_LOAD = re.compile(r"whisper_print_timings:\s+load time\s*=\s*([\d.]+)\s*ms")


def _elapsed_seconds(text: str) -> float:
    parts = [float(p) for p in text.strip().split(":")]
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return round(seconds, 2)


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _meminfo() -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    out[key] = round(int(rest.split()[0]) / 1024 / 1024, 2)
    except OSError:
        pass
    return out


def host_info() -> dict[str, Any]:
    mem = _meminfo()
    swap_total = mem.get("SwapTotal", 0.0)
    swap_free = mem.get("SwapFree", 0.0)
    return {
        "cpu": _cpu_model(),
        "cpu_threads": os.cpu_count(),
        "ram_total_gib": mem.get("MemTotal"),
        "ram_available_gib": mem.get("MemAvailable"),
        "swap_total_gib": swap_total,
        "swap_used_pct": (
            round((swap_total - swap_free) / swap_total * 100, 1) if swap_total else None
        ),
        "os": platform.platform(),
        "gpu": _gpu(),
    }


def _gpu() -> str | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def audio_seconds(path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return round(float(out.stdout.strip()), 2)
    except ValueError:
        return 0.0


def find_whisper_bin(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("WHISPER_CLI")
    if env:
        return env
    candidates = [
        Path.home() / "tama-proj/whisper.cpp/build/bin/whisper-cli",
        Path("build/bin/whisper-cli"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    found = shutil.which("whisper-cli")
    if found:
        return found
    raise SystemExit(
        "whisper-cli tidak ditemukan. Build dulu (lihat benchmarks/README.md) "
        "atau set WHISPER_CLI=/path/ke/whisper-cli"
    )


def measure(
    whisper_bin: str,
    model: Path,
    audio: Path,
    threads: int,
    language: str,
    extra: list[str] | None = None,
) -> dict[str, Any]:
    if not shutil.which("/usr/bin/time") and not Path("/usr/bin/time").exists():
        raise SystemExit("/usr/bin/time tidak ada — pasang paket `time`")

    with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as fh:
        time_out = Path(fh.name)

    cmd = [
        "/usr/bin/time", "-v", "-o", str(time_out),
        whisper_bin, "-m", str(model), "-f", str(audio),
        "-l", language, "-t", str(threads),
    ] + (extra or [])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    finally:
        blob = time_out.read_text(encoding="utf-8", errors="replace") if time_out.exists() else ""
        time_out.unlink(missing_ok=True)

    if proc.returncode != 0:
        raise SystemExit(f"whisper-cli gagal (exit {proc.returncode}):\n{proc.stderr[-800:]}")

    err = proc.stderr
    mem = _RE_MEM.search(blob)
    elapsed = _RE_ELAPSED.search(blob)
    cpu = _RE_CPU.search(blob)
    total = _RE_TOTAL.search(err)
    encode = _RE_ENCODE.search(err)
    load = _RE_LOAD.search(err)

    wall = _elapsed_seconds(elapsed.group(1)) if elapsed else 0.0
    dur = audio_seconds(audio)

    return {
        "model": model.name,
        "model_size_mb": round(model.stat().st_size / 1024 / 1024, 1),
        "audio": audio.name,
        "audio_seconds": dur,
        "threads": threads,
        "language": language,
        "wall_seconds": wall,
        "peak_rss_mb": round(int(mem.group(1)) / 1024) if mem else None,
        "cpu_percent": int(cpu.group(1)) if cpu else None,
        "rtf": round(dur / wall, 3) if wall and dur else None,
        "load_ms": round(float(load.group(1)), 1) if load else None,
        "total_ms": round(float(total.group(1)), 1) if total else None,
        "encode_ms_per_run": round(float(encode.group(3)), 1) if encode else None,
        "encode_runs": int(encode.group(2)) if encode else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark whisper.cpp → JSON")
    p.add_argument("--model", required=True, help="path model .bin")
    p.add_argument("--audio", required=True, help="path audio 16k mono wav")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--language", default="id")
    p.add_argument("--whisper-bin", default=None)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--note", default="", help="catatan bebas untuk entri ini")
    p.add_argument("--dry-run", action="store_true", help="cetak hasil, jangan tulis file")
    args = p.parse_args(argv)

    model = Path(args.model).expanduser()
    audio = Path(args.audio).expanduser()
    for path, label in ((model, "model"), (audio, "audio")):
        if not path.exists():
            raise SystemExit(f"{label} tidak ada: {path}")

    result = measure(
        find_whisper_bin(args.whisper_bin), model, audio, args.threads, args.language
    )
    result["measured_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.note:
        result["note"] = args.note

    print(json.dumps(result, indent=2))

    if args.dry_run:
        return 0

    out = Path(args.out)
    payload: dict[str, Any] = {"version": "0.1.0", "host": host_info(), "runs": []}
    if out.exists():
        payload = json.loads(out.read_text(encoding="utf-8"))
        payload["host"] = host_info()

    payload["runs"].append(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ ditambahkan ke {out} ({len(payload['runs'])} entri)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
