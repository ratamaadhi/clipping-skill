"""Tes murni `scripts.shapes`: geometri path ASS, warna, event, dan wipe.

Semua tes di sini berjalan tanpa ffmpeg. Bukti bahwa libass benar-benar
mengisi path dengan aturan nonzero, menerima koordinat desimal, dan
menganimasikan `\\t(\\clip)` ada di `tests/test_shapes_libass_oracle.py`
(tes itu SKIP dengan jujur bila tidak ada ffmpeg berlibass).

Aturan pembulatan waktu ASS: `shape_event` memakai penulis waktu tier-1 yang
sama dengan `kinetic` (`captions._ass_time`), yaitu `f"{detik:05.2f}"` pada
sisa detik. Konsekuensinya ditulis EKSPLISIT di tes:
`1.235 -> 0:00:01.24` (float 1,235 berada sedikit di atas titik tengah),
`1.2349 -> 0:00:01.23`, dan `59.999 -> 0:00:60.00` (penulis tidak memindahkan
kelebihan detik ke menit). Meniru penulis itu penting supaya stamp waktu
kedua modul tidak berbeda satu sentidetik.
"""

from __future__ import annotations

import math
import re
import unittest

from scripts import captions
from scripts import shapes

NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


# ---------------------------------------------------------------------------
# Parser path ASS
# ---------------------------------------------------------------------------

def parse_path(path: str) -> list[dict]:
    """Urai path `m/l/b` menjadi kontur dengan anchor dan semua titik.

    Mengembalikan daftar kontur: {"cmds": [...], "anchors": [(x, y), ...],
    "all": [(x, y), ...]}. `b` menyumbang tiga titik (dua kontrol + ujung);
    hanya ujungnya yang menjadi anchor untuk uji orientasi/luas.
    """
    tokens = path.split()
    if not tokens:
        raise AssertionError("path kosong")
    contours: list[dict] = []
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        i += 1
        if cmd not in ("m", "l", "b"):
            raise AssertionError(f"perintah path bukan m/l/b: {cmd!r} di {path!r}")
        if cmd == "m":
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
            contours.append({"cmds": ["m"], "anchors": [(x, y)], "all": [(x, y)]})
        elif cmd == "l":
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
            contours[-1]["cmds"].append("l")
            contours[-1]["anchors"].append((x, y))
            contours[-1]["all"].append((x, y))
        else:  # b
            pts = []
            for _ in range(3):
                x, y = float(tokens[i]), float(tokens[i + 1])
                i += 2
                pts.append((x, y))
            contours[-1]["cmds"].append("b")
            contours[-1]["all"].extend(pts)
            contours[-1]["anchors"].append(pts[2])
    return contours


def signed_area(points: list[tuple[float, float]]) -> float:
    """Luas bertanda shoelace (positif = urutan yang dipakai modul)."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        total += x0 * y1 - x1 * y0
    return total / 2.0


def bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def segment_corners(
    p: tuple[float, float], q: tuple[float, float], thickness: float
) -> list[tuple[float, float]]:
    """Empat sudut persegi panjang berujung butt untuk ruas p->q."""
    dx = q[0] - p[0]
    dy = q[1] - p[1]
    length = math.hypot(dx, dy)
    nx = -dy / length * thickness / 2.0
    ny = dx / length * thickness / 2.0
    return [
        (p[0] + nx, p[1] + ny),
        (q[0] + nx, q[1] + ny),
        (q[0] - nx, q[1] - ny),
        (p[0] - nx, p[1] - ny),
    ]


def all_paths() -> dict[str, tuple[str, tuple[float, float, float, float]]]:
    """Nama -> (path, batas teoretis inklusif koordinat)."""
    rect_path = shapes.rect(100.0, 200.0, 300.0, 150.0)
    round_path = shapes.rounded_rect(100.0, 200.0, 300.0, 150.0, 40.0)
    circle_path = shapes.circle(500.0, 600.0, 120.0)
    line_path = shapes.line(10.0, 20.0, 310.0, 220.0, 30.0)
    poly_points = [(100.0, 800.0), (400.0, 800.0), (700.0, 1000.0)]
    poly_path = shapes.polyline(poly_points, 30.0)
    check_path = shapes.check_mark(800.0, 1500.0, 200.0, 24.0)
    return {
        "rect": (rect_path, (100.0, 400.0, 200.0, 350.0)),
        "rounded_rect": (round_path, (100.0, 400.0, 200.0, 350.0)),
        "circle": (circle_path, (380.0, 620.0, 480.0, 720.0)),
        "line": (line_path, (10.0 - 15.0, 310.0 + 15.0, 20.0 - 15.0, 220.0 + 15.0)),
        "polyline": (
            poly_path,
            (100.0 - 15.0, 700.0 + 15.0, 800.0 - 15.0, 1000.0 + 15.0),
        ),
        "check_mark": (check_path, (700.0, 900.0, 1400.0, 1600.0)),
    }


# ---------------------------------------------------------------------------
# Geometri path
# ---------------------------------------------------------------------------

class PathGeometryTest(unittest.TestCase):
    def test_path_starts_with_move_and_only_has_m_l_b_numbers(self) -> None:
        for name, (path, _) in all_paths().items():
            with self.subTest(name=name):
                self.assertTrue(path.startswith("m "), path)
                for token in path.split():
                    if token in ("m", "l", "b"):
                        continue
                    self.assertRegex(
                        token, NUMBER,
                        msg=f"{name}: token {token!r} bukan angka/command di {path!r}",
                    )

    def test_contours_are_explicitly_closed(self) -> None:
        for name, (path, _) in all_paths().items():
            for k, contour in enumerate(parse_path(path)):
                first = contour["anchors"][0]
                last = contour["anchors"][-1]
                with self.subTest(name=name, contour=k):
                    self.assertAlmostEqual(first[0], last[0], places=6, msg=path)
                    self.assertAlmostEqual(first[1], last[1], places=6, msg=path)

    def test_coordinates_within_declared_bounds(self) -> None:
        for name, (path, bounds) in all_paths().items():
            x0, x1, y0, y1 = bounds
            for contour in parse_path(path):
                for x, y in contour["all"]:
                    with self.subTest(name=name, x=x, y=y):
                        self.assertGreaterEqual(x, x0 - 1e-6, msg=path)
                        self.assertLessEqual(x, x1 + 1e-6, msg=path)
                        self.assertGreaterEqual(y, y0 - 1e-6, msg=path)
                        self.assertLessEqual(y, y1 + 1e-6, msg=path)

    def test_rect_shoelace_area_is_exact(self) -> None:
        contours = parse_path(shapes.rect(10.0, 20.0, 300.5, 200.25))
        self.assertEqual(len(contours), 1)
        self.assertAlmostEqual(
            abs(signed_area(contours[0]["anchors"])), 300.5 * 200.25, places=6
        )

    def test_line_shoelace_area_is_thickness_times_length(self) -> None:
        contour = parse_path(shapes.line(10.0, 20.0, 310.0, 220.0, 30.0))[0]
        expected = 30.0 * math.hypot(300.0, 200.0)
        # Koordinat path dibulatkan 2 desimal; galat luas < 1 px^2.
        self.assertAlmostEqual(abs(signed_area(contour["anchors"])), expected, delta=1.0)

    def test_circle_anchor_area_is_two_r_squared(self) -> None:
        contour = parse_path(shapes.circle(500.0, 500.0, 200.0))[0]
        self.assertEqual(contour["cmds"].count("b"), 4)
        self.assertAlmostEqual(abs(signed_area(contour["anchors"])), 2 * 200.0**2, places=6)

    def test_all_contours_in_a_path_share_orientation(self) -> None:
        for name, (path, _) in all_paths().items():
            signs = []
            for contour in parse_path(path):
                area = signed_area(contour["anchors"])
                signs.append(1 if area > 0 else -1)
            with self.subTest(name=name, signs=signs):
                self.assertTrue(all(s == signs[0] for s in signs), msg=f"{name}: {signs}")
                self.assertNotEqual(signs[0], 0)

    def test_rounded_rect_r_zero_matches_rect_bbox(self) -> None:
        rect = parse_path(shapes.rect(100.0, 200.0, 300.0, 150.0))[0]
        rounded = parse_path(
            shapes.rounded_rect(100.0, 200.0, 300.0, 150.0, 0.0)
        )[0]
        self.assertEqual(bbox(rect["anchors"]), bbox(rounded["anchors"]))
        self.assertAlmostEqual(
            abs(signed_area(rect["anchors"])),
            abs(signed_area(rounded["anchors"])),
            places=6,
        )

    def test_rounded_rect_radius_is_clamped_to_half_min_side(self) -> None:
        clamped = shapes.rounded_rect(0.0, 0.0, 100.0, 80.0, 1000.0)
        expected = shapes.rounded_rect(0.0, 0.0, 100.0, 80.0, 40.0)
        self.assertEqual(clamped, expected)
        contour = parse_path(clamped)[0]
        x0, y0, x1, y1 = bbox(contour["all"])
        self.assertAlmostEqual(x0, 0.0, places=6)
        self.assertAlmostEqual(y0, 0.0, places=6)
        self.assertAlmostEqual(x1, 100.0, places=6)
        self.assertAlmostEqual(y1, 80.0, places=6)

    def test_rounded_rect_uses_kappa_cubic_control_points(self) -> None:
        """Kontrol bezier pertama = anchor + r*kappa (0,5522847498), bukan 0,5."""
        contour = parse_path(shapes.rounded_rect(0.0, 0.0, 100.0, 100.0, 20.0))[0]
        # Kontur: m (20,0) l (80,0) b c1 c2 (100,20) ...
        self.assertEqual(contour["cmds"][:3], ["m", "l", "b"])
        anchor = contour["all"][1]
        c1 = contour["all"][2]
        c2 = contour["all"][3]
        kappa = 0.5522847498
        self.assertAlmostEqual(anchor[0], 80.0, places=6)
        self.assertAlmostEqual(anchor[1], 0.0, places=6)
        self.assertAlmostEqual(c1[0], 80.0 + 20.0 * kappa, places=2)
        self.assertAlmostEqual(c1[1], 0.0, places=6)
        self.assertAlmostEqual(c2[0], 100.0, places=6)
        self.assertAlmostEqual(c2[1], 20.0 - 20.0 * kappa, places=2)

    def test_polyline_has_line_per_segment_and_circle_per_interior_point(self) -> None:
        contours = parse_path(
            shapes.polyline([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (200.0, 100.0)], 20.0)
        )
        # 3 ruas -> 3 kontur garis; 2 titik sambungan -> 2 lingkaran.
        self.assertEqual(len(contours), 5)
        self.assertEqual(sum(1 for c in contours if c["cmds"].count("b") == 4), 2)
        self.assertEqual(sum(1 for c in contours if "b" not in c["cmds"]), 3)

    def test_two_point_polyline_has_no_join_circle(self) -> None:
        contours = parse_path(shapes.polyline([(0.0, 0.0), (100.0, 0.0)], 20.0))
        self.assertEqual(len(contours), 1)

    def test_check_mark_fits_inside_size_box(self) -> None:
        cx, cy, size = 800.0, 1500.0, 200.0
        contours = parse_path(shapes.check_mark(cx, cy, size, 24.0))
        xs = [p[0] for contour in contours for p in contour["all"]]
        ys = [p[1] for contour in contours for p in contour["all"]]
        self.assertGreaterEqual(min(xs), cx - size / 2.0 - 1e-6)
        self.assertLessEqual(max(xs), cx + size / 2.0 + 1e-6)
        self.assertGreaterEqual(min(ys), cy - size / 2.0 - 1e-6)
        self.assertLessEqual(max(ys), cy + size / 2.0 + 1e-6)
        self.assertGreater(max(xs) - min(xs), size * 0.5)
        self.assertGreater(max(ys) - min(ys), size * 0.3)

    def test_every_path_is_deterministic(self) -> None:
        builders = [
            lambda: shapes.rect(1.1, 2.2, 30.3, 40.4),
            lambda: shapes.rounded_rect(1.1, 2.2, 30.3, 40.4, 5.5),
            lambda: shapes.circle(10.5, 20.5, 7.25),
            lambda: shapes.line(0.1, 0.2, 10.3, 20.4, 3.5),
            lambda: shapes.polyline([(0.0, 0.0), (5.5, 2.25), (9.0, 8.0)], 2.5),
            lambda: shapes.check_mark(5.0, 6.0, 20.0, 3.0),
        ]
        for build in builders:
            self.assertEqual(build(), build())

    def test_invalid_arguments_raise_value_error_naming_argument(self) -> None:
        nan = float("nan")
        inf = float("inf")
        cases = [
            ("rect w nol", lambda: shapes.rect(0, 0, 0, 10), "w"),
            ("rect h negatif", lambda: shapes.rect(0, 0, 10, -1), "h"),
            ("rect w nan", lambda: shapes.rect(0, 0, nan, 10), "w"),
            ("rect x inf", lambda: shapes.rect(inf, 0, 10, 10), "x"),
            ("rounded r negatif", lambda: shapes.rounded_rect(0, 0, 10, 10, -1), "r"),
            ("rounded w nol", lambda: shapes.rounded_rect(0, 0, 0, 10, 1), "w"),
            ("circle r nol", lambda: shapes.circle(0, 0, 0), "r"),
            ("circle r inf", lambda: shapes.circle(0, 0, inf), "r"),
            ("line titik sama", lambda: shapes.line(5, 5, 5, 5, 2), "x1"),
            ("line thickness nol", lambda: shapes.line(0, 0, 10, 0, 0), "thickness"),
            ("polyline satu titik", lambda: shapes.polyline([(0, 0)], 2), "points"),
            (
                "polyline titik nan",
                lambda: shapes.polyline([(0, 0), (nan, 0)], 2),
                "points",
            ),
            (
                "polyline titik berimpit",
                lambda: shapes.polyline([(0, 0), (0, 0)], 2),
                "points",
            ),
            ("polyline thickness negatif", lambda: shapes.polyline([(0, 0), (1, 1)], -1), "thickness"),
            ("check size nol", lambda: shapes.check_mark(0, 0, 0, 1), "size"),
            ("check thickness nol", lambda: shapes.check_mark(0, 0, 10, 0), "thickness"),
            ("check thickness >= size", lambda: shapes.check_mark(0, 0, 10, 10), "thickness"),
        ]
        for label, call, arg in cases:
            with self.subTest(label=label):
                with self.assertRaises(ValueError) as ctx:
                    call()
                self.assertIn(arg, str(ctx.exception), msg=f"{label}: {ctx.exception}")


# ---------------------------------------------------------------------------
# Warna
# ---------------------------------------------------------------------------

class ColourTest(unittest.TestCase):
    def test_colour_converts_rgb_to_ass_bgr(self) -> None:
        table = {
            "#FFFFFF": "&HFFFFFF&",
            "#112233": "&H332211&",
            "#000000": "&H000000&",
            "#A1B2C3": "&HC3B2A1&",
            "#a1b2c3": "&HC3B2A1&",
        }
        for value, expected in table.items():
            with self.subTest(value=value):
                self.assertEqual(shapes.colour(value), expected)

    def test_colour_rejects_malformed_hex(self) -> None:
        for value in ("FFFFFF", "#FFF", "#FFFFFFF", "#GGGGGG", "#12345", " #FFFFFF", "#FFFFFF ", "", 123):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as ctx:
                    shapes.colour(value)
                self.assertIn("colour", str(ctx.exception).lower())

    def test_alpha_table_is_exact(self) -> None:
        table = {
            1.0: "&H00&",
            0.5: "&H80&",
            0.0: "&HFF&",
            0.25: "&HBF&",
        }
        for value, expected in table.items():
            with self.subTest(value=value):
                self.assertEqual(shapes.alpha(value), expected)

    def test_alpha_rejects_out_of_range_and_nan(self) -> None:
        for value in (-0.01, 1.01, float("nan"), float("inf"), float("-inf"), "0.5"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as ctx:
                    shapes.alpha(value)
                self.assertIn("opacity", str(ctx.exception))

    def test_alpha_clamps_rounding_to_byte(self) -> None:
        # 0,999 -> 0,255 -> dibulatkan 0; 0,001 -> 254,745 -> 255.
        self.assertEqual(shapes.alpha(0.999), "&H00&")
        self.assertEqual(shapes.alpha(0.001), "&HFF&")


# ---------------------------------------------------------------------------
# shape_event
# ---------------------------------------------------------------------------

class ShapeEventTest(unittest.TestCase):
    def test_event_has_exactly_ten_fields(self) -> None:
        line = shapes.shape_event(0.0, 1.0, shapes.rect(0, 0, 10, 10))
        self.assertTrue(line.startswith("Dialogue: "))
        fields = line[len("Dialogue: "):].split(",", 9)
        self.assertEqual(len(fields), 10, msg=line)
        self.assertEqual(fields[0], "0")
        self.assertEqual(fields[3], "Shape")
        self.assertEqual(fields[4], "")
        self.assertEqual(fields[5:9], ["0", "0", "0", ""])

    def test_drawing_override_wraps_path_with_p1_and_p0(self) -> None:
        path = shapes.rect(10, 20, 30, 40)
        line = shapes.shape_event(0.0, 1.0, path)
        text = line.split(",", 9)[9]
        self.assertTrue(text.startswith("{\\an7\\pos(0.00,0.00)\\bord0\\shad0"))
        self.assertIn("\\p1}" + path + "{\\p0}", text)
        self.assertEqual(text.count("\\p1"), 1)
        self.assertEqual(text.count("\\p0"), 1)

    def test_colour_alpha_layer_and_pos_are_written(self) -> None:
        line = shapes.shape_event(
            0.0, 1.0, shapes.rect(0, 0, 5, 5),
            layer=3, fill="#112233", opacity=0.5, pos=(12.5, 20.0),
        )
        fields = line[len("Dialogue: "):].split(",", 9)
        self.assertEqual(fields[0], "3")
        text = fields[9]
        self.assertIn("\\pos(12.50,20.00)", text)
        self.assertIn("\\1c&H332211&", text)
        self.assertIn("\\1a&H80&", text)

    def test_times_follow_kinetic_writer_rounding_rules(self) -> None:
        """Aturan ditulis eksplisit: sama dengan `captions._ass_time`."""
        self.assertEqual(captions._ass_time(1.235), "0:00:01.24")
        self.assertEqual(captions._ass_time(1.2349), "0:00:01.23")
        self.assertEqual(captions._ass_time(59.999), "0:00:60.00")
        cases = [(1.235, 2.0), (61.234, 62.0), (0.0, 0.5), (3600.0, 3601.0)]
        for start, end in cases:
            with self.subTest(start=start):
                fields = shapes.shape_event(start, end, shapes.rect(0, 0, 1, 1)).split(",", 9)
                self.assertEqual(fields[1], captions._ass_time(start))
                self.assertEqual(fields[2], captions._ass_time(end))

    def test_extra_tags_are_inserted_before_drawing(self) -> None:
        line = shapes.shape_event(
            0.0, 1.0, shapes.circle(0, 0, 10), extra_tags="\\t(0,100,\\fscx120)"
        )
        text = line.split(",", 9)[9]
        self.assertIn("\\fscx120", text)
        self.assertLess(text.index("\\t(0,100,\\fscx120)"), text.index("\\p1"))

    def test_extra_tags_reject_braces_newlines_and_control_characters(self) -> None:
        bad = ["{", "}", "\\fscx120}", "\\fscx120{", "\n", "\r", "\x00", "\t", "\x7f"]
        for value in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError) as ctx:
                    shapes.shape_event(0.0, 1.0, shapes.rect(0, 0, 1, 1), extra_tags=value)
                self.assertIn("extra_tags", str(ctx.exception))

    def test_extra_tags_accept_real_ass_tags(self) -> None:
        for value in ("\\t(0,500,\\clip(1,2,3,4))", "\\clip(10,20,30,40)", ""):
            with self.subTest(value=value):
                shapes.shape_event(0.0, 1.0, shapes.rect(0, 0, 1, 1), extra_tags=value)

    def test_end_must_be_greater_than_start(self) -> None:
        for start, end in ((1.0, 1.0), (2.0, 1.0)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError) as ctx:
                    shapes.shape_event(start, end, shapes.rect(0, 0, 1, 1))
                self.assertIn("end", str(ctx.exception))

    def test_invalid_layer_style_and_pos_are_rejected(self) -> None:
        base = lambda **kw: shapes.shape_event(0.0, 1.0, shapes.rect(0, 0, 1, 1), **kw)
        for kwargs, name in (
            ({"layer": -1}, "layer"),
            ({"layer": 1.5}, "layer"),
            ({"style": "Sha,pe"}, "style"),
            ({"style": "Sha\npe"}, "style"),
            ({"pos": (0.0,)}, "pos"),
            ({"pos": (0.0, float("nan"))}, "pos"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError) as ctx:
                    base(**kwargs)
                self.assertIn(name, str(ctx.exception))

    def test_path_must_be_non_empty_and_not_inject_override(self) -> None:
        for path in ("", "   ", "m 0 0 l 1 1{\\p0}"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError) as ctx:
                    shapes.shape_event(0.0, 1.0, path)
                self.assertIn("path", str(ctx.exception))

    def test_custom_style_name_lands_in_field_four(self) -> None:
        line = shapes.shape_event(0.0, 1.0, shapes.rect(0, 0, 1, 1), style="Box")
        self.assertEqual(line.split(",", 9)[3], "Box")


# ---------------------------------------------------------------------------
# Wipe
# ---------------------------------------------------------------------------

class WipeTagsTest(unittest.TestCase):
    def test_right_wipe_exact_string(self) -> None:
        self.assertEqual(
            shapes.wipe_tags(100, 100, 900, 400, 0.0, 0.5, direction="right"),
            "\\clip(100.00,100.00,100.00,400.00)"
            "\\t(0,500,1,\\clip(100.00,100.00,900.00,400.00))",
        )

    def test_left_wipe_starts_at_right_edge(self) -> None:
        self.assertEqual(
            shapes.wipe_tags(100, 100, 900, 400, 0.1, 0.6, direction="left"),
            "\\clip(900.00,100.00,900.00,400.00)"
            "\\t(100,600,1,\\clip(100.00,100.00,900.00,400.00))",
        )

    def test_down_wipe_starts_at_top_edge(self) -> None:
        self.assertEqual(
            shapes.wipe_tags(100, 100, 900, 400, 0.0, 0.5, direction="down"),
            "\\clip(100.00,100.00,900.00,100.00)"
            "\\t(0,500,1,\\clip(100.00,100.00,900.00,400.00))",
        )

    def test_up_wipe_starts_at_bottom_edge(self) -> None:
        self.assertEqual(
            shapes.wipe_tags(100, 100, 900, 400, 0.0, 0.5, direction="up"),
            "\\clip(100.00,400.00,900.00,400.00)"
            "\\t(0,500,1,\\clip(100.00,100.00,900.00,400.00))",
        )

    def test_times_are_converted_to_integer_milliseconds(self) -> None:
        tag = shapes.wipe_tags(0, 0, 10, 10, 0.1234, 0.9876, accel=1.0)
        self.assertIn("\\t(123,988,1,", tag)
        self.assertNotIn("\\t(0.1234", tag)
        self.assertNotIn("\\t(0,0.9876", tag)

    def test_accel_is_written(self) -> None:
        tag = shapes.wipe_tags(0, 0, 10, 10, 0.0, 0.5, accel=2.0)
        self.assertIn("\\t(0,500,2,", tag)
        tag = shapes.wipe_tags(0, 0, 10, 10, 0.0, 0.5, accel=0.5)
        self.assertIn("\\t(0,500,0.5,", tag)

    def test_invalid_wipe_arguments_raise_value_error(self) -> None:
        base = lambda **kw: shapes.wipe_tags(0, 0, 10, 10, 0.0, 0.5, **kw)
        cases = [
            ({"direction": "diagonal"}, "direction"),
            ({"direction": "RIGHT"}, "direction"),
            ({"accel": 0.0}, "accel"),
            ({"accel": -1.0}, "accel"),
            ({"accel": float("nan")}, "accel"),
        ]
        for kwargs, name in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError) as ctx:
                    base(**kwargs)
                self.assertIn(name, str(ctx.exception))
        bad_calls = [
            (lambda: shapes.wipe_tags(100, 0, 100, 10, 0.0, 0.5), "x1"),
            (lambda: shapes.wipe_tags(0, 10, 10, 10, 0.0, 0.5), "y1"),
            (lambda: shapes.wipe_tags(0, 0, 10, 10, -0.1, 0.5), "t_start"),
            (lambda: shapes.wipe_tags(0, 0, 10, 10, 0.5, 0.5), "t_end"),
            (lambda: shapes.wipe_tags(0, 0, 10, 10, 0.6, 0.5), "t_end"),
            (lambda: shapes.wipe_tags(float("nan"), 0, 10, 10, 0.0, 0.5), "x0"),
        ]
        for call, name in bad_calls:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as ctx:
                    call()
                self.assertIn(name, str(ctx.exception))


# ---------------------------------------------------------------------------
# Dokumen ASS
# ---------------------------------------------------------------------------

class AssDocumentTest(unittest.TestCase):
    def _event(self) -> str:
        return shapes.shape_event(0.0, 1.0, shapes.rect(0, 0, 10, 10))

    def test_header_style_and_events_are_present(self) -> None:
        event = self._event()
        text = shapes.ass_document([event])
        for line in (
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 2",
            "[V4+ Styles]",
            "[Events]",
            "Style: Shape,",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ):
            self.assertIn(line, text)
        self.assertIn(event, text)
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("Style: ")), 1)
        self.assertNotIn("\r", text)

    def test_style_has_no_outline_or_shadow(self) -> None:
        text = shapes.ass_document([])
        style = [ln for ln in text.splitlines() if ln.startswith("Style: Shape,")][0]
        fields = style[len("Style: "):].split(",")
        # BorderStyle/Outline/Shadow ada di kolom 15/16/17 (0-based).
        self.assertEqual(fields[15], "1")  # BorderStyle
        self.assertEqual(fields[16], "0")  # Outline
        self.assertEqual(fields[17], "0")  # Shadow

    def test_custom_resolution_and_style_name(self) -> None:
        text = shapes.ass_document([], play_res=(720, 1280), style_name="Box")
        self.assertIn("PlayResX: 720", text)
        self.assertIn("PlayResY: 1280", text)
        self.assertIn("Style: Box,", text)
        self.assertNotIn("Style: Shape,", text)

    def test_events_are_joined_in_order(self) -> None:
        a = shapes.shape_event(0.0, 1.0, shapes.rect(0, 0, 1, 1))
        b = shapes.shape_event(1.0, 2.0, shapes.rect(1, 1, 2, 2))
        text = shapes.ass_document([a, b])
        self.assertLess(text.index(a), text.index(b))
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("Dialogue: ")), 2)

    def test_invalid_document_arguments_are_rejected(self) -> None:
        for kwargs, name in (
            ({"play_res": (0, 1920)}, "play_res"),
            ({"play_res": (1080, -1)}, "play_res"),
            ({"style_name": "Sha,pe"}, "style_name"),
            ({"style_name": "Sha\npe"}, "style_name"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError) as ctx:
                    shapes.ass_document([], **kwargs)
                self.assertIn(name, str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            shapes.ass_document(["Dialogue: 0,0:00:00.00,0:00:01.00,Shape,,0,0,0,,\n"])
        self.assertIn("events", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            shapes.ass_document("bukan daftar")
        self.assertIn("events", str(ctx.exception))


class ModuleSurfaceTest(unittest.TestCase):
    def test_all_is_explicit(self) -> None:
        expected = {
            "alpha",
            "ass_document",
            "check_mark",
            "circle",
            "colour",
            "line",
            "polyline",
            "rect",
            "rounded_rect",
            "shape_event",
            "wipe_tags",
        }
        self.assertEqual(set(shapes.__all__), expected)
        self.assertEqual(len(shapes.__all__), len(set(shapes.__all__)))


if __name__ == "__main__":
    unittest.main()
