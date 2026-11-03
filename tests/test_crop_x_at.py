"""`faces.crop_x_at` = sumber tunggal geometri `crop_expression` (Langkah 4b-1).

Dua hal yang dikunci:

1. `crop_x_at(t)` harus sama dengan evaluasi ekspresi ffmpeg pada waktu `t`,
   termasuk ramp 0,40 s. Evaluator mini di sini hanya mengenal angka, `t`,
   operator aritmetika, dan `clip(x, lo, hi)` — tidak ada parser baru.
2. String `crop_expression` harus identik byte-per-byte dengan versi HEAD.
   Salinan fungsi HEAD ditanam di berkas ini (bukan membaca git saat tes),
   sehingga refactor boleh mengubah struktur kode tetapi tidak boleh
   mengubah satu karakter pun dari ekspresi yang masuk filtergraph.
"""

from __future__ import annotations

import random
import unittest

from scripts import faces

TRANS = 0.40


# --- salinan VERBATIM `faces.crop_expression` di HEAD ---------------------
def _head_crop_expression(
    timeline: list[tuple[float, float]], crop_w: int, free_x: int
) -> str:
    if not timeline:
        return str(free_x // 2)

    TRANS = 0.40

    def x_of(bias: float) -> int:
        return int(round((bias + 1.0) / 2.0 * free_x))

    points = [(t, x_of(b)) for t, b in timeline]
    expr = str(points[0][1])
    for i in range(1, len(points)):
        t_cur, x_cur = points[i]
        x_prev = points[i - 1][1]
        delta = x_cur - x_prev
        if delta == 0:
            continue
        start = max(0.0, t_cur - TRANS)
        expr += f"+({delta})*clip((t-{start:.3f})/{TRANS:g},0,1)"
    return expr


def _eval_crop_expr(expr: str, t: float) -> float:
    """Evaluasi ekspresi crop dengan `clip` sebagai fungsi Python."""
    def clip(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    return float(eval(expr, {"__builtins__": {}}, {"t": t, "clip": clip}))  # noqa: S307


def _random_timeline(rng: random.Random, n: int | None = None) -> list[tuple[float, float]]:
    count = n if n is not None else rng.randint(1, 7)
    t = 0.0
    out: list[tuple[float, float]] = []
    for _ in range(count):
        t += rng.uniform(0.0, 2.5)
        out.append((round(t, 3), round(rng.uniform(-1.0, 1.0), 4)))
    return out


class CropXAtTest(unittest.TestCase):
    def test_empty_timeline_is_center(self) -> None:
        self.assertEqual(faces.crop_x_at([], 608, 1312, 0.0), 656.0)
        self.assertEqual(faces.crop_x_at([], 1080, 0, 9.0), 0.0)

    def test_before_first_point_and_after_last_point_are_flat(self) -> None:
        tl = [(1.0, -0.5), (3.0, 0.5)]
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 0.0), 328.0)
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 0.99), 328.0)
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 3.0), 984.0)
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 99.0), 984.0)

    def test_ramp_is_linear_over_exactly_0_40s(self) -> None:
        tl = [(0.0, -0.5), (2.0, 0.5)]
        # x0=328, x1=984, ramp mulai 1,6 dan selesai 2,0.
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 1.6), 328.0)
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 1.8), 656.0)
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 1.9), 820.0)
        self.assertAlmostEqual(faces.crop_x_at(tl, 608, 1312, 2.0), 984.0)

    def test_equals_expression_on_random_timelines(self) -> None:
        rng = random.Random(20261102)
        checked = 0
        for _ in range(60):
            tl = _random_timeline(rng)
            expr = faces.crop_expression(tl, 608, 1312)
            for _ in range(20):
                t = rng.uniform(0.0, tl[-1][0] + 1.0)
                self.assertAlmostEqual(
                    faces.crop_x_at(tl, 608, 1312, t),
                    _eval_crop_expr(expr, t),
                    places=9,
                    msg=f"timeline={tl} t={t}",
                )
                checked += 1
        self.assertGreaterEqual(checked, 50)

    def test_equals_expression_on_edge_cases(self) -> None:
        cases = [
            [],
            [(0.0, 0.0)],
            [(0.0, 0.0), (0.4, 0.0), (0.8, 0.0)],
            [(0.0, -1.0), (0.1, 1.0), (0.2, -1.0), (0.3, 1.0)],
            [(0.0, -0.1234), (0.0, 0.9876)],
            [(2.0, 0.5), (1.0, -0.5)],
            [(0.0, 1.0), (0.05, -1.0)],
            [(5.0, -0.9), (5.2, 0.9), (9.9, -0.9)],
        ]
        for tl in cases:
            expr = faces.crop_expression(tl, 608, 1312)
            for t in (-1.0, 0.0, 0.001, 0.2, 0.4, 0.399, 0.401, 1.0, 2.0, 5.0, 99.0):
                self.assertAlmostEqual(
                    faces.crop_x_at(tl, 608, 1312, t),
                    _eval_crop_expr(expr, t),
                    places=9,
                    msg=f"timeline={tl} t={t}",
                )


class CropExpressionHeadTest(unittest.TestCase):
    def test_string_identical_to_head_on_200_random_timelines(self) -> None:
        rng = random.Random(4711)
        for i in range(200):
            tl = _random_timeline(rng)
            crop_w = rng.choice([0, 608, 1080, 1312])
            free_x = rng.choice([0, 608, 1312])
            self.assertEqual(
                faces.crop_expression(tl, crop_w, free_x),
                _head_crop_expression(tl, crop_w, free_x),
                msg=f"iterasi {i}: timeline={tl} crop_w={crop_w} free_x={free_x}",
            )

    def test_string_identical_to_head_on_edge_cases(self) -> None:
        cases = [
            [],
            [(0.0, 0.0)],
            [(0.0, -1.0)],
            [(0.0, 0.0), (1.0, 0.0)],
            [(0.0, -0.5), (0.004, 0.5)],
            [(0.0, -0.5), (0.4, 0.5)],
            [(0.0, 0.4), (0.0, -0.4)],
            [(10.0, 0.25), (10.001, 0.75)],
            [(0.0, -0.123456), (2.345, 0.654321)],
        ]
        for tl in cases:
            for crop_w, free_x in ((608, 1312), (1312, 608), (0, 0), (1080, 0)):
                self.assertEqual(
                    faces.crop_expression(tl, crop_w, free_x),
                    _head_crop_expression(tl, crop_w, free_x),
                    msg=f"timeline={tl} crop_w={crop_w} free_x={free_x}",
                )


if __name__ == "__main__":
    unittest.main()
