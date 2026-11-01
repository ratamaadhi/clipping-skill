"""Periksa kualitas gerak hasil render: celah timestamp dan frame duplikat.

Dua cacat ini tidak terlihat di baris "✓ render" dan tidak tertangkap tes unit
biasa, karena keduanya baru muncul di keluaran ffmpeg:

  * celah pts   -> frame hilang, terasa sebagai patah-patah tepat setelah gerakan
  * duplikat    -> frame diulang, terasa sebagai tersendat saat kamera bergerak

Keduanya diukur tanpa numpy: celah dari ffprobe, duplikat dari filter
`tblend=difference` + `signalstats` yang mencetak rata-rata selisih per frame.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Ambang. Sumber 25/30 fps punya delta 0,04 / 0,0333 s; celah > 1,5x delta
# berarti ada frame yang hilang.
GAP_FACTOR = 1.5
# Rata-rata selisih luma antar frame di bawah ini = frame identik.
# Ambang kecil: duplikasi frame (mis. 25->30 fps) menghasilkan salinan PERSIS,
# sedangkan adegan nyaris diam bisa turun ke 0,1 tanpa ada kesalahan timing.
DUP_YAVG = 0.05
# Frame identik baru dianggap masalah kalau jumlahnya signifikan. Adegan diam
# yang dipadatkan encoder tidak boleh membuat render dinyatakan gagal.
DUP_FAIL_SHARE = 0.05


def frame_times(path: str | Path) -> list[float]:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True,
    ).stdout
    ts: list[float] = []
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            ts.append(float(line))
        except ValueError:
            continue
    return ts


def motion_series(path: str | Path) -> list[float]:
    """Rata-rata selisih luma antar frame berurutan (YAVG dari tblend difference)."""
    res = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-vf", "scale=270:480,tblend=all_mode=difference,"
                   "signalstats,"
                   "metadata=print:key=lavfi.signalstats.YAVG:file=-",
            "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    vals: list[float] = []
    for line in res.stdout.splitlines():
        if "YAVG=" in line:
            try:
                vals.append(float(line.split("YAVG=")[1]))
            except (ValueError, IndexError):
                continue
    return vals


def find_gaps(times: list[float], fps: float | None = None) -> list[dict]:
    if len(times) < 2:
        return []
    if fps is None:
        span = times[-1] - times[0]
        fps = (len(times) - 1) / span if span > 0 else 25.0
    step = 1.0 / fps
    gaps = []
    for i in range(len(times) - 1):
        d = times[i + 1] - times[i]
        if d > step * GAP_FACTOR:
            gaps.append({"after_frame": i, "t": round(times[i], 3), "delta": round(d, 4)})
    return gaps


def find_duplicates(series: list[float]) -> list[int]:
    return [i + 1 for i, v in enumerate(series) if v < DUP_YAVG]


def analyze(path: str | Path) -> dict:
    times = frame_times(path)
    fps = None
    if len(times) > 1 and times[-1] > times[0]:
        fps = round((len(times) - 1) / (times[-1] - times[0]), 3)
    gaps = find_gaps(times, fps)
    series = motion_series(path)
    dups = find_duplicates(series)
    share = len(dups) / len(times) if times else 0.0
    return {
        "path": str(path),
        "frames": len(times),
        "fps": fps,
        "gaps": gaps,
        "duplicates": dups,
        "duplicate_share": round(share, 4),
        "ok": not gaps and share <= DUP_FAIL_SHARE,
    }


def main(argv: list[str]) -> int:
    targets: list[Path] = []
    for arg in argv:
        p = Path(arg)
        if p.is_dir():
            targets.extend(sorted((p / "out").glob("*.mp4")) or sorted(p.glob("*.mp4")))
        elif p.exists():
            targets.append(p)
    if not targets:
        print("pakai: python3 -m scripts.verify <berkas.mp4|dir> [...]")
        return 2

    bad = 0
    print(f"  {'berkas':<22}{'frame':>7}{'fps':>7}{'celah':>7}{'duplikat':>10}  status")
    for t in targets:
        r = analyze(t)
        status = "OK" if r["ok"] else "MASALAH"
        if r["ok"] and r["duplicates"]:
            status = f"OK ({len(r['duplicates'])} frame identik, wajar pada adegan diam)"
        if not r["ok"]:
            bad += 1
        print(f"  {t.name:<22}{r['frames']:>7}{r['fps']:>7.2f}{len(r['gaps']):>7}{len(r['duplicates']):>10}  {status}")
        for g in r["gaps"][:3]:
            print(f"      celah di t={g['t']}s ({g['delta']}s, ~{round(g['delta'] * (r['fps'] or 25))} frame)")
    print()
    print(json.dumps({"checked": len(targets), "problems": bad}) if False else
          f"  {len(targets)} berkas diperiksa, {bad} bermasalah")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
