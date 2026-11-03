"""Tes `scripts.layout` — geometri layout sadar wajah (murni, tanpa ffmpeg).

Semua koordinat di sini adalah piksel keluaran 1080x1920 SEBELUM punch.
Tidak ada font, OpenCV, ffmpeg, atau berkas EDL yang dibaca: modul yang diuji
fungsi murni atas kamus/dataclass.

Dua hal yang sengaja dikunci tes:

1. **Semantik punch = semantik `motion.zoompan_filter`.** Ekspresi ffmpeg
   hanya berubah pada indeks frame `round(t_i * fps)` dan TIDAK punya ramp
   nilai; "ramp" satu-satunya adalah langkah keras di batas frame. Tes
   membandingkan langsung dengan `motion.zoom_expression`, bukan dengan tebakan.
2. **Caption tidak pernah dibuang.** Bila semua kandidat memotong wajah,
   caption tetap ada: diperkecil 15% di kandidat pertama, lalu kandidat dengan
   irisan terkecil dipilih.

Batas skema: `schema/edl.schema.json` versi sekarang hanya mendeklarasikan
`layout.version` dan `layout.caption[]` dengan kunci `t/an/y/x/size` (tanpa
`scale`/`reason`, dan tanpa `layout.overlays`). Keluaran 4a sengaja LEBIH kaya
(`scale`, `reason`, `overlays`) karena integrasi 4b belum boleh mengubah skema.
Tes bentuk di bawah memvalidasi subset yang dideklarasikan (kunci wajib + tipe)
dan mencatat tambahan itu secara eksplisit; lihat laporan tugas.
"""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from scripts import layout, motion

CANVAS_W = 1080.0
CANVAS_H = 1920.0
LINE_H = 96.6          # 1,15 em x 84 px (kinetic.LINE_HEIGHT_EM x em)
TWO_LINE_H = 2 * LINE_H


def _t(rect: layout.Rect) -> tuple[float, float, float, float]:
    return (rect.x, rect.y, rect.w, rect.h)


def _intersects_any(rect: layout.Rect, others: list[layout.Rect]) -> bool:
    return any(rect.intersects(other) for other in others)


def _assert_rect_almost(
    test: unittest.TestCase,
    got: layout.Rect,
    want: tuple[float, float, float, float],
    places: int = 6,
    msg: str | None = None,
) -> None:
    test.assertAlmostEqual(got.x, want[0], places=places, msg=msg)
    test.assertAlmostEqual(got.y, want[1], places=places, msg=msg)
    test.assertAlmostEqual(got.w, want[2], places=places, msg=msg)
    test.assertAlmostEqual(got.h, want[3], places=places, msg=msg)


class RectTest(unittest.TestCase):
    def test_fields_and_overlap(self) -> None:
        a = layout.Rect(0.0, 0.0, 100.0, 100.0)
        self.assertEqual(_t(a), (0.0, 0.0, 100.0, 100.0))
        self.assertTrue(a.intersects(layout.Rect(50.0, 50.0, 100.0, 100.0)))
        self.assertFalse(a.intersects(layout.Rect(100.0, 0.0, 10.0, 10.0)),
                         "tepi yang hanya bersentuhan bukan irisan piksel")
        self.assertFalse(a.intersects(layout.Rect(200.0, 200.0, 10.0, 10.0)))

    def test_intersection_area_exact(self) -> None:
        a = layout.Rect(0.0, 0.0, 100.0, 100.0)
        self.assertEqual(a.intersection_area(layout.Rect(50.0, 50.0, 100.0, 100.0)), 2500.0)
        self.assertEqual(a.intersection_area(layout.Rect(100.0, 0.0, 10.0, 10.0)), 0.0)
        self.assertEqual(
            a.intersection_area(layout.Rect(25.0, 10.0, 50.0, 20.0)), 1000.0
        )

    def test_contains_is_inclusive(self) -> None:
        outer = layout.Rect(0.0, 0.0, 100.0, 100.0)
        self.assertTrue(outer.contains(layout.Rect(0.0, 0.0, 100.0, 100.0)))
        self.assertTrue(outer.contains(layout.Rect(10.0, 10.0, 50.0, 50.0)))
        self.assertFalse(outer.contains(layout.Rect(90.0, 90.0, 50.0, 50.0)))

    def test_inflated_is_total_fraction(self) -> None:
        """`inflated(0,08)` memperbesar total 8% (4% tiap sisi), bukan 16%."""
        r = layout.Rect(100.0, 200.0, 200.0, 100.0).inflated(0.08)
        self.assertEqual(_t(r), (92.0, 196.0, 216.0, 108.0))

    def test_scaled_about_center_exact(self) -> None:
        r = layout.Rect(92.0, 196.0, 216.0, 108.0)
        _assert_rect_almost(
            self, r.scaled_about(540.0, 960.0, 1.14),
            (29.28, 89.04, 246.24, 123.12),
        )
        _assert_rect_almost(
            self, r.scaled_about(540.0, 960.0, 1.20),
            (2.4, 43.2, 259.2, 129.6),
        )

    def test_union_bbox(self) -> None:
        a = layout.Rect(0.0, 0.0, 100.0, 100.0)
        b = layout.Rect(50.0, 50.0, 100.0, 100.0)
        self.assertEqual(_t(a.union_bbox(b)), (0.0, 0.0, 150.0, 150.0))
        self.assertEqual(_t(b.union_bbox(a)), (0.0, 0.0, 150.0, 150.0))

    def test_validation_raises_named_value_error(self) -> None:
        bad = [
            (0.0, 0.0, 0.0, 10.0),
            (0.0, 0.0, 10.0, 0.0),
            (0.0, 0.0, -1.0, 10.0),
            (0.0, 0.0, float("inf"), 10.0),
            (float("nan"), 0.0, 10.0, 10.0),
            (0.0, float("inf"), 10.0, 10.0),
        ]
        for x, y, w, h in bad:
            with self.assertRaises(layout.LayoutError, msg=f"Rect({x},{y},{w},{h})") as ctx:
                layout.Rect(x, y, w, h)
            self.assertIsInstance(ctx.exception, ValueError)
            self.assertEqual(type(ctx.exception).__name__, "LayoutError")
            self.assertTrue(str(ctx.exception), "pesan error tidak boleh kosong")

    def test_inflate_and_scale_validation(self) -> None:
        r = layout.Rect(0.0, 0.0, 10.0, 10.0)
        with self.assertRaises(layout.LayoutError):
            r.inflated(-1.0)
        with self.assertRaises(layout.LayoutError):
            r.inflated(float("nan"))
        with self.assertRaises(layout.LayoutError):
            r.scaled_about(540.0, 960.0, 0.0)
        with self.assertRaises(layout.LayoutError):
            r.scaled_about(540.0, 960.0, float("inf"))

    def test_frozen(self) -> None:
        r = layout.Rect(0.0, 0.0, 10.0, 10.0)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            r.x = 5.0  # type: ignore[misc]


class ShotsTest(unittest.TestCase):
    def test_two_shots_one_without_faces(self) -> None:
        track = [
            {"t": 0.0, "faces": [{"x": 10.0, "y": 20.0, "w": 100.0, "h": 120.0}]},
            {"t": 2.0, "faces": []},
            {"t": 4.0, "faces": [
                {"x": 0.0, "y": 0.0, "w": 50.0, "h": 60.0},
                {"x": 500.0, "y": 700.0, "w": 200.0, "h": 240.0},
            ]},
        ]
        got = layout.shots(track, 6.0)
        self.assertEqual([(t0, t1) for t0, t1, _ in got], [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)])
        self.assertEqual(_t(got[0][2][0]), (10.0, 20.0, 100.0, 120.0))
        self.assertEqual(got[1][2], [])
        self.assertEqual([_t(r) for r in got[2][2]],
                         [(0.0, 0.0, 50.0, 60.0), (500.0, 700.0, 200.0, 240.0)])

    def test_empty_track(self) -> None:
        self.assertEqual(layout.shots(None, 5.0), [])
        self.assertEqual(layout.shots([], 5.0), [])

    def test_non_monotonic_rejected(self) -> None:
        track = [{"t": 0.0, "faces": []}, {"t": 2.0, "faces": []},
                 {"t": 1.0, "faces": []}]
        with self.assertRaises(layout.LayoutError) as ctx:
            layout.shots(track, 4.0)
        self.assertIn("monoton", str(ctx.exception).lower())

    def test_duplicate_time_rejected(self) -> None:
        track = [{"t": 1.0, "faces": []}, {"t": 1.0, "faces": []}]
        with self.assertRaises(layout.LayoutError):
            layout.shots(track, 4.0)

    def test_time_outside_clip_rejected(self) -> None:
        for t in (-0.1, 4.1):
            with self.assertRaises(layout.LayoutError, msg=f"t={t}"):
                layout.shots([{"t": t, "faces": []}], 4.0)

    def test_duration_must_be_positive_and_finite(self) -> None:
        for duration in (0.0, -1.0, float("inf"), float("nan")):
            with self.assertRaises(layout.LayoutError, msg=f"duration={duration}"):
                layout.shots([], duration)

    def test_missing_keys_rejected(self) -> None:
        with self.assertRaises(layout.LayoutError):
            layout.shots([{"t": 0.0}], 4.0)
        with self.assertRaises(layout.LayoutError):
            layout.shots([{"t": 0.0, "faces": [{"x": 1.0, "y": 2.0, "w": 3.0}]}], 4.0)

    def test_degenerate_face_is_skipped_negative_rejected(self) -> None:
        track = [{"t": 0.0, "faces": [
            {"x": 1.0, "y": 2.0, "w": 0.0, "h": 10.0},
            {"x": 1.0, "y": 2.0, "w": 10.0, "h": 0.0},
        ]}]
        self.assertEqual(layout.shots(track, 4.0)[0][2], [])
        with self.assertRaises(layout.LayoutError):
            layout.shots([{"t": 0.0, "faces": [
                {"x": 1.0, "y": 2.0, "w": -1.0, "h": 10.0},
            ]}], 4.0)


class PunchSemanticsTest(unittest.TestCase):
    """Tabel nilai diturunkan dari `motion.zoom_expression`, bukan ditebak."""

    SCHEDULE = [
        {"t": 0.0, "scale": 1.0},
        {"t": 2.5, "scale": 1.14},
        {"t": 5.0, "scale": 1.20},
    ]

    def test_continuous_step_function(self) -> None:
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 0.0), 1.0)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 2.499), 1.0)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 2.5), 1.14)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 4.999), 1.14)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 5.0), 1.20)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 99.0), 1.20)

    def test_no_schedule_means_no_punch(self) -> None:
        for punch in (None, [], [{"t": 0.0, "scale": 1.0}]):
            self.assertEqual(layout.punch_scale_at(punch, 3.0), 1.0)
            self.assertEqual(layout.max_punch_scale(punch, 0.0, 10.0), 1.0)

    def test_motion_expression_string_is_the_source_of_truth(self) -> None:
        """`if(lt(in,75), ...)`: hanya berubah di frame 75 dan 150 pada 30 fps."""
        self.assertEqual(
            motion.zoom_expression(self.SCHEDULE, 30.0),
            "if(lt(in,75),1.0000,if(lt(in,150),1.1400,1.2000))",
        )

    def test_frame_quantized_values_match_expression(self) -> None:
        fps = 30.0
        # Tabel yang sama dengan ekspresi di atas: frame < 75 -> 1,0;
        # 75 <= frame < 150 -> 1,14; >= 150 -> 1,20.
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 74 / fps, fps=fps), 1.0)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 75 / fps, fps=fps), 1.14)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 149 / fps, fps=fps), 1.14)
        self.assertEqual(layout.punch_scale_at(self.SCHEDULE, 150 / fps, fps=fps), 1.20)

    def test_non_integer_punch_time_and_float_boundary(self) -> None:
        """t=4,37 pada 30 fps menjadi frame 131; `131/30` < 4,37 di floating point.

        Ini alasan `fps=` ada: audit menilai per frame (`round(t*fps)`), jadi
        batas punch harus dibulatkan ke frame seperti `zoompan`, bukan
        dibandingkan dengan detik mentah.
        """
        schedule = [{"t": 0.0, "scale": 1.0}, {"t": 4.37, "scale": 1.14}]
        self.assertEqual(
            motion.zoom_expression(schedule, 30.0),
            "if(lt(in,131),1.0000,1.1400)",
        )
        t_frame = 131 / 30.0
        self.assertLess(t_frame, 4.37)
        self.assertEqual(layout.punch_scale_at(schedule, t_frame), 1.0)
        self.assertEqual(layout.punch_scale_at(schedule, t_frame, fps=30.0), 1.14)

    def test_max_punch_scale_window(self) -> None:
        self.assertEqual(layout.max_punch_scale(self.SCHEDULE, 0.0, 2.4), 1.0)
        self.assertEqual(layout.max_punch_scale(self.SCHEDULE, 2.4, 2.6), 1.14)
        self.assertEqual(layout.max_punch_scale(self.SCHEDULE, 2.5, 4.9), 1.14)
        self.assertEqual(layout.max_punch_scale(self.SCHEDULE, 4.9, 5.0), 1.20)
        self.assertEqual(layout.max_punch_scale(self.SCHEDULE, 3.0, 3.0), 1.14)

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(layout.LayoutError):
            layout.max_punch_scale(self.SCHEDULE, 5.0, 4.0)
        with self.assertRaises(layout.LayoutError):
            layout.punch_scale_at([{"t": 0.0, "scale": 0.0}], 1.0)
        with self.assertRaises(layout.LayoutError):
            layout.punch_scale_at(self.SCHEDULE, float("nan"))
        with self.assertRaises(layout.LayoutError):
            layout.punch_scale_at(self.SCHEDULE, 1.0, fps=0.0)


class ForbiddenZonesTest(unittest.TestCase):
    FACE = layout.Rect(100.0, 200.0, 200.0, 100.0)

    def test_exact_after_inflate_and_punch(self) -> None:
        for scale, want in (
            (1.0, (92.0, 196.0, 216.0, 108.0)),
            (1.14, (29.28, 89.04, 246.24, 123.12)),
            (1.20, (2.4, 43.2, 259.2, 129.6)),
        ):
            zones = layout.forbidden_zones([self.FACE], scale)
            self.assertEqual(len(zones), 1, msg=f"scale {scale}")
            _assert_rect_almost(self, zones[0], want, msg=f"scale {scale}")

    def test_inflate_override(self) -> None:
        zones = layout.forbidden_zones([self.FACE], 1.0, inflate=0.0)
        self.assertEqual(_t(zones[0]), (100.0, 200.0, 200.0, 100.0))

    def test_clipped_to_canvas(self) -> None:
        zones = layout.forbidden_zones([layout.Rect(0.0, 300.0, 200.0, 100.0)], 1.2)
        _assert_rect_almost(self, zones[0], (0.0, 163.2, 141.6, 129.6))
        for rect in zones:
            self.assertGreaterEqual(rect.x, 0.0)
            self.assertGreaterEqual(rect.y, 0.0)
            self.assertLessEqual(rect.x + rect.w, CANVAS_W)
            self.assertLessEqual(rect.y + rect.h, CANVAS_H)

    def test_face_entirely_outside_is_dropped(self) -> None:
        self.assertEqual(
            layout.forbidden_zones([layout.Rect(0.0, 0.0, 200.0, 100.0)], 1.2), []
        )

    def test_invalid_scale(self) -> None:
        with self.assertRaises(layout.LayoutError):
            layout.forbidden_zones([self.FACE], 0.0)


class CaptionRectTest(unittest.TestCase):
    def test_centered_block(self) -> None:
        r = layout.caption_rect(700.0, TWO_LINE_H, 1400.0)
        _assert_rect_almost(
            self, r, (190.0, 1400.0 - TWO_LINE_H / 2, 700.0, TWO_LINE_H)
        )

    def test_scale_and_custom_center(self) -> None:
        r = layout.caption_rect(700.0, LINE_H, 330.0, scale=0.85, cx=500.0)
        _assert_rect_almost(
            self, r,
            (500.0 - 700.0 * 0.85 / 2, 330.0 - LINE_H * 0.85 / 2,
             700.0 * 0.85, LINE_H * 0.85),
        )

    def test_validation(self) -> None:
        for args in ((0.0, 10.0), (10.0, -1.0), (float("inf"), 10.0)):
            with self.assertRaises(layout.LayoutError):
                layout.caption_rect(args[0], args[1], 100.0)
        with self.assertRaises(layout.LayoutError):
            layout.caption_rect(10.0, 10.0, float("nan"))
        with self.assertRaises(layout.LayoutError):
            layout.caption_rect(10.0, 10.0, 100.0, scale=0.0)


class PlaceCaptionTest(unittest.TestCase):
    def test_clear_shot_uses_first_candidate(self) -> None:
        got = layout.place_caption([], 700.0, TWO_LINE_H)
        self.assertEqual(got["y"], 1400.0)
        self.assertEqual(got["scale"], 1.0)
        self.assertTrue(got["reason"].startswith("clear"), msg=got["reason"])

    def test_bottom_blocked_falls_back_to_top(self) -> None:
        zones = [layout.Rect(0.0, 1200.0, 1080.0, 400.0)]
        got = layout.place_caption(zones, 700.0, TWO_LINE_H)
        self.assertEqual(got["y"], 330.0)
        self.assertEqual(got["scale"], 1.0)
        rect = layout.caption_rect(700.0, TWO_LINE_H, got["y"], scale=got["scale"])
        self.assertFalse(_intersects_any(rect, zones))

    def test_all_blocked_shrinks_first_candidate(self) -> None:
        zones = [
            layout.Rect(0.0, 1485.0, 1080.0, 200.0),
            layout.Rect(0.0, 250.0, 1080.0, 200.0),
        ]
        got = layout.place_caption(zones, 700.0, TWO_LINE_H)
        self.assertEqual(got["y"], 1400.0)
        self.assertEqual(got["scale"], layout.CAPTION_SHRINK)
        self.assertTrue(got["reason"].startswith("shrink"), msg=got["reason"])
        rect = layout.caption_rect(700.0, TWO_LINE_H, got["y"], scale=got["scale"])
        self.assertFalse(_intersects_any(rect, zones))

    def test_caption_never_dropped_and_min_overlap(self) -> None:
        zones = [layout.Rect(0.0, 0.0, 1080.0, 1920.0)]
        got = layout.place_caption(zones, 700.0, TWO_LINE_H)
        self.assertIsNotNone(got)
        self.assertEqual(got["y"], 1400.0)
        self.assertEqual(got["scale"], 1.0)
        self.assertTrue(got["reason"].startswith("min_overlap"), msg=got["reason"])

    def test_all_blocked_picks_second_candidate_when_it_overlaps_less(self) -> None:
        """Celah mutan 4a (T5): irisan minimal, bukan maksimal.

        Kedua kandidat memotong, dan percobaan `shrink` kandidat pertama juga
        memotong. Kandidat KEDUA (atas, y=330) memotong jauh lebih sedikit,
        jadi ia yang harus menang — bukan kandidat pertama.
        """
        zones = [
            layout.Rect(0.0, 1350.0, 1080.0, 400.0),   # memotong blok bawah banyak
            layout.Rect(0.0, 400.0, 1080.0, 100.0),    # memotong blok atas sedikit
        ]
        bottom = layout.caption_rect(700.0, TWO_LINE_H, 1400.0)
        top = layout.caption_rect(700.0, TWO_LINE_H, 330.0)
        shrunk = layout.caption_rect(
            700.0, TWO_LINE_H, 1400.0, scale=layout.CAPTION_SHRINK
        )
        assert _intersects_any(shrunk, zones), "prasyarat: shrink harus memotong juga"
        area_bottom = sum(bottom.intersection_area(z) for z in zones)
        area_top = sum(top.intersection_area(z) for z in zones)
        self.assertGreater(area_bottom, area_top)

        got = layout.place_caption(zones, 700.0, TWO_LINE_H)
        self.assertEqual(got["y"], 330.0, msg=got)
        self.assertEqual(got["scale"], 1.0, msg=got)
        self.assertTrue(got["reason"].startswith("min_overlap:y=330"), msg=got["reason"])

    def test_min_overlap_tie_prefers_earlier_candidate(self) -> None:
        zones = [layout.Rect(0.0, 0.0, 1080.0, 1920.0)]
        got = layout.place_caption(zones, 980.0, TWO_LINE_H)
        bottom = layout.caption_rect(980.0, TWO_LINE_H, 1400.0)
        top = layout.caption_rect(980.0, TWO_LINE_H, 330.0)
        self.assertAlmostEqual(bottom.intersection_area(zones[0]),
                               top.intersection_area(zones[0]))
        self.assertEqual(got["y"], 1400.0)

    def test_safe_zone_preferred_between_clear_candidates(self) -> None:
        """Prioritas: tidak memotong wajah > di zona aman > kandidat lebih awal."""
        got = layout.place_caption([], 700.0, LINE_H, candidates=(1500.0, 330.0))
        self.assertEqual(got["y"], 330.0, msg=got)
        self.assertTrue(got["reason"].startswith("clear_safe"), msg=got["reason"])

    def test_right_margin_can_make_both_unsafe_then_order_wins(self) -> None:
        got = layout.place_caption([], 980.0, LINE_H)
        self.assertEqual(got["y"], 1400.0)
        self.assertFalse(got["reason"].startswith("clear_safe"), msg=got["reason"])

    def test_deterministic_and_inputs_untouched(self) -> None:
        zones = [layout.Rect(0.0, 1200.0, 1080.0, 400.0)]
        before = [_t(z) for z in zones]
        first = layout.place_caption(zones, 700.0, TWO_LINE_H)
        second = layout.place_caption(zones, 700.0, TWO_LINE_H)
        self.assertEqual(first, second)
        self.assertEqual([_t(z) for z in zones], before)

    def test_validation(self) -> None:
        for candidates in ((), []):
            with self.assertRaises(layout.LayoutError):
                layout.place_caption([], 700.0, LINE_H, candidates=candidates)
        with self.assertRaises(layout.LayoutError):
            layout.place_caption([], 0.0, LINE_H)
        with self.assertRaises(layout.LayoutError):
            layout.place_caption([], 700.0, LINE_H, shrink=0.0)


class PlaceOverlayTest(unittest.TestCase):
    def test_top_slot_first_exact(self) -> None:
        got = layout.place_overlay("ui_panel", (400.0, 200.0), [], None, [])
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(_t(got), (340.0, 310.0, 400.0, 200.0))

    def test_top_blocked_uses_mid_low(self) -> None:
        zones = [layout.Rect(0.0, 260.0, 1080.0, 300.0)]
        got = layout.place_overlay("ui_panel", (400.0, 200.0), zones, None, [])
        assert got is not None
        self.assertEqual(_t(got), (340.0, 1020.0, 400.0, 200.0))

    def test_caption_blocks_top(self) -> None:
        caption = layout.Rect(300.0, 250.0, 500.0, 200.0)
        got = layout.place_overlay("phone_frame", (400.0, 200.0), [], caption, [])
        assert got is not None
        self.assertEqual(got.y, 1020.0)

    def test_taken_rects_block_slots(self) -> None:
        taken = [layout.Rect(0.0, 260.0, 1080.0, 300.0)]
        got = layout.place_overlay("ui_panel", (400.0, 200.0), [], None, taken)
        assert got is not None
        self.assertEqual(got.y, 1020.0)
        got2 = layout.place_overlay(
            "ui_panel", (400.0, 200.0), [], None, taken + [got]
        )
        self.assertIsNone(got2)

    def test_pullback_has_no_slot(self) -> None:
        self.assertIsNone(layout.place_overlay("pullback", (600.0, 400.0), [], None, []))
        self.assertIsNone(
            layout.place_overlay("zoom_through_text", (600.0, 400.0), [], None, [])
        )

    def test_clamped_preserving_aspect_and_centered(self) -> None:
        got = layout.place_overlay("ui_panel", (1200.0, 600.0), [], None, [])
        assert got is not None
        self.assertEqual(_t(got), (240.0, 260.0, 600.0, 300.0))
        self.assertAlmostEqual(got.w / got.h, 2.0)

    def test_never_upscaled(self) -> None:
        got = layout.place_overlay("ui_panel", (100.0, 50.0), [], None, [])
        assert got is not None
        self.assertEqual(_t(got), (490.0, 385.0, 100.0, 50.0))

    def test_custom_order_and_validation(self) -> None:
        got = layout.place_overlay(
            "ui_panel", (400.0, 200.0), [], None, [], order=("mid_low", "top_safe")
        )
        assert got is not None
        self.assertEqual(got.y, 1020.0)
        with self.assertRaises(layout.LayoutError):
            layout.place_overlay("ui_panel", (400.0, 200.0), [], None, [],
                                 order=("does_not_exist",))
        with self.assertRaises(layout.LayoutError):
            layout.place_overlay("ui_panel", (0.0, 200.0), [], None, [])

    def test_result_never_intersects_inputs(self) -> None:
        zones = [layout.Rect(0.0, 260.0, 1080.0, 300.0)]
        caption = layout.Rect(190.0, 1300.0, 700.0, 200.0)
        taken = [layout.Rect(0.0, 1000.0, 1080.0, 240.0)]
        got = layout.place_overlay("ui_panel", (400.0, 200.0), zones, caption, taken)
        self.assertIsNone(got)


class ComputeLayoutTest(unittest.TestCase):
    def test_one_entry_per_shot(self) -> None:
        track = [
            {"t": 0.0, "faces": []},
            {"t": 4.0, "faces": [{"x": 0.0, "y": 1300.0, "w": 1080.0, "h": 400.0}]},
        ]
        blocks = [
            {"start": 0.5, "end": 3.5, "w": 700.0, "h": LINE_H},
            {"start": 4.5, "end": 5.5, "w": 700.0, "h": LINE_H},
        ]
        out = layout.compute_layout(track, [], 6.0, caption_blocks=blocks, overlays=[])
        self.assertEqual(out["version"], 1)
        self.assertEqual([c["t"] for c in out["caption"]], [0.0, 4.0])
        self.assertEqual([c["an"] for c in out["caption"]], [2, 2])
        self.assertEqual(out["caption"][0]["y"], 1400.0)
        self.assertEqual(out["caption"][1]["y"], 330.0)
        self.assertEqual(out["overlays"], [])

    def test_never_changes_caption_mid_phrase(self) -> None:
        """Batas shot di tengah frasa: frasa itu tetap memakai keputusan lama.

        Shot 0 (0-3 s) tanpa wajah -> caption bawah. Shot 1 (3-6 s) wajah
        menutup bawah -> caption atas. Frasa B (2,0-4,0 s) melewati batas shot
        tetapi HARUS tetap di bawah sampai frasa berikutnya (C, mulai 4,2 s).
        """
        track = [
            {"t": 0.0, "faces": []},
            {"t": 3.0, "faces": [{"x": 0.0, "y": 1300.0, "w": 1080.0, "h": 400.0}]},
        ]
        blocks = [
            {"start": 0.5, "end": 1.5, "w": 700.0, "h": TWO_LINE_H},
            {"start": 2.0, "end": 4.0, "w": 700.0, "h": TWO_LINE_H},
            {"start": 4.2, "end": 5.5, "w": 700.0, "h": TWO_LINE_H},
        ]
        out = layout.compute_layout(track, [], 6.0, caption_blocks=blocks, overlays=[])
        self.assertEqual([c["t"] for c in out["caption"]], [0.0, 3.0])
        self.assertEqual(out["caption"][0]["y"], 1400.0)
        self.assertEqual(out["caption"][1]["y"], 330.0)

        def active(start: float) -> dict:
            before = [c for c in out["caption"] if c["t"] <= start + 1e-9]
            return before[-1]

        # Frasa yang dimulai sebelum batas shot memakai keputusan shot lama,
        # termasuk saat ia menyeberang ke shot berikutnya.
        self.assertEqual(active(0.5)["y"], 1400.0)
        self.assertEqual(active(2.0)["y"], 1400.0)
        self.assertEqual(active(4.2)["y"], 330.0)

    def test_phrase_starting_at_boundary_uses_next_decision(self) -> None:
        track = [
            {"t": 0.0, "faces": []},
            {"t": 2.0, "faces": [{"x": 0.0, "y": 1300.0, "w": 1080.0, "h": 400.0}]},
        ]
        blocks = [{"start": 2.0, "end": 3.0, "w": 700.0, "h": TWO_LINE_H}]
        out = layout.compute_layout(track, [], 4.0, caption_blocks=blocks, overlays=[])
        self.assertEqual(out["caption"][-1]["y"], 330.0)
        self.assertEqual(out["caption"][-1]["t"], 2.0)

    def test_no_face_track_uses_default_zone(self) -> None:
        blocks = [{"start": 0.0, "end": 1.0, "w": 700.0, "h": LINE_H}]
        out = layout.compute_layout(None, [], 3.0, caption_blocks=blocks, overlays=[])
        self.assertEqual(out["caption"], [{
            "t": 0.0, "an": 2, "y": 1400.0, "scale": 1.0,
            "reason": "no_face_track",
        }])
        out2 = layout.compute_layout([], [], 3.0, caption_blocks=blocks, overlays=[])
        self.assertEqual(out2["caption"], out["caption"])

    def test_no_caption_blocks_gives_no_entries(self) -> None:
        out = layout.compute_layout(None, [], 3.0, caption_blocks=[], overlays=[])
        self.assertEqual(out["caption"], [])

    def test_overlays_span_shots_and_avoid_caption_and_taken(self) -> None:
        track = [
            {"t": 0.0, "faces": []},
            {"t": 3.0, "faces": [{"x": 0.0, "y": 1300.0, "w": 1080.0, "h": 400.0}]},
        ]
        blocks = [
            {"start": 0.5, "end": 2.0, "w": 700.0, "h": TWO_LINE_H},
            {"start": 3.5, "end": 5.0, "w": 700.0, "h": TWO_LINE_H},
        ]
        overlays = [
            {"type": "ui_panel", "size": (400.0, 200.0), "start": 0.0, "end": 6.0},
            {"type": "pullback", "size": (600.0, 400.0), "start": 1.0, "end": 2.0},
            {"type": "phone_frame", "size": (500.0, 400.0), "start": 0.0, "end": 6.0},
        ]
        out = layout.compute_layout(track, [], 6.0, caption_blocks=blocks, overlays=overlays)
        got = out["overlays"]
        self.assertEqual([o["index"] for o in got], [0, 1, 2])
        self.assertIsNotNone(got[0]["rect"])
        self.assertEqual(got[0]["reason"], "slot=mid_low")
        self.assertIsNone(got[1]["rect"])
        self.assertEqual(got[1]["reason"], "no_slot_by_kind")
        self.assertIsNone(got[2]["rect"])
        self.assertEqual(got[2]["reason"], "no_free_slot")

    def test_empty_window_and_bad_kind(self) -> None:
        overlays = [
            {"type": "ui_panel", "size": (400.0, 200.0), "start": 2.0, "end": 1.0},
        ]
        out = layout.compute_layout(None, [], 3.0, caption_blocks=[], overlays=overlays)
        self.assertIsNone(out["overlays"][0]["rect"])
        self.assertEqual(out["overlays"][0]["reason"], "empty_window")
        with self.assertRaises(layout.LayoutError):
            layout.compute_layout(None, [], 3.0, caption_blocks=[],
                                  overlays=[{"type": "", "size": (10.0, 10.0)}])

    def test_deterministic(self) -> None:
        track = [{"t": 0.0, "faces": [{"x": 100.0, "y": 200.0, "w": 300.0, "h": 400.0}]}]
        blocks = [{"start": 0.0, "end": 2.0, "w": 700.0, "h": TWO_LINE_H}]
        overlays = [{"type": "ui_panel", "size": (400.0, 200.0)}]
        a = layout.compute_layout(track, [{"t": 0.0, "scale": 1.14}], 3.0,
                                  caption_blocks=blocks, overlays=overlays)
        b = layout.compute_layout(track, [{"t": 0.0, "scale": 1.14}], 3.0,
                                  caption_blocks=blocks, overlays=overlays)
        self.assertEqual(a, b)

    def test_output_shape_matches_schema_declared_subset(self) -> None:
        """Validasi manual, tanpa `jsonschema`.

        Skema mendeklarasikan `layout.version` (integer >= 1) dan
        `caption[]` wajib `t`/`an`/`y` (number/number-integer/number,
        `1 <= an <= 9`). Keluaran 4a menambah `scale`/`reason` dan
        `overlays` yang belum ada di skema; itu diperiksa di sini sebagai
        kunci tambahan yang disengaja (4b yang akan menyelaraskan skema).
        """
        track = [{"t": 0.0, "faces": []}]
        blocks = [{"start": 0.0, "end": 2.0, "w": 700.0, "h": TWO_LINE_H}]
        overlays = [{"type": "ui_panel", "size": (400.0, 200.0), "start": 0.0, "end": 1.0}]
        out = layout.compute_layout(track, [], 3.0, caption_blocks=blocks, overlays=overlays)

        self.assertIsInstance(out["version"], int)
        self.assertGreaterEqual(out["version"], 1)

        for entry in out["caption"]:
            self.assertIsInstance(entry, dict)
            self.assertIn("t", entry)
            self.assertIn("an", entry)
            self.assertIn("y", entry)
            self.assertIsInstance(entry["t"], (int, float))
            self.assertGreaterEqual(entry["t"], 0.0)
            self.assertIsInstance(entry["an"], int)
            self.assertGreaterEqual(entry["an"], 1)
            self.assertLessEqual(entry["an"], 9)
            self.assertIsInstance(entry["y"], (int, float))
            self.assertEqual(set(entry), {"t", "an", "y", "scale", "reason"})
            self.assertGreater(entry["scale"], 0.0)
            self.assertIsInstance(entry["reason"], str)
            self.assertTrue(entry["reason"])

        for item in out["overlays"]:
            self.assertEqual(set(item), {"index", "rect", "reason"})
            self.assertIsInstance(item["index"], int)
            self.assertIsInstance(item["reason"], str)
            if item["rect"] is not None:
                self.assertEqual(set(item["rect"]), {"x", "y", "w", "h"})
                for value in item["rect"].values():
                    self.assertIsInstance(value, (int, float))
                self.assertGreater(item["rect"]["w"], 0.0)
                self.assertGreater(item["rect"]["h"], 0.0)

    def test_invalid_blocks(self) -> None:
        good = {"start": 0.0, "end": 1.0, "w": 700.0, "h": LINE_H}
        for blocks in (
            [dict(good, start=1.0, end=0.0)],
            [dict(good, w=0.0)],
            [good, dict(good, start=0.5, end=2.0)],
            [dict(good, start=2.0, end=3.0), dict(good, start=0.0, end=1.0)],
        ):
            with self.assertRaises(layout.LayoutError, msg=str(blocks)):
                layout.compute_layout(None, [], 4.0, caption_blocks=blocks, overlays=[])


class AuditTest(unittest.TestCase):
    def _layout(self) -> dict:
        return {
            "version": 1,
            "caption": [{"t": 0.0, "an": 2, "y": 1400.0, "scale": 1.0,
                         "reason": "test"}],
            "overlays": [{"index": 0, "reason": "test",
                          "rect": {"x": 100.0, "y": 1250.0, "w": 100.0, "h": 100.0}}],
        }

    def test_exact_frame_counts_with_deliberate_collisions(self) -> None:
        """Wajah 1080x80 di y=1200: hanya bertabrakan setelah punch 1,2.

        Zona terinflasi berakhir di y=1283,2 pada skala 1,0 (tidak menyentuh
        caption y=1300) dan di y=1347,84 pada skala 1,2 (menyentuh). Punch
        berubah di t=1,0 s; pada 10 fps itu frame 10. Jadi tepat 10 dari 20
        frame bertabrakan — bukan 20 seperti kalau audit memakai skala maksimum
        global.
        """
        track = [{"t": 0.0, "faces": [{"x": 0.0, "y": 1200.0, "w": 1080.0, "h": 80.0}]}]
        punch = [{"t": 0.0, "scale": 1.0}, {"t": 1.0, "scale": 1.2}]
        blocks = [{"start": 0.0, "end": 2.0, "w": 700.0, "h": 200.0}]
        overlays = [{"type": "ui_panel", "size": (100.0, 100.0),
                     "start": 1.0, "end": 1.3}]
        got = layout.audit(self._layout(), track, punch, 2.0, blocks, overlays, 10.0)
        self.assertEqual(got["caption_face_frames"], 10)
        self.assertEqual(got["overlay_face_frames"], 4)
        self.assertEqual(got["caption_overlay_frames"], 4)
        self.assertEqual(got["worst"][0]["kind"], "caption_face")
        self.assertEqual(got["worst"][0]["frame"], 10)
        self.assertAlmostEqual(got["worst"][0]["area"], 33488.0, places=2)

    def test_no_collisions_is_zero(self) -> None:
        track = [{"t": 0.0, "faces": [{"x": 0.0, "y": 0.0, "w": 200.0, "h": 200.0}]}]
        blocks = [{"start": 0.0, "end": 2.0, "w": 700.0, "h": 200.0}]
        layout_dict = {
            "version": 1,
            "caption": [{"t": 0.0, "an": 2, "y": 1400.0, "scale": 1.0,
                         "reason": "test"}],
            "overlays": [{"index": 0, "reason": "test",
                          "rect": {"x": 900.0, "y": 1600.0, "w": 100.0, "h": 100.0}}],
        }
        overlays = [{"type": "ui_panel", "size": (100.0, 100.0),
                     "start": 1.0, "end": 1.3}]
        got = layout.audit(layout_dict, track, [], 2.0, blocks, overlays, 10.0)
        self.assertEqual(got["caption_face_frames"], 0)
        self.assertEqual(got["overlay_face_frames"], 0)
        self.assertEqual(got["caption_overlay_frames"], 0)
        self.assertEqual(got["worst"], [])

    def test_null_overlay_not_counted_and_outside_window_ignored(self) -> None:
        track = [{"t": 0.0, "faces": [{"x": 0.0, "y": 0.0, "w": 200.0, "h": 200.0}]}]
        blocks = [{"start": 0.0, "end": 1.0, "w": 700.0, "h": 200.0}]
        layout_dict = {
            "version": 1,
            "caption": [{"t": 0.0, "an": 2, "y": 1400.0, "scale": 1.0,
                         "reason": "test"}],
            "overlays": [
                {"index": 0, "rect": None, "reason": "no_free_slot"},
                {"index": 1, "rect": {"x": 100.0, "y": 0.0, "w": 100.0, "h": 100.0},
                 "reason": "test"},
            ],
        }
        overlays = [
            {"type": "ui_panel", "size": (100.0, 100.0), "start": 0.0, "end": 1.0},
            {"type": "ui_panel", "size": (100.0, 100.0), "start": 5.0, "end": 6.0},
        ]
        got = layout.audit(layout_dict, track, [], 2.0, blocks, overlays, 10.0)
        self.assertEqual(got["overlay_face_frames"], 0)
        self.assertEqual(got["caption_overlay_frames"], 0)

    def test_validation(self) -> None:
        with self.assertRaises(layout.LayoutError):
            layout.audit(self._layout(), [], [], 2.0, [], [], 0.0)


class SummaryScenarioTest(unittest.TestCase):
    """Skenario klip nyata (dokumentasi perilaku, bukan gerbang estetika).

    Wajah besar 1080x1150 mulai y=0 (60% atas frame), punch maks 1,2, caption
    dua baris selebar 980. Zona wajah terinflasi setelah punch berakhir di
    y=1243,2; kotak caption (pusat 1400, tinggi 193,2) mulai di 1303,4, jadi
    TIDAK memotong wajah. Yang dilanggar adalah zona aman kanan (tepi 1030 >
    960); SAFE bawah tidak dilanggar oleh anchor y (1400 <= 1440) meskipun
    tepi bawah kotak (1496,6) melewati 1440 — lihat catatan di `place_caption`.
    """

    def test_documented_decision_and_safe_violations(self) -> None:
        track = [{"t": 0.0, "faces": [{"x": 0.0, "y": 0.0, "w": 1080.0, "h": 1150.0}]}]
        punch = [{"t": 0.0, "scale": 1.0}, {"t": 3.0, "scale": 1.2}]
        blocks = [{"start": 0.5, "end": 9.0, "w": 980.0, "h": TWO_LINE_H}]
        out = layout.compute_layout(track, punch, 10.0, caption_blocks=blocks, overlays=[])
        entry = out["caption"][0]
        self.assertEqual(entry["y"], 1400.0)
        self.assertEqual(entry["scale"], 1.0)
        self.assertTrue(entry["reason"].startswith("clear"))

        zones = layout.forbidden_zones(
            [layout.Rect(0.0, 0.0, 1080.0, 1150.0)], 1.2
        )
        self.assertEqual((zones[0].x, zones[0].y, zones[0].w), (0.0, 0.0, 1080.0))
        self.assertAlmostEqual(zones[0].h, 1243.2, places=6)
        caption = layout.caption_rect(980.0, TWO_LINE_H, entry["y"])
        self.assertEqual(_intersects_any(caption, zones), False)

        right_violation = (caption.x + caption.w) - (CANVAS_W - layout.SAFE["right"])
        bottom_violation = (caption.y + caption.h) - (CANVAS_H - layout.SAFE["bottom"])
        self.assertAlmostEqual(right_violation, 70.0, places=6)
        self.assertAlmostEqual(bottom_violation, 56.6, places=6)

        audit = layout.audit(out, track, punch, 10.0, blocks, [], 10.0)
        self.assertEqual(audit["caption_face_frames"], 0)


class ScanFreeRectTest(unittest.TestCase):
    """Pengujian layout.scan_free_rect (penempatan tanpa penyusutan)."""

    def test_scan_free_rect_basic_and_exact_size(self) -> None:
        size = (960.0, 328.0)
        got = layout.scan_free_rect(size, [], [], [])
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual((got.x, got.y, got.w, got.h), (60.0, 250.0, 960.0, 328.0))

    def test_scan_free_rect_never_shrinks(self) -> None:
        # Mutan (b): scan_free_rect tidak boleh menyusutkan w atau h
        size = (960.0, 520.0)
        zones = [layout.Rect(0.0, 200.0, 1080.0, 300.0)]
        got = layout.scan_free_rect(size, zones, [], [])
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.w, 960.0)
        self.assertEqual(got.h, 520.0)

    def test_scan_free_rect_avoids_face_zones(self) -> None:
        # Mutan (c): zona wajah harus dihindari
        size = (960.0, 300.0)
        face_zone = layout.Rect(0.0, 200.0, 1080.0, 400.0)  # y: 200..600
        got = layout.scan_free_rect(size, [face_zone], [], [])
        self.assertIsNotNone(got)
        assert got is not None
        self.assertFalse(got.intersects(face_zone))
        self.assertGreaterEqual(got.y, 600.0)

    def test_scan_free_rect_respects_safe_bottom(self) -> None:
        # Mutan (d): tidak boleh melewati y_max = 1920 - SAFE.bottom - h = 1440 - h
        size = (960.0, 300.0)
        # Hambatan menutup kanvas sampai y=1200
        # Di y=1200, y+h = 1500 > 1440 -> tidak muat di zona aman bawah!
        zones = [layout.Rect(0.0, 0.0, 1080.0, 1200.0)]
        got = layout.scan_free_rect(size, zones, [], [])
        self.assertIsNone(got, "Harus None karena melebihi zona aman bawah")

    def test_scan_free_rect_avoid_caption_and_fallback(self) -> None:
        # Mutan (e): avoid_caption diuji
        size = (960.0, 200.0)
        # Caption di y=250..400
        caption = layout.Rect(100.0, 250.0, 800.0, 150.0)
        # Bila avoid_caption=True: lewati caption, pilih posisi di bawah caption (y >= 400)
        got_avoid = layout.scan_free_rect(size, [], [caption], [], avoid_caption=True)
        self.assertIsNotNone(got_avoid)
        assert got_avoid is not None
        self.assertFalse(got_avoid.intersects(caption))
        self.assertGreaterEqual(got_avoid.y, 400.0)

        # Bila caption menutup SEMUA posisi aman, tapi bebas wajah: fallback kembalikan posisi pertama
        full_caption = layout.Rect(0.0, 250.0, 1080.0, 1200.0)
        got_fallback = layout.scan_free_rect(size, [], [full_caption], [], avoid_caption=True)
        self.assertIsNotNone(got_fallback, "Harus fallback ke posisi bebas wajah saat caption menutupi semua")
        assert got_fallback is not None
        self.assertEqual(got_fallback.y, 250.0)

        # Bila avoid_caption=False: langsung ambil posisi pertama
        got_no_avoid = layout.scan_free_rect(size, [], [caption], [], avoid_caption=False)
        self.assertIsNotNone(got_no_avoid)
        assert got_no_avoid is not None
        self.assertEqual(got_no_avoid.y, 250.0)

    def test_scan_free_rect_real_video_case(self) -> None:
        # Kasus nyata: wajah (113, 341, 641, 547) dengan punch 1.0-1.2
        face = layout.Rect(113.0, 341.0, 641.0, 547.0)
        zones = layout.forbidden_zones([face], max_scale=1.2)
        card_size = (960.0, 328.0)
        got = layout.scan_free_rect(card_size, zones, x=60.0, step=20.0)
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.x, 60.0)
        self.assertEqual(got.w, 960.0)
        self.assertEqual(got.h, 328.0)
        # Zona wajah berakhir di ~899.85, sehingga pada step=20 jatuh di y >= 900
        self.assertGreaterEqual(got.y, 900.0)
        self.assertLessEqual(got.y, 960.0)
        for z in zones:
            self.assertFalse(got.intersects(z))


if __name__ == "__main__":
    unittest.main()
