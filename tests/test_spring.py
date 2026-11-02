"""Tes `scripts.lib.spring` — respons langkah massa-pegas teredam.

Semua toleransi diberi alasan di komentar, karena tes yang terlalu longgar
meloloskan implementasi yang salah (pelajaran putaran sebelumnya).
"""

from __future__ import annotations

import math
import unittest

from tests.helpers import ROOT  # noqa: F401

from scripts.lib import spring

# Bawaan "pop kata" dari docs/MOTION-TIER2-PLAN.md: m=1, k=700, c=32.
K, M, C = 700.0, 1.0, 32.0

# c kritis untuk k=700, m=1: 2*sqrt(700) = 52.915...
C_CRIT = 2.0 * math.sqrt(K * M)
# Overdamped jelas: zeta = 200/(2 sqrt 700) = 3.78
C_OVER = 200.0


def _peak(k: float = K, m: float = M, c: float = C, t_max: float = 0.6, dt: float = 1e-4) -> tuple[float, float]:
    """Puncak numerik (t, x) pada grid halus dt = 0,1 ms."""
    best_t, best_x = 0.0, 0.0
    n = int(round(t_max / dt))
    for i in range(n + 1):
        t = i * dt
        x = spring.spring(t, k=k, m=m, c=c)
        if x > best_x:
            best_t, best_x = t, x
    return best_t, best_x


class StepResponseTest(unittest.TestCase):
    def test_zero_at_zero(self) -> None:
        self.assertEqual(spring.spring(0.0), 0.0)

    def test_zero_for_negative_time(self) -> None:
        for t in (-1e-9, -0.5, -3.0):
            self.assertEqual(spring.spring(t), 0.0)

    def test_converges_to_one_in_three_regimes(self) -> None:
        """x(3 s) dalam +-0,5% dari 1 untuk zeta < 1, = 1, > 1.

        0,5% dipilih dari rencana. Pada 3 s sisa galat bawaan ~1e-11, kritis 0,
        overdamped c=200 (zeta 3,78) ~2,3e-5, jadi 0,5% longgar tetapi tetap
        mematikan mutan yang salah tanda/rumus (yang menyimpang >> 1).
        """
        for c in (C, C_CRIT, C_OVER):
            x = spring.spring(3.0, k=K, m=M, c=c)
            self.assertAlmostEqual(
                x, 1.0, delta=0.005, msg=f"c={c}: x(3.0)={x!r} di luar +-0,5%"
            )

    def test_small_time_is_quadratic(self) -> None:
        """x(t) ~ 0,5 (k/m) t^2 untuk t kecil (x(0)=0, x'(0)=0, x''(0)=k/m).

        Ini tes ekstra di luar daftar rencana, dan yang paling tajam untuk
        salah koefisien di cabang underdamped: menukar (z w0 / wd) dengan
        (wd / z w0) memberi x(1e-4) = -0,0048 alih-alih +3,496e-6.
        Toleransi 1% cukup: pada t=1e-4 suku orde t^4 hanya ~5e-7 relatif.
        """
        t = 1e-4
        expected = 0.5 * (K / M) * t * t
        x = spring.spring(t, k=K, m=M, c=C)
        self.assertGreater(x, 0.0, "x harus positif di awal (tidak boleh undershoot)")
        self.assertAlmostEqual(x / expected, 1.0, delta=0.01, msg=f"x({t})={x!r}")

    def test_overshoot_matches_theory(self) -> None:
        """Overshoot puncak numerik ~ exp(-pi zeta / sqrt(1-zeta^2)) dalam +-1%.

        Toleransi 1% dari rencana. Grid 0,1 ms membuat galat lokasi puncak
        ~(dt^2/2)*|x''| ~ 1e-9, jadi 1% tetap longgar; mutan tukar koefisien
        menyimpang 7,1% dan tertangkap.
        """
        zeta = spring.damping_ratio(K, M, C)
        self.assertAlmostEqual(zeta, 0.6047, delta=5e-4)
        theoretical = math.exp(-math.pi * zeta / math.sqrt(1.0 - zeta * zeta))
        _, peak = _peak()
        measured = peak - 1.0
        rel = abs(measured - theoretical) / theoretical
        self.assertLess(
            rel,
            0.01,
            msg=f"overshoot {measured:.6f} vs teori {theoretical:.6f} (rel {rel:.2%})",
        )

    def test_underdamped_has_positive_overshoot(self) -> None:
        """Mutan yang memakai rumus overdamped di cabang underdamped -> tidak ada overshoot."""
        _, peak = _peak()
        self.assertGreater(peak, 1.05)

    def test_critical_and_overdamped_monotone_and_bounded(self) -> None:
        """zeta >= 1: tidak pernah turun dan tidak pernah > 1 + 1e-12.

        Slack 1e-12 hanya untuk pembulatan double (1 ulp ~ 1,1e-16);
        overshoot nyata sekecil apa pun akan lolos jauh di atasnya.
        """
        for c in (C_CRIT, C_OVER):
            prev = -math.inf
            for i in range(0, 3001):
                t = i * 1e-3
                x = spring.spring(t, k=K, m=M, c=c)
                self.assertGreaterEqual(
                    x, prev, msg=f"c={c}: turun di t={t:.3f} ({prev!r} -> {x!r})"
                )
                self.assertLessEqual(
                    x, 1.0 + 1e-12, msg=f"c={c}: melewati 1 di t={t:.3f} ({x!r})"
                )
                prev = x

    def test_continuous_at_critical_damping(self) -> None:
        """Cabang kritis harus menyambung dengan cabang di kiri-kanannya.

        c sedikit di bawah/atas kritis (relatif 1e-6, zeta menyimpang 1e-6)
        harus memberi x dalam 1e-3 dari x kritis. Terukur: selisih maks
        4,4e-7. Mutan "lupa menangani zeta=1" (pembagian wd=0) error;
        mutan pita toleransi terlalu lebar (mis. 0,1) menyimpang 2,2e-2.
        """
        for sign in (-1.0, 1.0):
            c = C_CRIT * (1.0 + sign * 1e-6)
            worst = 0.0
            for i in range(0, 101):
                t = i * 0.005  # 0 .. 0,5 s
                diff = abs(spring.spring(t, k=K, m=M, c=c) - spring.spring(t, k=K, m=M, c=C_CRIT))
                worst = max(worst, diff)
            self.assertLess(
                worst, 1e-3, msg=f"c={c!r} (sisi {sign:+.0f}): selisih maks {worst!r}"
            )


class DefaultPopTest(unittest.TestCase):
    def test_peak_time_in_planned_window(self) -> None:
        """Puncak bawaan 0,12-0,18 s (rencana: ~0,15 s). Teori pi/wd = 0,1491 s."""
        peak_t, _ = _peak()
        self.assertGreaterEqual(peak_t, 0.12, msg=f"puncak {peak_t:.4f} s")
        self.assertLessEqual(peak_t, 0.18, msg=f"puncak {peak_t:.4f} s")

    def test_settle_time_in_planned_window(self) -> None:
        """Settle 2% bawaan 0,20-0,32 s (rencana: ~0,25 s). Terukur 0,224 s."""
        s = spring.settle_time(K, M, C)
        self.assertGreaterEqual(s, 0.20, msg=f"settle {s:.4f} s")
        self.assertLessEqual(s, 0.32, msg=f"settle {s:.4f} s")

    def test_settle_time_is_last_excursion(self) -> None:
        """Sesudah settle_time, |x-1| <= tol sepanjang sisa horizon.

        Ini membedakan "waktu terakhir keluar tol" dari "waktu pertama masuk tol":
        yang pertama ~0,224 s, yang kedua ~0,11 s.
        """
        s = spring.settle_time(K, M, C, tol=0.02)
        for i in range(int(s * 1000) + 1, 5001):
            t = i / 1000.0
            self.assertLessEqual(abs(spring.spring(t) - 1.0), 0.02, msg=f"t={t:.3f}")

    def test_damping_ratio_default(self) -> None:
        self.assertAlmostEqual(spring.damping_ratio(K, M, C), 0.6047431568, delta=1e-9)


class SampleTest(unittest.TestCase):
    def test_exact_point_count(self) -> None:
        """ceil(dur*fps)+1 titik, tanpa kehilangan frame karena galat float.

        0,7*30 = 21,000000000000004 dan (1/3)*30 = 10,000000000000002:
        ceil tanpa pembulatan memberi 23 dan 12 titik (salah); int() memberi
        22 dan 11 (kebetulan benar untuk 0,7, salah untuk 1/3).
        """
        # Kasus terakhir sengaja dipilih dari hasil pindai: durasi*fps di sana
        # jatuh TEPAT di atas bilangan bulat karena galat float
        # (0,28*25 = 7.000000000000001; 1,12*50 = 28.000000000000004;
        #  1,1*50 = 55.00000000000001). Tanpa `round(..., 9)` hasilnya
        # kelebihan satu frame -> mutan "ceil tanpa round" tertangkap.
        cases = [
            (0.5, 30),
            (1.0, 30),
            (0.7, 30),
            (0.2, 24),
            (1 / 3, 30),
            (0.28, 25),
            (1.12, 50),
            (1.1, 50),
            (0.56, 25),
        ]
        for duration, fps in cases:
            pts = spring.sample(duration, fps)
            expected = math.ceil(round(duration * fps, 9)) + 1
            self.assertEqual(
                len(pts), expected, msg=f"dur={duration!r} fps={fps}: {len(pts)} != {expected}"
            )

    def test_times_are_frame_times(self) -> None:
        fps = 30
        pts = spring.sample(0.5, fps)
        for i, (t, _x) in enumerate(pts):
            self.assertEqual(t, i / fps, msg=f"titik {i}: {t!r} != {i / fps!r}")

    def test_first_point_is_origin(self) -> None:
        pts = spring.sample(0.5, 30)
        self.assertEqual(pts[0], (0.0, 0.0))

    def test_values_match_spring(self) -> None:
        for t, x in spring.sample(0.2, 24):
            self.assertAlmostEqual(x, spring.spring(t), delta=1e-12)

    def test_zero_duration_single_point(self) -> None:
        self.assertEqual(spring.sample(0.0, 30), [(0.0, 0.0)])

    def test_bad_fps_rejected(self) -> None:
        with self.assertRaises(ValueError):
            spring.sample(1.0, 0)


class ValidationTest(unittest.TestCase):
    def test_non_positive_parameters_rejected(self) -> None:
        for kwargs in ({"k": 0.0}, {"k": -1.0}, {"m": 0.0}, {"m": -2.0}, {"c": 0.0}, {"c": -0.5}):
            args = {"k": K, "m": M, "c": C, **kwargs}
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    spring.spring(0.1, **args)
                with self.assertRaises(ValueError):
                    spring.damping_ratio(**args)
                with self.assertRaises(ValueError):
                    spring.settle_time(**args)

    def test_nan_parameter_rejected(self) -> None:
        with self.assertRaises(ValueError):
            spring.spring(0.1, k=float("nan"))


if __name__ == "__main__":
    unittest.main()
