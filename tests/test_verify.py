"""Tes pemeriksa gerak: fungsi murni + satu integrasi ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import verify

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class FindGapsTest(unittest.TestCase):
    def test_uniform_25fps_has_no_gap(self) -> None:
        times = [round(i * 0.04, 3) for i in range(50)]
        self.assertEqual(verify.find_gaps(times, 25.0), [])

    def test_double_interval_is_a_gap(self) -> None:
        times = [round(i * 0.04, 3) for i in range(20)]
        times = [t if t < 0.4 else round(t + 0.08, 3) for t in times]
        gaps = verify.find_gaps(times, 25.0)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0]["delta"], 0.12, places=3)

    def test_zero_duplicate_still_detects_gap(self) -> None:
        """Celah harus ketahuan walau tidak ada frame duplikat sama sekali."""
        times = [0.0, 0.04, 0.08, 0.16, 0.20]
        self.assertEqual(len(verify.find_gaps(times, 25.0)), 1)

    def test_too_short_is_empty(self) -> None:
        self.assertEqual(verify.find_gaps([], 25.0), [])
        self.assertEqual(verify.find_gaps([0.0], 25.0), [])

    def test_fps_inferred_when_missing(self) -> None:
        times = [round(i * 0.04, 3) for i in range(30)]
        self.assertEqual(len(verify.find_gaps(times)), 0)


class FindDuplicatesTest(unittest.TestCase):
    def test_clean_series_has_none(self) -> None:
        self.assertEqual(verify.find_duplicates([5.0, 6.0, 7.0]), [])

    def test_frozen_frame_is_reported_with_index(self) -> None:
        series = [5.0, 0.0, 6.0, 0.001, 7.0]
        self.assertEqual(verify.find_duplicates(series), [2, 4])

    def test_threshold_only_catches_near_exact_copies(self) -> None:
        """Adegan nyaris diam (YAVG ~0,2) bukan duplikat; salinan persis iya."""
        self.assertEqual(verify.find_duplicates([0.01, 0.02]), [1, 2])
        self.assertEqual(verify.find_duplicates([0.2, 0.3]), [])


@unittest.skipUnless(HAS_FFMPEG, "butuh ffmpeg + ffprobe")
class AnalyzeTest(unittest.TestCase):
    def test_clean_clip_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "clean.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p),
                ],
                check=True,
            )
            r = verify.analyze(p)
        self.assertEqual(r["gaps"], [])
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["fps"] or 0, 25.0, delta=0.5)

    def test_frozen_clip_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "frozen.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=gray:size=320x240:rate=25:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p),
                ],
                check=True,
            )
            r = verify.analyze(p)
        self.assertTrue(r["duplicates"], "klip beku harus terdeteksi")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
