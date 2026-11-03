"""Metrik mask untuk spike matte (Langkah 1b).

Semua fungsi memakai mask sebagai array 2D: bilangan bulat (> 127 dianggap depan)
atau float (>= 0,5 dianggap depan). numpy hanya dibutuhkan oleh fungsi yang
memproses piksel; `percentile` dan `face_in_matte_ratio` murni Python.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy opsional
    np = None

AREA_MIN = 0.03
AREA_MAX = 0.90
FACE_COVER_MIN = 0.90   # sebuah wajah dianggap "di dalam" bila >= 90% kotaknya tertutup mask
FACE_MIN_FRAMES = 10    # kurang dari ini, proporsinya tidak bermakna


def percentile(values: Sequence[float], q: float) -> float:
    """Persentil interpolasi linear, tanpa numpy. Kosong -> 0,0."""
    if not values:
        return 0.0
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (q / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def face_in_matte_ratio(
    coverages: Sequence[float],
    min_frames: int = FACE_MIN_FRAMES,
    threshold: float = FACE_COVER_MIN,
) -> float | None:
    """Proporsi frame berwajah yang wajahnya tertutup mask >= `threshold`.
    None bila frame berwajah terlalu sedikit."""
    if len(coverages) < min_frames:
        return None
    return sum(1 for c in coverages if c >= threshold) / len(coverages)


def _binary(mask: Any) -> Any:
    a = np.asarray(mask)
    if a.dtype.kind == "b":
        return a  # sudah biner; `True > 127` akan salah menghasilkan semua False
    if a.dtype.kind == "f":
        return a >= 0.5
    return a > 127


def area_fraction(mask: Any) -> float:
    return float(_binary(mask).mean())


def area_ok(mask: Any, lo: float = AREA_MIN, hi: float = AREA_MAX) -> bool:
    """Menangkap mask kosong (model gagal) dan mask penuh (semua jadi orang)."""
    return lo <= area_fraction(mask) <= hi


def perimeter(mask: Any) -> int:
    """Jumlah piksel depan yang bertetangga-4 dengan piksel bukan-depan.

    Tepi frame BUKAN tepi objek (orang yang terpotong tepi bawah tidak punya garis
    di sana), jadi di luar frame dianggap sama dengan piksel terdekat."""
    fg = _binary(mask)
    p = np.pad(fg, 1, mode="edge")
    interior = p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return int((fg & ~interior).sum())


def edge_shift(prev: Any, cur: Any) -> float:
    """Rata-rata pergeseran tepi antara dua mask berurutan, dalam piksel.

    `|XOR| / rata-rata keliling`. Ini rata-rata sepanjang SELURUH tepi: persegi yang
    bergeser 2 px hanya menggerakkan dua dari empat sisinya, jadi nilainya ~1."""
    a = _binary(prev)
    b = _binary(cur)
    xor = int((a ^ b).sum())
    if xor == 0:
        return 0.0
    perim = (perimeter(a) + perimeter(b)) / 2.0
    return xor / max(perim, 1.0)


def flicker(prev: Any, cur: Any, nxt: Any) -> float:
    """Kedip tepi pada `cur`: piksel yang `prev == nxt` tetapi `cur` berbeda (menyala lalu
    padam, atau sebaliknya), dibagi keliling `cur`. Satuannya piksel amplitudo kedip.

    Gerak searah (tangan bergerak, kepala menoleh) menghasilkan 0, karena piksel yang
    berubah tidak kembali. Itu yang memisahkan jitter model dari isi video; `edge_shift`
    tidak bisa karena ia menghitung gerak asli sebagai getaran."""
    a, b, c = _binary(prev), _binary(cur), _binary(nxt)
    blink = int(((a == c) & (a != b)).sum())
    if blink == 0:
        return 0.0
    return blink / max(float(perimeter(b)), 1.0)


def lag_px(smoothed: Any, raw: Any) -> float:
    """Kelambanan penghalusan temporal: |XOR(mask halus, mask mentah)| / keliling(mask mentah).

    Satuannya piksel jarak rata-rata tepi halus dari tepi mentah, diukur sepanjang tepi
    mask MENTAH (penyebutnya mentah: mask halus yang menyusut tidak boleh membuat nilai
    tampak kecil karena kelilingnya ikut mengecil). Mask mentah berderau, jadi nilainya
    tidak pernah 0 di data nyata; skalanya datang dari kontrol bobot 0,6."""
    a = _binary(smoothed)
    b = _binary(raw)
    xor = int((a ^ b).sum())
    if xor == 0:
        return 0.0
    return xor / max(float(perimeter(b)), 1.0)


def face_coverage(mask: Any, box: Sequence[float]) -> float:
    """Proporsi ELIPS terpancang di kotak wajah (x, y, w, h) yang berada di dalam mask.

    Bukan kotaknya: wajah oval tidak bisa mengisi kotak persegi (sudut ~21% luas jatuh di
    latar atau rambut), jadi mask yang sempurna pun hanya mencapai ~78,5% pada kotak dan
    tidak akan pernah lolos ambang 90%. Bagian elips di luar frame dibuang dari penyebut."""
    fg = _binary(mask)
    h, w = fg.shape
    x, y, bw, bh = (float(v) for v in box)
    if bw <= 0 or bh <= 0:
        return 0.0
    x0, y0 = max(0, int(math.floor(x))), max(0, int(math.floor(y)))
    x1, y1 = min(w, int(math.ceil(x + bw))), min(h, int(math.ceil(y + bh)))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    ys, xs = np.mgrid[y0:y1, x0:x1]
    cx, cy = x + bw / 2.0, y + bh / 2.0
    inside = ((xs + 0.5 - cx) / (bw / 2.0)) ** 2 + ((ys + 0.5 - cy) / (bh / 2.0)) ** 2 <= 1.0
    n = int(inside.sum())
    if n == 0:
        return 0.0
    return float(fg[y0:y1, x0:x1][inside].sum()) / n


CUT_THRESHOLD = 20.0  # sama dengan scripts/faces.py


def is_cut(prev_thumb: Any, thumb: Any, threshold: float = CUT_THRESHOLD) -> bool:
    """Pergantian shot dari dua thumbnail abu-abu (32x18): beda rata-rata > ambang.
    Frame pertama (prev None) tidak pernah cut."""
    if prev_thumb is None:
        return False
    d = np.abs(np.asarray(prev_thumb).astype(np.int16) - np.asarray(thumb).astype(np.int16))
    return float(d.mean()) > threshold
