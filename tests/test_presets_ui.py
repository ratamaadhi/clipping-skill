"""Tes murni preset `ui_panel` di `scripts.presets` — tanpa ffmpeg.

Kontrak yang dikunci (docs/MOTION-TIER2-PLAN.md Langkah 5b, baris #03 "ui world"):

* props ketat: `title` 1..28 karakter tanpa newline, `tag` 1..16 karakter
  tanpa newline, `thumbs` 1..6 bulat (bawaan 3), `input` opsional <= 28
  karakter (bawaan ""); kunci tak dikenal ditolak dengan daftar kunci sah;
* teks diukur dengan `fontmetrics` dan DITOLAK bila tidak muat (lebar terukur
  vs tersedia di pesan error);
* `rect` opsional (bawaan x=60, y=260, w=960, h dihitung dari isi); `rect.h`
  terlalu pendek ditolak dengan PresetError jelas, bukan disusutkan diam-diam;
  tinggi maksimum <= 700 px;
* kartu krem #F6EEDC opasitas 0.96 radius 48, judul Archivo Black gelap #1B1B1F,
  thumbnail pastel 270x170 (celah tetap, pecah 2 baris bila thumbs > 3),
  tag pil kuning #FFD60A teks gelap, bilah input putih teks abu-gelap;
* masuk 0.30 s geser turun 60 px kaku (badan, judul, bilah input); setelah
  kartu penuh (start + ENTRY), thumbnail muncul satu per satu dengan pop spring
  jeda 80 ms (konversi frame SEKALI), lalu tag pil pop sesudah thumbnail
  terakhir; keluar fade 0.20 s seluruh elemen;
* maksimum 40 Dialogue untuk 6 thumbnail; deterministik; font hilang -> satu
  peringatan, bukan exception.

Pembuktian piksel (bbox kartu, warna interior, kekakuan masuk, frame muncul
thumbnail/tag, overshoot, durasi audio) ada di `tests/test_presets_ui_render.py`.
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

TYPE = "ui_panel"
FPS = 30.0
START = 0.4
END = 3.6
TITLE = "COMPONENTS"
TAG = "NEW"
THUMBS = 3
INPUT = "Search items..."

# Golden hashes dokumen lama untuk memastikan implementasi baru tidak merusak
# preset yang sudah ada.
ZOOM_GOLDEN_SHA256 = (
    "d016b1dbfc61dbc473913967d19e7a645b63d359fb8f83431eab7943aa77b9b0"
)
CHECKLIST_GOLDEN_SHA256 = (
    "4aeca9985f515776a4bc7d6866298348a8f7f9f1e168b8b9001fb0c624240982"
)
CHART_GOLDEN_SHA256 = (
    "f024e0dfe112313517439f2821b2c9823d602ab9ebea81e2bea3cc30aaedbf3b"
)


# ---------------------------------------------------------------------------
# Fixture helpers
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
        "title": TITLE,
        "tag": TAG,
        "thumbs": THUMBS,
        "input": INPUT,
    }
    props.update(overrides)
    return props


def _overlay(props: dict | None = None, **overrides: object) -> dict:
    overlay: dict = {
        "type": TYPE,
        "start": START,
        "end": END,
        "props": _props() if props is None else props,
    }
    overlay.update(overrides)
    return overlay


def _build(clip: dict, **kwargs: object) -> tuple[str | None, list[str]]:
    return presets.build_fx_ass(clip, fps=FPS, **kwargs)


def _dialogue_lines(ass: str | None) -> list[str]:
    if ass is None:
        return []
    return [line for line in ass.splitlines() if line.startswith("Dialogue: ")]


def _fields(dialogue: str) -> list[str]:
    assert dialogue.startswith("Dialogue: ")
    return dialogue[len("Dialogue: "):].split(",", 9)


def _role_lines(ass: str | None, role: str) -> list[str]:
    return [line for line in _dialogue_lines(ass) if _fields(line)[4] == role]


def _text_field(dialogue: str) -> str:
    return _fields(dialogue)[9]


def _shape_path(dialogue: str) -> str:
    match = re.search(r"\\p1}(.*?)\{\\p0\}", _text_field(dialogue))
    assert match is not None, f"tidak ada path pada: {dialogue}"
    return match.group(1).strip()


def _path_bounds(path: str) -> tuple[float, float, float, float]:
    tokens = path.split()
    xs: list[float] = []
    ys: list[float] = []
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        if cmd in ("m", "l"):
            xs.append(float(tokens[i + 1]))
            ys.append(float(tokens[i + 2]))
            i += 3
        elif cmd == "b":
            for k in range(3):
                xs.append(float(tokens[i + 1 + 2 * k]))
                ys.append(float(tokens[i + 2 + 2 * k]))
            i += 7
        else:
            i += 1
    return min(xs), min(ys), max(xs), max(ys)


def _move(dialogue: str) -> tuple[float, float, float, float, int, int] | None:
    match = re.search(
        r"\\move\(([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^)]+)\)",
        _text_field(dialogue),
    )
    if not match:
        return None
    x0, y0, x1, y1, t0, t1 = match.groups()
    return float(x0), float(y0), float(x1), float(y1), int(t0), int(t1)


def _pos(dialogue: str) -> tuple[float, float] | None:
    match = re.search(r"\\pos\(([^,]+),([^)]+)\)", _text_field(dialogue))
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def _shown_text(dialogue: str) -> str:
    cleaned = re.sub(r"\{.*?\}", "", _text_field(dialogue))
    return cleaned.strip()


def _start_seconds(dialogue: str) -> float:
    match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", _fields(dialogue)[1])
    assert match is not None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def _end_seconds(dialogue: str) -> float:
    match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", _fields(dialogue)[2])
    assert match is not None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class RegistryTest(unittest.TestCase):
    def test_ui_panel_is_registered(self) -> None:
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
# Validasi Props
# ---------------------------------------------------------------------------

class PropsValidationTest(unittest.TestCase):
    def test_valid_props_pass(self) -> None:
        ass, warnings = _build(_clip([_overlay()]))
        self.assertIsNotNone(ass)
        self.assertEqual(warnings, [])

    def test_props_not_dict_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(props="invalid")]))  # type: ignore[arg-type]
        self.assertIn("overlay[0]", str(ctx.exception))
        self.assertIn(TYPE, str(ctx.exception))
        self.assertIn("props harus objek", str(ctx.exception))

    def test_unknown_props_key_rejected(self) -> None:
        props = _props(extra_key="forbidden")
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(props)]))
        self.assertIn("overlay[0]", str(ctx.exception))
        self.assertIn(TYPE, str(ctx.exception))
        self.assertIn("extra_key", str(ctx.exception))
        for key in ("title", "tag", "thumbs", "input"):
            self.assertIn(key, str(ctx.exception))

    def test_title_missing_rejected(self) -> None:
        props = _props()
        props.pop("title")
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(props)]))
        self.assertIn("props['title'] wajib ada", str(ctx.exception))

    def test_title_not_str_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(title=123))]))
        self.assertIn("props['title'] harus string", str(ctx.exception))

    def test_title_empty_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(title=""))]))
        self.assertIn("props['title'] harus 1..28 karakter", str(ctx.exception))

    def test_title_too_long_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(title="A" * 29))]))
        self.assertIn("props['title'] harus 1..28 karakter", str(ctx.exception))

    def test_title_newline_rejected(self) -> None:
        for nl in ("Line\nTwo", "Line\rTwo"):
            with self.subTest(nl=nl):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(title=nl))]))
                self.assertIn("tidak boleh memuat newline", str(ctx.exception))

    def test_tag_missing_rejected(self) -> None:
        props = _props()
        props.pop("tag")
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(props)]))
        self.assertIn("props['tag'] wajib ada", str(ctx.exception))

    def test_tag_not_str_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(tag=456))]))
        self.assertIn("props['tag'] harus string", str(ctx.exception))

    def test_tag_empty_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(tag=""))]))
        self.assertIn("props['tag'] harus 1..16 karakter", str(ctx.exception))

    def test_tag_too_long_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(tag="A" * 17))]))
        self.assertIn("props['tag'] harus 1..16 karakter", str(ctx.exception))

    def test_tag_newline_rejected(self) -> None:
        for nl in ("Tag\nOne", "Tag\rOne"):
            with self.subTest(nl=nl):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(tag=nl))]))
                self.assertIn("tidak boleh memuat newline", str(ctx.exception))

    def test_thumbs_default_is_three(self) -> None:
        props = _props()
        props.pop("thumbs")
        ass, _ = _build(_clip([_overlay(props)]))
        self.assertIsNotNone(ass)
        thumbs = _role_lines(ass, "thumb")
        self.assertEqual(len(thumbs), 3)

    def test_thumbs_zero_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(thumbs=0))]))
        self.assertIn("props['thumbs'] harus bilangan bulat 1..6", str(ctx.exception))

    def test_thumbs_seven_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(thumbs=7))]))
        self.assertIn("props['thumbs'] harus bilangan bulat 1..6", str(ctx.exception))

    def test_thumbs_non_integer_rejected(self) -> None:
        for bad in (2.5, "3", [3]):
            with self.subTest(bad=bad):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(thumbs=bad))]))
                self.assertIn("props['thumbs'] harus bilangan bulat 1..6", str(ctx.exception))

    def test_thumbs_bool_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(thumbs=True))]))
        self.assertIn("props['thumbs'] harus bilangan bulat 1..6", str(ctx.exception))

    def test_thumbs_1_to_6_valid(self) -> None:
        for k in range(1, 7):
            with self.subTest(thumbs=k):
                ass, _ = _build(_clip([_overlay(_props(thumbs=k))]))
                self.assertIsNotNone(ass)
                thumbs = _role_lines(ass, "thumb")
                self.assertEqual(len(thumbs), k)

    def test_input_default_is_empty_bar_without_text_dialogue(self) -> None:
        props = _props()
        props.pop("input")
        ass, _ = _build(_clip([_overlay(props)]))
        self.assertIsNotNone(ass)
        input_bars = _role_lines(ass, "inputbar")
        self.assertEqual(len(input_bars), 1)
        input_texts = _role_lines(ass, "inputtext")
        self.assertEqual(len(input_texts), 0)

    def test_input_empty_string_has_no_text_dialogue(self) -> None:
        ass, _ = _build(_clip([_overlay(_props(input=""))]))
        self.assertIsNotNone(ass)
        input_bars = _role_lines(ass, "inputbar")
        self.assertEqual(len(input_bars), 1)
        input_texts = _role_lines(ass, "inputtext")
        self.assertEqual(len(input_texts), 0)

    def test_input_with_text_creates_both_bar_and_text_dialogues(self) -> None:
        ass, _ = _build(_clip([_overlay(_props(input="Click to type"))]))
        self.assertIsNotNone(ass)
        input_bars = _role_lines(ass, "inputbar")
        self.assertEqual(len(input_bars), 1)
        input_texts = _role_lines(ass, "inputtext")
        self.assertEqual(len(input_texts), 1)
        self.assertEqual(_shown_text(input_texts[0]), "Click to type")

    def test_input_not_str_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(input=123))]))
        self.assertIn("props['input'] harus string", str(ctx.exception))

    def test_input_too_long_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(input="A" * 29))]))
        self.assertIn("props['input'] harus <= 28 karakter", str(ctx.exception))

    def test_input_newline_rejected(self) -> None:
        for nl in ("Text\nLine", "Text\rLine"):
            with self.subTest(nl=nl):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(input=nl))]))
                self.assertIn("tidak boleh memuat newline", str(ctx.exception))

    def test_end_le_start_rejected(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(start=2.0, end=1.5)]))
        self.assertIn("end harus > start", str(ctx.exception))

    def test_overlay_outside_clip_skipped_with_warning(self) -> None:
        ass, warnings = _build(_clip([_overlay(start=5.0, end=6.0)]))
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1)
        self.assertIn("dilewati", warnings[0])


# ---------------------------------------------------------------------------
# Text Fit & Rect Validation
# ---------------------------------------------------------------------------

class TextFitAndRectTest(unittest.TestCase):
    def test_header_text_too_wide_rejected_with_measured_vs_available(self) -> None:
        font = fontmetrics.Font.load(ARCHIVO_FILE)
        title = "W" * 28
        tag = "W" * 16
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(title=title, tag=tag))]))
        msg = str(ctx.exception)
        self.assertIn("tidak muat di header", msg)
        self.assertIn("tersedia", msg)

    def test_input_text_too_wide_rejected_with_measured_vs_available(self) -> None:
        input_text = "W" * 28
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(input=input_text))]))
        msg = str(ctx.exception)
        self.assertIn("tidak muat di bilah input", msg)
        self.assertIn("tersedia", msg)

    def test_default_rect_dimensions(self) -> None:
        ass, _ = _build(_clip([_overlay(_props(thumbs=3))]))
        card = _role_lines(ass, "card")[0]
        bounds = _path_bounds(_shape_path(card))
        self.assertEqual(presets.UI_CARD_X, 60.0)
        self.assertEqual(presets.UI_CARD_Y, 260.0)
        self.assertEqual(presets.UI_CARD_W, 960.0)
        self.assertEqual(presets.UI_CARD_RADIUS, 48.0)
        self.assertAlmostEqual(bounds[0], 60.0, delta=0.1)
        self.assertAlmostEqual(bounds[1], 260.0, delta=0.1)
        self.assertAlmostEqual(bounds[2] - bounds[0], 960.0, delta=0.1)
        expected_h = presets._ui_required_height(3)
        self.assertAlmostEqual(bounds[3] - bounds[1], expected_h, delta=0.1)
        self.assertLessEqual(expected_h, presets.UI_CARD_MAX_H)

    def test_rect_h_too_short_rejected_without_silent_shrinking(self) -> None:
        expected_h = presets._ui_required_height(3)
        too_short_h = expected_h - 20.0
        rect = {"x": 60.0, "y": 260.0, "w": 960.0, "h": too_short_h}
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(thumbs=3), rect=rect)]))
        msg = str(ctx.exception)
        self.assertIn("rect['h']", msg)
        self.assertIn("tinggi yang dibutuhkan", msg)
        self.assertIn("tidak boleh disusutkan", msg)

    def test_rect_w_too_narrow_for_thumbnails_rejected(self) -> None:
        rect = {"x": 60.0, "y": 260.0, "w": 800.0, "h": 500.0}
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(thumbs=3), rect=rect)]))
        msg = str(ctx.exception)
        self.assertIn("rect['w']", msg)
        self.assertIn("lebar yang dibutuhkan", msg)

    def test_rect_out_of_canvas_rejected(self) -> None:
        for bad_rect in (
            {"x": -10.0, "y": 260.0, "w": 960.0, "h": 500.0},
            {"x": 60.0, "y": -5.0, "w": 960.0, "h": 500.0},
            {"x": 200.0, "y": 260.0, "w": 960.0, "h": 500.0},
            {"x": 60.0, "y": 1600.0, "w": 960.0, "h": 500.0},
        ):
            with self.subTest(bad_rect=bad_rect):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_overlay(_props(), rect=bad_rect)]))
                self.assertIn("keluar kanvas", str(ctx.exception))

    def test_rect_unknown_key_rejected(self) -> None:
        rect = {"x": 60.0, "y": 260.0, "w": 960.0, "h": 500.0, "extra": 1}
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_overlay(_props(), rect=rect)]))
        self.assertIn("rect kunci tidak dikenal", str(ctx.exception))


# ---------------------------------------------------------------------------
# Height calculation & Thumbnail layout
# ---------------------------------------------------------------------------

class HeightAndLayoutTest(unittest.TestCase):
    def test_card_height_for_1_3_4_6_thumbs(self) -> None:
        self.assertEqual(presets.UI_INPUT_H, 60.0)
        h1 = presets._ui_required_height(1)
        h3 = presets._ui_required_height(3)
        h4 = presets._ui_required_height(4)
        h6 = presets._ui_required_height(6)

        self.assertEqual(h1, h3, "1 dan 3 thumbnail harus 1 baris (tinggi sama)")
        self.assertEqual(h4, h6, "4 dan 6 thumbnail harus 2 baris (tinggi sama)")
        self.assertGreater(h4, h3, "2 baris harus lebih tinggi dari 1 baris")
        self.assertEqual(h1, 398.0)
        self.assertEqual(h6, 588.0)
        self.assertLessEqual(h1, presets.UI_CARD_MAX_H)
        self.assertLessEqual(h6, presets.UI_CARD_MAX_H)
        self.assertLessEqual(h6, 700.0)

    def test_thumbnail_grid_positions_for_6_thumbs(self) -> None:
        self.assertEqual(presets.UI_THUMB_GAP_X, 30.0)
        self.assertEqual(presets.UI_THUMB_W, 270.0)
        ass, _ = _build(_clip([_overlay(_props(thumbs=6))]))
        thumbs = _role_lines(ass, "thumb")
        self.assertEqual(len(thumbs), 6)
        positions = [_pos(line) for line in thumbs]
        self.assertTrue(all(p is not None for p in positions))
        pos_list = [p for p in positions if p is not None]

        # Baris 0: thumb 0, 1, 2 (y sama, x bertambah dengan selisih 270 + 30 = 300 px)
        self.assertAlmostEqual(pos_list[0][1], pos_list[1][1], delta=0.01)
        self.assertAlmostEqual(pos_list[1][1], pos_list[2][1], delta=0.01)
        self.assertAlmostEqual(
            pos_list[1][0] - pos_list[0][0],
            300.0, delta=0.01
        )
        self.assertAlmostEqual(
            pos_list[2][0] - pos_list[1][0],
            300.0, delta=0.01
        )

        # Baris 1: thumb 3, 4, 5 (y sama, x sejajar dengan baris 0)
        self.assertAlmostEqual(pos_list[3][1], pos_list[4][1], delta=0.01)
        self.assertAlmostEqual(pos_list[4][1], pos_list[5][1], delta=0.01)
        self.assertAlmostEqual(pos_list[0][0], pos_list[3][0], delta=0.01)
        self.assertAlmostEqual(pos_list[1][0], pos_list[4][0], delta=0.01)
        self.assertAlmostEqual(pos_list[2][0], pos_list[5][0], delta=0.01)
        self.assertAlmostEqual(
            pos_list[3][1] - pos_list[0][1],
            presets.UI_THUMB_H + presets.UI_THUMB_GAP_Y, delta=0.01
        )


# ---------------------------------------------------------------------------
# Struktur Dokumen & Dialogue
# ---------------------------------------------------------------------------

class DocumentStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ass, self.warnings = _build(_clip([_overlay(_props(thumbs=6))]))
        assert self.ass is not None

    def test_all_dialogues_have_ten_fields(self) -> None:
        for line in _dialogue_lines(self.ass):
            fields = line[len("Dialogue: "):].split(",", 9)
            self.assertEqual(len(fields), 10, msg=f"bukan 10 field: {line}")

    def test_special_characters_are_escaped(self) -> None:
        props = _props(
            title="UI {World} \\ 1",
            tag="Tag {1} \\",
            input="Input {test} \\",
        )
        ass, _ = _build(_clip([_overlay(props)]))
        assert ass is not None
        title_line = _role_lines(ass, "title")[0]
        tag_line = _role_lines(ass, "tagtext")[0]
        input_line = _role_lines(ass, "inputtext")[0]

        self.assertIn("UI (World) / 1", _shown_text(title_line))
        self.assertIn("Tag (1) /", _shown_text(tag_line))
        self.assertIn("Input (test) /", _shown_text(input_line))

    def test_dialogue_count_le_40_for_6_thumbs(self) -> None:
        dialogues = _dialogue_lines(self.ass)
        self.assertLessEqual(len(dialogues), 40)
        # Untuk 6 thumbnail: 1 card, 1 title, 1 inputbar, 1 inputtext,
        # 6 thumbs, 1 tagbubble, 1 tagtext = 12 dialogues.
        self.assertEqual(len(dialogues), 12)

    def test_layer_order(self) -> None:
        def layer_of(role: str) -> int:
            lines = _role_lines(self.ass, role)
            self.assertTrue(lines, msg=f"tidak ada baris untuk {role}")
            return int(_fields(lines[0])[0])

        card_l = layer_of("card")
        thumb_l = layer_of("thumb")
        inputbar_l = layer_of("inputbar")
        inputtext_l = layer_of("inputtext")
        title_l = layer_of("title")
        tagbubble_l = layer_of("tagbubble")
        tagtext_l = layer_of("tagtext")

        self.assertLess(card_l, thumb_l)
        self.assertLess(card_l, inputbar_l)
        self.assertLessEqual(inputbar_l, inputtext_l)
        self.assertLess(card_l, title_l)
        self.assertLess(tagbubble_l, tagtext_l)

    def test_dialogue_single_thumbnail_format(self) -> None:
        thumb = _role_lines(self.ass, "thumb")[0]
        self.assertIn("\\fscx0\\fscy0", _text_field(thumb))
        self.assertIn("\\p1", _text_field(thumb))
        self.assertIn("\\p0", _text_field(thumb))
        pos = _pos(thumb)
        self.assertIsNotNone(pos)

    def test_dialogue_tag_format(self) -> None:
        bubble = _role_lines(self.ass, "tagbubble")[0]
        text = _role_lines(self.ass, "tagtext")[0]
        self.assertIn(shapes.colour(presets.UI_TAG_BG_COLOUR), _text_field(bubble))
        self.assertIn(shapes.colour(presets.UI_TAG_TEXT_COLOUR), _text_field(text))
        self.assertEqual(_shown_text(text), TAG)


# ---------------------------------------------------------------------------
# Waktu & Gerak (Entry, Stagger, Exit)
# ---------------------------------------------------------------------------

class TimingAndMotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ass, self.warnings = _build(_clip([_overlay(_props(thumbs=3))]))
        assert self.ass is not None

    def test_rigid_entry_move(self) -> None:
        self.assertEqual(presets.UI_ENTRY_OFFSET, 60.0)
        self.assertEqual(presets.UI_ENTRY, 0.30)
        entry_roles = ("card", "title", "inputbar", "inputtext")
        deltas: set[float] = set()
        for role in entry_roles:
            lines = _role_lines(self.ass, role)
            self.assertTrue(lines, msg=f"tidak ada event untuk {role}")
            for line in lines:
                move = _move(line)
                self.assertIsNotNone(move, msg=f"{role} tidak punya \\move")
                assert move is not None
                x0, y0, x1, y1, t0, t1 = move
                if role in ("card", "inputbar"):
                    self.assertEqual((x0, y0), (0.0, -presets.UI_ENTRY_OFFSET))
                    self.assertEqual((x1, y1), (0.0, 0.0))
                else:
                    self.assertAlmostEqual(x1 - x0, 0.0, delta=0.01)
                    self.assertAlmostEqual(
                        y1 - y0, presets.UI_ENTRY_OFFSET, delta=0.01
                    )
                deltas.add(round(y1 - y0 if role not in ("card", "inputbar") else -y0, 2))
                # Alfa ease-out
                self.assertIn(
                    f"\\1a&HFF&\\t(0,{t1},{presets.UI_ENTRY_ACCEL:g},"
                    if role in ("card", "inputbar")
                    else f"\\alpha&HFF&\\t(0,{t1},{presets.UI_ENTRY_ACCEL:g},",
                    _text_field(line),
                )
        self.assertEqual(deltas, {60.0})

    def test_thumbnails_staggered_by_80ms(self) -> None:
        thumbs = _role_lines(self.ass, "thumb")
        self.assertEqual(len(thumbs), 3)

        self.assertEqual(presets.UI_THUMB_STAGGER, 0.080)
        # START = 0.40, UI_ENTRY = 0.30 -> entry_time = 0.70 s (frame 21)
        # Jeda 80 ms (0.080 s) @30 fps dihitung manual (spesifikasi literal):
        # thumb 0: 0.70 s -> round(0.70 * 30) = 21 -> start ASS: 0:00:00.67
        # thumb 1: 0.78 s -> round(0.78 * 30) = 23 -> start ASS: 0:00:00.74
        # thumb 2: 0.86 s -> round(0.86 * 30) = 26 -> start ASS: 0:00:00.84
        expected_frames = [21, 23, 26]
        expected_ass_times = ["0:00:00.67", "0:00:00.74", "0:00:00.84"]

        for k, line in enumerate(thumbs):
            actual_start_sec = _start_seconds(line)
            expected_start_sec = presets._frame_start_time(expected_frames[k], FPS)
            self.assertAlmostEqual(
                actual_start_sec, expected_start_sec, delta=0.01,
                msg=f"thumbnail {k} mulai {actual_start_sec}s vs {expected_start_sec}s",
            )
            self.assertEqual(_fields(line)[1], expected_ass_times[k])

    def test_tag_starts_after_last_thumbnail(self) -> None:
        tag_bubble = _role_lines(self.ass, "tagbubble")[0]
        tag_text = _role_lines(self.ass, "tagtext")[0]

        # Tag dimulai setelah thumb terakhir (0.4 + 0.3 + 3 * 0.08 = 0.94 s -> frame 28 -> 0:00:00.91)
        expected_frame = 28
        expected_start_sec = presets._frame_start_time(expected_frame, FPS)

        self.assertAlmostEqual(
            _start_seconds(tag_bubble), expected_start_sec, delta=0.01
        )
        self.assertAlmostEqual(
            _start_seconds(tag_text), expected_start_sec, delta=0.01
        )
        self.assertEqual(_fields(tag_bubble)[1], "0:00:00.91")
        self.assertEqual(_fields(tag_text)[1], "0:00:00.91")

    def test_exit_fade_200ms_on_all_elements(self) -> None:
        self.assertEqual(presets.UI_EXIT, 0.20)
        for line in _dialogue_lines(self.ass):
            self.assertIn(
                "\\alpha&HFF&)", _text_field(line),
                msg=f"event tidak memuat tag fade keluar: {line}",
            )


# ---------------------------------------------------------------------------
# Font & Determinisme
# ---------------------------------------------------------------------------

class FontAndDeterminismTest(unittest.TestCase):
    def test_determinism_identical_output(self) -> None:
        clip = _clip([_overlay()])
        ass1, _ = _build(clip)
        ass2, _ = _build(clip)
        self.assertEqual(ass1, ass2)
        self.assertIsNotNone(ass1)

    def test_missing_font_skips_with_one_warning(self) -> None:
        missing = ROOT / "assets" / "fonts" / "TidakAdaFont.ttf"
        ass, warnings = _build(_clip([_overlay()]), font_path=missing)
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1)
        self.assertIn("font", warnings[0].lower())

    def test_wrong_family_skips_without_exception(self) -> None:
        ass, warnings = _build(_clip([_overlay()]), font_path=DMSERIF_FILE)
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Archivo Black", warnings[0])

    def test_ui_panel_and_checklist_share_sans_style(self) -> None:
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
        self.assertIsNotNone(ass)
        assert ass is not None
        self.assertEqual(ass.count("Style: Sans,"), 1)

    def test_zoom_checklist_and_chart_golden_hashes_are_preserved(self) -> None:
        # Dokumen zoom_through_text 5b-1
        zoom_clip = _clip(
            [{
                "type": "zoom_through_text", "start": 0.5, "end": 3.0,
                "props": {"text": "5 JAM"},
            }],
            segments=((0.0, 3.0),),
        )
        zoom_ass, _ = presets.build_fx_ass(zoom_clip, fps=FPS)
        assert zoom_ass is not None
        self.assertEqual(
            hashlib.sha256(zoom_ass.encode("utf-8")).hexdigest(),
            ZOOM_GOLDEN_SHA256,
            "dokumen zoom_through_text 5b-1 berubah",
        )

        # Dokumen checklist 5b-2
        checklist_clip = _clip(
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
        check_ass, _ = presets.build_fx_ass(checklist_clip, fps=FPS)
        assert check_ass is not None
        self.assertEqual(
            hashlib.sha256(check_ass.encode("utf-8")).hexdigest(),
            CHECKLIST_GOLDEN_SHA256,
            "dokumen checklist 5b-2 berubah",
        )

        # Dokumen chart_grow 5b-3
        chart_clip = _clip(
            [{
                "type": "chart_grow", "start": 0.4, "end": 3.6,
                "props": {
                    "labels": ["SEN", "SEL", "RAB", "KAM", "JUM"],
                    "values": [10.0, 40.0, 25.0, 55.0, 80.0],
                    "tag": "+240%",
                    "title": "GROWTH",
                },
            }],
            segments=((0.0, 4.0),),
        )
        chart_ass, _ = presets.build_fx_ass(chart_clip, fps=FPS)
        assert chart_ass is not None
        self.assertEqual(
            hashlib.sha256(chart_ass.encode("utf-8")).hexdigest(),
            CHART_GOLDEN_SHA256,
            "dokumen chart_grow 5b-3 berubah",
        )

    def test_ui_panel_and_phone_frame_golden_hashes_are_preserved(self) -> None:
        ui_clip = _clip(
            [{
                "type": "ui_panel", "start": 0.4, "end": 3.6,
                "props": {
                    "title": "COMPONENTS",
                    "tag": "PRO",
                    "thumbs": 3,
                    "input": "Search UI...",
                },
            }],
            segments=((0.0, 4.0),),
        )
        ui_ass, _ = presets.build_fx_ass(ui_clip, fps=FPS)
        assert ui_ass is not None
        self.assertEqual(
            hashlib.sha256(ui_ass.encode("utf-8")).hexdigest(),
            "693eeb2d63999875e680e753311e2deb632bcf5b1297de05fb5366cc4bd3c59e",
            "dokumen ui_panel berubah",
        )

        phone_clip = _clip(
            [{
                "type": "phone_frame", "start": 0.4, "end": 3.6,
                "props": {
                    "title": "TRANSFER",
                    "lines": ["Transfer masuk Rp 50rb", "Dari Budi Santoso", "Sisa saldo Rp 1.5jt"],
                },
            }],
            segments=((0.0, 4.0),),
        )
        phone_ass, _ = presets.build_fx_ass(phone_clip, fps=FPS)
        assert phone_ass is not None
        self.assertEqual(
            hashlib.sha256(phone_ass.encode("utf-8")).hexdigest(),
            "b769aa078a0bb7a2b4c5ed5bcc66639219e9b98d5fd2a0f2b366f23a658b84fe",
            "dokumen phone_frame berubah",
        )
