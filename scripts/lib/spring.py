"""Respons langkah sistem massa-pegas teredam (0 -> 1), stdlib saja.

Dipakai untuk "pop kata" caption kinetic: skala 60% -> 100% mengikuti x(t).
Rumus persis dari docs/MOTION-TIER2-PLAN.md (Langkah 3):

    w0 = sqrt(k/m), z = c / (2 sqrt(km)), wd = w0 sqrt(1 - z^2)
    z < 1 : x(t) = 1 - e^(-z w0 t) (cos(wd t) + (z w0 / wd) sin(wd t))
    z = 1 : x(t) = 1 - e^(-w0 t) (1 + w0 t)
    z > 1 : x(t) = 1 - (r2 e^(r1 t) - r1 e^(r2 t)) / (r2 - r1)
            r1,2 = -w0 (z -+ sqrt(z^2 - 1))

Tidak ada dependensi (D-004): hanya `math`.
"""

from __future__ import annotations

import math

__all__ = ["CRITICAL_TOL", "damping_ratio", "sample", "settle_time", "spring"]

# Pita |z - 1| < CRITICAL_TOL memakai rumus kritis.
# Alasan: di dekat z = 1, wd = w0 sqrt(1 - z^2) -> 0 sehingga suku
# (z w0 / wd) sin(wd t) adalah 0/0 secara numerik; rumus kritis adalah limit
# analitiknya. 1e-9 cukup lebar untuk membunuh galat pembulatan double
# (z dihitung dari c / (2 sqrt(km))) dan cukup sempit untuk tidak mengubah
# bentuk kurva: pada |z - 1| = 1e-9 selisih x(t) terhadap limit < 5e-10.
CRITICAL_TOL = 1e-9

# Bawaan "pop kata" dari rencana: m=1, k=700, c=32.
DEFAULT_K = 700.0
DEFAULT_M = 1.0
DEFAULT_C = 32.0


def _validate(k: float, m: float, c: float) -> None:
    """k, m, c harus positif dan berhingga. NaN ikut ditolak (NaN > 0 = False)."""
    for name, value in (("k", k), ("m", m), ("c", c)):
        if not (value > 0.0) or not math.isfinite(value):
            raise ValueError(f"{name} harus > 0 dan berhingga, dapat {value!r}")


def damping_ratio(k: float = DEFAULT_K, m: float = DEFAULT_M, c: float = DEFAULT_C) -> float:
    """Rasio redaman z = c / (2 sqrt(k m)). z < 1 underdamped, z = 1 kritis."""
    _validate(k, m, c)
    return c / (2.0 * math.sqrt(k * m))


def spring(
    t: float,
    k: float = DEFAULT_K,
    m: float = DEFAULT_M,
    c: float = DEFAULT_C,
) -> float:
    """Posisi massa saat t untuk respons langkah 0 -> 1. t <= 0 -> 0.0 persis."""
    _validate(k, m, c)
    if t <= 0.0:
        return 0.0

    w0 = math.sqrt(k / m)
    z = c / (2.0 * math.sqrt(k * m))

    if abs(z - 1.0) < CRITICAL_TOL:
        # z = 1: 1 - e^(-w0 t) (1 + w0 t)
        return 1.0 - math.exp(-w0 * t) * (1.0 + w0 * t)

    if z < 1.0:
        wd = w0 * math.sqrt(1.0 - z * z)
        envelope = math.exp(-z * w0 * t)
        return 1.0 - envelope * (
            math.cos(wd * t) + (z * w0 / wd) * math.sin(wd * t)
        )

    # z > 1 (overdamped)
    root = math.sqrt(z * z - 1.0)
    r1 = -w0 * (z - root)
    r2 = -w0 * (z + root)
    return 1.0 - (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / (r2 - r1)


def sample(
    duration: float,
    fps: float,
    k: float = DEFAULT_K,
    m: float = DEFAULT_M,
    c: float = DEFAULT_C,
) -> list[tuple[float, float]]:
    """Sampel x(t) pada waktu frame: ceil(dur*fps)+1 titik, t_i = i/fps.

    Pembulatan 9 desimal sebelum ceil mencegah kelebihan frame akibat galat
    float. Contoh nyata yang sudah diverifikasi: 0.28*25 = 7.000000000000001,
    1.12*50 = 28.000000000000004, dan 1.1*50 = 55.00000000000001; ceil tanpa
    pembulatan memberi 8, 29, dan 56 titik, padahal seharusnya 7, 28, 55.
    """
    if not (fps > 0.0) or not math.isfinite(fps):
        raise ValueError(f"fps harus > 0 dan berhingga, dapat {fps!r}")
    if not math.isfinite(duration):
        raise ValueError(f"duration harus berhingga, dapat {duration!r}")
    frames = math.ceil(round(duration * fps, 9))
    if frames < 0:
        frames = 0
    return [(i / fps, spring(i / fps, k=k, m=m, c=c)) for i in range(frames + 1)]


def settle_time(
    k: float = DEFAULT_K,
    m: float = DEFAULT_M,
    c: float = DEFAULT_C,
    tol: float = 0.02,
    horizon: float = 5.0,
    step: float = 1.0 / 1000.0,
) -> float:
    """Waktu terakhir |x(t) - 1| > tol, dicari numerik pada grid `step`.

    horizon 5 s cukup: pada bawaan |x-1| < 2% sejak 0,224 s dan meluruh
    eksponensial (z w0 = 16 s^-1), jadi tidak ada lintasan balik di luar tol.
    """
    if not (step > 0.0) or not math.isfinite(step):
        raise ValueError(f"step harus > 0 dan berhingga, dapat {step!r}")
    if not (horizon > 0.0) or not math.isfinite(horizon):
        raise ValueError(f"horizon harus > 0 dan berhingga, dapat {horizon!r}")
    _validate(k, m, c)

    last = 0.0
    steps = int(round(horizon / step))
    for i in range(steps + 1):
        t = i * step
        if abs(spring(t, k=k, m=m, c=c) - 1.0) > tol:
            last = t
    return last
