"""Tes metrik mask (Langkah 1b).

Metrik dihitung dengan numpy, yang hanya ada bila langkah opsional OpenCV terpasang,
jadi tes ini di-skip tanpa numpy. Persentil sengaja bebas numpy.
"""

from __future__ import annotations

import unittest

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from benchmarks import matte_metrics as m


def rect(h: int, w: int, y: int, x: int, rh: int, rw: int):
    a = np.zeros((h, w), dtype=np.uint8)
    a[y : y + rh, x : x + rw] = 255
    return a


class PercentileTest(unittest.TestCase):
    def test_linear_interpolation(self) -> None:
        self.assertEqual(m.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(m.percentile([1, 2, 3, 4, 5], 95), 4.8)

    def test_edges_and_degenerate(self) -> None:
        self.assertEqual(m.percentile([7], 95), 7)
        self.assertEqual(m.percentile([], 50), 0.0)
        self.assertEqual(m.percentile([3, 1, 2], 0), 1)
        self.assertEqual(m.percentile([3, 1, 2], 100), 3)


class FaceRatioTest(unittest.TestCase):
    """Murni Python: proporsi frame yang wajahnya >= 90% berada di dalam mask."""

    def test_counts_frames_over_threshold(self) -> None:
        cov = [1.0] * 17 + [0.89] * 3
        self.assertAlmostEqual(m.face_in_matte_ratio(cov), 17 / 20)

    def test_threshold_is_inclusive(self) -> None:
        self.assertEqual(m.face_in_matte_ratio([0.9] * 12), 1.0)

    def test_too_few_faces_means_no_metric(self) -> None:
        self.assertIsNone(m.face_in_matte_ratio([1.0] * 9))
        self.assertIsNone(m.face_in_matte_ratio([]))
        self.assertEqual(m.face_in_matte_ratio([1.0] * 10), 1.0)


@unittest.skipIf(np is None, "numpy tidak terpasang")
class PerimeterTest(unittest.TestCase):
    def test_rectangle_inside_frame(self) -> None:
        self.assertEqual(m.perimeter(rect(100, 100, 20, 20, 40, 30)), 2 * (40 + 30) - 4)

    def test_frame_border_is_not_an_edge(self) -> None:
        # orang yang terpotong tepi bawah frame: sisi bawah bukan tepi objek
        mask = rect(100, 100, 60, 20, 40, 30)  # menempel baris terakhir
        self.assertEqual(m.perimeter(mask), 30 + 2 * (40 - 1))

    def test_empty_and_full(self) -> None:
        self.assertEqual(m.perimeter(np.zeros((10, 10), np.uint8)), 0)
        self.assertEqual(m.perimeter(np.full((10, 10), 255, np.uint8)), 0)


@unittest.skipIf(np is None, "numpy tidak terpasang")
class EdgeShiftTest(unittest.TestCase):
    def test_identical_masks_are_zero(self) -> None:
        a = rect(100, 100, 20, 20, 40, 40)
        self.assertEqual(m.edge_shift(a, a.copy()), 0.0)

    def test_two_empty_masks_do_not_divide_by_zero(self) -> None:
        z = np.zeros((50, 50), np.uint8)
        self.assertEqual(m.edge_shift(z, z), 0.0)

    def test_uniform_growth_of_two_pixels_is_about_two(self) -> None:
        a = rect(120, 120, 40, 40, 40, 40)
        b = rect(120, 120, 38, 38, 44, 44)
        self.assertAlmostEqual(m.edge_shift(a, b), 2.0, delta=0.15)

    def test_horizontal_shift_moves_only_two_of_four_sides(self) -> None:
        a = rect(120, 120, 40, 40, 40, 40)
        b = rect(120, 120, 40, 42, 40, 40)
        expected = (4 * 40) / (2 * (40 + 40) - 4)
        self.assertAlmostEqual(m.edge_shift(a, b), expected, places=6)

    def test_binarizes_soft_masks(self) -> None:
        a = rect(60, 60, 10, 10, 20, 20)
        soft = (a.astype(np.float32) / 255.0) * 0.9  # alpha 0.9 di dalam, 0 di luar
        self.assertEqual(m.edge_shift(a, soft), 0.0)


@unittest.skipIf(np is None, "numpy tidak terpasang")
class LagTest(unittest.TestCase):
    """`lag` = |XOR(mask halus, mask mentah)| / keliling(mask mentah).

    Biaya penghalusan temporal: makin kuat penghalusan, makin kecil flicker, tapi tepi
    mask halus tertinggal dari tepi mask mentah di benda yang bergerak."""

    def test_identical_masks_are_zero(self) -> None:
        a = rect(120, 120, 40, 40, 40, 40)
        self.assertEqual(m.lag_px(a, a.copy()), 0.0)

    def test_lag_of_three_pixels_is_two_sides_over_perimeter(self) -> None:
        raw = rect(120, 120, 40, 40, 40, 40)
        smoothed = rect(120, 120, 40, 43, 40, 40)  # tertinggal 3 px horizontal
        expected = (6 * 40) / (2 * (40 + 40) - 4)   # 240 / 156
        self.assertAlmostEqual(m.lag_px(smoothed, raw), expected, places=6)

    def test_binarizes_soft_masks(self) -> None:
        a = rect(60, 60, 10, 10, 20, 20)
        soft = (a.astype(np.float32) / 255.0) * 0.9  # alpha 0.9 di dalam, 0 di luar
        self.assertEqual(m.lag_px(soft, a), 0.0)

    def test_two_empty_masks_do_not_divide_by_zero(self) -> None:
        z = np.zeros((50, 50), np.uint8)
        self.assertEqual(m.lag_px(z, z), 0.0)

    def test_mixed_types_are_accepted(self) -> None:
        # mask halus dari produksi float32, mask mentah uint8
        raw = rect(120, 120, 40, 40, 40, 40)
        smoothed = rect(120, 120, 40, 43, 40, 40).astype(np.float32)
        self.assertAlmostEqual(m.lag_px(smoothed, raw), 240 / 156, places=6)


def ellipse_mask(h: int, w: int, cx: float, cy: float, rx: float, ry: float):
    ys, xs = np.mgrid[0:h, 0:w]
    inside = ((xs + 0.5 - cx) / rx) ** 2 + ((ys + 0.5 - cy) / ry) ** 2 <= 1.0
    return inside.astype(np.uint8) * 255


@unittest.skipIf(np is None, "numpy tidak terpasang")
class FlickerTest(unittest.TestCase):
    """Piksel yang berkedip balik (A == C != B) dibagi keliling B. Gerak searah = 0."""

    def test_static_mask_is_zero(self) -> None:
        a = rect(120, 120, 40, 40, 40, 40)
        self.assertEqual(m.flicker(a, a.copy(), a.copy()), 0.0)

    def test_consistent_motion_is_zero(self) -> None:
        a = rect(120, 120, 40, 30, 40, 40)
        b = rect(120, 120, 40, 32, 40, 40)
        c = rect(120, 120, 40, 34, 40, 40)
        self.assertEqual(m.flicker(a, b, c), 0.0)

    def test_one_pixel_blink_is_one(self) -> None:
        a = rect(120, 120, 40, 40, 40, 40)
        b = rect(120, 120, 39, 39, 42, 42)  # mengembang 1 px lalu kembali
        c = a.copy()
        # cincin 1 px = 42*42 - 40*40 = 164; keliling b = 2*(42+42)-4 = 164
        self.assertAlmostEqual(m.flicker(a, b, c), 1.0, places=6)

    def test_two_empty_masks_do_not_divide_by_zero(self) -> None:
        z = np.zeros((30, 30), np.uint8)
        self.assertEqual(m.flicker(z, z, z), 0.0)

    def test_binarizes_soft_masks(self) -> None:
        a = rect(60, 60, 10, 10, 20, 20)
        soft = (a.astype(np.float32) / 255.0) * 0.9
        self.assertEqual(m.flicker(a, soft, a), 0.0)


@unittest.skipIf(np is None, "numpy tidak terpasang")
class FaceCoverageTest(unittest.TestCase):
    """Cakupan dihitung pada ELIPS yang terpancang di kotak wajah, bukan pada kotaknya.

    Wajah oval tidak bisa mengisi kotak persegi: sudut kotak (~21% luas) jatuh di latar
    atau rambut. Mask yang sempurna pun akan gagal ambang 90% bila dinilai pada kotak."""

    def setUp(self) -> None:
        self.mask = rect(100, 100, 0, 0, 100, 50)  # separuh kiri frame

    def test_inside_outside_straddling(self) -> None:
        self.assertEqual(m.face_coverage(self.mask, (10, 10, 20, 20)), 1.0)
        self.assertEqual(m.face_coverage(self.mask, (60, 10, 20, 20)), 0.0)
        self.assertAlmostEqual(m.face_coverage(self.mask, (40, 10, 20, 20)), 0.5)

    def test_a_perfect_oval_head_scores_one(self) -> None:
        box = (30, 20, 40, 60)  # x, y, w, h
        head = ellipse_mask(100, 100, 50, 50, 20, 30)
        self.assertGreaterEqual(m.face_coverage(head, box), 0.99)

    def test_the_corner_trap(self) -> None:
        # alasan metrik ini ada: pada KOTAK, kepala sempurna hanya ~78,5%
        box = (30, 20, 40, 60)
        head = ellipse_mask(100, 100, 50, 50, 20, 30)
        x, y, w, h = box
        on_box = float((head[y : y + h, x : x + w] > 0).mean())
        self.assertAlmostEqual(on_box, 3.14159265 / 4, delta=0.02)
        self.assertLess(on_box, 0.90)

    def test_a_hole_in_the_face_is_caught(self) -> None:
        box = (30, 20, 40, 60)
        full = rect(100, 100, 0, 0, 100, 100)
        self.assertEqual(m.face_coverage(full, box), 1.0)
        holed = full.copy()
        holed[40:60, 40:60] = 0  # lubang di tengah wajah (mis. kacamata hilang)
        self.assertLess(m.face_coverage(holed, box), 0.90)

    def test_box_is_clipped_to_frame(self) -> None:
        self.assertEqual(m.face_coverage(self.mask, (-10, 10, 30, 20)), 1.0)

    def test_degenerate_box_is_zero(self) -> None:
        self.assertEqual(m.face_coverage(self.mask, (10, 10, 0, 20)), 0.0)
        self.assertEqual(m.face_coverage(self.mask, (500, 500, 20, 20)), 0.0)


@unittest.skipIf(np is None, "numpy tidak terpasang")
class CutTest(unittest.TestCase):
    """Pergantian shot: thumbnail 32x18 abu-abu, beda rata-rata > 20 (sama dengan faces.py).
    Tanpa ini, mask orang A dihaluskan ke mask orang B dan `edge_shift` meledak di cut."""

    def test_identical_is_not_a_cut(self) -> None:
        a = np.full((18, 32), 100, np.uint8)
        self.assertFalse(m.is_cut(a, a.copy()))

    def test_small_change_is_not_a_cut(self) -> None:
        a = np.full((18, 32), 100, np.uint8)
        self.assertFalse(m.is_cut(a, a + 10))

    def test_big_change_is_a_cut(self) -> None:
        a = np.full((18, 32), 40, np.uint8)
        self.assertTrue(m.is_cut(a, a + 60))

    def test_threshold_is_exclusive(self) -> None:
        a = np.full((18, 32), 100, np.uint8)
        self.assertFalse(m.is_cut(a, a + 20))
        self.assertTrue(m.is_cut(a, a + 21))

    def test_no_overflow_on_uint8(self) -> None:
        self.assertTrue(m.is_cut(np.full((18, 32), 5, np.uint8), np.full((18, 32), 250, np.uint8)))

    def test_first_frame_is_never_a_cut(self) -> None:
        self.assertFalse(m.is_cut(None, np.full((18, 32), 5, np.uint8)))


@unittest.skipIf(np is None, "numpy tidak terpasang")
class AreaTest(unittest.TestCase):
    def test_rejects_empty_and_full(self) -> None:
        self.assertFalse(m.area_ok(np.zeros((50, 50), np.uint8)))
        self.assertFalse(m.area_ok(np.full((50, 50), 255, np.uint8)))

    def test_accepts_a_person_sized_mask(self) -> None:
        self.assertTrue(m.area_ok(rect(100, 100, 10, 30, 80, 40)))  # 32%

    def test_fraction(self) -> None:
        self.assertAlmostEqual(m.area_fraction(rect(100, 100, 0, 0, 50, 100)), 0.5)


if __name__ == "__main__":
    unittest.main()
