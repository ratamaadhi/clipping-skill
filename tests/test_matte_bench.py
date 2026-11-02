"""Tes runner spike matte (Langkah 1b): bagian yang bisa diuji tanpa model dan tanpa video."""

from __future__ import annotations

import unittest

try:
    import numpy as np
    import cv2  # noqa: F401  (alpha_from_* memakai cv2.resize)
except Exception:  # pragma: no cover
    np = None

from benchmarks import matte_bench as b
from benchmarks import matte_gate as g


class CropFilterTest(unittest.TestCase):
    def test_landscape_is_cropped_to_9_16(self) -> None:
        # 1080 * 9/16 = 607,5 -> 608, sama dengan crop reframe produksi (docs/REFRAME.md)
        self.assertEqual(b.crop_filter(1920, 1080, 0.0), "crop=608:1080:0:0")
        self.assertEqual(b.crop_filter(1920, 1080, 0.5), "crop=608:1080:656:0")
        self.assertEqual(b.crop_filter(1920, 1080, 1.0), "crop=608:1080:1312:0")

    def test_already_vertical_is_left_alone(self) -> None:
        self.assertEqual(b.crop_filter(720, 1280, 0.5), "")
        self.assertEqual(b.crop_filter(1080, 1920, 0.5), "")

    def test_crop_x_is_clamped(self) -> None:
        self.assertEqual(b.crop_filter(1920, 1080, -3.0), "crop=608:1080:0:0")
        self.assertEqual(b.crop_filter(1920, 1080, 9.0), "crop=608:1080:1312:0")

    def test_four_by_five_is_cropped_not_stretched(self) -> None:
        f = b.crop_filter(1080, 1350, 0.5)
        self.assertTrue(f.startswith("crop=760:1350:"), f)

    def test_crop_x_is_even(self) -> None:
        for cx in (0.13, 0.37, 0.71):
            x = int(b.crop_filter(1920, 1080, cx).split(":")[2])
            self.assertEqual(x % 2, 0)


class VideoFilterTest(unittest.TestCase):
    def test_chain_order(self) -> None:
        vf = b.build_vf(1920, 1080, 0.5, fps=15, width=540, height=960)
        self.assertEqual(vf, "crop=608:1080:656:0,fps=15,scale=540:960")

    def test_vertical_source_skips_crop(self) -> None:
        self.assertEqual(
            b.build_vf(720, 1280, 0.5, fps=15, width=540, height=960),
            "fps=15,scale=540:960",
        )


class MachineGuardTest(unittest.TestCase):
    """Angka dari mesin berbeda tidak boleh bercampur di satu berkas: gate menilai
    `meta.cpu` sekali untuk seluruh berkas."""

    def test_same_cpu_is_accepted(self) -> None:
        self.assertTrue(b.same_machine({"cpu": "Apple M3"}, {"cpu": "Apple M3"}))

    def test_different_cpu_is_rejected(self) -> None:
        self.assertFalse(b.same_machine({"cpu": "i5-7300U"}, {"cpu": "Apple M3"}))

    def test_new_file_is_accepted(self) -> None:
        self.assertTrue(b.same_machine({}, {"cpu": "Apple M3"}))


@unittest.skipIf(np is None, "numpy/cv2 tidak terpasang")
class PostprocessTest(unittest.TestCase):
    def test_pphumanseg_logits_become_alpha(self) -> None:
        logits = np.zeros((1, 2, 192, 192), np.float32)
        logits[0, 0] = 5.0            # latar menang di mana-mana
        logits[0, 1, 48:144, 48:144] = 9.0   # orang menang di tengah
        logits[0, 0, 48:144, 48:144] = -9.0
        a = b.alpha_from_pphumanseg(logits, (960, 540))
        self.assertEqual(a.shape, (960, 540))
        self.assertGreaterEqual(float(a.min()), 0.0)
        self.assertLessEqual(float(a.max()), 1.0)
        self.assertGreater(float(a[480, 270]), 0.95)
        self.assertLess(float(a[10, 10]), 0.05)

    def test_modnet_output_is_resized_and_clipped(self) -> None:
        out = np.full((1, 1, 512, 512), 1.4, np.float32)
        out[0, 0, :, :256] = -0.3
        a = b.alpha_from_modnet(out, (960, 540))
        self.assertEqual(a.shape, (960, 540))
        self.assertEqual(float(a.max()), 1.0)
        self.assertEqual(float(a.min()), 0.0)

    def test_temporal_smoothing(self) -> None:
        prev = np.zeros((4, 4), np.float32)
        cur = np.ones((4, 4), np.float32)
        out = b.smooth(prev, cur, 0.6)
        self.assertTrue(np.allclose(out, 0.6))
        self.assertTrue(np.array_equal(b.smooth(None, cur, 0.6), cur))


class RecordTest(unittest.TestCase):
    def test_record_has_every_key_the_gate_reads(self) -> None:
        rec = b.build_record(
            model_kind="pphumanseg",
            source="a.mp4",
            frames=90,
            wall_s=9.0,
            infer_s=3.0,
            rss_mb=500.0,
            load_ms=80.0,
            face_in_matte=0.98,
            flickers=[0.1, 0.2, 0.9],
            edge_shifts=[0.5, 0.7, 2.0],
            area_ok_ratio=1.0,
            n_faces=20,
        )
        for key in g.REQUIRED_KEYS:
            self.assertIn(key, rec)
        self.assertEqual(rec["flicker_p50"], 0.2)
        self.assertIn("edge_shift_p50", rec, "diagnostik tetap dicatat")
        self.assertIsNone(rec["human_ok"], "keputusan manusia tidak boleh terisi otomatis")
        self.assertAlmostEqual(rec["fps_e2e"], 10.0)
        self.assertAlmostEqual(rec["fps_infer"], 30.0)
        self.assertEqual(rec["id"], "pphumanseg@a")

    def test_zero_time_does_not_crash(self) -> None:
        rec = b.build_record(
            model_kind="modnet", source="a.mp4", frames=0, wall_s=0.0, infer_s=0.0,
            rss_mb=0.0, load_ms=0.0, face_in_matte=None, flickers=[], edge_shifts=[],
            area_ok_ratio=0.0, n_faces=0,
        )
        self.assertEqual(rec["fps_e2e"], 0.0)
        self.assertIsNone(rec["flicker_p50"], "tanpa data, bukan 0 (0 akan lolos gate)")

    def test_lag_summary_is_linear_percentile(self) -> None:
        rec = b.build_record(
            model_kind="modnet", source="a.mp4", frames=90, wall_s=9.0, infer_s=3.0,
            rss_mb=500.0, load_ms=80.0, face_in_matte=0.98,
            flickers=[0.1], edge_shifts=[0.5], area_ok_ratio=1.0, n_faces=20,
            lags=[0.4, 0.6, 2.0],
        )
        self.assertEqual(rec["lag_p50"], 0.6)
        from benchmarks import matte_metrics as mm

        self.assertEqual(rec["lag_p95"], round(mm.percentile([0.4, 0.6, 2.0], 95), 3))
        self.assertAlmostEqual(rec["lag_p95"], 1.86)  # 0.6 + 0.9*(2.0-0.6)

    def test_no_lag_samples_is_none_not_zero(self) -> None:
        rec = b.build_record(
            model_kind="modnet", source="a.mp4", frames=90, wall_s=9.0, infer_s=3.0,
            rss_mb=500.0, load_ms=80.0, face_in_matte=0.98,
            flickers=[0.1], edge_shifts=[0.5], area_ok_ratio=1.0, n_faces=20,
            lags=[],
        )
        self.assertIsNone(rec["lag_p50"], "0 akan lolos gate; tanpa data harus None")
        self.assertIsNone(rec["lag_p95"])

    def test_lags_defaults_to_empty(self) -> None:
        # pemanggil lama tetap valid: parameter keyword opsional
        rec = b.build_record(
            model_kind="modnet", source="a.mp4", frames=1, wall_s=1.0, infer_s=1.0,
            rss_mb=1.0, load_ms=1.0, face_in_matte=None, flickers=[], edge_shifts=[],
            area_ok_ratio=1.0, n_faces=0,
        )
        self.assertIn("lag_p50", rec)
        self.assertIsNone(rec["lag_p50"])


if __name__ == "__main__":
    unittest.main()
