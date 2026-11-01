"""Tes logika reframe berbasis wajah. Tidak butuh OpenCV — hanya matematika."""

from __future__ import annotations

import unittest

from scripts import faces


def _face(cx: float, motion: float = 0.0, w: float = 0.08) -> dict:
    return {"cx": cx, "cy": 0.3, "w": w, "motion": motion}


def _sample(t: float, faces: list[dict], cut: bool = False) -> dict:
    return {"t": t, "cut": cut, "faces": faces}


class BiasTimelineTest(unittest.TestCase):
    def test_one_point_per_shot(self) -> None:
        samples = [
            _sample(0.0, [_face(0.3), _face(0.7)]),
            _sample(0.2, [_face(0.3), _face(0.7)]),
            _sample(0.4, [_face(0.7)], cut=True),
            _sample(0.6, [_face(0.7)]),
        ]
        tl = faces.bias_timeline(samples, 1920, 608, 0.0)
        self.assertEqual(len(tl), 2, tl)

    def test_bias_within_range(self) -> None:
        samples = [_sample(0.0, [_face(0.05)]), _sample(0.2, [_face(0.95)])]
        for _, b in faces.bias_timeline(samples, 1920, 608, 0.0):
            self.assertGreaterEqual(b, -1.0)
            self.assertLessEqual(b, 1.0)

    def test_face_at_left_edge_moves_crop_left(self) -> None:
        samples = [_sample(0.0, [_face(0.2)])]
        tl = faces.bias_timeline(samples, 1920, 608, 0.0)
        self.assertEqual(len(tl), 1)
        self.assertLess(tl[0][1], -0.4, "wajah di kiri harus menggeser crop ke kiri")

    def test_no_faces_returns_empty(self) -> None:
        self.assertEqual(faces.bias_timeline([_sample(0.0, [])], 1920, 608, 0.0), [])

    def test_source_already_target_ratio(self) -> None:
        self.assertEqual(faces.bias_timeline([_sample(0.0, [_face(0.5)])], 608, 608, 0.0), [])

    def test_speaking_face_wins_when_motion_differs(self) -> None:
        # kiri hampir diam, kanan aktif bicara -> pilih kanan
        samples = [_sample(0.0, [_face(0.3, 0.002), _face(0.7, 0.12)])]
        tl = faces.bias_timeline(samples, 1920, 608, 0.0)
        self.assertEqual(len(tl), 1)
        self.assertGreater(tl[0][1], 0.0, "harus mengikuti wajah yang bergerak")


class CropExpressionTest(unittest.TestCase):
    def test_empty_returns_center(self) -> None:
        self.assertEqual(faces.crop_expression([], 608, 1312), str(1312 // 2))

    def test_constant_bias_is_plain_number(self) -> None:
        expr = faces.crop_expression([(0.0, 0.0), (1.0, 0.0)], 608, 1312)
        self.assertTrue(expr.isdigit(), expr)

    def test_moving_bias_uses_clipped_ramps(self) -> None:
        expr = faces.crop_expression([(0.0, -0.5), (2.0, 0.5)], 608, 1312)
        self.assertIn("clip(", expr)
        self.assertIn("t-", expr)

    def test_expression_stays_reasonably_short(self) -> None:
        tl = [(float(i), -0.5 + i * 0.02) for i in range(40)]
        expr = faces.crop_expression(tl, 608, 1312)
        self.assertLess(len(expr), 4000, "ekspresi kepanjangan untuk filtergraph")


if __name__ == "__main__":
    unittest.main()
