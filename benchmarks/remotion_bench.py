"""Driver spike Remotion (Langkah 1).

Mengukur dari LUAR proses Node: RSS pohon (Node + Chromium), delta swap, dan
waktu dinding. Angka waktu dari dalam (remotion_bench.mjs) dipakai hanya untuk
memisahkan bundling dari rendering.

Hasil ditulis ke benchmarks/remotion.json; vonisnya dibaca gate.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
HERE = ROOT / "remotion"
sys.path.insert(0, str(ROOT.parent))

from scripts.lib import procmem  # noqa: E402

WATCHDOG_RSS_MB = 4000.0  # jaring terakhir; RSS pohon menghitung halaman bersama ganda
MIN_AVAIL_MB = 400.0      # sinyal OOM yang sebenarnya: jangan sampai sistem kehabisan
SAMPLE_S = 0.3

CONFIGS: list[dict[str, Any]] = [
    {"id": "Card1080", "width": 1080, "height": 1920, "concurrency": 1},
    {"id": "Card1080", "width": 1080, "height": 1920, "concurrency": 2},
    {"id": "Card600", "width": 1080, "height": 600, "concurrency": 1},
    {"id": "Card300", "width": 540, "height": 300, "concurrency": 1},
    {"id": "CardAlpha", "width": 540, "height": 300, "concurrency": 1},
]


def alpha_ok(frames_dir: Path) -> bool:
    """PNG IHDR byte 25 = color type; 6 berarti RGBA (alpha benar-benar ada)."""
    pngs = sorted(frames_dir.glob("*.png"))
    if not pngs:
        return False
    head = pngs[0].read_bytes()[:30]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    return head[25] == 6


def one_run(cfg: dict[str, Any], frames: int, browser: str, out_dir: Path) -> dict[str, Any]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    swap0 = procmem.swap_counters()
    avail0 = procmem.mem_available_mb()
    cmd = [
        "node",
        "remotion_bench.mjs",
        f"--id={cfg['id']}",
        f"--out={out_dir}",
        f"--concurrency={cfg['concurrency']}",
        f"--frames={frames}",
    ]
    if browser:
        cmd.append(f"--browser={browser}")

    wall0 = time.time()
    proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    rss_peak = 0.0
    avail_min = avail0
    killed = False
    while proc.poll() is None:
        rss_peak = max(rss_peak, procmem.tree_rss_mb(proc.pid))
        avail = procmem.mem_available_mb()
        avail_min = min(avail_min, avail)
        if avail < MIN_AVAIL_MB or rss_peak > WATCHDOG_RSS_MB:
            killed = True
            proc.kill()
            break
        time.sleep(SAMPLE_S)
    out, err = proc.communicate()
    wall = time.time() - wall0
    swap1 = procmem.swap_counters()

    if proc.returncode != 0:
        return {
            **cfg,
            "error": (err or out or "").strip()[-400:],
            "frames": 0,
            "fps": 0.0,
            "rss_mb": round(rss_peak, 1),
            "swap_pages": swap1[1] - swap0[1],
            "alpha_ok": False,
            "wall_s": round(wall, 2),
        }

    try:
        inner = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        inner = {}

    rendered = int(inner.get("frames", 0)) or 0
    if rendered == 0:
        return {
            **cfg,
            "error": (err or out or "tidak ada frame dihasilkan").strip()[-400:],
            "frames": 0,
            "fps": 0.0,
            "rss_mb": round(rss_peak, 1),
            "swap_pages": swap1[1] - swap0[1],
            "alpha_ok": False,
            "wall_s": round(wall, 2),
        }
    render_s = float(inner.get("render_ms", 0)) / 1000.0 or wall
    return {
        **cfg,
        "frames": rendered,
        "fps": round(rendered / render_s, 2) if render_s > 0 else 0.0,
        "rss_mb": round(rss_peak, 1),
        "swap_pages": swap1[1] - swap0[1],
        "avail_before_mb": round(avail0, 0),
        "avail_min_mb": round(avail_min, 0),
        "avail_drop_mb": round(avail0 - avail_min, 0),
        "killed_by_watchdog": killed,
        "alpha_ok": alpha_ok(out_dir),
        "bundle_ms": round(float(inner.get("bundle_ms", 0))),
        "render_ms": round(float(inner.get("render_ms", 0))),
        "wall_s": round(wall, 2),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    frames = 150
    runs = 3
    quick = "--quick" in argv
    if quick:
        frames, runs = 12, 1

    browser = ""
    for a in argv:
        if a.startswith("--browser="):
            browser = a.split("=", 1)[1]
    if not browser:
        cand = Path.home() / ".local" / "bin" / "chromium"
        browser = str(cand) if cand.exists() else ""

    results: list[dict[str, Any]] = []
    tmp = ROOT / "frames_tmp"
    only = ""
    cooldown = 15.0
    for a in argv:
        if a.startswith("--only="):
            only = a.split("=", 1)[1]
        if a.startswith("--cooldown="):
            cooldown = float(a.split("=", 1)[1])

    for cfg in CONFIGS:
        if only and cfg["id"] != only:
            continue
        # Jeda antar konfigurasi: tanpa ini, sisa tekanan memori dari run
        # sebelumnya membuat konfigurasi berikutnya gagal karena watchdog,
        # bukan karena kemampuannya sendiri.
        if results and cooldown > 0:
            time.sleep(cooldown)
        for r in range(runs):
            res = one_run(cfg, frames, browser, tmp)
            res["run"] = r + 1
            results.append(res)
            status = res.get("error") or (
                f"{res['fps']:.2f} fps  RSS {res['rss_mb']:.0f} MB  "
                f"turun {res.get('avail_drop_mb', 0):.0f} MB  swap {res['swap_pages']}  "
                f"alpha={res['alpha_ok']}"
            )
            print(f"  {cfg['id']:>9} k={cfg['concurrency']} run {r + 1}: {status}", flush=True)

    payload = {
        "frames": frames,
        "runs_per_config": runs,
        "browser": browser,
        "runs": results,
    }
    (ROOT / "remotion.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\n✓ {ROOT / 'remotion.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
