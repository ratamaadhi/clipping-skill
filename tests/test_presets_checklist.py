"""Tes murni preset `checklist` di `scripts.presets` — tanpa ffmpeg.

Kontrak yang dikunci di sini (docs/MOTION-TIER2-PLAN.md Langkah 5b, baris #07):

* props ketat: `title` 1..28 karakter tanpa newline, `items` 2..6 buah
  `{text, done_at}`; `done_at` null atau angka di `[start + ENTRY, end]`;
* teks judul/butir diukur dengan `fontmetrics` dan DITOLAK bila tidak muat;
* `rect` opsional; tinggi bawaan dihitung dari isi; `rect.h` terlalu pendek
  ditolak, bukan disusutkan diam-diam; seluruh kartu di dalam 1080x1920;
* dokumen ASS: kartu layer 0 < lingkaran < centang < teks, escape `{` `}`
  `\\`, satu event per keadaan penghitung `n of N`;
* semua waktu diturunkan dari frame `round(t * fps)` (PIPELINE.md §7), jadi
  penghitung berganti tepat pada frame `done_at` — dibuktikan di
  `tests/test_presets_checklist_render.py` pada piksel sungguhan;
* deterministik; font Archivo Black hilang/salah -> `(None, [satu peringatan])`.

Tes ini TIDAK merender. Pembuktian libass (kekakuan masuk, pop spring,
warna, frame penghitung) ada di `tests/test_presets_checklist_render.py`.
"""

from __future__ import annotations

import hashlib
import math
import re
import unittest
from pathlib import Path

from tests.helpers import ROOT

from scripts import presets
from scripts.lib import fontmetrics

ARCHIVO_FILE = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"
DMSERIF_FILE = ROOT / "assets" / "fonts" / "DMSerifDisplay-Italic.ttf"

TYPE = "checklist"
FPS = 30.0

# Dokumen `zoom_through_text` untuk klip yang sama HARUS byte-identik dengan
# keluaran Langkah 5b-1. Hash diambil dari implementasi 5b-1 sebelum preset
# `checklist` ditambahkan (laporan tugas 5b-2).
ZOOM_GOLDEN_SHA256 = "d016b1dbfc61dbc473913967d19e7a645b63d359fb8f83431eab7943aa77b9b0"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _clip(overlays: list | None = None, segments=None, clip_id: str = "clip_01") -> dict:
    segs = segments if segments is not None else ((0.0, 6.0),)
    return {
        "id": clip_id,
        "segments": [{"src_start": a, "src_end": b} for a, b in segs],
        "overlays": overlays if overlays is not None else [],
    }


def _items(count: int = 2, *, start: float = 0.4, end: float = 5.0) -> list[dict]:
    done = [1.0, 2.0, 0.8, 2.6, 1.6, 3.2]
    return [
        {"text": f"Butir {i + 1}", "done_at": done[i]}
        for i in range(count)
    ]


def _overlay(
    props: dict | None = None,
    *,
    start: object = 0.4,
    end: object = 5.0,
    rect: dict | None = None,
) -> dict:
    item: dict = {"type": TYPE, "start": start, "end": end}
    if props is not None:
        item["props"] = props
    if rect is not None:
        item["rect"] = rect
    return item


def _props(items: list | None = None, *, title: object = "CHECKLIST") -> dict:
    return {"title": title, "items": _items() if items is None else items}


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
    """Teks yang benar-benar digambar: buang blok override terakhir."""
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


def _shape_path(line: str) -> str:
    text = _text_field(line)
    match = re.search(r"\\p1}(.*?)\{\\p0}", text, re.S)
    if not match:
        raise AssertionError(f"event tidak punya path \\p1: {text!r}")
    return match.group(1)


def _time_chain(line: str, tag: str) -> list[tuple[int, int]]:
    """Semua pasangan (t0, t1) milidetik pada rantai `\\t` untuk tag tertentu."""
    pattern = re.compile(r"\\t\((\d+),(\d+)," + re.escape(tag))
    return [(int(a), int(b)) for a, b in pattern.findall(_text_field(line))]


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


def _scale_chain(line: str) -> list[tuple[int, int, int]]:
    pattern = re.compile(
        r"\\t\((\d+),(\d+),\\fscx(\d+)\\fscy(\d+)\)"
    )
    out = []
    for t0, t1, sx, sy in pattern.findall(_text_field(line)):
        if sx != sy:
            raise AssertionError(f"fscx/fscy tidak sama: {sx!r} vs {sy!r}")
        out.append((int(t0), int(t1), int(sx)))
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class RegistryTest(unittest.TestCase):
    def test_checklist_is_registered(self) -> None:
        self.assertIn(TYPE, presets.REGISTRY)
        self.assertIn(TYPE, presets.PRESET_TYPES)
        self.assertTrue(callable(presets.REGISTRY[TYPE]))

    def test_zoom_still_registered_and_order_is_stable(self) -> None:
        self.assertEqual(
            presets.PRESET_TYPES,
            ("zoom_through_text", "checklist", "chart_grow", "ui_panel", "phone_frame"),
        )
        self.assertEqual(set(presets.REGISTRY), set(presets.PRESET_TYPES))

    def test_unknown_types_are_ignored_without_warnings(self) -> None:
        clip = _clip([
            {"type": "future_effect", "start": 0.0, "end": 1.0, "props": {"x": 1}},
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

    def test_title_missing(self) -> None:
        self._assert_error({"items": _items()}, "title")

    def test_title_empty(self) -> None:
        self._assert_error(_props(title=""), "title")

    def test_title_too_long(self) -> None:
        self._assert_error(_props(title="x" * 29), "title")

    def test_title_newline(self) -> None:
        for text in ("a\nb", "a\rb"):
            with self.subTest(text=text):
                self._assert_error(_props(title=text), "title")

    def test_title_not_string(self) -> None:
        self._assert_error(_props(title=7), "title")

    def test_items_missing(self) -> None:
        self._assert_error({"title": "CHECKLIST"}, "items")

    def test_items_not_list(self) -> None:
        self._assert_error(_props(items="dua"), "items")

    def test_items_too_few(self) -> None:
        self._assert_error(_props(items=_items()[:1]), "items")

    def test_items_too_many(self) -> None:
        self._assert_error(_props(items=_items(6) + [{"text": "x", "done_at": None}]), "items")

    def test_item_not_object(self) -> None:
        self._assert_error(_props(items=["bukan objek", {"text": "x", "done_at": None}]), "items")

    def test_item_missing_text(self) -> None:
        self._assert_error(
            _props(items=[{"done_at": None}, {"text": "x", "done_at": None}]),
            "text",
        )

    def test_item_missing_done_at(self) -> None:
        self._assert_error(
            _props(items=[{"text": "x"}, {"text": "y", "done_at": None}]),
            "done_at",
        )

    def test_item_unknown_key(self) -> None:
        message = self._assert_error(
            _props(items=[{"text": "x", "done_at": None, "done": 1},
                          {"text": "y", "done_at": None}]),
            "done",
        )
        self.assertIn("text", message)
        self.assertIn("done_at", message)

    def test_item_text_rules(self) -> None:
        cases = (("", "text"), ("x" * 29, "text"), ("a\nb", "text"), (7, "text"))
        for text, needle in cases:
            with self.subTest(text=text):
                self._assert_error(
                    _props(items=[{"text": text, "done_at": None},
                                  {"text": "y", "done_at": None}]),
                    needle,
                )

    def test_done_at_type_and_finiteness(self) -> None:
        for value in ("1.0", True, float("nan"), float("inf")):
            with self.subTest(value=value):
                self._assert_error(
                    _props(items=[{"text": "x", "done_at": value},
                                  {"text": "y", "done_at": None}]),
                    "done_at",
                )

    def test_done_at_before_entry_window(self) -> None:
        # start 0.4 + ENTRY 0.3 = 0.7; 0.69 di luar.
        message = self._assert_error(
            _props(items=[{"text": "x", "done_at": 0.69},
                          {"text": "y", "done_at": None}]),
            "done_at",
        )
        self.assertIn("0.7", message)

    def test_done_at_after_end(self) -> None:
        self._assert_error(
            _props(items=[{"text": "x", "done_at": 5.01},
                          {"text": "y", "done_at": None}]),
            "done_at",
        )

    def test_done_at_boundaries_accepted(self) -> None:
        for value in (0.7, 5.0, None):
            with self.subTest(value=value):
                ass, warnings = _build(_clip([
                    _overlay(_props(items=[
                        {"text": "x", "done_at": value},
                        {"text": "y", "done_at": None},
                    ]))
                ]))
                self.assertIsNotNone(ass)
                self.assertEqual(warnings, [])

    def test_unknown_props_key_lists_valid_keys(self) -> None:
        message = self._assert_error(_props(title="A") | {"done": []}, "done")
        self.assertIn("title", message)
        self.assertIn("items", message)

    def test_second_overlay_error_names_its_index(self) -> None:
        overlays = [
            _overlay(_props(), start=0.4, end=5.0),
            _overlay({"title": "", "items": _items()}, start=0.4, end=5.0),
        ]
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip(overlays))
        self.assertIn("overlay[1]", str(ctx.exception))


# ---------------------------------------------------------------------------
# Teks harus muat (diukur, bukan ditebak)
# ---------------------------------------------------------------------------

class TextFitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.font = fontmetrics.Font.load(ARCHIVO_FILE)

    def test_title_too_wide_names_measured_and_available(self) -> None:
        title = "W" * 28
        measured = self.font.width(title, presets.CHECK_TITLE_EM)
        counter = self.font.width("2 of 2", presets.CHECK_COUNTER_EM)
        available = (
            presets.CARD_W
            - 2 * presets.CARD_PAD_X
            - counter
            - presets.CHECK_TITLE_GAP
        )
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(title=title))]))
        message = str(ctx.exception)
        self.assertIn("tidak muat", message)
        self.assertIn("terukur", message)
        self.assertIn("tersedia", message)
        self.assertIn(f"{measured:g}", message)
        self.assertIn(f"{available:g}", message)

    def test_item_too_wide_names_measured_and_available(self) -> None:
        item = {"text": "W" * 28, "done_at": None}
        measured = self.font.width(item["text"], presets.CHECK_ITEM_EM)
        available = (
            presets.CARD_W
            - 2 * presets.CARD_PAD_X
            - 2 * presets.RING_RADIUS
            - presets.CHECK_ROW_GAP
        )
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(items=[item, {"text": "y", "done_at": None}]))]))
        message = str(ctx.exception)
        self.assertIn("terukur", message)
        self.assertIn("tersedia", message)
        self.assertIn(f"{measured:g}", message)
        self.assertIn(f"{available:g}", message)

    def test_narrow_28_characters_fit(self) -> None:
        ass, warnings = _build(_clip([
            _overlay(_props(items=[
                {"text": "i" * 28, "done_at": None},
                {"text": "i" * 28, "done_at": None},
            ]))
        ]))
        self.assertIsNotNone(ass)
        self.assertEqual(warnings, [])

    def test_title_room_shrinks_with_the_counter(self) -> None:
        # Judul yang muat tanpa penghitung tetapi tidak muat bersamanya harus
        # ditolak: ruang header dipakai judul + penghitung, bukan judul saja.
        title = "W" * 19
        measured = self.font.width(title, presets.CHECK_TITLE_EM)
        counter = self.font.width("2 of 2", presets.CHECK_COUNTER_EM)
        full_width = presets.CARD_W - 2 * presets.CARD_PAD_X
        available = full_width - counter - presets.CHECK_TITLE_GAP
        self.assertLess(measured, full_width, msg="fixture harus muat tanpa penghitung")
        self.assertGreater(measured, available, msg="fixture harus tidak muat dengan penghitung")
        with self.assertRaises(presets.PresetError):
            _build(_clip([_overlay(_props(title=title))]))


# ---------------------------------------------------------------------------
# rect + tinggi kartu
# ---------------------------------------------------------------------------

class RectTest(unittest.TestCase):
    def _card_line(self, clip: dict) -> str:
        ass, warnings = _build(clip)
        self.assertEqual(warnings, [])
        assert ass is not None
        cards = _role_lines(ass, "card")
        self.assertEqual(len(cards), 1)
        return cards[0]

    def test_default_rect_and_height_from_content(self) -> None:
        for count in range(2, 7):
            with self.subTest(count=count):
                clip = _clip([_overlay(_props(items=_items(count)))])
                bounds = _path_bounds(_shape_path(self._card_line(clip)))
                expected_h = (
                    2 * presets.CARD_PAD_Y
                    + presets.CARD_HEADER_H
                    + count * presets.CARD_ROW_H
                )
                expected = (
                    presets.CARD_X, presets.CARD_Y,
                    presets.CARD_X + presets.CARD_W,
                    presets.CARD_Y + expected_h,
                )
                for got, want in zip(bounds, expected):
                    self.assertAlmostEqual(got, want, delta=0.02)

    def test_custom_rect_is_respected(self) -> None:
        rect = {"x": 100, "y": 300, "w": 800, "h": 300}
        clip = _clip([_overlay(_props(), rect=rect)])
        bounds = _path_bounds(_shape_path(self._card_line(clip)))
        self.assertEqual(
            tuple(round(v, 2) for v in bounds),
            (100.0, 300.0, 900.0, 600.0),
        )

    def test_rect_too_short_raises_instead_of_shrinking(self) -> None:
        required = (
            2 * presets.CARD_PAD_Y
            + presets.CARD_HEADER_H
            + 6 * presets.CARD_ROW_H
        )
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([
                _overlay(_props(items=_items(6)),
                         rect={"x": 60, "y": 200, "w": 960, "h": required - 1})
            ]))
        message = str(ctx.exception)
        self.assertIn("rect", message)
        self.assertIn(f"{required:g}", message)

    def test_rect_exact_required_height_accepted(self) -> None:
        required = (
            2 * presets.CARD_PAD_Y
            + presets.CARD_HEADER_H
            + 2 * presets.CARD_ROW_H
        )
        ass, warnings = _build(_clip([
            _overlay(_props(), rect={"x": 60, "y": 200, "w": 960, "h": required})
        ]))
        self.assertIsNotNone(ass)
        self.assertEqual(warnings, [])

    def test_rect_must_be_inside_canvas(self) -> None:
        cases = (
            {"x": -1, "y": 200, "w": 960, "h": 264},
            {"x": 0, "y": -1, "w": 960, "h": 264},
            {"x": 121, "y": 200, "w": 960, "h": 264},
            {"x": 60, "y": 1700, "w": 960, "h": 264},
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
            {"x": 60, "y": 260, "w": 0, "h": 264},
            {"x": 60, "y": 260, "w": 960, "h": -1},
            {"x": 60, "y": 260, "w": 960, "h": 264, "z": 1},
            {"x": "60", "y": 260, "w": 960, "h": 264},
        )
        for rect in cases:
            with self.subTest(rect=rect):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(), rect=rect)]))
                self.assertIn("rect", str(ctx.exception))


# ---------------------------------------------------------------------------
# Struktur dokumen + Style
# ---------------------------------------------------------------------------

class DocumentStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            {"text": "Beli kopi", "done_at": 2.0},
            {"text": "Rapat jam 9", "done_at": 1.0},
            {"text": "Tulis recap", "done_at": None},
        ]
        self.ass, self.warnings = _build(_clip([_overlay(_props(items=self.items))]))
        assert self.ass is not None
        self.lines = _dialogues(self.ass)

    def test_every_dialogue_has_ten_fields(self) -> None:
        self.assertTrue(self.lines)
        for line in self.lines:
            with self.subTest(line=line[:60]):
                self.assertEqual(len(_fields(line)), 10)

    def test_event_budget_for_six_items(self) -> None:
        items = [
            {"text": f"Butir {i + 1}", "done_at": 0.8 + 0.4 * i}
            for i in range(6)
        ]
        ass, _ = _build(_clip([_overlay(_props(items=items), end=5.0)]))
        assert ass is not None
        count = len(_dialogues(ass))
        self.assertLessEqual(count, presets.CHECK_MAX_DIALOGUES, msg=count)
        self.assertEqual(count, 33)

    def test_layer_order_card_ring_check_text(self) -> None:
        def layers(role: str) -> set[int]:
            return {int(_fields(line)[0]) for line in _role_lines(self.ass, role)}

        card = layers("card")
        ring = layers("ring")
        green = layers("green")
        check = layers("check")
        text = layers("title") | layers("counter") | layers("item")
        self.assertEqual(card, {presets.CARD_LAYER})
        self.assertEqual(ring, {presets.RING_LAYER})
        self.assertEqual(green, {presets.RING_LAYER})
        self.assertEqual(check, {presets.CHECK_LAYER})
        self.assertEqual(text, {presets.TEXT_LAYER})
        self.assertLess(max(card), min(ring))
        self.assertLess(max(ring), min(check))
        self.assertLess(max(check), min(text))

    def test_card_colours_and_radius_constants(self) -> None:
        self.assertEqual(presets.CARD_RADIUS, 40.0)
        self.assertEqual(presets.CARD_COLOUR, "#14161B")
        self.assertAlmostEqual(presets.CARD_OPACITY, 0.86, places=2)
        self.assertEqual(presets.RING_COLOUR, "#5B616B")
        self.assertEqual(presets.GREEN_COLOUR, "#22C55E")

        card = _role_lines(self.ass, "card")[0]
        from scripts import shapes
        self.assertIn(f"\\1c{shapes.colour(presets.CARD_COLOUR)}", _text_field(card))
        self.assertIn(
            f"\\1a{shapes.alpha(presets.CARD_OPACITY)}", _text_field(card)
        )
        ring = _role_lines(self.ass, "ring")[0]
        self.assertIn(f"\\1c{shapes.colour(presets.RING_COLOUR)}", _text_field(ring))
        green = _role_lines(self.ass, "green")[0]
        self.assertIn(f"\\1c{shapes.colour(presets.GREEN_COLOUR)}", _text_field(green))
        check = _role_lines(self.ass, "check")[0]
        self.assertIn(f"\\1c{shapes.colour(presets.CHECK_COLOUR)}", _text_field(check))

    def test_ring_is_a_ring_not_a_disc(self) -> None:
        # Dua kontur: lingkaran luar + lingkaran dalam berlawanan arah
        # (aturan nonzero; dibuktikan oracle shapes). Path tanpa kontur kedua
        # akan menjadi cakram penuh dan pusat cincin bukan latar kartu.
        path = _shape_path(_role_lines(self.ass, "ring")[0])
        self.assertGreaterEqual(path.count("m "), 2)
        x0, y0, x1, y1 = _path_bounds(path)
        self.assertAlmostEqual(x1 - x0, 2 * presets.RING_RADIUS, delta=0.1)
        self.assertAlmostEqual(y1 - y0, 2 * presets.RING_RADIUS, delta=0.1)

    def test_escape_braces_and_backslash(self) -> None:
        ass, _ = _build(_clip([
            _overlay({"title": "A{b}\\c", "items": [
                {"text": "x{y}\\z", "done_at": None},
                {"text": "aman", "done_at": None},
            ]})
        ]))
        assert ass is not None
        title_text = _shown_text(_role_lines(ass, "title")[0])
        item_text = _shown_text(_role_lines(ass, "item")[0])
        self.assertEqual(title_text, "A(b)/c")
        self.assertEqual(item_text, "x(y)/z")
        for text in (title_text, item_text):
            self.assertNotIn("{", text)
            self.assertNotIn("}", text)
            self.assertNotIn("\\", text)

    def test_sans_style_uses_bundled_archivo(self) -> None:
        font = fontmetrics.Font.load(ARCHIVO_FILE)
        rows = [
            ln for ln in self.ass.splitlines()
            if ln.startswith(f"Style: {presets.CHECK_STYLE},")
        ]
        self.assertEqual(len(rows), 1)
        fields = rows[0][len("Style: "):].split(",")
        self.assertEqual(fields[0], presets.CHECK_STYLE)
        self.assertEqual(fields[1], font.family)
        self.assertEqual(fields[1], "Archivo Black")
        self.assertAlmostEqual(
            float(fields[2]),
            round(presets.CHECK_TITLE_EM * font.cell_height_ratio, 2),
            places=2,
        )
        self.assertEqual(fields[7], "0")   # Bold: berkas sudah Black
        self.assertEqual(fields[8], "0")   # Italic
        self.assertEqual(fields[16], "0")  # Outline
        self.assertEqual(fields[17], "0")  # Shadow
        self.assertNotIn("Style: Serif,", self.ass)

    def test_font_sizes_follow_em_times_cell_ratio(self) -> None:
        font = fontmetrics.Font.load(ARCHIVO_FILE)
        expected = {
            "title": round(presets.CHECK_TITLE_EM * font.cell_height_ratio, 2),
            "item": round(presets.CHECK_ITEM_EM * font.cell_height_ratio, 2),
            "counter": round(presets.CHECK_COUNTER_EM * font.cell_height_ratio, 2),
        }
        for role, size in expected.items():
            with self.subTest(role=role):
                line = _role_lines(self.ass, role)[0]
                self.assertIn(f"\\fs{size:g}", _text_field(line))

    def test_entry_move_is_rigid_in_the_text_layer_too(self) -> None:
        # Semua elemen yang mulai di awal overlay memakai \move dengan durasi
        # dan delta yang SAMA. Teks: delta 60 px ke bawah. Bentuk: \an7 path
        # absolut, delta juga 60 px.
        entry_roles = ("card", "ring", "title", "counter", "item")
        deltas = set()
        windows = set()
        for role in entry_roles:
            for line in _role_lines(self.ass, role):
                start = _start_seconds(line)
                if abs(start - _start_seconds(self.lines[0])) > 1e-9:
                    continue  # state penghitung sesudah masuk
                move = _move(line)
                self.assertIsNotNone(move, msg=f"{role} tidak punya \\move")
                assert move is not None
                x0, y0, x1, y1, t0, t1 = move
                if role == "card":
                    self.assertEqual((x0, y0), (0.0, -presets.CHECK_ENTRY_OFFSET))
                    self.assertEqual((x1, y1), (0.0, 0.0))
                else:
                    self.assertAlmostEqual(x1 - x0, 0.0, delta=0.01)
                    self.assertAlmostEqual(y1 - y0, presets.CHECK_ENTRY_OFFSET, delta=0.01)
                deltas.add(round(y1 - y0, 2))
                windows.add((t0, t1))
        self.assertEqual(deltas, {presets.CHECK_ENTRY_OFFSET})
        self.assertEqual(windows, {(0, round(presets.CHECK_ENTRY * 1000))})

    def test_pop_chain_overshoots_and_settles_at_100(self) -> None:
        green = _role_lines(self.ass, "green")[0]
        self.assertIn("\\fscx0\\fscy0", _text_field(green))
        chain = _scale_chain(green)
        self.assertTrue(chain, msg="tidak ada rantai \\t skala")
        self.assertLessEqual(len(chain), presets.CHECK_POP_MAX_SEGMENTS)
        self.assertEqual(chain[0][0], 0)
        values = [value for _, _, value in chain]
        self.assertGreater(max(values), 100, msg=f"tanpa overshoot: {values}")
        self.assertEqual(values[-1], 100)
        times = [t0 for t0, _, _ in chain] + [chain[-1][1]]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))

        check = _role_lines(self.ass, "check")[0]
        self.assertEqual(_scale_chain(check), chain)


# ---------------------------------------------------------------------------
# Waktu: penghitung tepat pada frame done_at
# ---------------------------------------------------------------------------

class CounterTimingTest(unittest.TestCase):
    def setUp(self) -> None:
        # Urutan butir SENGAJA tidak sama dengan urutan waktu: butir 0 selesai
        # paling akhir. Penghitung harus naik menurut waktu, bukan indeks.
        self.items = [
            {"text": "Satu", "done_at": 2.0},
            {"text": "Dua", "done_at": 1.23},
            {"text": "Tiga", "done_at": None},
        ]
        self.ass, self.warnings = _build(
            _clip([_overlay(_props(items=self.items), start=0.4, end=3.6)])
        )
        assert self.ass is not None
        self.counters = sorted(
            _role_lines(self.ass, "counter"), key=_start_seconds
        )

    def test_counter_has_one_event_per_state(self) -> None:
        texts = [_shown_text(line) for line in self.counters]
        self.assertEqual(texts, ["0 of 3", "1 of 3", "2 of 3"])

    def test_counter_changes_exactly_at_done_frame(self) -> None:
        # done_at 1.23 -> frame round(1.23*30) = 37, bukan floor = 36.
        expected = [(round(0.4 * FPS), 0), (37, 1), (60, 2)]
        self.assertEqual(len(self.counters), len(expected))
        for line, (frame, _count) in zip(self.counters, expected):
            start = _start_seconds(line)
            lower = (frame - 1) / FPS
            upper = frame / FPS
            self.assertLess(lower, start, msg=f"mulai {start} <= frame sebelumnya {lower}")
            self.assertLessEqual(start, upper + 1e-9, msg=f"mulai {start} > frame {frame}")

    def test_counter_states_touch_without_overlap(self) -> None:
        for previous, nxt in zip(self.counters, self.counters[1:]):
            self.assertEqual(_fields(previous)[2], _fields(nxt)[1])

    def test_counter_last_state_ends_at_overlay_end(self) -> None:
        self.assertEqual(_end_seconds(self.counters[-1]), 3.6)

    def test_duplicate_done_at_jumps_count_once(self) -> None:
        items = [
            {"text": "A", "done_at": 1.0},
            {"text": "B", "done_at": 1.0},
            {"text": "C", "done_at": None},
        ]
        ass, _ = _build(_clip([_overlay(_props(items=items), start=0.4, end=3.6)]))
        assert ass is not None
        counters = sorted(_role_lines(ass, "counter"), key=_start_seconds)
        self.assertEqual([_shown_text(ln) for ln in counters], ["0 of 3", "2 of 3"])

    def test_green_and_check_start_at_done_frame(self) -> None:
        for item, frame in ((self.items[1], 37), (self.items[0], 60)):
            with self.subTest(item=item["text"], frame=frame):
                # Cari event green/check pada baris butir yang sama berdasarkan
                # waktu mulai: keduanya hanya ada satu per butir selesai.
                for role in ("green", "check"):
                    match = [
                        ln for ln in _role_lines(self.ass, role)
                        if (frame - 1) / FPS < _start_seconds(ln) <= frame / FPS + 1e-9
                    ]
                    self.assertEqual(len(match), 1, msg=f"{role} frame {frame}")

    def test_done_at_null_has_no_green_or_check(self) -> None:
        self.assertEqual(len(_role_lines(self.ass, "green")), 2)
        self.assertEqual(len(_role_lines(self.ass, "check")), 2)
        self.assertEqual(len(_role_lines(self.ass, "item")), 3)
        self.assertEqual(len(_role_lines(self.ass, "ring")), 3)

    def test_exit_fade_is_200ms_on_every_event(self) -> None:
        for line in _dialogues(self.ass):
            chain = _time_chain(line, "\\alpha&HFF&")
            self.assertTrue(chain, msg=f"{_role(line)} tanpa fade keluar")
            t0, t1 = chain[-1]
            self.assertAlmostEqual(
                t1 - t0, round(presets.CHECK_EXIT * 1000), delta=1,
                msg=f"{_role(line)}: fade {t0}..{t1} ms",
            )


# ---------------------------------------------------------------------------
# C15: frame -> sentidetik PERTAMA sesudah frame sebelumnya (bukan round())
# ---------------------------------------------------------------------------

class CentisecondRoundingTest(unittest.TestCase):
    """Frame di mana `round(frame / 30, 2)` membulat KE ATAS.

    Mutan C15 mengganti `_frame_start_time` dengan `round(frame / fps, 2)`;
    tes lama hanya memakai frame 37 dan 60, tempat kedua rumus kebetulan
    jatuh di frame yang sama. Frame 38/41/68 @30 fps membulat ke atas
    (1,27 / 1,37 / 2,27 > timestamp frame), jadi mutan menunda event satu
    frame. Tes ini mengunci string waktu event-nya, bukan hanya efeknya.
    """

    FRAMES = (38, 41, 68)
    EXPECTED = ("0:00:00.37", "0:00:01.24", "0:00:01.34", "0:00:02.24")

    def setUp(self) -> None:
        items = [
            {"text": f"Butir {i + 1}", "done_at": frame / FPS}
            for i, frame in enumerate(self.FRAMES)
        ]
        self.ass, self.warnings = _build(
            _clip([_overlay(_props(items=items), start=0.4, end=3.6)])
        )
        assert self.ass is not None
        self.counters = sorted(
            _role_lines(self.ass, "counter"), key=_start_seconds
        )

    def test_counter_start_strings_are_first_centisecond_after_previous_frame(self):
        self.assertEqual(self.warnings, [])
        self.assertEqual(
            [_shown_text(line) for line in self.counters],
            ["0 of 3", "1 of 3", "2 of 3", "3 of 3"],
        )
        self.assertEqual(
            [_fields(line)[1] for line in self.counters], list(self.EXPECTED)
        )
        for line, frame in zip(self.counters[1:], self.FRAMES):
            start = _start_seconds(line)
            self.assertLess((frame - 1) / FPS, start)
            self.assertLessEqual(start, frame / FPS + 1e-9)
            # Frame ini memang pembeda: round() membulat ke atas, jadi nilai
            # naif jatuh SESUDAH timestamp frame dan event tampil satu frame
            # terlambat. String event tidak boleh sama dengan nilai naif itu.
            naive = round(frame / FPS, 2)
            self.assertGreater(naive, frame / FPS)
            self.assertNotEqual(_fields(line)[1], presets._ass_time(naive))

    def test_green_and_check_start_in_the_same_frame_window(self):
        for frame in self.FRAMES:
            with self.subTest(frame=frame):
                for role in ("green", "check"):
                    match = [
                        line for line in _role_lines(self.ass, role)
                        if (frame - 1) / FPS < _start_seconds(line)
                        <= frame / FPS + 1e-9
                    ]
                    self.assertEqual(len(match), 1, msg=f"{role} frame {frame}")


# ---------------------------------------------------------------------------
# Font hilang, determinisme, dokumen lama
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
        self.assertIn(TYPE, warnings[0])

    def test_wrong_family_is_skipped_without_exception(self) -> None:
        ass, warnings = _build(
            _clip([_overlay(_props())]), font_path=DMSERIF_FILE
        )
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1, msg=warnings)
        self.assertIn("Archivo Black", warnings[0])

    def test_mixed_presets_get_both_styles(self) -> None:
        overlays = [
            {
                "type": "zoom_through_text", "start": 0.0, "end": 1.0,
                "props": {"text": "5 JAM"},
            },
            _overlay(_props(items=[
                {"text": "Beli kopi", "done_at": 1.5},
                {"text": "Rapat jam 9", "done_at": 2.0},
            ]), start=1.0, end=3.0),
        ]
        ass, warnings = _build(_clip(overlays, segments=((0.0, 3.0),)))
        self.assertEqual(warnings, [])
        assert ass is not None
        self.assertIn("Style: Serif,DM Serif Display,", ass)
        self.assertIn("Style: Sans,Archivo Black,", ass)
        self.assertIn("5 JAM", ass)  # teks zoom tetap ada
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


if __name__ == "__main__":
    unittest.main()
