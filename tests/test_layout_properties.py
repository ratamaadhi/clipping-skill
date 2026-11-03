"""Tes properti `scripts.layout` pada grid geometri (murni, deterministik).

Grid: pusat wajah `cx, cy` di {0,2; 0,3; ...; 0,8} x kanvas, lebar wajah
{160, 280, 420} px, skala punch {1,0; 1,14; 1,20}, blok caption 1 dan 2 baris
dengan lebar 700/980 px. Properti yang diuji adalah INVARIAN, bukan angka
tunggal: caption tidak pernah memotong wajah bila ada kandidat bebas, caption
tidak pernah hilang, overlay tidak pernah menimpa apa pun, dan tidak ada rect
yang keluar kanvas.
"""

from __future__ import annotations

import math
import unittest

from scripts import layout

CANVAS = (1080.0, 1920.0)
LINE_H = 96.6
CENTERS = tuple(round(0.2 + 0.1 * i, 1) for i in range(7))
FACE_WIDTHS = (160.0, 280.0, 420.0)
PUNCH_SCALES = (1.0, 1.14, 1.20)
BLOCKS = (
    (700.0, LINE_H),
    (980.0, LINE_H),
    (700.0, 2 * LINE_H),
    (980.0, 2 * LINE_H),
)
SLOT_KINDS = ("ui_panel", "phone_frame", "chart_grow", "checklist")
NO_SLOT_KINDS = ("pullback", "zoom_through_text")


def _face(cx_frac: float, cy_frac: float, width: float) -> layout.Rect:
    height = width * 1.3
    return layout.Rect(
        cx_frac * CANVAS[0] - width / 2.0,
        cy_frac * CANVAS[1] - height / 2.0,
        width,
        height,
    )


def _clear(rect: layout.Rect, zones: list[layout.Rect]) -> bool:
    return not any(rect.intersects(zone) for zone in zones)


def _in_canvas(rect: layout.Rect) -> bool:
    return (
        rect.x >= 0.0
        and rect.y >= 0.0
        and rect.x + rect.w <= CANVAS[0] + 1e-9
        and rect.y + rect.h <= CANVAS[1] + 1e-9
    )


def _grid():
    for cx in CENTERS:
        for cy in CENTERS:
            for width in FACE_WIDTHS:
                for punch in PUNCH_SCALES:
                    for block_w, block_h in BLOCKS:
                        yield cx, cy, width, punch, block_w, block_h


class CaptionGridPropertyTest(unittest.TestCase):
    def test_never_cuts_face_when_a_candidate_is_free(self) -> None:
        for cx, cy, width, punch, block_w, block_h in _grid():
            face = _face(cx, cy, width)
            zones = layout.forbidden_zones([face], punch)
            decision = layout.place_caption(zones, block_w, block_h)
            rect = layout.caption_rect(block_w, block_h, decision["y"],
                                       scale=decision["scale"])
            full = [layout.caption_rect(block_w, block_h, y)
                    for y in layout.CAPTION_CANDIDATES_Y]
            shrunk = layout.caption_rect(
                block_w, block_h, layout.CAPTION_CANDIDATES_Y[0],
                scale=layout.CAPTION_SHRINK,
            )
            free_exists = any(_clear(r, zones) for r in full) or _clear(shrunk, zones)
            msg = (f"cx={cx} cy={cy} w={width} punch={punch} "
                   f"block={block_w}x{block_h} decision={decision}")
            if free_exists:
                self.assertFalse(decision["reason"].startswith("min_overlap"), msg)
                self.assertTrue(_clear(rect, zones), msg)

    def test_bottom_blocked_and_top_free_uses_top(self) -> None:
        for cx, cy, width, punch, block_w, block_h in _grid():
            zones = layout.forbidden_zones([_face(cx, cy, width)], punch)
            bottom = layout.caption_rect(block_w, block_h,
                                         layout.CAPTION_CANDIDATES_Y[0])
            top = layout.caption_rect(block_w, block_h,
                                      layout.CAPTION_CANDIDATES_Y[1])
            if not _clear(bottom, zones) and _clear(top, zones):
                decision = layout.place_caption(zones, block_w, block_h)
                msg = (f"cx={cx} cy={cy} w={width} punch={punch} "
                       f"block={block_w}x{block_h} decision={decision}")
                self.assertEqual(decision["y"], layout.CAPTION_CANDIDATES_Y[1], msg)
                self.assertEqual(decision["scale"], 1.0, msg)

    def test_result_identical_on_two_calls(self) -> None:
        for cx, cy, width, punch, block_w, block_h in _grid():
            zones = layout.forbidden_zones([_face(cx, cy, width)], punch)
            self.assertEqual(
                layout.place_caption(zones, block_w, block_h),
                layout.place_caption(zones, block_w, block_h),
            )

    def test_caption_rect_stays_in_canvas(self) -> None:
        for cx, cy, width, punch, block_w, block_h in _grid():
            zones = layout.forbidden_zones([_face(cx, cy, width)], punch)
            decision = layout.place_caption(zones, block_w, block_h)
            rect = layout.caption_rect(block_w, block_h, decision["y"],
                                       scale=decision["scale"])
            self.assertTrue(_in_canvas(rect), msg=f"{decision} -> {rect}")

    def test_giant_face_never_drops_caption(self) -> None:
        zones = [layout.Rect(0.0, 0.0, CANVAS[0], CANVAS[1])]
        for block_w, block_h in BLOCKS:
            decision = layout.place_caption(zones, block_w, block_h)
            self.assertIsNotNone(decision)
            self.assertIn(decision["y"], layout.CAPTION_CANDIDATES_Y)
            self.assertIn(decision["scale"], (1.0, layout.CAPTION_SHRINK))
            self.assertEqual(
                decision["scale"] == layout.CAPTION_SHRINK
                or decision["reason"].startswith("min_overlap"),
                True,
                msg=decision,
            )
            self.assertTrue(decision["reason"])

    def test_two_faces_covering_both_candidates_falls_back_to_min_overlap(self) -> None:
        zones = layout.forbidden_zones(
            [
                layout.Rect(0.0, 0.0, CANVAS[0], 900.0),
                layout.Rect(0.0, 1200.0, CANVAS[0], 720.0),
            ],
            1.0,
        )
        for block_w, block_h in BLOCKS:
            decision = layout.place_caption(zones, block_w, block_h)
            self.assertTrue(decision["reason"].startswith("min_overlap"), msg=decision)


class OverlayGridPropertyTest(unittest.TestCase):
    def test_overlay_never_intersects_face_caption_or_other_overlay(self) -> None:
        for cx, cy, width, punch, block_w, block_h in _grid():
            zones = layout.forbidden_zones([_face(cx, cy, width)], punch)
            decision = layout.place_caption(zones, block_w, block_h)
            caption = layout.caption_rect(block_w, block_h, decision["y"],
                                          scale=decision["scale"])
            taken: list[layout.Rect] = []
            for kind in SLOT_KINDS:
                rect = layout.place_overlay(kind, (300.0, 150.0), zones, caption, taken)
                msg = (f"kind={kind} cx={cx} cy={cy} w={width} punch={punch} "
                       f"block={block_w}x{block_h} rect={rect}")
                if rect is None:
                    continue
                self.assertFalse(any(rect.intersects(z) for z in zones), msg)
                self.assertFalse(rect.intersects(caption), msg)
                self.assertFalse(any(rect.intersects(t) for t in taken), msg)
                self.assertTrue(_in_canvas(rect), msg)
                taken.append(rect)

    def test_no_slot_kinds_are_always_none(self) -> None:
        for kind in NO_SLOT_KINDS:
            self.assertIsNone(layout.place_overlay(kind, (300.0, 150.0), [], None, []))

    def test_all_slots_taken_gives_none(self) -> None:
        taken = [layout.Rect(0.0, 0.0, CANVAS[0], CANVAS[1])]
        for kind in SLOT_KINDS:
            self.assertIsNone(
                layout.place_overlay(kind, (300.0, 150.0), [], None, taken)
            )

    def test_overlay_size_is_clamped_within_each_slot(self) -> None:
        for kind in SLOT_KINDS:
            for size in ((2000.0, 400.0), (100.0, 1000.0), (300.0, 150.0)):
                rect = layout.place_overlay(kind, size, [], None, [])
                self.assertIsNotNone(rect)
                assert rect is not None
                self.assertLessEqual(rect.w, 960.0 + 1e-9)
                self.assertLessEqual(rect.h, 300.0 + 1e-9)
                self.assertTrue(math.isclose(rect.w / rect.h, size[0] / size[1],
                                             rel_tol=1e-9), msg=(kind, size, rect))


if __name__ == "__main__":
    unittest.main()
