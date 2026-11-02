"""Vonis gate untuk kelayakan Remotion di mesin ini.

Ambang ditetapkan lebih dulu, sebelum ada angka. Kalau ambang ditentukan setelah
melihat hasil, gate-nya tidak menjaga apa pun.

  RSS pohon <= 1,0 GB   RAM tersedia 1,6-1,9 GiB dan swap sudah penuh, jadi
                        Chromium di atas 1 GB berarti tidak ada jaring pengaman.
  >= 2,5 fps @1080x1920 cukup cepat untuk overlay beberapa detik.
  swap tidak bergerak   kalau pswpout naik, rendering memindahkan halaman ke disk;
                        itu bukan "lambat", itu hampir macet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RSS_MAX_MB = 1024.0
FPS_GO = 2.5
FPS_SPARSE_MIN = 1.5
SWAP_MAX_PAGES = 10000  # ~40 MB; di atas ini dianggap thrash

RANK = {"NO_GO": 0, "GO_SPARSE": 1, "GO": 2}


def verdict(result: dict[str, Any]) -> str:
    """GO / GO_SPARSE / NO_GO untuk satu hasil pengukuran."""
    if not result.get("alpha_ok", False):
        return "NO_GO"
    if float(result.get("rss_mb", 0.0)) > RSS_MAX_MB:
        return "NO_GO"
    if int(result.get("swap_pages", 0)) > SWAP_MAX_PAGES:
        return "NO_GO"
    fps = float(result.get("fps", 0.0))
    if fps >= FPS_GO:
        return "GO"
    if fps >= FPS_SPARSE_MIN:
        return "GO_SPARSE"
    return "NO_GO"


def overall(runs: list[dict[str, Any]]) -> str:
    """Vonis keseluruhan = yang terburuk, karena satu konfigurasi jelek cukup
    untuk membuat render tidak bisa diandalkan."""
    if not runs:
        return "NO_GO"
    return min((verdict(r) for r in runs), key=lambda v: RANK[v])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("pakai: python3 -m benchmarks.gate <remotion.json>")
        return 2
    data = json.loads(Path(argv[0]).read_text())
    runs = data.get("runs", [])

    print(f"{'ukuran':>12} {'konk':>5} {'fps':>6} {'RSS MB':>8} {'swap':>7}  vonis")
    for r in runs:
        size = f"{r.get('width', '?')}x{r.get('height', '?')}"
        print(
            f"{size:>12} {r.get('concurrency', '?'):>5} "
            f"{float(r.get('fps', 0)):>6.2f} {float(r.get('rss_mb', 0)):>8.0f} "
            f"{int(r.get('swap_pages', 0)):>7}  {verdict(r)}"
        )

    final = overall(runs)
    print()
    print(f"VONIS: {final}")
    if final == "NO_GO":
        print("Langkah 6 (overlay Remotion) dibekukan. Langkah 2-5 tetap jalan.")
    elif final == "GO_SPARSE":
        print("Hanya overlay jarang yang layak; overlay seluruh klip tidak.")
    else:
        print("Overlay Remotion layak, dengan konkurensi 1 dan watchdog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
