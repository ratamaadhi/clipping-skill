"""Tes murni preset `chart_grow` di `scripts.presets` — tanpa ffmpeg.

Kontrak yang dikunci (docs/MOTION-TIER2-PLAN.md Langkah 5b, baris #10):

* props ketat: `labels` 3..8 string 1..10 karakter, `values` panjang sama dan
  tidak konstan, `tag` 1..16 karakter, `title` opsional <= 28, `grow`
  0,6..2,5 s; kunci tak dikenal ditolak dengan daftar kunci sah;
* label/tag diukur dengan `fontmetrics` dan DITOLAK bila tidak muat;
* `rect` opsional (bawaan 60,260,960,520); `rect.h` terlalu pendek untuk
  judul + plot + label ditolak, bukan disusutkan diam-diam;
* pemetaan nilai -> y linier: min di dasar plot, max di puncak; simpul x
  terdistribusi rata;
* kemajuan kepala garis memakai ease-in-out kosinus yang MONOTON dan
  mencapai lebar penuh tepat pada `start + ENTRY + grow`;
* titik ujung mengikuti kepala garis lewat satu event per sub-ruas `\\move`,
  dengan waktu relatif yang sama dengan rantai `\\t(\\clip)` garis;
* tag baru muncul setelah garis selesai tumbuh, di atas/di samping titik;
* maksimum 40 Dialogue untuk 8 titik; deterministik; font hilang -> satu
  peringatan, bukan exception.

Pembuktian piksel (bbox kartu, lebar garis per waktu, jarak titik-kepala,
label, tag, lapisan caption) ada di `tests/test_presets_chart_render.py`.
"""

from __future__ import annotations

import hashlib
import math
import re
import unittest
from pathlib import Path

from tests.helpers import ROOT

from scripts import presets
from scripts import shapes
from scripts.lib import fontmetrics

ARCHIVO_FILE = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"
DMSERIF_FILE = ROOT / "assets" / "fonts" / "DMSerifDisplay-Italic.ttf"

TYPE = "chart_grow"
FPS = 30.0
START = 0.4
END = 3.6
LABELS = ("SEN", "SEL", "RAB", "KAM", "JUM")
VALUES = (10.0, 40.0, 25.0, 55.0, 80.0)
TAG = "+240%"
TITLE = "GROWTH"

# Dokumen `checklist` untuk fixture tetap HARUS byte-identik dengan keluaran
# Langkah 5b-2 (diambil sebelum preset `chart_grow` ditambahkan).
CHECKLIST_GOLDEN_SHA256 = (
    "4aeca9985f515776a4bc7d6866298348a8f7f9f1e168b8b9001fb0c624240982"
)
# Dokumen `zoom_through_text` 5b-1 (konstanta sama dengan tes 5b-1/5b-2).
ZOOM_GOLDEN_SHA256 = (
    "d016b1dbfc61dbc473913967d19e7a645b63d359fb8f83431eab7943aa77b9b0"
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _clip(overlays: list | None = None, segments=None, clip_id: str = "clip_01") -> dict:
    segs = segments if segments is not None else ((0.0, 4.0),)
    return {
        "id": clip_id,
        "segments": [{"src_start": a, "src_end": b} for a, b in segs],
        "overlays": overlays if overlays is not None else [],
    }


def _props(**overrides: object) -> dict:
    props: dict = {
        "labels": list(LABELS),
        "values": list(VALUES),
        "tag": TAG,
        "title": TITLE,
    }
    props.update(overrides)
    return props


def _overlay(
    props: dict | None = None,
    *,
    start: object = START,
    end: object = END,
    rect: dict | None = None,
) -> dict:
    item: dict = {"type": TYPE, "start": start, "end": end}
    if props is not None:
        item["props"] = props
    if rect is not None:
        item["rect"] = rect
    return item


def _build(clip: dict, **kwargs: object):
    return presets.build_fx_ass(clip, fps=FPS, **kwargs)


def _dialogues(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def _fields(line: str) -> list[str]:
    return line[len("Dialogue: "):].split(",", 9)


def _role(line: str) -> str:
    return _fields(line)[4]


def _text_field(line: str) -> str:
    return _fields(line)[9]


def _shown_text(line: str) -> str:
    return _text_field(line).rsplit("}", 1)[-1]


def _seconds(stamp: str) -> float:
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _start_seconds(line: str) -> float:
    return _seconds(_fields(line)[1])


def _end_seconds(line: str) -> float:
    return _seconds(_fields(line)[2])


def _role_lines(ass: str, role: str) -> list[str]:
    return [ln for ln in _dialogues(ass) if _role(ln) == role]


def _shape_path(line: str) -> str:
    match = re.search(r"\\p1}(.*?)\{\\p0}", _text_field(line), re.S)
    if not match:
        raise AssertionError(f"event tidak punya path \\p1: {_text_field(line)!r}")
    return match.group(1)


def _path_bounds(path: str) -> tuple[float, float, float, float]:
    tokens = path.split()
    xs: list[float] = []
    ys: list[float] = []
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        i += 1
        pairs = 1 if cmd in ("m", "l") else 3
        for _ in range(pairs):
            xs.append(float(tokens[i]))
            ys.append(float(tokens[i + 1]))
            i += 2
    return min(xs), min(ys), max(xs), max(ys)


def _move(line: str) -> tuple[float, float, float, float, int, int] | None:
    match = re.search(
        r"\\move\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(\d+),(\d+)\)",
        _text_field(line),
    )
    if not match:
        return None
    return (
        float(match.group(1)), float(match.group(2)),
        float(match.group(3)), float(match.group(4)),
        int(match.group(5)), int(match.group(6)),
    )


def _pos(line: str) -> tuple[float, float] | None:
    match = re.search(r"\\pos\((-?[\d.]+),(-?[\d.]+)\)", _text_field(line))
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def _clip_chain(line: str) -> tuple[list[tuple[float, float, float, float]],
                                   list[tuple[int, int]]]:
    text = _text_field(line)
    boxes = [
        tuple(float(v) for v in match)
        for match in re.findall(
            r"\\clip\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\)", text
        )
    ]
    times = [
        (int(a), int(b))
        for a, b in re.findall(r"\\t\((\d+),(\d+),1,\\clip\(", text)
    ]
    return boxes, times


def _alpha_chain(line: str) -> list[tuple[int, int]]:
    return [
        (int(a), int(b))
        for a, b in re.findall(r"\\t\((\d+),(\d+),\\alpha&HFF&\)", _text_field(line))
    ]


def _scale_chain(line: str) -> list[tuple[int, int, int]]:
    out = []
    for t0, t1, sx, sy in re.findall(
        r"\\t\((\d+),(\d+),\\fscx(\d+)\\fscy(\d+)\)", _text_field(line)
    ):
        out.append((int(t0), int(t1), int(sx)))
    return out


def _geometry(has_title: bool = True) -> dict:
    return presets._chart_geometry(
        {"x": presets.CHART_CARD_X, "y": presets.CHART_CARD_Y,
         "w": presets.CHART_CARD_W, "h": presets.CHART_CARD_H},
        has_title,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class RegistryTest(unittest.TestCase):
    def test_chart_is_registered(self) -> None:
        self.assertIn(TYPE, presets.REGISTRY)
        self.assertIn(TYPE, presets.PRESET_TYPES)
        self.assertTrue(callable(presets.REGISTRY[TYPE]))

    def test_preset_types_order_is_stable(self) -> None:
        self.assertEqual(
            presets.PRESET_TYPES,
            ("zoom_through_text", "checklist", "chart_grow", "ui_panel", "phone_frame"),
        )
        self.assertEqual(set(presets.REGISTRY), set(presets.PRESET_TYPES))

    def test_unknown_types_are_ignored_without_warnings(self) -> None:
        clip = _clip([
            {"type": "future_effect", "start": 0.0, "end": 1.0, "props": {}},
            {"type": "vs", "start": 0.0, "end": 1.0, "left": "A", "right": "B"},
        ])
        ass, warnings = _build(clip)
        self.assertIsNone(ass)
        self.assertEqual(warnings, [])


# ---------------------------------------------------------------------------
# Validasi props
# ---------------------------------------------------------------------------

class PropsValidationTest(unittest.TestCase):
    def _assert_error(self, props: object, needle: str) -> str:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(props)]))
        message = str(ctx.exception)
        self.assertIn("overlay[0]", message)
        self.assertIn(TYPE, message)
        self.assertIn(needle, message, msg=message)
        return message

    def test_props_not_object(self) -> None:
        self._assert_error([], "props")

    def test_labels_missing(self) -> None:
        self._assert_error({"values": list(VALUES), "tag": TAG}, "labels")

    def test_labels_not_list(self) -> None:
        self._assert_error(_props(labels="SEN"), "labels")

    def test_labels_too_few(self) -> None:
        self._assert_error(_props(labels=["A", "B"], values=[1.0, 2.0]), "labels")

    def test_labels_too_many(self) -> None:
        self._assert_error(
            _props(labels=["A"] * 9, values=[float(i) for i in range(9)]), "labels"
        )

    def test_label_items_invalid(self) -> None:
        cases = (
            (7, "labels"),
            ("", "labels"),
            ("x" * 11, "labels"),
            ("a\nb", "labels"),
        )
        for bad, needle in cases:
            with self.subTest(bad=bad):
                labels = ["A", bad, "C"]
                self._assert_error(
                    _props(labels=labels, values=[1.0, 2.0, 3.0]), needle
                )

    def test_values_missing(self) -> None:
        self._assert_error({"labels": list(LABELS), "tag": TAG}, "values")

    def test_values_not_list(self) -> None:
        self._assert_error(_props(values="123"), "values")

    def test_values_length_mismatch(self) -> None:
        self._assert_error(_props(values=[1.0, 2.0]), "values")
        self._assert_error(_props(values=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), "values")

    def test_values_must_be_finite_numbers(self) -> None:
        for bad in ("1", True, float("nan"), float("inf")):
            with self.subTest(bad=bad):
                self._assert_error(
                    _props(values=[1.0, bad, 3.0, 4.0, 5.0]), "values"
                )

    def test_constant_values_are_rejected(self) -> None:
        message = self._assert_error(
            _props(values=[5.0, 5.0, 5.0, 5.0, 5.0]), "values"
        )
        self.assertIn("skala", message)

    def test_tag_rules(self) -> None:
        for bad in ("", "x" * 17, "a\nb", 7):
            with self.subTest(bad=bad):
                self._assert_error(_props(tag=bad), "tag")

    def test_title_rules(self) -> None:
        for bad in ("x" * 29, "a\nb", 7):
            with self.subTest(bad=bad):
                self._assert_error(_props(title=bad), "title")

    def test_title_optional(self) -> None:
        props = _props()
        props.pop("title")
        ass, warnings = _build(_clip([_overlay(props)]))
        self.assertIsNotNone(ass)
        self.assertEqual(warnings, [])

    def test_grow_values(self) -> None:
        for bad in (0.59, 2.51, "1.2", True, float("nan")):
            with self.subTest(bad=bad):
                self._assert_error(_props(grow=bad), "grow")

    def test_grow_boundaries_accepted(self) -> None:
        for value in (0.6, 2.5):
            with self.subTest(value=value):
                ass, warnings = _build(
                    _clip([_overlay(_props(grow=value), start=0.4, end=5.0)],
                          segments=((0.0, 5.0),))
                )
                self.assertIsNotNone(ass)
                self.assertEqual(warnings, [])

    def test_unknown_prop_key_lists_valid_keys(self) -> None:
        message = self._assert_error(_props(done_at=1.0), "done_at")
        for key in ("labels", "values", "tag", "title", "grow"):
            self.assertIn(key, message)

    def test_second_overlay_error_names_its_index(self) -> None:
        overlays = [
            _overlay(_props(), start=0.4, end=3.6),
            _overlay(_props(labels=["A"]), start=0.4, end=3.6),
        ]
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip(overlays))
        self.assertIn("overlay[1]", str(ctx.exception))

    def test_grow_must_finish_inside_window(self) -> None:
        # start 0.4 + ENTRY 0.3 + grow 1.2 = 1.9 > end 1.6.
        message = ""
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(), start=0.4, end=1.6)]))
        message = str(ctx.exception)
        self.assertIn("grow", message)
        self.assertIn("overlay[0]", message)

    def test_overlay_outside_clip_is_skipped_with_one_warning(self) -> None:
        ass, warnings = _build(
            _clip([_overlay(_props(), start=9.0, end=10.0)])
        )
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1)
        self.assertIn("overlay[0]", warnings[0])


# ---------------------------------------------------------------------------
# Teks harus muat
# ---------------------------------------------------------------------------

class TextFitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.font = fontmetrics.Font.load(ARCHIVO_FILE)

    def test_label_too_wide_names_measured_and_available(self) -> None:
        label = "W" * 10
        measured = self.font.width(label, presets.CHART_LABEL_EM)
        available = min(
            (presets.CHART_CARD_W - 2 * presets.CHART_PAD_X
             - 2 * presets.CHART_PLOT_INSET_X) / 2.0
            - presets.CHART_LABEL_SIDE_GAP,
            2.0 * (presets.CHART_PAD_X + presets.CHART_PLOT_INSET_X
                   - presets.CHART_LABEL_SIDE_GAP),
        )
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(labels=["A", label, "C"],
                                         values=[1.0, 2.0, 3.0]))]))
        message = str(ctx.exception)
        self.assertIn("tidak muat", message)
        self.assertIn(f"{measured:g}", message)
        self.assertIn(f"{available:g}", message)

    def test_short_labels_fit(self) -> None:
        ass, warnings = _build(
            _clip([_overlay(_props(labels=["SEN", "SEL", "RAB"],
                                  values=[1.0, 2.0, 3.0]))])
        )
        self.assertIsNotNone(ass)
        self.assertEqual(warnings, [])

    def test_tag_too_wide_in_narrow_card(self) -> None:
        rect = {"x": 60, "y": 260, "w": 500, "h": 520}
        tag = "W" * 16
        measured = self.font.width(tag, presets.CHART_TAG_EM) + 2 * presets.CHART_TAG_PAD_X
        available = rect["w"] - 2 * presets.CHART_PAD_X
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([
                _overlay(_props(labels=["A", "B", "C"], values=[1.0, 2.0, 3.0],
                                tag=tag), rect=rect)
            ]))
        message = str(ctx.exception)
        self.assertIn("tidak muat", message)
        self.assertIn(f"{measured:g}", message)
        self.assertIn(f"{available:g}", message)


# ---------------------------------------------------------------------------
# rect + tinggi kartu
# ---------------------------------------------------------------------------

class RectTest(unittest.TestCase):
    def _card_bounds(self, clip: dict) -> tuple[float, float, float, float]:
        ass, warnings = _build(clip)
        self.assertEqual(warnings, [])
        assert ass is not None
        cards = _role_lines(ass, "card")
        self.assertEqual(len(cards), 1)
        return _path_bounds(_shape_path(cards[0]))

    def test_default_rect_is_60_260_960_520(self) -> None:
        bounds = self._card_bounds(_clip([_overlay(_props())]))
        self.assertEqual(
            tuple(round(v, 2) for v in bounds),
            (60.0, 260.0, 1020.0, 780.0),
        )

    def test_custom_rect_is_respected(self) -> None:
        rect = {"x": 100, "y": 300, "w": 800, "h": 400}
        bounds = self._card_bounds(_clip([_overlay(_props(labels=["A", "B", "C"],
                                                         values=[1.0, 2.0, 3.0]),
                                          rect=rect)]))
        self.assertEqual(tuple(round(v, 2) for v in bounds), (100.0, 300.0, 900.0, 700.0))

    def test_required_height_with_title_is_386(self) -> None:
        required = (
            2 * presets.CHART_PAD_Y + presets.CHART_TITLE_H
            + presets.CHART_TAG_BAND + presets.CHART_PLOT_MIN_H
            + presets.CHART_LABEL_H
        )
        self.assertEqual(required, 386.0)
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(), rect={"x": 60, "y": 200, "w": 960,
                                                   "h": required - 1})]))
        message = str(ctx.exception)
        self.assertIn("rect", message)
        self.assertIn("386", message)

    def test_required_height_without_title_is_330(self) -> None:
        props = _props()
        props.pop("title")
        required = (
            2 * presets.CHART_PAD_Y + presets.CHART_TAG_BAND
            + presets.CHART_PLOT_MIN_H + presets.CHART_LABEL_H
        )
        self.assertEqual(required, 330.0)
        with self.assertRaises(presets.PresetError):
            _build(_clip([_overlay(props, rect={"x": 60, "y": 200, "w": 960,
                                                "h": required - 1})]))

    def test_rect_exact_height_accepted(self) -> None:
        for props, height in ((_props(), 386), (None, 330)):
            with self.subTest(height=height):
                if props is None:
                    props = _props()
                    props.pop("title")
                ass, warnings = _build(
                    _clip([_overlay(props, rect={"x": 60, "y": 200, "w": 960,
                                                 "h": height})])
                )
                self.assertIsNotNone(ass)
                self.assertEqual(warnings, [])

    def test_rect_must_be_inside_canvas(self) -> None:
        cases = (
            {"x": -1, "y": 200, "w": 960, "h": 386},
            {"x": 0, "y": -1, "w": 960, "h": 386},
            {"x": 121, "y": 200, "w": 960, "h": 386},
            {"x": 60, "y": 1535, "w": 960, "h": 386},
        )
        for rect in cases:
            with self.subTest(rect=rect):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(), rect=rect)]))
                self.assertIn("rect", str(ctx.exception))

    def test_rect_shape_validation(self) -> None:
        cases = (
            "kotak",
            {"x": 60, "y": 260, "w": 960},
            {"x": 60, "y": 260, "w": 0, "h": 520},
            {"x": 60, "y": 260, "w": 960, "h": -1},
            {"x": 60, "y": 260, "w": 960, "h": 520, "z": 1},
            {"x": "60", "y": 260, "w": 960, "h": 520},
        )
        for rect in cases:
            with self.subTest(rect=rect):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(), rect=rect)]))
                self.assertIn("rect", str(ctx.exception))


# ---------------------------------------------------------------------------
# Pemetaan nilai -> y + distribusi x
# ---------------------------------------------------------------------------

class ValueMappingTest(unittest.TestCase):
    def test_geometry_numbers_are_hardcoded(self) -> None:
        geom = _geometry(has_title=True)
        self.assertAlmostEqual(geom["plot_x0"], 128.0, delta=0.01)
        self.assertAlmostEqual(geom["plot_x1"], 952.0, delta=0.01)
        self.assertAlmostEqual(geom["plot_top"], 442.0, delta=0.01)
        self.assertAlmostEqual(geom["plot_bottom"], 696.0, delta=0.01)
        self.assertAlmostEqual(geom["label_y"], 708.0, delta=0.01)

    def test_min_at_bottom_and_max_at_top(self) -> None:
        geom = _geometry(has_title=True)
        points = presets._chart_points(list(VALUES), geom)
        self.assertAlmostEqual(points[0][1], geom["plot_bottom"], delta=0.01)  # 10
        self.assertAlmostEqual(points[4][1], geom["plot_top"], delta=0.01)     # 80
        self.assertAlmostEqual(points[1][1], 587.142857, delta=0.01)          # 40
        self.assertAlmostEqual(points[2][1], 641.571428, delta=0.01)          # 25
        self.assertAlmostEqual(points[3][1], 532.714285, delta=0.01)          # 55

    def test_linear_mapping_midpoint(self) -> None:
        geom = _geometry(has_title=True)
        mid = presets._chart_points([0.0, 50.0, 100.0], geom)
        self.assertAlmostEqual(mid[1][1], (geom["plot_top"] + geom["plot_bottom"]) / 2.0,
                               delta=0.01)

    def test_x_nodes_are_evenly_distributed(self) -> None:
        geom = _geometry(has_title=True)
        points = presets._chart_points(list(VALUES), geom)
        xs = [x for x, _ in points]
        self.assertAlmostEqual(xs[0], 128.0, delta=0.01)
        self.assertAlmostEqual(xs[-1], 952.0, delta=0.01)
        steps = [b - a for a, b in zip(xs, xs[1:])]
        for step in steps:
            self.assertAlmostEqual(step, steps[0], delta=0.01)

    def test_titles_shifts_plot_top_only(self) -> None:
        with_title = _geometry(has_title=True)
        without = _geometry(has_title=False)
        self.assertAlmostEqual(
            with_title["plot_top"] - without["plot_top"], presets.CHART_TITLE_H,
            delta=0.01,
        )
        self.assertAlmostEqual(with_title["plot_bottom"], without["plot_bottom"],
                               delta=0.01)


# ---------------------------------------------------------------------------
# Kurva tumbuh + kepala garis
# ---------------------------------------------------------------------------

class GrowCurveTest(unittest.TestCase):
    def test_progress_is_cosine_ease_in_out(self) -> None:
        # Angka tangan: ease kosinus, BUKAN linier.
        self.assertAlmostEqual(presets._chart_progress(0.0), 0.0, places=9)
        self.assertAlmostEqual(presets._chart_progress(0.25), 0.1464466094, places=6)
        self.assertAlmostEqual(presets._chart_progress(0.5), 0.5, places=6)
        self.assertAlmostEqual(presets._chart_progress(0.75), 0.8535533906, places=6)
        self.assertAlmostEqual(presets._chart_progress(1.0), 1.0, places=9)

    def test_progress_is_monotone_and_clamped(self) -> None:
        values = [presets._chart_progress(i / 200.0) for i in range(-20, 221)]
        self.assertEqual(values[0], 0.0)
        self.assertEqual(values[-1], 1.0)
        for left, right in zip(values, values[1:]):
            self.assertGreaterEqual(right, left)

    def test_head_follows_polyline_between_vertices(self) -> None:
        geom = _geometry(has_title=True)
        points = presets._chart_points([0.0, 100.0, 50.0], geom)
        x, y = presets._chart_head_point(points, 0.25)
        self.assertAlmostEqual(x, points[0][0] + 0.25 * (points[-1][0] - points[0][0]),
                               delta=0.01)
        self.assertAlmostEqual(y, points[1][1] * 0.5 + points[0][1] * 0.5, delta=0.01)

    def test_grow_nodes_reach_full_width_exactly_at_grow_end(self) -> None:
        nodes = presets._chart_grow_nodes(36)
        self.assertEqual(nodes[0], (0, 0.0))
        self.assertEqual(nodes[-1][0], 36)
        self.assertAlmostEqual(nodes[-1][1], 1.0, places=9)
        frames = [frame for frame, _ in nodes]
        self.assertEqual(frames, sorted(frames))
        self.assertEqual(len(frames), len(set(frames)))
        self.assertLessEqual(len(nodes) - 1, presets.CHART_GROW_SEGMENTS)

    def test_clip_chain_matches_head_positions(self) -> None:
        ass, _ = _build(_clip([_overlay(_props())]))
        assert ass is not None
        line = _role_lines(ass, "line")[0]
        boxes, times = _clip_chain(line)
        geom = _geometry(has_title=True)
        points = presets._chart_points(list(VALUES), geom)
        nodes = presets._chart_grow_nodes(int(round(1.2 * FPS)))
        self.assertEqual(len(boxes), len(nodes))
        for (x0, _y0, x1, _y1), (_frame, progress) in zip(boxes, nodes):
            self.assertAlmostEqual(x0, geom["plot_x0"], delta=0.02)
            self.assertAlmostEqual(x1, points[0][0] + progress * (points[-1][0] - points[0][0]),
                                   delta=0.02)
        rights = [box[2] for box in boxes]
        self.assertEqual(rights, sorted(rights))
        self.assertEqual(len(times), len(nodes) - 1)
        for (_a, b), (_c, d) in zip(times, times[1:]):
            self.assertEqual(b, _c)

    def test_dot_moves_track_the_same_nodes(self) -> None:
        ass, _ = _build(_clip([_overlay(_props())]))
        assert ass is not None
        dots = _role_lines(ass, "dot")
        nodes = presets._chart_grow_nodes(int(round(1.2 * FPS)))
        self.assertEqual(len(dots), len(nodes) - 1)
        geom = _geometry(has_title=True)
        points = presets._chart_points(list(VALUES), geom)
        expected = [presets._chart_head_point(points, progress)
                    for _frame, progress in nodes]
        previous_end: tuple[float, float] | None = None
        for i, line in enumerate(dots):
            move = _move(line)
            self.assertIsNotNone(move)
            assert move is not None
            x0, y0, x1, y1, _t0, _t1 = move
            want_x0, want_y0 = expected[i]
            want_x1, want_y1 = expected[i + 1]
            self.assertAlmostEqual(x0, want_x0, delta=0.02)
            self.assertAlmostEqual(y0, want_y0, delta=0.02)
            self.assertAlmostEqual(x1, want_x1, delta=0.02)
            self.assertAlmostEqual(y1, want_y1, delta=0.02)
            if previous_end is not None:
                self.assertEqual((x0, y0), previous_end)
            previous_end = (x1, y1)
        self.assertEqual(
            (round(_move(dots[-1])[2], 2), round(_move(dots[-1])[3], 2)),
            (round(points[-1][0], 2), round(points[-1][1], 2)),
        )


# ---------------------------------------------------------------------------
# Struktur dokumen
# ---------------------------------------------------------------------------

class DocumentStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ass, self.warnings = _build(_clip([_overlay(_props())]))
        assert self.ass is not None
        self.lines = _dialogues(self.ass)

    def test_every_dialogue_has_ten_fields(self) -> None:
        self.assertTrue(self.lines)
        for line in self.lines:
            with self.subTest(line=line[:50]):
                self.assertEqual(len(_fields(line)), 10)

    def test_event_budget_for_eight_points(self) -> None:
        labels = ["A", "B", "C", "D", "E", "F", "G", "H"]
        values = [1.0, 5.0, 2.0, 8.0, 3.0, 6.0, 4.0, 7.0]
        ass, warnings = _build(
            _clip([_overlay(_props(labels=labels, values=values),
                            end=4.0)], segments=((0.0, 4.0),))
        )
        assert ass is not None
        count = len(_dialogues(ass))
        self.assertLessEqual(count, presets.CHART_MAX_DIALOGUES, msg=count)
        self.assertEqual(count, 31)

    def test_layer_order(self) -> None:
        def layers(role: str) -> set[int]:
            return {int(_fields(line)[0]) for line in _role_lines(self.ass, role)}

        base = layers("card") | layers("grid") | layers("axis")
        self.assertEqual(base, {presets.CHART_CARD_LAYER})
        self.assertEqual(layers("line"), {presets.CHART_LINE_LAYER})
        self.assertEqual(layers("dot"), {presets.CHART_DOT_LAYER})
        text = layers("title") | layers("label")
        self.assertEqual(text, {presets.CHART_TEXT_LAYER})
        self.assertEqual(layers("tagbubble"), {presets.CHART_TAG_BUBBLE_LAYER})
        self.assertEqual(layers("tagtext"), {presets.CHART_TAG_TEXT_LAYER})
        self.assertLess(max(base), min(layers("line")))
        self.assertLess(max(layers("line")), min(layers("dot")))
        self.assertLess(max(layers("dot")), min(text))
        self.assertLess(max(text), min(layers("tagbubble")))
        self.assertLess(max(layers("tagbubble")), min(layers("tagtext")))

    def test_card_uses_checklist_palette_and_radius(self) -> None:
        self.assertEqual(presets.CARD_COLOUR, "#14161B")
        self.assertEqual(presets.CHART_CARD_RADIUS, 40.0)
        self.assertAlmostEqual(presets.CHART_CARD_OPACITY, 0.86, places=2)
        card = _role_lines(self.ass, "card")[0]
        text = _text_field(card)
        self.assertIn(f"\\1c{shapes.colour('#14161B')}", text)
        self.assertIn(f"\\1a{shapes.alpha(0.86)}", text)

    def test_line_colour_and_thickness(self) -> None:
        self.assertEqual(presets.CHART_LINE_COLOUR, "#FFD60A")
        self.assertEqual(presets.CHART_LINE_THICKNESS, 10.0)
        line = _role_lines(self.ass, "line")[0]
        self.assertIn(f"\\1c{shapes.colour('#FFD60A')}", _text_field(line))
        bounds = _path_bounds(_shape_path(line))
        # Stroke 10 px memperlebar tiap ujung <= 5 px dari simpul pertama/akhir.
        self.assertAlmostEqual(bounds[0], 128.0, delta=6.0)
        self.assertAlmostEqual(bounds[2], 952.0, delta=6.0)

    def test_line_path_has_round_joints(self) -> None:
        # polyline n titik = (n-1) ruas + (n-2) lingkaran sambungan. Mutan
        # "tanpa lingkaran sambungan" mengganti bentuk ini.
        path = _shape_path(_role_lines(self.ass, "line")[0])
        n = len(VALUES)
        self.assertEqual(path.count("m "), 2 * n - 3)
        self.assertEqual(path.count("b "), 4 * (n - 2))

    def test_dots_are_circles_with_dark_ring(self) -> None:
        dots = _role_lines(self.ass, "dot")
        self.assertTrue(dots)
        for dot in dots:
            path = _shape_path(dot)
            self.assertEqual(path.count("b "), 4)
            x0, y0, x1, y1 = _path_bounds(path)
            self.assertAlmostEqual(x1 - x0, 2 * presets.CHART_DOT_RADIUS, delta=0.1)
            self.assertAlmostEqual(y1 - y0, 2 * presets.CHART_DOT_RADIUS, delta=0.1)
            self.assertIn(f"\\bord{presets.CHART_DOT_RING:g}", _text_field(dot))

    def test_grid_and_axis_events(self) -> None:
        self.assertEqual(presets.CHART_GRID_LINES, 4)
        grid = _role_lines(self.ass, "grid")
        axis = _role_lines(self.ass, "axis")
        self.assertEqual(len(grid), 1)
        self.assertEqual(len(axis), 1)
        self.assertEqual(_shape_path(grid[0]).count("m "), 4)
        self.assertEqual(_shape_path(grid[0]).count("m "), presets.CHART_GRID_LINES)
        self.assertEqual(_shape_path(axis[0]).count("m "), 1)
        self.assertIn(f"\\1c{shapes.colour(presets.CHART_GRID_COLOUR)}",
                      _text_field(grid[0]))
        self.assertIn(f"\\1c{shapes.colour(presets.CHART_AXIS_COLOUR)}",
                      _text_field(axis[0]))
        axis_bounds = _path_bounds(_shape_path(axis[0]))
        self.assertAlmostEqual((axis_bounds[1] + axis_bounds[3]) / 2.0, 696.0, delta=0.01)

        labels = _role_lines(self.ass, "label")
        self.assertEqual(len(labels), len(LABELS))
        for line, want in zip(labels, [128.0, 334.0, 540.0, 746.0, 952.0]):
            move = _move(line)
            self.assertIsNotNone(move)
            assert move is not None
            self.assertAlmostEqual(move[2], want, delta=0.02)
            self.assertAlmostEqual(move[3], 708.0, delta=0.02)

    def test_labels_appear_in_order_and_match_their_nodes(self) -> None:
        labels = _role_lines(self.ass, "label")
        self.assertEqual([_shown_text(line) for line in labels], list(LABELS))
        xs = [128.0, 334.0, 540.0, 746.0, 952.0]
        for line, want in zip(labels, xs):
            move = _move(line)
            assert move is not None
            self.assertAlmostEqual(move[2], want, delta=0.02)

    def test_title_is_top_left_and_optional(self) -> None:
        title = _role_lines(self.ass, "title")
        self.assertEqual(len(title), 1)
        move = _move(title[0])
        assert move is not None
        self.assertAlmostEqual(move[2], 60.0 + presets.CHART_PAD_X, delta=0.02)
        self.assertAlmostEqual(move[3], 260.0 + presets.CHART_PAD_Y, delta=0.02)
        self.assertEqual(_shown_text(title[0]), TITLE)

        props = _props()
        props.pop("title")
        ass, _ = _build(_clip([_overlay(props)]))
        assert ass is not None
        self.assertEqual(_role_lines(ass, "title"), [])

    def test_escape_braces_and_backslash(self) -> None:
        ass, _ = _build(_clip([
            _overlay(_props(labels=["A{B", "C}D", "E\\F"], values=[1.0, 2.0, 3.0],
                            tag="x{y}\\z"))
        ]))
        assert ass is not None
        label_texts = [_shown_text(line) for line in _role_lines(ass, "label")]
        self.assertEqual(label_texts, ["A(B", "C)D", "E/F"])
        tag_text = _shown_text(_role_lines(ass, "tagtext")[0])
        self.assertEqual(tag_text, "x(y)/z")
        for text in label_texts + [tag_text]:
            self.assertNotIn("{", text)
            self.assertNotIn("}", text)
            self.assertNotIn("\\", text)

    def test_sans_style_uses_bundled_archivo(self) -> None:
        font = fontmetrics.Font.load(ARCHIVO_FILE)
        rows = [
            line for line in self.ass.splitlines()
            if line.startswith(f"Style: {presets.CHECK_STYLE},")
        ]
        self.assertEqual(len(rows), 1)
        fields = rows[0][len("Style: "):].split(",")
        self.assertEqual(fields[1], font.family)
        self.assertNotIn("Style: Serif,", self.ass)

    def test_entry_move_is_rigid(self) -> None:
        self.assertEqual(presets.CHART_ENTRY_OFFSET, 60.0)
        entry_roles = ("card", "grid", "axis", "line", "title", "label")
        windows: set[tuple[int, int]] = set()
        deltas: set[float] = set()
        for role in entry_roles:
            for line in _role_lines(self.ass, role):
                move = _move(line)
                self.assertIsNotNone(move, msg=f"{role} tidak punya \\move")
                assert move is not None
                x0, y0, x1, y1, t0, t1 = move
                if role in ("card", "grid", "axis", "line"):
                    self.assertEqual((x0, y0), (0.0, -presets.CHART_ENTRY_OFFSET))
                    self.assertEqual((x1, y1), (0.0, 0.0))
                else:
                    self.assertAlmostEqual(x1 - x0, 0.0, delta=0.01)
                    self.assertAlmostEqual(y1 - y0, presets.CHART_ENTRY_OFFSET,
                                           delta=0.01)
                windows.add((t0, t1))
                deltas.add(round(y1 - y0, 2))
        self.assertEqual(len(windows), 1, msg=windows)
        self.assertEqual(deltas, {60.0})
        self.assertEqual(deltas, {presets.CHART_ENTRY_OFFSET})

    def test_all_elements_move_by_chart_entry_offset_during_entry(self) -> None:
        self.assertAlmostEqual(presets.CHART_ENTRY_OFFSET, 60.0, delta=0.01)
        entry_roles = ("card", "grid", "axis", "line", "title", "label")
        for role in entry_roles:
            lines = _role_lines(self.ass, role)
            self.assertTrue(lines, msg=f"tidak ada event untuk {role}")
            for line in lines:
                move = _move(line)
                self.assertIsNotNone(move, msg=f"{role} tidak punya \\move")
                assert move is not None
                x0, y0, x1, y1, t0, t1 = move
                delta_y = y1 - y0 if role not in ("card", "grid", "axis", "line") else -y0
                self.assertAlmostEqual(
                    delta_y, 60.0, delta=0.01,
                    msg=f"{role} tidak bergerak sejauh 60 px ({delta_y})",
                )

    def test_dot_ring_is_dark_and_thin(self) -> None:
        self.assertEqual(presets.CHART_DOT_RING_COLOUR, "#14161B")
        self.assertLessEqual(presets.CHART_DOT_RING, 4.0)
        dot = _role_lines(self.ass, "dot")[0]
        self.assertIn(f"\\3c{shapes.colour('#14161B')}", _text_field(dot))


# ---------------------------------------------------------------------------
# Waktu: kepala garis, titik, tag
# ---------------------------------------------------------------------------

class TimingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ass, self.warnings = _build(_clip([_overlay(_props())]))
        assert self.ass is not None
        self.start_t = _start_seconds(_role_lines(self.ass, "line")[0])

    def test_grow_starts_after_rigid_entry_and_ends_at_frame_57(self) -> None:
        # start 0.4 -> frame 12; ENTRY 0.3 -> 9 frame; grow 1.2 -> 36 frame.
        entry_frame = 12 + 9
        grow_end_frame = entry_frame + 36
        self.assertEqual(grow_end_frame, 57)
        line = _role_lines(self.ass, "line")[0]
        _boxes, times = _clip_chain(line)
        self.assertEqual(
            times[0][0], round((entry_frame / FPS - self.start_t) * 1000.0)
        )
        self.assertEqual(
            times[-1][1], round((grow_end_frame / FPS - self.start_t) * 1000.0)
        )
        self.assertEqual(times[-1][1], 1530)

    def test_dot_events_start_at_their_node_frames(self) -> None:
        nodes = presets._chart_grow_nodes(36)
        dots = _role_lines(self.ass, "dot")
        start_frame = 12 + 9
        for line, (offset, _progress) in zip(dots, nodes[:-1]):
            want = presets._ass_time(
                presets._frame_start_time(start_frame + offset, FPS)
            )
            self.assertEqual(_fields(line)[1], want)
        self.assertEqual(_fields(dots[-1])[2], "0:00:03.60")

    def test_tag_starts_exactly_after_grow(self) -> None:
        grow_end_frame = 57
        want = presets._ass_time(
            presets._frame_start_time(grow_end_frame, FPS)
        )
        self.assertEqual(want, "0:00:01.87")
        for role in ("tagbubble", "tagtext"):
            line = _role_lines(self.ass, role)[0]
            self.assertEqual(_fields(line)[1], want)
        bubble = _role_lines(self.ass, "tagbubble")[0]
        self.assertIn("\\fscx0\\fscy0", _text_field(bubble))
        chain = _scale_chain(bubble)
        values = [value for _a, _b, value in chain]
        self.assertGreater(max(values), 100, msg=f"tanpa overshoot: {values}")
        self.assertEqual(values[-1], 100)

    def test_tag_position_is_above_the_endpoint(self) -> None:
        font = fontmetrics.Font.load(ARCHIVO_FILE)
        bubble_w, bubble_h = presets._chart_tag_size(TAG, font)
        self.assertAlmostEqual(bubble_h, presets.CHART_TAG_H, delta=0.01)
        geom = _geometry(has_title=True)
        points = presets._chart_points(list(VALUES), geom)
        cx, cy = presets._chart_tag_center(
            {"x": 60.0, "y": 260.0, "w": 960.0, "h": 520.0},
            points[-1], bubble_w, bubble_h,
        )
        text_pos = _pos(_role_lines(self.ass, "tagtext")[0])
        bubble_pos = _pos(_role_lines(self.ass, "tagbubble")[0])
        self.assertIsNotNone(text_pos)
        self.assertIsNotNone(bubble_pos)
        self.assertAlmostEqual(text_pos[0], cx, delta=0.02)
        self.assertAlmostEqual(text_pos[1], cy, delta=0.02)
        self.assertAlmostEqual(bubble_pos[0], cx, delta=0.02)
        self.assertAlmostEqual(bubble_pos[1], cy, delta=0.02)
        self.assertGreater(cy, points[-1][1] - 2 * presets.CHART_TAG_H)
        self.assertLess(cy, points[-1][1])

        # Path gelembung digambar relatif terhadap `\pos` (pusat 0,0).
        bounds = _path_bounds(_shape_path(_role_lines(self.ass, "tagbubble")[0]))
        self.assertAlmostEqual(bounds[0], -bubble_w / 2.0, delta=0.02)
        self.assertAlmostEqual(bounds[2], bubble_w / 2.0, delta=0.02)
        self.assertAlmostEqual(bounds[1], -bubble_h / 2.0, delta=0.02)
        self.assertAlmostEqual(bounds[3], bubble_h / 2.0, delta=0.02)

    def test_exit_fade_is_200ms_on_every_event(self) -> None:
        for line in _dialogues(self.ass):
            chain = _alpha_chain(line)
            self.assertTrue(chain, msg=f"{_role(line)} tanpa fade keluar")
            t0, t1 = chain[-1]
            self.assertAlmostEqual(
                t1 - t0, round(presets.CHART_EXIT * 1000), delta=1,
                msg=f"{_role(line)}: fade {t0}..{t1} ms",
            )
        card = _role_lines(self.ass, "card")[0]
        self.assertIn("\\1a&HFF&", _text_field(card))
        self.assertIn("\\t(0,330,0.5,", _text_field(card))

    def test_overlay_start_is_clamped_to_zero(self) -> None:
        ass, warnings = _build(
            _clip([_overlay(_props(), start=-0.3, end=3.0)],
                  segments=((0.0, 3.0),))
        )
        self.assertIsNotNone(ass)
        self.assertEqual(warnings, [])
        assert ass is not None
        line = _role_lines(ass, "line")[0]
        self.assertEqual(_fields(line)[1], "0:00:00.00")


# ---------------------------------------------------------------------------
# Determinisme + font + dokumen lama
# ---------------------------------------------------------------------------

class FontAndDeterminismTest(unittest.TestCase):
    def test_two_calls_identical(self) -> None:
        clip = _clip([_overlay(_props())])
        self.assertEqual(_build(clip), _build(clip))
        self.assertIsNotNone(_build(clip)[0])

    def test_missing_font_skips_with_one_warning(self) -> None:
        missing = ROOT / "assets" / "fonts" / "TidakAda.ttf"
        ass, warnings = _build(_clip([_overlay(_props())]), font_path=missing)
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1, msg=warnings)
        self.assertIn("font", warnings[0].lower())

    def test_wrong_family_is_skipped_without_exception(self) -> None:
        ass, warnings = _build(
            _clip([_overlay(_props())]), font_path=DMSERIF_FILE
        )
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1, msg=warnings)
        self.assertIn("Archivo Black", warnings[0])

    def test_chart_and_checklist_share_one_sans_style(self) -> None:
        overlays = [
            _overlay(_props()),
            {
                "type": "checklist", "start": 0.4, "end": 3.6,
                "props": {"title": "CEK", "items": [
                    {"text": "Satu", "done_at": 2.0},
                    {"text": "Dua", "done_at": None},
                ]},
            },
        ]
        ass, warnings = _build(_clip(overlays))
        self.assertEqual(warnings, [])
        assert ass is not None
        rows = [line for line in ass.splitlines()
                if line.startswith("Style: Sans,")]
        self.assertEqual(len(rows), 1)
        self.assertGreater(len(_role_lines(ass, "card")), 0)

    def test_zoom_only_document_is_byte_identical_to_5b1(self) -> None:
        clip = _clip(
            [{
                "type": "zoom_through_text", "start": 0.5, "end": 3.0,
                "props": {"text": "5 JAM"},
            }],
            segments=((0.0, 3.0),),
        )
        ass, warnings = _build(clip)
        self.assertEqual(warnings, [])
        assert ass is not None
        digest = hashlib.sha256(ass.encode("utf-8")).hexdigest()
        self.assertEqual(digest, ZOOM_GOLDEN_SHA256)
        self.assertNotIn("Style: Sans,", ass)

    def test_checklist_only_document_is_byte_identical_to_5b2(self) -> None:
        clip = _clip(
            [{
                "type": "checklist", "start": 0.4, "end": 5.0,
                "props": {"title": "CHECKLIST", "items": [
                    {"text": "Satu", "done_at": 1.0},
                    {"text": "Dua", "done_at": 2.0},
                    {"text": "Tiga", "done_at": None},
                ]},
            }],
            segments=((0.0, 6.0),),
        )
        ass, warnings = _build(clip)
        self.assertEqual(warnings, [])
        assert ass is not None
        digest = hashlib.sha256(ass.encode("utf-8")).hexdigest()
        self.assertEqual(digest, CHECKLIST_GOLDEN_SHA256)
        self.assertNotIn("Style: Serif,", ass)


if __name__ == "__main__":
    unittest.main()
