"""Tes render: perhitungan crop 9:16 dan rantai filter. Tidak menjalankan ffmpeg."""

from __future__ import annotations

import unittest

from tests.helpers import ROOT  # noqa: F401

from scripts import render


class CropParamsTest(unittest.TestCase):
    def test_landscape_16_9(self) -> None:
        cw, ch, x, y = render.crop_params(1920, 1080)
        self.assertEqual(ch, 1080)
        self.assertEqual(cw, 608)
        self.assertEqual(x, (1920 - 608) // 2)
        self.assertEqual(y, 0)

    def test_already_vertical_no_crop(self) -> None:
        cw, ch, x, y = render.crop_params(1080, 1920)
        self.assertEqual((cw, ch, x, y), (1080, 1920, 0, 0))

    def test_square_source(self) -> None:
        cw, ch, x, y = render.crop_params(1080, 1080)
        self.assertEqual(ch, 1080)
        self.assertEqual(cw, 608)
        self.assertEqual(x, (1080 - 608) // 2)

    def test_bias_right(self) -> None:
        cw, ch, x, _ = render.crop_params(1920, 1080, bias_x=1.0)
        self.assertEqual(x, 1920 - cw)

    def test_bias_left(self) -> None:
        cw, _, x, _ = render.crop_params(1920, 1080, bias_x=-1.0)
        self.assertEqual(x, 0)

    def test_crop_even_dimensions(self) -> None:
        for w, h in [(1920, 1080), (1280, 720), (3840, 2160), (1000, 1000), (720, 1280)]:
            cw, ch, x, y = render.crop_params(w, h)
            self.assertEqual(cw % 2, 0, msg=f"{w}x{h} -> cw {cw}")
            self.assertEqual(ch % 2, 0, msg=f"{w}x{h} -> ch {ch}")
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + cw, w)
            self.assertLessEqual(y + ch, h)

    def test_aspect_close_to_target(self) -> None:
        for w, h in [(1920, 1080), (1080, 1080), (2560, 1440)]:
            cw, ch, _, _ = render.crop_params(w, h)
            self.assertAlmostEqual(cw / ch, 9 / 16, delta=0.01, msg=f"{w}x{h}")

    def test_invalid_dimensions_raise(self) -> None:
        with self.assertRaises(render.RenderError):
            render.crop_params(0, 1080)


class FilterChainTest(unittest.TestCase):
    def _edl(self, w: int = 1920, h: int = 1080) -> dict:
        return {
            "source": {"width": w, "height": h, "audio_rate": 48000, "path": "x.mp4"},
            "output": {"loudness_lufs": -14.0, "true_peak_db": -1.0},
        }

    def test_contains_scale_and_subtitles(self) -> None:
        chain = render._vf_chain(self._edl(), {"reframe": {"mode": "center"}},
                                 "captions/clip_01.ass", None)
        self.assertIn("scale=1080:1920", chain)
        self.assertIn("subtitles=captions/clip_01.ass", chain)
        self.assertIn("setsar=1", chain)

    def test_crop_applied_for_landscape(self) -> None:
        chain = render._vf_chain(self._edl(), {"reframe": {"mode": "center"}},
                                 "c.ass", None)
        self.assertIn("crop=608:1080:", chain)

    def test_no_crop_for_vertical(self) -> None:
        chain = render._vf_chain(self._edl(1080, 1920), {"reframe": {"mode": "center"}},
                                 "c.ass", None)
        self.assertNotIn("crop=", chain)

    def test_fontsdir_included(self) -> None:
        chain = render._vf_chain(self._edl(), {"reframe": {"mode": "center"}},
                                 "c.ass", "/usr/share/fonts")
        self.assertIn("fontsdir=/usr/share/fonts", chain)

    def test_filter_order(self) -> None:
        chain = render._vf_chain(self._edl(), {"reframe": {"mode": "center"}}, "c.ass", None)
        self.assertLess(chain.index("crop="), chain.index("scale="))
        self.assertLess(chain.index("scale="), chain.index("subtitles="))


class RenderGuardTest(unittest.TestCase):
    def test_missing_source_raises(self) -> None:
        edl = {
            "source": {"path": "/nonexistent/xyz.mp4", "width": 1920, "height": 1080,
                       "audio_rate": 48000},
            "output": {"loudness_lufs": -14.0, "true_peak_db": -1.0},
        }
        clip = {
            "id": "clip_01",
            "segments": [{"src_start": 0.0, "src_end": 5.0, "speed": 1.0}],
            "captions": [],
            "reframe": {"mode": "center"},
        }
        with self.assertRaises(render.RenderError):
            render.render_clip(edl, clip, "/tmp", "/tmp/out.mp4")

    def test_zero_duration_raises(self) -> None:
        edl = {
            "source": {"path": "/tmp", "width": 1920, "height": 1080, "audio_rate": 48000},
            "output": {"loudness_lufs": -14.0, "true_peak_db": -1.0},
        }
        clip = {
            "id": "clip_01",
            "segments": [{"src_start": 5.0, "src_end": 5.0, "speed": 1.0}],
            "captions": [],
            "reframe": {"mode": "center"},
        }
        with self.assertRaises(render.RenderError):
            render.render_clip(edl, clip, "/tmp", "/tmp/out.mp4")


if __name__ == "__main__":
    unittest.main()
