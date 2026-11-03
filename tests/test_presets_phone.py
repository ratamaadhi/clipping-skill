"""Tes murni preset `phone_frame` di `scripts.presets_phone` — tanpa ffmpeg.

Kontrak yang dikunci (docs/MOTION-TIER2-PLAN.md Langkah 5b, baris #06 "phone mockup"):

* props ketat: `title` 1..22 karakter tanpa newline, `lines` daftar 2..4 string
  tiap string 1..22 karakter tanpa newline, `accent` opsional '#RRGGBB'
  (bawaan #FFD60A), `side` opsional 'right' (bawaan) atau 'left';
* teks diukur dengan `fontmetrics` dan DITOLAK bila tidak muat (lebar terukur
  vs tersedia di pesan error);
* `rect` opsional (bawaan x=640 untuk side='right' atau 60 untuk side='left',
  y=250, w=380, h dihitung dari isi: 560/660/760 px untuk 2/3/4 baris);
* `rect.h` terlalu pendek ditolak dengan PresetError jelas, bukan disusutkan
  diam-diam; seluruh rect harus dalam kanvas 1080x1920;
* urutan layer: badan < layar < notch < teks;
* masuk: seluruh perangkat meluncur kaku dari sisi (140 px selama ENTRY 0.35 s)
  dengan move identik; baris-baris muncul berurutan (fade-in 120 ms + geser 12 px)
  dengan jeda 180 ms antar-baris; keluar fade 0.20 s seluruh elemen;
* maksimum 40 Dialogue untuk 4 baris; deterministik;
* font hilang -> satu peringatan dan plan=None, bukan exception;
* `INTEGRATION` memuat nama hook yang sebenarnya ada di `presets.py`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import ROOT

from scripts import presets
from scripts import shapes
from scripts.lib import fontmetrics

try:
    from scripts import presets_phone
except ImportError:
    presets_phone = None  # type: ignore[assignment]


ARCHIVO_FILE = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"

FPS = 30.0
CLIP_DUR = 4.0
START = 0.4
END = 3.6
TITLE = "NOTIFIKASI"
LINES = ["Transfer masuk Rp 50rb", "Saldo bertambah", "Bonus harian aktif"]


def _clip_overlay(
    *,
    props: dict[str, Any] | None = None,
    start: float = START,
    end: float = END,
    rect: dict[str, float] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": "phone_frame",
        "start": start,
        "end": end,
        "props": props
        if props is not None
        else {"title": TITLE, "lines": list(LINES)},
    }
    if rect is not None:
        item["rect"] = rect
    return item


def _fields(dialogue: str) -> list[str]:
    self_prefix = "Dialogue: "
    if dialogue.startswith(self_prefix):
        dialogue = dialogue[len(self_prefix) :]
    return dialogue.split(",", 9)


class PhoneFrameImportTest(unittest.TestCase):
    """Pastikan modul scripts.presets_phone ada dan mengekspor antarmuka publik."""

    def test_module_exists_and_exports_expected_api(self) -> None:
        self.assertIsNotNone(
            presets_phone,
            "modul `scripts.presets_phone` belum diimplementasikan",
        )
        assert presets_phone is not None
        self.assertEqual(presets_phone.TYPE, "phone_frame")
        self.assertTrue(callable(presets_phone.build))
        self.assertTrue(callable(presets_phone.events))
        self.assertTrue(callable(presets_phone.style_lines))
        self.assertTrue(hasattr(presets_phone, "INTEGRATION"))

    def test_specification_constants_match_literals(self) -> None:
        """Kunci semua konstanta spesifikasi phone_frame terhadap nilai literal teoretis."""
        assert presets_phone is not None
        self.assertEqual(presets_phone.PHONE_DEFAULT_X_RIGHT, 640.0)
        self.assertEqual(presets_phone.PHONE_DEFAULT_X_LEFT, 60.0)
        self.assertEqual(presets_phone.PHONE_DEFAULT_Y, 250.0)
        self.assertEqual(presets_phone.PHONE_DEFAULT_W, 380.0)
        self.assertEqual(presets_phone.PHONE_BASE_H, 360.0)
        self.assertEqual(presets_phone.PHONE_LINE_ROW_H, 100.0)
        self.assertEqual(presets_phone.PHONE_BODY_RADIUS, 56.0)
        self.assertEqual(presets_phone.PHONE_SCREEN_INSET, 14.0)
        self.assertEqual(presets_phone.PHONE_SCREEN_RADIUS, 44.0)
        self.assertEqual(presets_phone.PHONE_NOTCH_W, 80.0)
        self.assertEqual(presets_phone.PHONE_NOTCH_H, 18.0)
        self.assertEqual(presets_phone.PHONE_NOTCH_RADIUS, 9.0)
        self.assertEqual(presets_phone.PHONE_NOTCH_TOP_MARGIN, 14.0)
        self.assertEqual(presets_phone.PHONE_ENTRY, 0.35)
        self.assertEqual(presets_phone.PHONE_ENTRY_OFFSET, 140.0)
        self.assertEqual(presets_phone.PHONE_EXIT, 0.20)
        self.assertEqual(presets_phone.PHONE_LINE_STAGGER, 0.180)
        self.assertEqual(presets_phone.PHONE_LINE_FADE_IN, 0.120)
        self.assertEqual(presets_phone.PHONE_LINE_OFFSET_Y, 12.0)
        self.assertEqual(presets_phone.PHONE_BULLET_RADIUS, 5.0)
        self.assertEqual(presets_phone.PHONE_BULLET_GAP, 14.0)


class PhonePropsValidationTest(unittest.TestCase):
    """Validasi ketat props overlay phone_frame."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")

    def test_missing_props_rejected(self) -> None:
        item = {"type": "phone_frame", "start": START, "end": END}
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props wajib ada", str(ctx.exception))

    def test_props_not_dict_rejected(self) -> None:
        item = {"type": "phone_frame", "start": START, "end": END, "props": "bad"}
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props harus objek", str(ctx.exception))

    def test_unknown_props_rejected_with_known_keys(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": LINES, "foo": "bar"})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props tidak dikenal: 'foo'", str(ctx.exception))
        self.assertIn("dikenal:", str(ctx.exception))

    def test_title_missing_rejected(self) -> None:
        item = _clip_overlay(props={"lines": LINES})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['title'] wajib ada", str(ctx.exception))

    def test_title_empty_rejected(self) -> None:
        item = _clip_overlay(props={"title": "", "lines": LINES})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['title'] harus 1..22 karakter", str(ctx.exception))

    def test_title_too_long_rejected(self) -> None:
        item = _clip_overlay(props={"title": "A" * 23, "lines": LINES})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['title'] harus 1..22 karakter", str(ctx.exception))

    def test_title_newline_rejected(self) -> None:
        item = _clip_overlay(props={"title": "Line 1\nLine 2", "lines": LINES})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("tidak boleh memuat newline", str(ctx.exception))

    def test_lines_missing_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['lines'] wajib ada", str(ctx.exception))

    def test_lines_not_list_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": "single string"})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['lines'] harus daftar", str(ctx.exception))

    def test_lines_count_less_than_2_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": ["Hanya satu"]})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['lines'] harus 2..4", str(ctx.exception))

    def test_lines_count_greater_than_4_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": ["1", "2", "3", "4", "5"]})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['lines'] harus 2..4", str(ctx.exception))

    def test_line_item_empty_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": ["Baris 1", ""]})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['lines'][1] harus 1..22 karakter", str(ctx.exception))

    def test_line_item_too_long_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": ["Baris 1", "W" * 23]})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['lines'][1] harus 1..22 karakter", str(ctx.exception))

    def test_line_item_newline_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": ["Baris 1", "Baris\n2"]})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("tidak boleh memuat newline", str(ctx.exception))

    def test_accent_invalid_hex_rejected(self) -> None:
        item = _clip_overlay(
            props={"title": TITLE, "lines": LINES, "accent": "yellow"}
        )
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['accent'] harus '#RRGGBB'", str(ctx.exception))

    def test_accent_custom_hex_accepted(self) -> None:
        item = _clip_overlay(
            props={"title": TITLE, "lines": LINES, "accent": "#00FFCC"}
        )
        plan, warnings = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["accent"], "#00FFCC")

    def test_side_invalid_rejected(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": LINES, "side": "top"})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['side'] harus 'right' atau 'left'", str(ctx.exception))

    def test_side_left_sets_left_position(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": LINES, "side": "left"})
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["side"], "left")
        self.assertEqual(plan["rect"]["x"], presets_phone.PHONE_DEFAULT_X_LEFT)
        self.assertEqual(plan["rect"]["x"], 60.0)

    def test_side_right_sets_right_position(self) -> None:
        item = _clip_overlay(props={"title": TITLE, "lines": LINES, "side": "right"})
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["side"], "right")
        self.assertEqual(plan["rect"]["x"], presets_phone.PHONE_DEFAULT_X_RIGHT)
        self.assertEqual(plan["rect"]["x"], 640.0)


class PhoneRectValidationTest(unittest.TestCase):
    """Validasi rect perangkat, kanvas 1080x1920, dan tinggi hand-calculated."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")

    def test_hand_calculated_heights_for_2_3_4_lines(self) -> None:
        """Tinggi perangkat terhitung harus tepat: 560 (2 baris), 660 (3 baris), 760 (4 baris)."""
        for count, expected_h in [(2, 560.0), (3, 660.0), (4, 760.0)]:
            lines = [f"Baris {i+1}" for i in range(count)]
            item = _clip_overlay(props={"title": TITLE, "lines": lines})
            plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
            self.assertIsNotNone(plan)
            assert plan is not None
            self.assertEqual(plan["rect"]["w"], 380.0)
            self.assertEqual(
                plan["rect"]["h"],
                expected_h,
                msg=f"tinggi untuk {count} baris harus {expected_h}, dapat {plan['rect']['h']}",
            )
            # Rasio ponsel 4 baris = 380:760 = 1:2
            if count == 4:
                self.assertAlmostEqual(plan["rect"]["w"] / plan["rect"]["h"], 0.5)

    def test_rect_unknown_keys_rejected(self) -> None:
        item = _clip_overlay(
            rect={"x": 640, "y": 250, "w": 380, "h": 660, "z": 0}
        )
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("rect kunci tidak dikenal: 'z'", str(ctx.exception))

    def test_rect_missing_key_rejected(self) -> None:
        item = _clip_overlay(rect={"x": 640, "y": 250, "w": 380})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("rect['h'] wajib ada", str(ctx.exception))

    def test_rect_negative_or_zero_rejected(self) -> None:
        for w, h in [(-380, 660), (380, 0)]:
            with self.subTest(w=w, h=h):
                item = _clip_overlay(rect={"x": 640, "y": 250, "w": w, "h": h})
                with self.assertRaises(presets.PresetError):
                    presets_phone.build(0, item, CLIP_DUR, fps=FPS)

    def test_rect_outside_canvas_rejected(self) -> None:
        cases = [
            {"x": -10, "y": 250, "w": 380, "h": 660},
            {"x": 640, "y": -5, "w": 380, "h": 660},
            {"x": 750, "y": 250, "w": 380, "h": 660},  # 750+380 = 1130 > 1080
            {"x": 640, "y": 1400, "w": 380, "h": 660},  # 1400+660 = 2060 > 1920
        ]
        for rect in cases:
            with self.subTest(rect=rect):
                item = _clip_overlay(rect=rect)
                with self.assertRaises(presets.PresetError) as ctx:
                    presets_phone.build(0, item, CLIP_DUR, fps=FPS)
                self.assertIn("keluar kanvas 1080x1920", str(ctx.exception))

    def test_rect_h_too_short_raises_preset_error(self) -> None:
        """rect.h lebih pendek dari yang dibutuhkan ditolak, bukan disusutkan diam-diam."""
        # 3 baris butuh h=660. Berikan 600.
        item = _clip_overlay(
            props={"title": TITLE, "lines": LINES},
            rect={"x": 640, "y": 250, "w": 380, "h": 600},
        )
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("tinggi yang dibutuhkan", str(ctx.exception))
        self.assertIn("tidak boleh disusutkan", str(ctx.exception))


class PhoneFontmetricsWidthTest(unittest.TestCase):
    """Pemeriksaan fontmetrics: teks yang tak muat lebar layar ditolak."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")

    def test_title_too_wide_for_screen_rejected(self) -> None:
        # 22 huruf 'W' tebal dalam Archivo Black em 22 melebihi lebar layar tersedia ~296 px
        wide_title = "W" * 22
        item = _clip_overlay(props={"title": wide_title, "lines": LINES})
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['title'] tidak muat", str(ctx.exception))
        self.assertIn("lebar terukur", str(ctx.exception))
        self.assertIn("tersedia", str(ctx.exception))

    def test_line_text_too_wide_for_screen_rejected(self) -> None:
        wide_line = "W" * 22
        item = _clip_overlay(
            props={"title": TITLE, "lines": ["Normal line", wide_line]}
        )
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("props['lines'][1] tidak muat", str(ctx.exception))
        self.assertIn("lebar terukur", str(ctx.exception))
        self.assertIn("tersedia", str(ctx.exception))


class PhoneTimingAndClipWindowTest(unittest.TestCase):
    """Jendela waktu, pemotongan, dan durasi klip."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")

    def test_window_completely_outside_clip_returns_none_and_warning(self) -> None:
        # start >= clip_duration
        item = _clip_overlay(start=4.5, end=6.0)
        plan, warnings = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIsNone(plan)
        self.assertEqual(len(warnings), 1)
        self.assertIn("sepenuhnya di luar durasi klip", warnings[0])

        # end <= 0
        item2 = _clip_overlay(start=-3.0, end=-0.5)
        plan2, warnings2 = presets_phone.build(0, item2, CLIP_DUR, fps=FPS)
        self.assertIsNone(plan2)
        self.assertEqual(len(warnings2), 1)
        self.assertIn("sepenuhnya di luar durasi klip", warnings2[0])

    def test_end_less_than_start_after_clipping_raises_preset_error(self) -> None:
        item = _clip_overlay(start=2.0, end=1.5)
        with self.assertRaises(presets.PresetError) as ctx:
            presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIn("end harus > start", str(ctx.exception))

    def test_window_less_than_one_frame_returns_none_and_warning(self) -> None:
        # start=1.000, end=1.010 pada 30 fps
        item = _clip_overlay(start=1.000, end=1.010)
        plan, warnings = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        self.assertIsNone(plan)
        self.assertEqual(len(warnings), 1)
        self.assertIn("kurang dari satu frame", warnings[0])


class PhoneFontMissingTest(unittest.TestCase):
    """Font hilang atau keluarga salah -> plan=None + peringatan, bukan exception."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")

    def test_missing_font_path_returns_none_and_warning(self) -> None:
        item = _clip_overlay()
        fake_font = Path("/tmp/nonexistent_font_file.ttf")
        plan, warnings = presets_phone.build(
            0, item, CLIP_DUR, fps=FPS, font_path=fake_font
        )
        self.assertIsNone(plan)
        self.assertEqual(len(warnings), 1)
        self.assertIn("dilewati: font", warnings[0])


class PhoneLayerAndDialogueStructureTest(unittest.TestCase):
    """Urutan layer (badan < layar < notch < teks), format 10 field, escape ASS."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")
        self.font = fontmetrics.Font.load(ARCHIVO_FILE)
        self.item = _clip_overlay()
        self.plan, _ = presets_phone.build(0, self.item, CLIP_DUR, fps=FPS)
        assert self.plan is not None
        self.events = presets_phone.events(self.plan, FPS, self.font)

    def test_dialogue_count_within_40(self) -> None:
        self.assertLessEqual(len(self.events), presets_phone.PHONE_MAX_DIALOGUES)
        self.assertLessEqual(len(self.events), 40)
        # 3 baris: 5 shell/header + 2*3 = 11 dialogues
        self.assertEqual(len(self.events), 11)

    def test_all_dialogues_have_10_fields(self) -> None:
        for idx, line in enumerate(self.events):
            with self.subTest(idx=idx):
                fields = _fields(line)
                self.assertEqual(
                    len(fields),
                    10,
                    msg=f"baris {idx} tidak memiliki 10 field: {line}",
                )

    def test_layer_order_body_screen_notch_text(self) -> None:
        """Urutan layer harus badan < layar < notch < teks."""
        roles: dict[str, int] = {}
        for line in self.events:
            fields = _fields(line)
            layer = int(fields[0])
            name = fields[4]
            roles[name] = layer

        self.assertIn("body", roles)
        self.assertIn("screen", roles)
        self.assertIn("notch", roles)
        self.assertIn("title", roles)
        self.assertIn("line_text_0", roles)

        self.assertLess(roles["body"], roles["screen"])
        self.assertLess(roles["screen"], roles["notch"])
        self.assertLess(roles["notch"], roles["title"])
        self.assertLess(roles["notch"], roles["line_text_0"])

    def test_escape_special_characters_in_text(self) -> None:
        item = _clip_overlay(
            props={
                "title": "Title {1} \\ test",
                "lines": ["Line {A} \\ OK", "Line 2"],
            }
        )
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        assert plan is not None
        events = presets_phone.events(plan, FPS, self.font)
        joined = "\n".join(events)
        # { } \ di dalam teks harus di-escape menjadi ( ) /
        self.assertIn("Title (1) / test", joined)
        self.assertIn("Line (A) / OK", joined)
        # Tidak boleh ada kurung kurawal liar di field teks di luar override
        for line in events:
            role = _fields(line)[4]
            if not (role == "title" or role.startswith("line_text_")):
                continue
            text_field = _fields(line)[9]
            # Override ASS berada di awal {...}
            m = re.match(r"^\{[^}]*\}(.*)$", text_field)
            self.assertIsNotNone(m)
            assert m is not None
            content = m.group(1)
            self.assertNotIn("{", content)
            self.assertNotIn("}", content)
            self.assertNotIn("\\", content)

    def test_lines_order_preserved(self) -> None:
        """Urutan baris teks tidak boleh terbalik."""
        item = _clip_overlay(props={"title": TITLE, "lines": LINES})
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        assert plan is not None
        events = presets_phone.events(plan, FPS, self.font)
        for k, text in enumerate(LINES):
            line_evt = next(
                line for line in events if _fields(line)[4] == f"line_text_{k}"
            )
            self.assertTrue(
                _fields(line_evt)[9].endswith(text),
                msg=f"baris {k} teks tidak cocok dengan urutan",
            )

    def test_determinism(self) -> None:
        events1 = presets_phone.events(self.plan, FPS, self.font)
        events2 = presets_phone.events(self.plan, FPS, self.font)
        self.assertEqual(events1, events2)


class PhoneMotionAndTimingTest(unittest.TestCase):
    """Kekakuan slide 140 px, stagger baris 180 ms, fade 120 ms, fade out 0.20 s."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")
        self.font = fontmetrics.Font.load(ARCHIVO_FILE)

    def test_slide_move_tags_have_identical_delta_and_duration(self) -> None:
        """Seluruh elemen header/shell memakai move dengan dx=140, dy=0, durasi 350 ms."""
        item = _clip_overlay(props={"title": TITLE, "lines": LINES, "side": "right"})
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        assert plan is not None
        events = presets_phone.events(plan, FPS, self.font)

        # Elemen shell: body, screen, notch, underline, title
        entry_ms = int(round(presets_phone.PHONE_ENTRY * 1000.0))  # 350
        self.assertEqual(entry_ms, 350)

        for line in events:
            role = _fields(line)[4]
            if role in ("body", "screen", "notch", "underline"):
                text_field = _fields(line)[9]
                # Format: \move(140,0,0,0,0,350)
                self.assertIn(f"\\move(140,0,0,0,0,{entry_ms})", text_field)
            elif role == "title":
                text_field = _fields(line)[9]
                # Title x moves from title_x + 140 to title_x
                m = re.search(
                    r"\\move\(([0-9.]+),([0-9.]+),([0-9.]+),([0-9.]+),0,(\d+)\)",
                    text_field,
                )
                self.assertIsNotNone(m)
                assert m is not None
                x0, y0, x1, y1, t = (
                    float(m.group(1)),
                    float(m.group(2)),
                    float(m.group(3)),
                    float(m.group(4)),
                    int(m.group(5)),
                )
                self.assertAlmostEqual(x0 - x1, 140.0)
                self.assertAlmostEqual(y0, y1)
                self.assertEqual(t, entry_ms)

    def test_slide_move_tags_left_side(self) -> None:
        """side='left' memakai move dengan dx=-140 (dari kiri)."""
        item = _clip_overlay(props={"title": TITLE, "lines": LINES, "side": "left"})
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        assert plan is not None
        events = presets_phone.events(plan, FPS, self.font)
        entry_ms = int(round(presets_phone.PHONE_ENTRY * 1000.0))

        for line in events:
            role = _fields(line)[4]
            if role in ("body", "screen", "notch", "underline"):
                text_field = _fields(line)[9]
                self.assertIn(f"\\move(-140,0,0,0,0,{entry_ms})", text_field)

    def test_line_stagger_and_theoretical_start_frames(self) -> None:
        """Baris-baris muncul berurutan dengan jeda 180 ms pada frame teoretis."""
        self.assertEqual(presets_phone.PHONE_LINE_STAGGER, 0.180)
        item = _clip_overlay(
            start=START, end=END, props={"title": TITLE, "lines": LINES}
        )
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        assert plan is not None
        events = presets_phone.events(plan, FPS, self.font)

        entry_frame = plan["frame_start"] + round(0.35 * FPS)
        for k in range(len(LINES)):
            expected_frame = entry_frame + round(k * 0.180 * FPS)
            expected_start_time = presets._frame_start_time(expected_frame, FPS)
            expected_ass = presets._ass_time(expected_start_time)

            bullet_line = next(
                line
                for line in events
                if _fields(line)[4] == f"line_bullet_{k}"
            )
            text_line = next(
                line
                for line in events
                if _fields(line)[4] == f"line_text_{k}"
            )

            self.assertEqual(_fields(bullet_line)[1], expected_ass)
            self.assertEqual(_fields(text_line)[1], expected_ass)

    def test_line_entry_fade_and_slide_up(self) -> None:
        """Tiap baris mengalami fade-in 120 ms dan geser ke atas 12 px (move dari y+12 ke y)."""
        item = _clip_overlay()
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        assert plan is not None
        events = presets_phone.events(plan, FPS, self.font)

        for k in range(len(LINES)):
            bullet_line = next(
                line
                for line in events
                if _fields(line)[4] == f"line_bullet_{k}"
            )
            text_line = next(
                line
                for line in events
                if _fields(line)[4] == f"line_text_{k}"
            )

            # Bullet shape move: \move(0,12,0,0,0,120) dan alpha fade \1a&HFF&\t(0,120,\1a&H00&)
            self.assertIn("\\move(0,12,0,0,0,120)", _fields(bullet_line)[9])
            self.assertIn("\\1a&HFF&\\t(0,120,", _fields(bullet_line)[9])

            # Text move: y0 - y1 = 12 px
            m = re.search(
                r"\\move\(([0-9.]+),([0-9.]+),([0-9.]+),([0-9.]+),0,120\)",
                _fields(text_line)[9],
            )
            self.assertIsNotNone(m)
            assert m is not None
            y0, y1 = float(m.group(2)), float(m.group(4))
            self.assertAlmostEqual(y0 - y1, 12.0)
            self.assertIn("\\alpha&HFF&\\t(0,120,\\alpha&H00&)", _fields(text_line)[9])

    def test_exit_fade_tags_present(self) -> None:
        """Seluruh elemen memiliki tag fade keluar ke &HFF& selama EXIT (0.20 s)."""
        self.assertEqual(presets_phone.PHONE_EXIT, 0.20)
        item = _clip_overlay()
        plan, _ = presets_phone.build(0, item, CLIP_DUR, fps=FPS)
        assert plan is not None
        events = presets_phone.events(plan, FPS, self.font)

        exit_ms = round(presets_phone.PHONE_EXIT * 1000)  # 200 ms
        for line in events:
            text_field = _fields(line)[9]
            m = re.search(r"\\t\((\d+),(\d+),\\(?:alpha|1a)&HFF&\)", text_field)
            self.assertIsNotNone(
                m,
                msg=f"event tidak memiliki tag fade keluar \\t(t0,t1,\\alpha&HFF&): {line}",
            )
            assert m is not None
            t0, t1 = int(m.group(1)), int(m.group(2))
            self.assertAlmostEqual(
                t1 - t0,
                exit_ms,
                delta=1,
                msg=f"durasi fade keluar {t1-t0} ms vs {exit_ms} ms pada {line}",
            )


class PhoneIntegrationHooksTest(unittest.TestCase):
    """Pemeriksaan INTEGRATION: hook yang dinyatakan harus benar-benar ada di presets.py."""

    def setUp(self) -> None:
        if presets_phone is None:
            self.skipTest("presets_phone belum ada")

    def test_integration_hooks_exist_on_presets(self) -> None:
        integration = presets_phone.INTEGRATION
        self.assertIsInstance(integration, dict)
        self.assertGreaterEqual(len(integration), 3)
        self.assertLessEqual(len(integration), 5)

        for hook_name in integration:
            self.assertTrue(
                hasattr(presets, hook_name),
                msg=f"hook '{hook_name}' tidak ditemukan di `scripts.presets`",
            )


if __name__ == "__main__":
    unittest.main()
