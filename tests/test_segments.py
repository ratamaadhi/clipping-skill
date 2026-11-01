"""Tes pemetaan waktu untuk klip multi-segment (buang jeda).

Invarian yang dijaga:
  - tidak ada jeda > max_gap di dalam satu segmen
  - out_start tiap segmen = jumlah durasi segmen sebelumnya
  - timestamp yang jatuh di jeda yang dibuang tidak boleh muncul di output
"""

from __future__ import annotations

import unittest

from scripts import edl


class PlanSegmentsTest(unittest.TestCase):
    def test_splits_on_big_gap(self) -> None:
        spans = [(0.0, 3.0), (7.0, 10.0)]
        segs = edl.plan_segments(spans, 0.0, 10.0)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[0]["src_start"], 0.0, places=2)
        self.assertAlmostEqual(segs[0]["src_end"], 3.0, places=2)
        self.assertAlmostEqual(segs[1]["src_start"], 7.0, places=2)
        self.assertAlmostEqual(segs[1]["out_start"], 3.0, places=2)

    def test_small_gap_stays_one_segment(self) -> None:
        spans = [(0.0, 3.0), (3.3, 6.0)]
        segs = edl.plan_segments(spans, 0.0, 6.0)
        self.assertEqual(len(segs), 1)

    def test_out_start_is_cumulative(self) -> None:
        spans = [(0.0, 2.0), (5.0, 6.5), (9.0, 12.0)]
        segs = edl.plan_segments(spans, 0.0, 12.0)
        self.assertEqual(len(segs), 3)
        expected = 0.0
        for seg in segs:
            self.assertAlmostEqual(seg["out_start"], expected, places=3)
            expected += seg["src_end"] - seg["src_start"]

    def test_no_gap_inside_segment(self) -> None:
        spans = [(0.0, 2.0), (4.0, 5.0), (9.0, 11.0)]
        segs = edl.plan_segments(spans, 0.0, 11.0)
        for seg in segs:
            self.assertLessEqual(seg["src_end"] - seg["src_start"], 11.0)
        # setiap segmen harus berisi bicara, bukan jeda kosong
        for seg in segs:
            covered = any(
                s >= seg["src_start"] - 1e-6 and e <= seg["src_end"] + 1e-6 for s, e in spans
            )
            self.assertTrue(covered, seg)

    def test_clamped_to_clip_range(self) -> None:
        spans = [(-2.0, 3.0), (4.0, 30.0)]
        segs = edl.plan_segments(spans, 0.0, 10.0)
        self.assertAlmostEqual(segs[0]["src_start"], 0.0, places=3)
        self.assertAlmostEqual(segs[-1]["src_end"], 10.0, places=3)

    def test_tiny_segment_dropped_or_merged(self) -> None:
        spans = [(0.0, 5.0), (8.0, 8.1), (12.0, 15.0)]
        segs = edl.plan_segments(spans, 0.0, 15.0)
        for seg in segs:
            self.assertGreaterEqual(seg["src_end"] - seg["src_start"], edl.MIN_SEG_DUR - 1e-6)

    def test_keeps_original_when_no_gaps(self) -> None:
        spans = [(0.0, 10.0)]
        segs = edl.plan_segments(spans, 0.0, 10.0)
        self.assertEqual(len(segs), 1)
        self.assertAlmostEqual(segs[0]["out_start"], 0.0)


class MapTimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.segs = edl.plan_segments([(0.0, 3.0), (7.0, 10.0)], 0.0, 10.0)

    def test_inside_first_segment(self) -> None:
        self.assertAlmostEqual(edl.map_time(self.segs, 1.5), 1.5, places=3)

    def test_inside_second_segment_shifts(self) -> None:
        # src 7.0 adalah awal segmen kedua, out 3.0
        self.assertAlmostEqual(edl.map_time(self.segs, 8.0), 4.0, places=3)

    def test_dropped_gap_returns_none(self) -> None:
        self.assertIsNone(edl.map_time(self.segs, 5.0))

    def test_boundary_end_of_segment(self) -> None:
        self.assertAlmostEqual(edl.map_time(self.segs, 3.0), 3.0, places=3)


class MapIntervalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.segs = edl.plan_segments([(0.0, 3.0), (7.0, 10.0)], 0.0, 10.0)

    def test_inside_removed_gap_is_dropped(self) -> None:
        self.assertIsNone(edl.map_interval(self.segs, 4.0, 5.0))

    def test_straddling_end_is_clamped(self) -> None:
        out = edl.map_interval(self.segs, 2.5, 5.0)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertAlmostEqual(out[0], 2.5, places=3)
        self.assertAlmostEqual(out[1], 3.0, places=3)

    def test_straddling_start_is_clamped(self) -> None:
        out = edl.map_interval(self.segs, 5.0, 8.0)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertAlmostEqual(out[0], 3.0, places=3)
        self.assertAlmostEqual(out[1], 4.0, places=3)

    def test_spanning_whole_gap_uses_both_sides(self) -> None:
        out = edl.map_interval(self.segs, 2.0, 8.0)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertAlmostEqual(out[0], 2.0, places=3)
        self.assertAlmostEqual(out[1], 4.0, places=3)

    def test_degenerate_returns_none(self) -> None:
        self.assertIsNone(edl.map_interval(self.segs, 3.0, 3.0))


if __name__ == "__main__":
    unittest.main()
