"""Tes unit murni untuk scripts/pullback.py (Langkah 5b-6).

Menguji:
1. Validasi props ketat (from, to, decimals, suffix, label, title, window, shrink, grow, count).
2. Validasi window (kanvas, rasio 9:16, batas area angka).
3. Batasan durasi (shrink + count + grow <= window durasi).
4. Penanganan multi-overlay (<=3 non-overlapping, tolak tumpang tindih, tolak >3).
5. Klip duration clamping dan skipping overlay di luar klip dengan peringatan.
6. Kurva easing smoothstep (p*p*(3-2p)), monoton, skala target tepat.
7. Filter graph parser dan label (in_label, out_label, escaping).
8. Generator dokumen ASS (count-up bertingkat, batas <=40 Dialogue, format decimals, sudut membulat).
9. Perilaku font hilang -> (None, [peringatan]).
10. Determinisme keluaran.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path
from typing import Any

from scripts import pullback
from scripts.pullback import (
    PullbackError,
    ALLOWED_PROPS,
    NUMBER_AREA_BOTTOM,
    DEFAULT_WINDOW,
    DEFAULT_SHRINK,
    DEFAULT_GROW,
    DEFAULT_COUNT,
    CREAM_HEX,
    DARK_HEX,
    build,
    filter_graph,
    ass,
    _smoothstep,
    _format_number,
)


class PullbackErrorTypeTest(unittest.TestCase):
    def test_pullback_error_is_subclass_of_value_error(self):
        self.assertTrue(issubclass(PullbackError, ValueError))
        err = PullbackError("pesan galat")
        self.assertIsInstance(err, ValueError)


class PropsValidationTest(unittest.TestCase):
    def setUp(self):
        self.clip = {
            "id": "clip_test",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "overlays": [
                {
                    "type": "pullback",
                    "start": 1.0,
                    "end": 7.0,
                    "props": {
                        "from": 0,
                        "to": 100,
                    },
                }
            ],
        }

    def test_valid_minimal_props(self):
        plan, warnings = build(self.clip, fps=30.0)
        self.assertIsNotNone(plan)
        self.assertEqual(warnings, [])
        self.assertEqual(len(plan["overlays"]), 1)
        ov = plan["overlays"][0]
        self.assertEqual(ov["props"]["from"], 0.0)
        self.assertEqual(ov["props"]["to"], 100.0)
        self.assertEqual(ov["props"]["decimals"], 0)
        self.assertEqual(ov["props"]["suffix"], "")
        self.assertEqual(ov["props"]["label"], "")
        self.assertEqual(ov["props"]["title"], "")
        # Kunci dengan angka literal dari spesifikasi
        self.assertEqual(ov["props"]["shrink"], 0.6)
        self.assertEqual(ov["props"]["grow"], 0.5)
        self.assertEqual(ov["props"]["count"], 1.2)
        self.assertEqual(
            ov["props"]["window"],
            {"x": 216.0, "y": 640.0, "w": 648.0, "h": 1152.0},
        )
        self.assertEqual(ov["props"]["shrink"], DEFAULT_SHRINK)
        self.assertEqual(ov["props"]["grow"], DEFAULT_GROW)
        self.assertEqual(ov["props"]["count"], DEFAULT_COUNT)
        self.assertEqual(ov["props"]["window"], DEFAULT_WINDOW)

    def test_missing_from_raises_error(self):
        self.clip["overlays"][0]["props"] = {"to": 100}
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        self.assertIn("overlay[0]", str(ctx.exception))
        self.assertIn("from", str(ctx.exception).lower())

    def test_missing_to_raises_error(self):
        self.clip["overlays"][0]["props"] = {"from": 0}
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        self.assertIn("overlay[0]", str(ctx.exception))
        self.assertIn("to", str(ctx.exception).lower())

    def test_from_equal_to_raises_error(self):
        self.clip["overlays"][0]["props"] = {"from": 50, "to": 50}
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        self.assertIn("overlay[0]", str(ctx.exception))
        self.assertIn("to", str(ctx.exception).lower())

    def test_non_finite_from_to_raises_error(self):
        for bad_val in (float("nan"), float("inf"), float("-inf"), "100", True, None):
            self.clip["overlays"][0]["props"] = {"from": bad_val, "to": 100}
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("from", str(ctx.exception).lower())

            self.clip["overlays"][0]["props"] = {"from": 0, "to": bad_val}
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("to", str(ctx.exception).lower())

    def test_unknown_props_key_raises_error_with_allowed_list(self):
        self.clip["overlays"][0]["props"]["bogus_prop"] = 42
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        msg = str(ctx.exception)
        self.assertIn("overlay[0]", msg)
        self.assertIn("bogus_prop", msg)
        for key in ("from", "to", "window", "shrink", "grow", "count"):
            self.assertIn(key, msg)

    def test_decimals_validation(self):
        for valid_dec in (0, 1, 2):
            self.clip["overlays"][0]["props"]["decimals"] = valid_dec
            plan, _ = build(self.clip, fps=30.0)
            self.assertEqual(plan["overlays"][0]["props"]["decimals"], valid_dec)

        for bad_dec in (-1, 3, 1.5, "1", True, None):
            self.clip["overlays"][0]["props"]["decimals"] = bad_dec
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("decimals", str(ctx.exception).lower())

    def test_suffix_validation(self):
        for valid_suf in ("", "%", "K", "X", "+20%"):
            self.clip["overlays"][0]["props"]["suffix"] = valid_suf
            plan, _ = build(self.clip, fps=30.0)
            self.assertEqual(plan["overlays"][0]["props"]["suffix"], valid_suf)

        for bad_suf in ("TOOLONG", "A\nB", 123, None):
            self.clip["overlays"][0]["props"]["suffix"] = bad_suf
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("suffix", str(ctx.exception).lower())

    def test_label_and_title_validation(self):
        for valid_str in ("", "Test Label", "A" * 28):
            self.clip["overlays"][0]["props"]["label"] = valid_str
            self.clip["overlays"][0]["props"]["title"] = valid_str
            plan, _ = build(self.clip, fps=30.0)
            self.assertEqual(plan["overlays"][0]["props"]["label"], valid_str)
            self.assertEqual(plan["overlays"][0]["props"]["title"], valid_str)

        for bad_str in ("A" * 29, "New\nline", 123, None):
            self.clip["overlays"][0]["props"]["label"] = bad_str
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("label", str(ctx.exception).lower())

            self.clip["overlays"][0]["props"]["label"] = ""
            self.clip["overlays"][0]["props"]["title"] = bad_str
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("title", str(ctx.exception).lower())


class WindowValidationTest(unittest.TestCase):
    def setUp(self):
        self.clip = {
            "id": "clip_win",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "overlays": [
                {
                    "type": "pullback",
                    "start": 1.0,
                    "end": 7.0,
                    "props": {"from": 0, "to": 100},
                }
            ],
        }

    def test_custom_valid_window(self):
        # 540x960 centered: x=(1080-540)/2=270, y=700 (below 600, y+h=1660<=1920)
        self.clip["overlays"][0]["props"]["window"] = {"x": 270, "y": 700, "w": 540}
        plan, _ = build(self.clip, fps=30.0)
        win = plan["overlays"][0]["props"]["window"]
        self.assertEqual(win["x"], 270.0)
        self.assertEqual(win["y"], 700.0)
        self.assertEqual(win["w"], 540.0)
        self.assertEqual(win["h"], 960.0)

    def test_window_aspect_ratio_not_9_16_raises_error(self):
        self.clip["overlays"][0]["props"]["window"] = {
            "x": 216,
            "y": 640,
            "w": 648,
            "h": 1000,  # not 648 * 16 / 9 = 1152
        }
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        self.assertIn("window", str(ctx.exception).lower())
        self.assertIn("9:16", str(ctx.exception).lower())

    def test_window_outside_canvas_raises_error(self):
        # x < 0
        self.clip["overlays"][0]["props"]["window"] = {"x": -10, "y": 640, "w": 648}
        with self.assertRaises(PullbackError):
            build(self.clip, fps=30.0)

        # x + w > 1080
        self.clip["overlays"][0]["props"]["window"] = {"x": 500, "y": 640, "w": 648}
        with self.assertRaises(PullbackError):
            build(self.clip, fps=30.0)

        # y + h > 1920
        self.clip["overlays"][0]["props"]["window"] = {"x": 216, "y": 800, "w": 648}
        with self.assertRaises(PullbackError):
            build(self.clip, fps=30.0)

        # w <= 0
        self.clip["overlays"][0]["props"]["window"] = {"x": 216, "y": 640, "w": 0}
        with self.assertRaises(PullbackError):
            build(self.clip, fps=30.0)

    def test_window_overlaps_number_area_raises_error(self):
        # Angka literal: batas bawah area angka adalah 600.0.
        # y < 600.0 harus ditolak dengan PullbackError.
        for bad_y in (599.0, 599.9, 400.0, 0.0):
            self.clip["overlays"][0]["props"]["window"] = {
                "x": 216,
                "y": bad_y,
                "w": 648,
            }
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("area angka", str(ctx.exception).lower())

        # y == 600.0 berada tepat di batas bawah dan diterima
        self.clip["overlays"][0]["props"]["window"] = {
            "x": 216,
            "y": 600.0,
            "w": 648,
        }
        plan, _ = build(self.clip, fps=30.0)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["overlays"][0]["props"]["window"]["y"], 600.0)


class TimingAndMultiOverlayTest(unittest.TestCase):
    def setUp(self):
        self.clip = {
            "id": "clip_time",
            "segments": [{"src_start": 0.0, "src_end": 15.0}],
            "overlays": [
                {
                    "type": "pullback",
                    "start": 1.0,
                    "end": 6.0,
                    "props": {"from": 0, "to": 100},
                }
            ],
        }

    def test_shrink_grow_count_ranges(self):
        # Default total: 0.6 + 1.2 + 0.5 = 2.3s <= 5.0s
        plan, _ = build(self.clip, fps=30.0)
        self.assertIsNotNone(plan)

        # Valid custom
        self.clip["overlays"][0]["props"].update({
            "shrink": 0.3,
            "grow": 0.3,
            "count": 0.4,
        })
        plan, _ = build(self.clip, fps=30.0)
        self.assertIsNotNone(plan)

        # Out of bounds shrink
        for bad in (0.2, 1.3):
            self.clip["overlays"][0]["props"]["shrink"] = bad
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("shrink", str(ctx.exception).lower())
        self.clip["overlays"][0]["props"]["shrink"] = 0.6

        # Out of bounds grow
        for bad in (0.2, 1.3):
            self.clip["overlays"][0]["props"]["grow"] = bad
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("grow", str(ctx.exception).lower())
        self.clip["overlays"][0]["props"]["grow"] = 0.5

        # Out of bounds count
        for bad in (0.3, 3.1):
            self.clip["overlays"][0]["props"]["count"] = bad
            with self.assertRaises(PullbackError) as ctx:
                build(self.clip, fps=30.0)
            self.assertIn("count", str(ctx.exception).lower())

    def test_duration_too_short_for_total_phases_raises_error(self):
        # overlay duration = 2.0s, but shrink(0.6) + count(1.2) + grow(0.5) = 2.3s
        self.clip["overlays"][0]["start"] = 1.0
        self.clip["overlays"][0]["end"] = 3.0
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        self.assertIn("tidak muat", str(ctx.exception).lower())

    def test_overlay_outside_clip_is_skipped_with_warning(self):
        # Clip duration is 15s. Overlay is at 16s..20s
        self.clip["overlays"][0]["start"] = 16.0
        self.clip["overlays"][0]["end"] = 20.0
        plan, warnings = build(self.clip, fps=30.0)
        self.assertIsNone(plan)
        self.assertEqual(len(warnings), 1)
        self.assertIn("di luar", warnings[0].lower())

    def test_overlay_clamped_to_clip_duration(self):
        # Overlay starts at 10.0 and ends at 17.0 on 15.0s clip
        # Clamped end = 15.0. Duration = 5.0s >= 2.3s -> accepted
        self.clip["overlays"][0]["start"] = 10.0
        self.clip["overlays"][0]["end"] = 17.0
        plan, warnings = build(self.clip, fps=30.0)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["overlays"][0]["end"], 15.0)

    def test_multiple_non_overlapping_overlays_allowed_up_to_3(self):
        self.clip["overlays"] = [
            {"type": "pullback", "start": 0.5, "end": 4.0, "props": {"from": 0, "to": 10}},
            {"type": "pullback", "start": 5.0, "end": 8.5, "props": {"from": 10, "to": 20}},
            {"type": "pullback", "start": 9.5, "end": 14.0, "props": {"from": 20, "to": 30}},
        ]
        plan, warnings = build(self.clip, fps=30.0)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["overlays"]), 3)
        self.assertEqual(warnings, [])

    def test_more_than_3_overlays_raises_error(self):
        self.clip["overlays"] = [
            {"type": "pullback", "start": 0.5, "end": 3.0, "props": {"from": 0, "to": 10}},
            {"type": "pullback", "start": 3.5, "end": 6.0, "props": {"from": 10, "to": 20}},
            {"type": "pullback", "start": 6.5, "end": 9.0, "props": {"from": 20, "to": 30}},
            {"type": "pullback", "start": 9.5, "end": 12.0, "props": {"from": 30, "to": 40}},
        ]
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        self.assertIn("maksimum 3", str(ctx.exception).lower())

    def test_overlapping_overlays_raises_error(self):
        self.clip["overlays"] = [
            {"type": "pullback", "start": 1.0, "end": 6.0, "props": {"from": 0, "to": 10}},
            {"type": "pullback", "start": 5.0, "end": 9.0, "props": {"from": 10, "to": 20}},
        ]
        with self.assertRaises(PullbackError) as ctx:
            build(self.clip, fps=30.0)
        self.assertIn("tumpang tindih", str(ctx.exception).lower())


class EasingAndMathTest(unittest.TestCase):
    def test_smoothstep_curve_properties(self):
        # Monotonic, p(0)=0, p(1)=1
        self.assertAlmostEqual(_smoothstep(0.0), 0.0)
        self.assertAlmostEqual(_smoothstep(1.0), 1.0)
        self.assertAlmostEqual(_smoothstep(0.5), 0.5)

        # Monotonicity check
        prev = -1.0
        for i in range(101):
            p = i / 100.0
            val = _smoothstep(p)
            self.assertGreaterEqual(val, prev)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)
            prev = val

        # Derivative zero at endpoints: test near endpoints
        # At p=0.01: smoothstep is 3*(0.01)^2 - 2*(0.01)^3 = 0.000298 << 0.01 (linear)
        self.assertLess(_smoothstep(0.05), 0.05)
        # At p=0.95: smoothstep is 1 - 0.007125 > 0.95 (linear)
        self.assertGreater(_smoothstep(0.95), 0.95)

    def test_format_number(self):
        self.assertEqual(_format_number(42.0, 0), "42")
        self.assertEqual(_format_number(42.456, 1), "42.5")
        self.assertEqual(_format_number(42.456, 2), "42.46")
        self.assertEqual(_format_number(0.0, 0), "0")


class FilterGraphTest(unittest.TestCase):
    def setUp(self):
        self.clip = {
            "id": "clip_fg",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "overlays": [
                {
                    "type": "pullback",
                    "start": 2.0,
                    "end": 8.0,
                    "props": {
                        "from": 0,
                        "to": 100,
                        "shrink": 0.6,
                        "grow": 0.5,
                        "count": 1.2,
                    },
                }
            ],
        }

    def test_filter_graph_contains_in_and_out_labels(self):
        plan, _ = build(self.clip, fps=30.0)
        fg = filter_graph(plan, in_label="v1", out_label="vpb", fps=30.0)
        self.assertIsInstance(fg, list)
        joined = ";".join(fg)
        self.assertIn("[v1]", joined)
        self.assertIn("[vpb]", joined)
        self.assertIn(CREAM_HEX, joined)
        self.assertIn("scale=", joined)
        self.assertIn("overlay=", joined)

    def test_filter_graph_escaping_and_syntax(self):
        plan, _ = build(self.clip, fps=30.0)
        fg = filter_graph(plan, in_label="in", out_label="out", fps=30.0)
        for part in fg:
            # Check bracket balance
            self.assertEqual(part.count("["), part.count("]"))
            # Check quote balance
            self.assertEqual(part.count("'") % 2, 0)
            self.assertNotIn("\n", part)
            self.assertNotIn("\r", part)


class ASSDocumentTest(unittest.TestCase):
    def setUp(self):
        self.clip = {
            "id": "clip_ass",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "overlays": [
                {
                    "type": "pullback",
                    "start": 2.0,
                    "end": 8.0,
                    "props": {
                        "from": 0,
                        "to": 100,
                        "suffix": "%",
                        "title": "STATISTIK",
                        "label": "Tingkat Keberhasilan",
                        "decimals": 0,
                        "shrink": 0.6,
                        "grow": 0.5,
                        "count": 1.2,
                    },
                }
            ],
        }

    def test_ass_generates_valid_document_under_40_dialogues(self):
        plan, _ = build(self.clip, fps=30.0)
        doc, warnings = ass(plan, fps=30.0)
        self.assertIsNotNone(doc)
        self.assertEqual(warnings, [])
        self.assertIn("[Script Info]", doc)
        self.assertIn("[V4+ Styles]", doc)
        self.assertIn("[Events]", doc)
        self.assertIn("Archivo Black", doc)

        dialogues = [line for line in doc.splitlines() if line.startswith("Dialogue:")]
        self.assertGreater(len(dialogues), 5)
        self.assertLessEqual(len(dialogues), 40)

        # Check title and label
        self.assertTrue(any("STATISTIK" in d for d in dialogues))
        self.assertTrue(any("Tingkat Keberhasilan" in d for d in dialogues))

        # Check last count-up value is exact `to` with suffix
        # The last dialogue for number should have "100" and "%"
        number_dialogues = [d for d in dialogues if "%" in d]
        self.assertGreater(len(number_dialogues), 1)
        self.assertIn("100", number_dialogues[-1])

    def test_ass_missing_font_returns_none_with_warning(self):
        plan, _ = build(self.clip, fps=30.0, font_path="/nonexistent/font.ttf")
        doc, warnings = ass(plan, fps=30.0)
        self.assertIsNone(doc)
        self.assertEqual(len(warnings), 1)
        self.assertIn("font", warnings[0].lower())

    def test_determinism_output_is_identical(self):
        plan1, w1 = build(self.clip, fps=30.0)
        plan2, w2 = build(self.clip, fps=30.0)
        self.assertEqual(plan1, plan2)
        self.assertEqual(w1, w2)

        fg1 = filter_graph(plan1, in_label="v1", out_label="vpb", fps=30.0)
        fg2 = filter_graph(plan2, in_label="v1", out_label="vpb", fps=30.0)
        self.assertEqual(fg1, fg2)

        doc1, _ = ass(plan1, fps=30.0)
        doc2, _ = ass(plan2, fps=30.0)
        self.assertEqual(doc1, doc2)


def _dialogues(ass_doc: str) -> list[str]:
    return [line for line in ass_doc.splitlines() if line.startswith("Dialogue:")]


def _fields(dialogue_line: str) -> list[str]:
    assert dialogue_line.startswith("Dialogue:")
    return dialogue_line[len("Dialogue:"):].strip().split(",", 9)


class LiteralDefaultsSpecificationTest(unittest.TestCase):
    def test_literal_constants_match_specification(self):
        self.assertEqual(pullback.CORNER_RADIUS, 36.0)
        self.assertEqual(pullback.DEFAULT_GROW, 0.5)
        self.assertEqual(pullback.DEFAULT_SHRINK, 0.6)
        self.assertEqual(pullback.DEFAULT_COUNT, 1.2)
        self.assertEqual(pullback.NUMBER_AREA_BOTTOM, 600.0)
        self.assertEqual(pullback.DARK_HEX, "#1B1B1F")
        self.assertEqual(pullback.DARK_ASS_COLOR, "&H001F1B1B&")
        self.assertEqual(
            pullback.DEFAULT_WINDOW,
            {"x": 216.0, "y": 640.0, "w": 648.0, "h": 1152.0},
        )


class UIEventTimingAndFadeTest(unittest.TestCase):
    def setUp(self):
        # Clip dengan waktu eksplisit: start=2.0s, end=8.0s, shrink=0.6s, count=1.2s, grow=0.5s @30fps
        # t_shrink_end = 2.0 + 0.6 = 2.6s -> frame index 78 -> _frame_start_time(78, 30.0) = 2.57s -> "0:00:02.57"
        # t_grow_start = 8.0 - 0.5 = 7.5s -> frame index 225 -> _frame_start_time(225, 30.0) = 7.47s -> "0:00:07.47"
        self.clip = {
            "id": "clip_timing",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "overlays": [
                {
                    "type": "pullback",
                    "start": 2.0,
                    "end": 8.0,
                    "props": {
                        "from": 12,
                        "to": 88,
                        "suffix": "%",
                        "title": "NAIK SEJAK 2019",
                        "label": "2019",
                        "shrink": 0.6,
                        "grow": 0.5,
                        "count": 1.2,
                    },
                }
            ],
        }

    def test_all_ui_events_strictly_within_stable_phase_with_fade(self):
        plan, _ = build(self.clip, fps=30.0)
        doc, _ = ass(plan, fps=30.0)
        self.assertIsNotNone(doc)
        dialogues = _dialogues(doc)
        self.assertGreater(len(dialogues), 0)

        # Angka tangan yang dihitung manual dari rumus sentidetik frame:
        expected_stable_start = "0:00:02.57"
        expected_stable_end = "0:00:07.47"

        # 1. SEMUA event UI harus mulai >= expected_stable_start dan berakhir <= expected_stable_end
        # Tidak ada event UI yang menyentuh jendela shrink [2.0, 2.6) atau grow [7.5, 8.0]
        for line in dialogues:
            f = _fields(line)
            start_str = f[1]
            end_str = f[2]
            self.assertGreaterEqual(
                start_str, expected_stable_start,
                f"Event UI mulai sebelum shrink selesai ({start_str} < {expected_stable_start}): {line}"
            )
            self.assertLessEqual(
                end_str, expected_stable_end,
                f"Event UI berakhir sesudah grow mulai ({end_str} > {expected_stable_end}): {line}"
            )

        # 2. Judul, label, hiasan header (garis & dots), dan sudut membulat
        # harus mulai TEPAT di expected_stable_start dan berakhir TEPAT di expected_stable_end,
        # serta memuat fade-in dan fade-out 120 ms (\fad(120,120)).
        title_lines = [d for d in dialogues if "NAIK SEJAK 2019" in d]
        self.assertEqual(len(title_lines), 1)
        f_title = _fields(title_lines[0])
        self.assertEqual(f_title[1], expected_stable_start)
        self.assertEqual(f_title[2], expected_stable_end)
        self.assertIn(r"\fad(120,120)", f_title[9])

        label_lines = [d for d in dialogues if "2019" in d and "NAIK SEJAK" not in d]
        self.assertEqual(len(label_lines), 1)
        f_label = _fields(label_lines[0])
        self.assertEqual(f_label[1], expected_stable_start)
        self.assertEqual(f_label[2], expected_stable_end)
        self.assertIn(r"\fad(120,120)", f_label[9])

        shape_lines = [d for d in dialogues if "Shape" in d]
        self.assertGreaterEqual(len(shape_lines), 3)  # garis header, dots, corner caps
        for s_line in shape_lines:
            f_s = _fields(s_line)
            self.assertEqual(f_s[1], expected_stable_start)
            self.assertEqual(f_s[2], expected_stable_end)
            self.assertIn(r"\fad(120,120)", f_s[9])

        # 3. Angka count-up:
        # Step pertama mulai di expected_stable_start dengan alpha FF (transparan)
        number_lines = [d for d in dialogues if "%" in d]
        self.assertGreater(len(number_lines), 5)
        f_num_first = _fields(number_lines[0])
        self.assertEqual(f_num_first[1], expected_stable_start)
        self.assertIn(r"\alpha&HFF&", f_num_first[9])

        # Step hold (terakhir) berakhir di expected_stable_end dengan fade-out 120 ms
        f_num_last = _fields(number_lines[-1])
        self.assertEqual(f_num_last[2], expected_stable_end)
        self.assertIn("88", f_num_last[9])
        self.assertIn(r"\fad(0,120)", f_num_last[9])

    def test_short_stable_duration_fade_adaptation(self):
        # Saat fase stabil < 0.3s (misal 0.2s), fade disesuaikan (<= 0.2 * 0.4 * 1000 = 80ms)
        ov = {
            "index": 0,
            "start": 1.0,
            "end": 2.2,
            "duration": 1.2,
            "props": {
                "from": 0,
                "to": 10,
                "decimals": 0,
                "suffix": "",
                "title": "T",
                "label": "L",
                "shrink": 0.5,
                "grow": 0.5,
                "count": 0.2,  # stable_duration = 1.2 - 0.5 - 0.5 = 0.2s < 0.3s
                "window": dict(pullback.DEFAULT_WINDOW),
            },
        }
        plan = {
            "clip_id": "test",
            "clip_duration": 5.0,
            "overlays": [ov],
            "font_path": pullback.DEFAULT_FONT_PATH,
        }
        doc, _ = ass(plan, fps=30.0)
        self.assertIsNotNone(doc)
        dialogues = _dialogues(doc)
        title_lines = [d for d in dialogues if r"{\fad(" in d and "T" in d]
        self.assertEqual(len(title_lines), 1)
        # fade 80 ms, bukan 120 ms
        self.assertIn(r"\fad(80,80)", title_lines[0])


if __name__ == "__main__":
    unittest.main()
