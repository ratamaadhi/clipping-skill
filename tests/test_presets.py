"""Tes murni `scripts.presets` — tanpa ffmpeg, tanpa berkas sementara.

Yang diuji di sini adalah KONTRAK modul: daftar tipe, validasi props/waktu,
struktur dokumen ASS, dan determinisme. Pembuktian bahwa libass benar-benar
memakai font bundel dan menggambar skala/alfa ada di
`tests/test_presets_render.py` (skipUnless ffmpeg+libass).

Angka acuan perilaku `zoom_through_text`:
  * skala 80% -> 320% dalam `duration` (bawaan 0,7 s), easing `accel=2`;
  * alfa 1 -> 0 pada 40% terakhir `duration`;
  * event `[start, min(end, start + duration)]`;
  * satu `Dialogue` per overlay, Style `Serif` (DM Serif Display Italic).
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from tests.helpers import ROOT

from scripts import presets
from scripts.lib import fontmetrics

FONT_FILE = ROOT / "assets" / "fonts" / "DMSerifDisplay-Italic.ttf"
ARCHIVO_FILE = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"

TYPE = "zoom_through_text"


# ---------------------------------------------------------------------------
# Pembangun fixture
# ---------------------------------------------------------------------------

def _clip(overlays: list | None = None, segments=None, clip_id: str = "clip_01") -> dict:
    segs = segments if segments is not None else ((0.0, 3.0),)
    return {
        "id": clip_id,
        "segments": [{"src_start": a, "src_end": b} for a, b in segs],
        "overlays": overlays if overlays is not None else [],
    }


def _item(props: dict | None = None, *, start: object = 0.5, end: object = 3.0) -> dict:
    base: dict = {"type": TYPE, "start": start, "end": end}
    if props is not None:
        base["props"] = props
    return base


def _props(**overrides: object) -> dict:
    props = {"text": "5 JAM"}
    props.update(overrides)
    return props


def _build(clip: dict, **kwargs: object):
    return presets.build_fx_ass(clip, fps=30.0, **kwargs)


def _dialogues(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def _fields(line: str) -> list[str]:
    """Pecah Dialogue menjadi 10 field; koma di dalam `Text` aman (maxsplit 9)."""
    return line[len("Dialogue: "):].split(",", 9)


def _text_field(line: str) -> str:
    return _fields(line)[9]


def _style(ass: str, name: str = "Serif") -> list[str]:
    prefix = f"Style: {name},"
    rows = [ln for ln in ass.splitlines() if ln.startswith(prefix)]
    if not rows:
        raise AssertionError(f"Style {name!r} tidak ada di dokumen:\n{ass}")
    return rows[0][len("Style: "):].split(",")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class RegistryTest(unittest.TestCase):
    def test_preset_types_is_tuple_with_known_names(self) -> None:
        self.assertIsInstance(presets.PRESET_TYPES, tuple)
        self.assertEqual(
            presets.PRESET_TYPES,
            (TYPE, "checklist", "chart_grow", "ui_panel", "phone_frame"),
        )

    def test_registry_keys_match_preset_types(self) -> None:
        self.assertEqual(set(presets.REGISTRY), set(presets.PRESET_TYPES))
        for name, builder in presets.REGISTRY.items():
            self.assertTrue(callable(builder), msg=name)

    def test_preset_error_is_value_error(self) -> None:
        self.assertTrue(issubclass(presets.PresetError, ValueError))


# ---------------------------------------------------------------------------
# Overlay yang bukan preset / tidak ada preset
# ---------------------------------------------------------------------------

class IgnoreOtherTypesTest(unittest.TestCase):
    def test_no_overlays_returns_none_without_warnings(self) -> None:
        ass, warnings = _build(_clip())
        self.assertIsNone(ass)
        self.assertEqual(warnings, [])

    def test_missing_overlays_key_returns_none(self) -> None:
        clip = _clip()
        del clip["overlays"]
        ass, warnings = _build(clip)
        self.assertIsNone(ass)
        self.assertEqual(warnings, [])

    def test_vs_and_unknown_types_are_ignored_silently(self) -> None:
        overlays = [
            {"type": "vs", "start": 0.0, "end": 1.0, "left": "Kopi", "right": "Teh"},
            {"type": "future_preset", "start": 0.0, "end": 1.0, "props": {"x": 1}},
            {"start": 0.0, "end": 1.0, "props": {"text": "tanpa tipe"}},
            {"type": ["zoom_through_text"], "start": 0.0, "end": 1.0},
            "bukan objek",
        ]
        ass, warnings = _build(_clip(overlays))
        self.assertIsNone(ass)
        self.assertEqual(warnings, [])

    def test_mixed_types_build_only_preset_events(self) -> None:
        overlays = [
            {"type": "vs", "start": 0.0, "end": 1.0, "left": "Kopi", "right": "Teh"},
            _item(_props()),
        ]
        ass, warnings = _build(_clip(overlays))
        self.assertIsNotNone(ass)
        self.assertEqual(warnings, [])
        assert ass is not None
        self.assertEqual(len(_dialogues(ass)), 1)


# ---------------------------------------------------------------------------
# Validasi props
# ---------------------------------------------------------------------------

class PropsValidationTest(unittest.TestCase):
    def _assert_error(self, props, needle: str) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_item(props)]))
        message = str(ctx.exception)
        self.assertIn("overlay[0]", message)
        self.assertIn(TYPE, message)
        self.assertIn(needle, message, msg=message)

    def test_text_empty(self) -> None:
        self._assert_error({"text": ""}, "text")

    def test_text_too_long(self) -> None:
        self._assert_error({"text": "x" * 25}, "text")

    def test_text_newline(self) -> None:
        self._assert_error({"text": "a\nb"}, "text")

    def test_text_carriage_return(self) -> None:
        self._assert_error({"text": "a\rb"}, "text")

    def test_text_not_string(self) -> None:
        self._assert_error({"text": 7}, "text")

    def test_text_missing(self) -> None:
        self._assert_error({}, "text")

    def test_colour_bad_shape(self) -> None:
        self._assert_error(_props(colour="#12345"), "colour")

    def test_colour_not_hex(self) -> None:
        self._assert_error(_props(colour="merah"), "colour")

    def test_colour_not_string(self) -> None:
        self._assert_error(_props(colour=0xFFFFFF), "colour")

    def test_size_em_below_range(self) -> None:
        self._assert_error(_props(size_em=59), "size_em")

    def test_size_em_above_range(self) -> None:
        self._assert_error(_props(size_em=401), "size_em")

    def test_size_em_not_number(self) -> None:
        self._assert_error(_props(size_em="besar"), "size_em")

    def test_size_em_nan(self) -> None:
        self._assert_error(_props(size_em=float("nan")), "size_em")

    def test_size_em_bool_rejected(self) -> None:
        self._assert_error(_props(size_em=True), "size_em")

    def test_duration_below_range(self) -> None:
        self._assert_error(_props(duration=0.39), "duration")

    def test_duration_above_range(self) -> None:
        self._assert_error(_props(duration=1.51), "duration")

    def test_duration_none(self) -> None:
        self._assert_error(_props(duration=None), "duration")

    def test_unknown_prop_rejected_with_name(self) -> None:
        self._assert_error(_props(size=200), "size")

    def test_props_not_object(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([{"type": TYPE, "start": 0.0, "end": 1.0, "props": []}]))
        message = str(ctx.exception)
        self.assertIn("overlay[0]", message)
        self.assertIn("props", message)

    def test_second_overlay_error_names_its_index(self) -> None:
        overlays = [_item(_props()), _item(_props(duration=2.0))]
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip(overlays))
        message = str(ctx.exception)
        self.assertIn("overlay[1]", message)
        self.assertIn("duration", message)

    def test_boundary_values_are_accepted(self) -> None:
        cases = (
            {"text": "x"},
            {"text": "x" * 24},
            _props(size_em=60),
            _props(size_em=400),
            _props(duration=0.4),
            _props(duration=1.5),
            _props(colour="#abcdef"),
        )
        for props in cases:
            with self.subTest(props=props):
                ass, warnings = _build(_clip([_item(props)]))
                self.assertIsNotNone(ass)
                self.assertEqual(warnings, [])


# ---------------------------------------------------------------------------
# Escape teks
# ---------------------------------------------------------------------------

class TextEscapeTest(unittest.TestCase):
    def test_braces_and_backslash_are_neutralised(self) -> None:
        ass, _ = _build(_clip([_item(_props(text="a{b}\\c"))]))
        assert ass is not None
        text = _text_field(_dialogues(ass)[0])
        # Buang blok override (yang memang berisi `\c` dan kurawal), lalu
        # periksa teks yang benar-benar digambar.
        shown = text.rsplit("}", 1)[1]
        self.assertEqual(shown, "a(b)/c")
        self.assertNotIn("{", shown)
        self.assertNotIn("}", shown)
        self.assertNotIn("\\", shown)

    def test_comma_stays_in_text_field(self) -> None:
        ass, _ = _build(_clip([_item(_props(text="5, JAM"))]))
        assert ass is not None
        line = _dialogues(ass)[0]
        self.assertEqual(len(_fields(line)), 10)
        self.assertIn("5, JAM", _text_field(line))


# ---------------------------------------------------------------------------
# Waktu: klip, pemotongan, peringatan
# ---------------------------------------------------------------------------

class TimingTest(unittest.TestCase):
    def test_event_ends_at_start_plus_duration(self) -> None:
        ass, warnings = _build(_clip([_item(_props(), start=0.5, end=3.0)]))
        assert ass is not None
        self.assertEqual(warnings, [])
        fields = _fields(_dialogues(ass)[0])
        self.assertEqual(fields[1], "0:00:00.50")
        self.assertEqual(fields[2], "0:00:01.20")

    def test_overlay_end_is_clamped_to_clip_duration(self) -> None:
        ass, _ = _build(
            _clip([_item(_props(duration=1.0), start=2.5, end=10.0)])
        )
        assert ass is not None
        fields = _fields(_dialogues(ass)[0])
        self.assertEqual(fields[1], "0:00:02.50")
        self.assertEqual(fields[2], "0:00:03.00")

    def test_clip_duration_sums_segments_not_last_minus_first(self) -> None:
        # Dua segmen 0..1 dan 10..12 -> durasi klip 3 s, bukan 12 s.
        ass, _ = _build(
            _clip(
                [_item(_props(duration=1.0), start=2.5, end=10.0)],
                segments=((0.0, 1.0), (10.0, 12.0)),
            )
        )
        assert ass is not None
        self.assertEqual(_fields(_dialogues(ass)[0])[2], "0:00:03.00")

    def test_start_before_zero_is_clamped(self) -> None:
        ass, _ = _build(_clip([_item(_props(), start=-0.5, end=0.5)]))
        assert ass is not None
        fields = _fields(_dialogues(ass)[0])
        self.assertEqual(fields[1], "0:00:00.00")
        self.assertEqual(fields[2], "0:00:00.50")

    def test_overlay_entirely_outside_is_skipped_with_one_warning(self) -> None:
        for start, end in ((5.0, 6.0), (-2.0, -1.0), (3.0, 3.5)):
            with self.subTest(start=start, end=end):
                ass, warnings = _build(_clip([_item(_props(), start=start, end=end)]))
                self.assertIsNone(ass)
                self.assertEqual(len(warnings), 1, msg=warnings)
                self.assertIn("overlay[0]", warnings[0])
                self.assertIn(TYPE, warnings[0])

    def test_outside_overlay_does_not_hide_the_other_events(self) -> None:
        overlays = [
            _item(_props(), start=5.0, end=6.0),
            _item(_props(text="MASIH"), start=1.0, end=2.0),
        ]
        ass, warnings = _build(_clip(overlays))
        assert ass is not None
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len(_dialogues(ass)), 1)
        self.assertIn("MASIH", ass)

    def test_end_not_after_start_raises(self) -> None:
        with self.assertRaises(presets.PresetError) as ctx:
            _build(_clip([_item(_props(), start=1.0, end=1.0)]))
        message = str(ctx.exception)
        self.assertIn("overlay[0]", message)
        self.assertIn("end", message)

    def test_touching_end_and_tiny_inside_window(self) -> None:
        # end==start pada overlay di dalam klip -> error.
        with self.assertRaises(presets.PresetError):
            _build(_clip([_item(_props(), start=2.9, end=2.9)]))
        # Jendela 50 ms yang masih di dalam klip tetap valid.
        ass, _ = _build(_clip([_item(_props(), start=2.9, end=2.95)]))
        assert ass is not None
        self.assertEqual(_fields(_dialogues(ass)[0])[2], "0:00:02.95")

    def test_start_end_must_be_numbers(self) -> None:
        for start, end, needle in (("0.5", 2.0, "start"), (0.5, "2.0", "end")):
            with self.subTest(start=start, end=end):
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([_item(_props(), start=start, end=end)]))
                self.assertIn(needle, str(ctx.exception))

    def test_no_segments_raises_preset_error(self) -> None:
        with self.assertRaises(presets.PresetError):
            _build(_clip([_item(_props())], segments=()))


# ---------------------------------------------------------------------------
# Struktur event dan Style
# ---------------------------------------------------------------------------

class EventStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ass, self.warnings = _build(_clip([_item(_props())]))
        assert self.ass is not None
        self.lines = _dialogues(self.ass)

    def test_one_dialogue_per_overlay(self) -> None:
        ass, _ = _build(
            _clip([_item(_props(text="SATU"), start=0.2, end=1.0),
                   _item(_props(text="DUA"), start=1.5, end=2.5)])
        )
        assert ass is not None
        self.assertEqual(len(_dialogues(ass)), 2)

    def test_every_dialogue_has_ten_fields(self) -> None:
        self.assertEqual(len(self.lines), 1)
        self.assertEqual(len(_fields(self.lines[0])), 10)

    def test_default_center_and_scale_chain(self) -> None:
        text = _text_field(self.lines[0])
        self.assertIn("\\an5\\pos(540,960)", text)
        self.assertIn("\\fscx80\\fscy80", text)
        self.assertIn("\\t(0,700,2,\\fscx320\\fscy320)", text)
        self.assertIn("\\alpha&H00&", text)
        self.assertIn("\\t(420,700,\\alpha&HFF&)", text)

    def test_rect_moves_center(self) -> None:
        item = _item(_props())
        item["rect"] = {"x": 100, "y": 200, "w": 800, "h": 400}
        ass, _ = _build(_clip([item]))
        assert ass is not None
        self.assertIn("\\an5\\pos(500,400)", _text_field(_dialogues(ass)[0]))

    def test_bad_rect_raises(self) -> None:
        for rect in ({"x": 0, "y": 0, "w": 0, "h": 10}, {"x": 0, "y": 0, "w": 10}, "kotak"):
            with self.subTest(rect=rect):
                item = _item(_props())
                item["rect"] = rect
                with self.assertRaises(presets.PresetError) as ctx:
                    _build(_clip([item]))
                self.assertIn("rect", str(ctx.exception))

    def test_duration_sets_millisecond_tags(self) -> None:
        ass, _ = _build(_clip([_item(_props(duration=1.0))]))
        assert ass is not None
        text = _text_field(_dialogues(ass)[0])
        self.assertIn("\\t(0,1000,2,\\fscx320\\fscy320)", text)
        self.assertIn("\\t(600,1000,\\alpha&HFF&)", text)

    def test_colour_default_and_custom(self) -> None:
        white = _text_field(self.lines[0])
        self.assertIn("\\c&HFFFFFF&", white)

        ass, _ = _build(_clip([_item(_props(colour="#112233"))]))
        assert ass is not None
        self.assertIn("\\c&H332211&", _text_field(_dialogues(ass)[0]))

    def test_style_fields(self) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        fields = _style(self.ass)
        self.assertEqual(fields[0], "Serif")
        self.assertEqual(fields[1], font.family)
        self.assertAlmostEqual(
            float(fields[2]), round(160.0 * font.cell_height_ratio, 2), places=2
        )
        self.assertEqual(fields[7], "0")    # Bold
        self.assertEqual(fields[8], "-1")   # Italic
        self.assertEqual(fields[16], "0")   # Outline
        self.assertEqual(fields[17], "0")   # Shadow
        self.assertEqual(fields[18], "5")   # Alignment tengah

    def test_style_fontsize_follows_size_em(self) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        ass, _ = _build(_clip([_item(_props(size_em=200))]))
        assert ass is not None
        fields = _style(ass)
        self.assertAlmostEqual(
            float(fields[2]), round(200.0 * font.cell_height_ratio, 2), places=2
        )
        # Event juga membawa \fs yang sama, supaya dua overlay berbeda ukuran
        # tetap benar walau berbagi satu Style.
        self.assertIn("\\fs", _text_field(_dialogues(ass)[0]))

    def test_style_comes_from_font_family_not_guess(self) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        self.assertEqual(font.family, "DM Serif Display")
        self.assertEqual(font.full_name, "DM Serif Display Italic")
        self.assertEqual(_style(self.ass)[1], font.family)


# ---------------------------------------------------------------------------
# Determinisme + font tidak tersedia
# ---------------------------------------------------------------------------

class DeterminismAndFontTest(unittest.TestCase):
    def test_two_calls_are_identical(self) -> None:
        clip = _clip([_item(_props(text="5 JAM"), start=0.2, end=2.0)])
        first = _build(clip)
        second = _build(clip)
        self.assertEqual(first, second)
        self.assertIsNotNone(first[0])

    def test_missing_font_returns_none_and_one_warning(self) -> None:
        missing = ROOT / "assets" / "fonts" / "TidakAda.ttf"
        ass, warnings = _build(_clip([_item(_props())]), font_path=missing)
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1, msg=warnings)
        self.assertIn("font", warnings[0].lower())

    def test_missing_font_warns_once_for_many_overlays(self) -> None:
        overlays = [_item(_props(text="SATU"), start=0.2, end=1.0),
                    _item(_props(text="DUA"), start=1.2, end=2.0)]
        missing = ROOT / "assets" / "fonts" / "TidakAda.ttf"
        ass, warnings = _build(_clip(overlays), font_path=missing)
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1, msg=warnings)

    def test_wrong_font_family_is_skipped_without_exception(self) -> None:
        ass, warnings = _build(_clip([_item(_props())]), font_path=ARCHIVO_FILE)
        self.assertIsNone(ass)
        self.assertEqual(len(warnings), 1, msg=warnings)
        self.assertIn("DM Serif Display", warnings[0])


if __name__ == "__main__":
    unittest.main()
