"""Diagnostik: apakah frame diam lebih murah per frame daripada frame animasi?

Merender hanya fase hold (90 frame) dan hanya frame animasi (30 frame: masuk 0-14 + keluar 105-119)
pada ukuran yang sama, lewat jalur render yang sama dengan holdframe.py. Hasil: holdframe_diag.json.

  python3 -B benchmarks/holdframe_diag.py [--size=600] [--reps=2]
"""

from __future__ import annotations

import json
import shutil
import statistics
import sys
import time

import holdframe as hf

SPECS = {
    "hold_only_90": f"{hf.HOLD_FIRST}-{hf.HOLD_LAST}",
    "animated_only_30": f"0-{hf.HOLD_FIRST - 1},{hf.N - hf.EXIT_F}-{hf.N - 1}",
}


def main(argv: list[str]) -> int:
    size, reps = "600", 2
    for a in argv:
        if a.startswith("--size="):
            size = a.split("=", 1)[1]
        elif a.startswith("--reps="):
            reps = int(a.split("=", 1)[1])
    if hf.stray_renderers():
        print("render lain sedang berjalan, dibatalkan")
        return 3
    comp = hf.SIZES[size]["id"]
    base = hf.ROOT / "holdframe_diag_work"
    res: dict[str, list[dict[str, float]]] = {k: [] for k in SPECS}
    for rep in range(reps):
        order = list(SPECS) if rep % 2 == 0 else list(reversed(list(SPECS)))
        for name in order:
            time.sleep(hf.COOLDOWN_S)
            r = hf.render(comp, SPECS[name], base / name, hf.DEFAULT_BROWSER, base / f"log_{name}_{rep}")
            if not r["ok"]:
                print("gagal:", name, r["error"])
                shutil.rmtree(base, ignore_errors=True)
                return 1
            n = r["files"]
            ms = r["inner"]["render_ms"]
            res[name].append({"frames": n, "render_s": ms / 1000, "ms_per_frame": ms / n, "wall_s": r["wall_s"]})
            print(f"  {name:>17} #{rep + 1}: {n} frame  render {ms / 1000:.2f}s  {ms / n:.0f} ms/frame", flush=True)
    shutil.rmtree(base, ignore_errors=True)
    out = {
        "id": comp, "reps": reps,
        "specs": SPECS,
        "runs": res,
        "median_ms_per_frame": {k: round(statistics.median(x["ms_per_frame"] for x in v), 1) for k, v in res.items()},
        "note": "ms/frame = render_ms dalam proses / jumlah frame; berisi biaya awal per panggilan renderFrames yang ikut terbagi",
    }
    (hf.ROOT / "holdframe_diag.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["median_ms_per_frame"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
