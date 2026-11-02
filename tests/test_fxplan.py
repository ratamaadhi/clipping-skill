"""Pengujian komprehensif untuk pengesah rencana efek video (scripts/fxplan.py)."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from scripts import fxcatalog
from tests.helpers import ROOT
from tests.test_schema_drift import missing_required, undeclared_keys
from tests.test_schema_fx_plan import load_report_schema

# Impor fxplan (akan dibuat pada implementasi)
try:
    from scripts import fxplan
except ImportError:
    fxplan = None  # type: ignore


class FxPlanValidationTest(unittest.TestCase):
    """Pengujian aturan pengesahan 1-9 pada scripts/fxplan.py."""

    def setUp(self) -> None:
        self.report_schema = load_report_schema()

    def _make_edl(self, **kwargs: Any) -> dict[str, Any]:
        clip: dict[str, Any] = {
            "id": "clip_04",
            "duration": 50.0,
            "segments": [{"src_start": 0.0, "src_end": 50.0}],
            "reframe": {
                "face_track": [
                    {"t": 0.0, "faces": [{"x": 450.0, "y": 1500.0, "w": 180.0, "h": 250.0}]}
                ]
            },
            "punch": [],
            "overlays": [],
            "captions": [],
        }
        clip.update(kwargs)
        return {
            "version": "0.1.0",
            "clips": [clip],
        }

    def _make_plan(self, items: list[dict[str, Any]], clip_id: str = "clip_04") -> dict[str, Any]:
        return {
            "version": 1,
            "mode": "suggest",
            "clips": [
                {
                    "clip_id": clip_id,
                    "items": items,
                }
            ],
        }

    # -----------------------------------------------------------------------
    # Aturan 1: Struktur
    # -----------------------------------------------------------------------
    def test_rule1_unknown_effect_type(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "efek_gaib",
                "start": 5.0,
                "end": 8.0,
                "props": {},
                "reason": "Uji efek tidak dikenal",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item_rep = rep["clips"][0]["items"][0]
        self.assertEqual(item_rep["status"], "rejected")
        self.assertTrue(any("katalog" in e for e in item_rep["errors"]))
        self.assertIsNone(item_rep["overlay"])

    def test_rule1_unknown_clip_id(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan(
            [
                {
                    "id": "p1",
                    "type": "zoom_through_text",
                    "start": 5.0,
                    "end": 5.7,
                    "props": {"text": "Halo"},
                    "reason": "Alasan sah",
                }
            ],
            clip_id="clip_tidak_ada",
        )
        rep = fxplan.validate(edl, plan)
        item_rep = rep["clips"][0]["items"][0]
        self.assertEqual(item_rep["status"], "rejected")
        self.assertTrue(any("EDL" in e or "tidak ditemukan" in e for e in item_rep["errors"]))

    def test_rule1_invalid_times(self) -> None:
        edl = self._make_edl()
        # Kasus A: start < 0
        # Kasus B: end <= start
        # Kasus C: end > clip_duration
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": -1.0,
                "end": 2.0,
                "props": {"text": "A"},
                "reason": "Waktu minus",
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 10.0,
                "end": 8.0,
                "props": {"text": "B"},
                "reason": "End lebih kecil",
            },
            {
                "id": "p3",
                "type": "zoom_through_text",
                "start": 48.0,
                "end": 55.0,
                "props": {"text": "C"},
                "reason": "End lewati klip",
            },
        ])
        rep = fxplan.validate(edl, plan)
        for it in rep["clips"][0]["items"]:
            self.assertEqual(it["status"], "rejected")
            self.assertTrue(len(it["errors"]) > 0)

    def test_rule1_reason_mandatory_and_length(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 5.0,
                "end": 5.7,
                "props": {"text": "A"},
                "reason": "",  # Kosong
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 10.0,
                "end": 10.7,
                "props": {"text": "B"},
                "reason": "X" * 201,  # Terlalu panjang
            },
        ])
        rep = fxplan.validate(edl, plan)
        self.assertEqual(rep["clips"][0]["items"][0]["status"], "rejected")
        self.assertTrue(any("reason" in e.lower() for e in rep["clips"][0]["items"][0]["errors"]))
        self.assertEqual(rep["clips"][0]["items"][1]["status"], "rejected")
        self.assertTrue(any("reason" in e.lower() for e in rep["clips"][0]["items"][1]["errors"]))

    def test_rule1_duplicate_item_ids(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "dup_id",
                "type": "zoom_through_text",
                "start": 5.0,
                "end": 5.7,
                "props": {"text": "Satu"},
                "reason": "Item pertama",
            },
            {
                "id": "dup_id",
                "type": "zoom_through_text",
                "start": 15.0,
                "end": 15.7,
                "props": {"text": "Dua"},
                "reason": "Item kedua id kembar",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = rep["clips"][0]["items"]
        # Item kedua ditolak karena id duplikat
        self.assertEqual(items[1]["status"], "rejected")
        self.assertTrue(any("unik" in e.lower() for e in items[1]["errors"]))

    # -----------------------------------------------------------------------
    # Aturan 2: Props dari Pembuat Preset Nyata
    # -----------------------------------------------------------------------
    def test_rule2_preset_error_invalid_props(self) -> None:
        edl = self._make_edl()
        # ui_panel dengan thumbs=9 (melebihi batas UI_MAX_THUMBS=6)
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "ui_panel",
                "start": 5.0,
                "end": 10.0,
                "props": {"title": "Layar", "tag": "BARU", "thumbs": 9},
                "reason": "Thumbs terlalu banyak",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "rejected")
        self.assertTrue(any("thumbs" in e.lower() for e in item["errors"]))

    def test_rule2_valid_props_pass(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "checklist",
                "start": 5.0,
                "end": 11.0,
                "props": {
                    "title": "Tips Sukses",
                    "items": [
                        {"text": "Fokus", "done_at": 6.0},
                        {"text": "Konsisten", "done_at": 8.0},
                    ],
                },
                "reason": "Daftar langkah kerja",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted")
        self.assertIsNotNone(item["overlay"])
        self.assertEqual(item["overlay"]["type"], "checklist")

    # -----------------------------------------------------------------------
    # Aturan 3: Anggaran per klip
    # -----------------------------------------------------------------------
    def test_rule3_budget_max_overlays_per_clip(self) -> None:
        edl = self._make_edl()
        # Berikan 4 item berjarak aman: 3 pertama diterima, ke-4 ditolak karena max 3
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 4.0,
                "end": 4.7,
                "props": {"text": "A"},
                "reason": "Item 1",
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 10.0,
                "end": 10.7,
                "props": {"text": "B"},
                "reason": "Item 2",
            },
            {
                "id": "p3",
                "type": "checklist",
                "start": 16.0,
                "end": 22.0,
                "props": {
                    "title": "C",
                    "items": [{"text": "1", "done_at": 17.0}, {"text": "2", "done_at": 19.0}],
                },
                "reason": "Item 3",
            },
            {
                "id": "p4",
                "type": "checklist",
                "start": 35.0,
                "end": 41.0,
                "props": {
                    "title": "D",
                    "items": [{"text": "1", "done_at": 36.0}, {"text": "2", "done_at": 38.0}],
                },
                "reason": "Item 4 melebihi max 3",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = rep["clips"][0]["items"]
        self.assertEqual(items[0]["status"], "accepted")
        self.assertEqual(items[1]["status"], "accepted")
        self.assertEqual(items[2]["status"], "accepted")
        self.assertEqual(items[3]["status"], "rejected")
        self.assertTrue(any("anggaran" in e.lower() for e in items[3]["errors"]))

    def test_rule3_budget_max_accent_per_clip(self) -> None:
        edl = self._make_edl()
        # MAX_ACCENT_PER_CLIP = 2. Coba kirim 3 zoom_through_text
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 4.0,
                "end": 4.7,
                "props": {"text": "Satu"},
                "reason": "Aksen 1",
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 10.0,
                "end": 10.7,
                "props": {"text": "Dua"},
                "reason": "Aksen 2",
            },
            {
                "id": "p3",
                "type": "zoom_through_text",
                "start": 16.0,
                "end": 16.7,
                "props": {"text": "Tiga"},
                "reason": "Aksen 3 melebihi batas accent (2)",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = rep["clips"][0]["items"]
        self.assertEqual(items[0]["status"], "accepted")
        self.assertEqual(items[1]["status"], "accepted")
        self.assertEqual(items[2]["status"], "rejected")
        self.assertTrue(any("accent" in e.lower() or "anggaran" in e.lower() for e in items[2]["errors"]))

    # -----------------------------------------------------------------------
    # Aturan 4: Tumpang tindih dan jarak minimum
    # -----------------------------------------------------------------------
    def test_rule4_overlap_between_plan_items(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 5.0,
                "end": 6.0,
                "props": {"text": "Awal"},
                "reason": "Mulai duluan",
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 5.5,
                "end": 6.5,
                "props": {"text": "Tumpuk"},
                "reason": "Tumpang tindih dengan p1",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = rep["clips"][0]["items"]
        self.assertEqual(items[0]["status"], "accepted")
        self.assertEqual(items[1]["status"], "rejected")
        self.assertTrue(any("tumpang tindih" in e.lower() or "overlap" in e.lower() for e in items[1]["errors"]))

    def test_rule4_min_gap_between_overlays(self) -> None:
        edl = self._make_edl()
        # MIN_GAP_SECONDS = 4.0s. Item 1 berakhir 5.0, item 2 mulai 7.0 (gap = 2.0s < 4.0s)
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 4.0,
                "end": 5.0,
                "props": {"text": "A"},
                "reason": "Item 1",
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 7.0,
                "end": 7.7,
                "props": {"text": "B"},
                "reason": "Gap 2.0s < 4.0s",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = rep["clips"][0]["items"]
        self.assertEqual(items[0]["status"], "accepted")
        self.assertEqual(items[1]["status"], "rejected")
        self.assertTrue(any("jarak" in e.lower() or "gap" in e.lower() for e in items[1]["errors"]))

    def test_rule4_card_min_gap_between_cards(self) -> None:
        edl = self._make_edl()
        # CARD_MIN_GAP_SECONDS = 10.0s. Kartu 1 selesai di 11.0, kartu 2 mulai di 17.0 (gap = 6.0s < 10.0s)
        plan = self._make_plan([
            {
                "id": "c1",
                "type": "checklist",
                "start": 5.0,
                "end": 11.0,
                "props": {
                    "title": "K1",
                    "items": [{"text": "1", "done_at": 6.0}, {"text": "2", "done_at": 8.0}],
                },
                "reason": "Kartu 1",
            },
            {
                "id": "c2",
                "type": "checklist",
                "start": 17.0,
                "end": 23.0,
                "props": {
                    "title": "K2",
                    "items": [{"text": "1", "done_at": 18.0}, {"text": "2", "done_at": 20.0}],
                },
                "reason": "Kartu 2 jarak 6s < 10s",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = rep["clips"][0]["items"]
        self.assertEqual(items[0]["status"], "accepted")
        self.assertEqual(items[1]["status"], "rejected")
        self.assertTrue(any("jarak" in e.lower() or "kartu" in e.lower() for e in items[1]["errors"]))

    def test_rule4_conflict_with_existing_edl_vs_overlay(self) -> None:
        # EDL memiliki overlay VS di 1.0..4.0
        edl = self._make_edl(overlays=[
            {"type": "vs", "start": 1.0, "end": 4.0, "left": "A", "right": "B"}
        ])
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 3.0,
                "end": 3.7,
                "props": {"text": "Kalah"},
                "reason": "Beririsan dengan VS tier-1",
            }
        ])
        rep = fxplan.validate(edl, plan)
        items = rep["clips"][0]["items"]
        self.assertEqual(items[0]["status"], "rejected")
        self.assertTrue(any("edl" in e.lower() or "tumpang tindih" in e.lower() for e in items[0]["errors"]))

    def test_rule4_conflict_resolved_by_start_order(self) -> None:
        edl = self._make_edl()
        # Item 'late' ditulis pertama di plan tapi start=10.0; item 'early' ditulis kedua tapi start=4.0
        # Keduanya berjarak hanya 2 detik (4.0-4.7 dan 6.0-6.7).
        # Yang start=4.0 harus MENANG walau di urutan belakang JSON!
        plan = self._make_plan([
            {
                "id": "second_in_time",
                "type": "zoom_through_text",
                "start": 6.0,
                "end": 6.7,
                "props": {"text": "B"},
                "reason": "Ditulis lebih awal di JSON tapi waktu lebih akhir",
            },
            {
                "id": "first_in_time",
                "type": "zoom_through_text",
                "start": 4.0,
                "end": 4.7,
                "props": {"text": "A"},
                "reason": "Ditulis belakangan tapi waktu lebih awal",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = {it["id"]: it for it in rep["clips"][0]["items"]}
        self.assertEqual(items["first_in_time"]["status"], "accepted")
        self.assertEqual(items["second_in_time"]["status"], "rejected")

    # -----------------------------------------------------------------------
    # Aturan 5: Jendela Hook
    # -----------------------------------------------------------------------
    def test_rule5_hook_window_card_and_transform(self) -> None:
        edl = self._make_edl()
        # HOOK_WINDOW_SECONDS = 2.0s
        # 1. Kartu mulai 1.0s tanpa hook=True -> ditolak
        plan_no_hook = self._make_plan([
            {
                "id": "card_no_hook",
                "type": "checklist",
                "start": 1.0,
                "end": 7.0,
                "props": {
                    "title": "T",
                    "items": [{"text": "1", "done_at": 2.0}, {"text": "2", "done_at": 4.0}],
                },
                "reason": "Kartu tanpa hook=True",
                "hook": False,
            }
        ])
        rep_no_hook = fxplan.validate(edl, plan_no_hook)
        self.assertEqual(rep_no_hook["clips"][0]["items"][0]["status"], "rejected")
        self.assertTrue(any("hook" in e.lower() for e in rep_no_hook["clips"][0]["items"][0]["errors"]))

        # 2. Kartu mulai 1.0s dengan hook=True -> accepted_with_warnings
        plan_with_hook = self._make_plan([
            {
                "id": "card_with_hook",
                "type": "checklist",
                "start": 1.0,
                "end": 7.0,
                "props": {
                    "title": "T",
                    "items": [{"text": "1", "done_at": 2.0}, {"text": "2", "done_at": 4.0}],
                },
                "reason": "Kartu dengan hook=True",
                "hook": True,
            }
        ])
        rep_with_hook = fxplan.validate(edl, plan_with_hook)
        self.assertEqual(rep_with_hook["clips"][0]["items"][0]["status"], "accepted_with_warnings")
        self.assertTrue(any("hook" in w.lower() for w in rep_with_hook["clips"][0]["items"][0]["warnings"]))

        # 3. Aksen mulai 0.8s tanpa hook -> diterima (accent boleh di hook window)
        plan_accent = self._make_plan([
            {
                "id": "accent_in_hook",
                "type": "zoom_through_text",
                "start": 0.8,
                "end": 1.5,
                "props": {"text": "Boom!"},
                "reason": "Aksen di hook window",
            }
        ])
        rep_accent = fxplan.validate(edl, plan_accent)
        self.assertEqual(rep_accent["clips"][0]["items"][0]["status"], "accepted")

    # -----------------------------------------------------------------------
    # Aturan 6: Gerbang Close-Up
    # -----------------------------------------------------------------------
    def test_rule6_no_face_track_card_without_rect_rejected(self) -> None:
        # Tanpa face_track sama sekali
        edl = self._make_edl(reframe={})
        plan = self._make_plan([
            {
                "id": "c1",
                "type": "checklist",
                "start": 5.0,
                "end": 11.0,
                "props": {
                    "title": "T",
                    "items": [{"text": "1", "done_at": 6.0}, {"text": "2", "done_at": 8.0}],
                },
                "reason": "Kartu tanpa rect pada edl tanpa face_track",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "rejected")
        self.assertTrue(any("face_track" in e.lower() for e in item["errors"]))

    def test_rule6_no_face_track_card_with_rect_warning(self) -> None:
        edl = self._make_edl(reframe={})
        plan = self._make_plan([
            {
                "id": "c1",
                "type": "checklist",
                "start": 5.0,
                "end": 11.0,
                "props": {
                    "title": "T",
                    "items": [{"text": "1", "done_at": 6.0}, {"text": "2", "done_at": 8.0}],
                },
                "rect": {"x": 60.0, "y": 260.0, "w": 960.0, "h": 320.0},
                "reason": "Kartu dengan rect eksplisit pada edl tanpa face_track",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted_with_warnings")
        self.assertTrue(any("face_track" in w.lower() for w in item["warnings"]))

    def test_rule6_close_up_card_without_rect_rejected(self) -> None:
        # Wajah besar: close-up (tinggi 900px > 0.35 * 1920)
        edl = self._make_edl(reframe={
            "face_track": [
                {"t": 0.0, "faces": [{"x": 100.0, "y": 200.0, "w": 880.0, "h": 900.0}]}
            ]
        })
        plan = self._make_plan([
            {
                "id": "c1",
                "type": "checklist",
                "start": 5.0,
                "end": 11.0,
                "props": {
                    "title": "T",
                    "items": [{"text": "1", "done_at": 6.0}, {"text": "2", "done_at": 8.0}],
                },
                "reason": "Kartu tanpa rect di close-up",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "rejected")
        self.assertTrue(any("close-up" in e.lower() or "close_up" in e.lower() for e in item["errors"]))

    def test_rule6_explicit_rect_overlapping_face_warning(self) -> None:
        # Wajah di x=100, y=200, w=880, h=900
        # rect eksplisit berimpit: x=200, y=300, w=500, h=400
        edl = self._make_edl(reframe={
            "face_track": [
                {"t": 0.0, "faces": [{"x": 100.0, "y": 200.0, "w": 880.0, "h": 900.0}]}
            ]
        })
        plan = self._make_plan([
            {
                "id": "c1",
                "type": "checklist",
                "start": 5.0,
                "end": 11.0,
                "props": {
                    "title": "T",
                    "items": [{"text": "1", "done_at": 6.0}, {"text": "2", "done_at": 8.0}],
                },
                "rect": {"x": 200.0, "y": 300.0, "w": 500.0, "h": 400.0},
                "reason": "Rect sengaja berimpit wajah",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted_with_warnings")
        self.assertTrue(any("%" in w for w in item["warnings"]))

    def test_rule6_rect_exceeding_canvas_error(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "c1",
                "type": "checklist",
                "start": 5.0,
                "end": 11.0,
                "props": {
                    "title": "T",
                    "items": [{"text": "1", "done_at": 6.0}, {"text": "2", "done_at": 8.0}],
                },
                "rect": {"x": 500.0, "y": 1700.0, "w": 800.0, "h": 400.0},  # Melewati kanvas y=2100 > 1920
                "reason": "Rect melewati kanvas",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "rejected")
        self.assertTrue(any("kanvas" in e.lower() for e in item["errors"]))

    # -----------------------------------------------------------------------
    # Aturan 7: Pullback
    # -----------------------------------------------------------------------
    def test_rule7_pullback_stable_phase_too_short(self) -> None:
        edl = self._make_edl()
        # DEFAULT_SHRINK = 0.6, DEFAULT_GROW = 0.5.
        # MIN_STABLE_SECONDS_PULLBACK = 1.5s
        # Total minimum window untuk fase stabil = 0.6 + 1.5 + 0.5 = 2.6s.
        # Jika start=5.0, end=7.4 -> durasi 2.4s -> fase stabil = 2.4 - 1.1 = 1.3s < 1.5s -> error!
        plan = self._make_plan([
            {
                "id": "pb1",
                "type": "pullback",
                "start": 5.0,
                "end": 7.4,
                "props": {"from": 10.0, "to": 50.0},
                "reason": "Pullback fase stabil terlalu pendek",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "rejected")
        self.assertTrue(any("stabil" in e.lower() for e in item["errors"]))

    def test_rule7_pullback_valid_accepted(self) -> None:
        edl = self._make_edl()
        # Durasi 6 detik: stabil = 6.0 - 1.1 = 4.9s >= 1.5s
        plan = self._make_plan([
            {
                "id": "pb1",
                "type": "pullback",
                "start": 5.0,
                "end": 11.0,
                "props": {"from": 10.0, "to": 50.0, "title": "Omset", "suffix": "Jt"},
                "reason": "Statistik omset melonjak",
            }
        ])
        rep = fxplan.validate(edl, plan)
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted")
        self.assertIsNotNone(item["overlay"])

    # -----------------------------------------------------------------------
    # Aturan 8: Peringatan Non-fatal
    # -----------------------------------------------------------------------
    def test_rule8_near_clip_edge_and_punch_and_moment(self) -> None:
        edl = self._make_edl(
            punch=[{"t": 10.0, "scale": 1.2}],
        )
        candidates = {
            "version": "0.1.0",
            "clips": [
                {
                    "clip_id": "clip_04",
                    "moments": [{"id": "m001"}],
                }
            ],
        }
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 0.2,  # <= 0.5s dari awal klip
                "end": 0.9,
                "props": {"text": "Awal"},
                "reason": "Dekat awal klip",
                "moment": "m_gaib",  # Momen tidak ada di candidates
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 10.2,  # Berimpit dengan punch di 10.0 (|10.2 - 10.0| = 0.2 <= 0.3)
                "end": 10.9,
                "props": {"text": "Punch"},
                "reason": "Dekat punch",
                "moment": "m001",  # Ada di candidates
            },
        ])
        rep = fxplan.validate(edl, plan, candidates=candidates)
        items = {it["id"]: it for it in rep["clips"][0]["items"]}

        # p1: warning awal klip + warning momen tidak ada
        self.assertEqual(items["p1"]["status"], "accepted_with_warnings")
        self.assertTrue(any("awal" in w.lower() for w in items["p1"]["warnings"]))
        self.assertTrue(any("momen" in w.lower() for w in items["p1"]["warnings"]))

        # p2: warning punch
        self.assertEqual(items["p2"]["status"], "accepted_with_warnings")
        self.assertTrue(any("punch" in w.lower() for w in items["p2"]["warnings"]))

    def test_rule8_duration_exceeding_max_warning_vs_error(self) -> None:
        edl = self._make_edl()
        # zoom_through_text: max = 1.5s, 1.5 * 1.5 = 2.25s.
        # Kasus A: durasi = 1.8s (> 1.5s tapi <= 2.25s) -> accepted_with_warnings
        # Kasus B: durasi = 2.5s (> 2.25s) -> rejected (error)
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 5.0,
                "end": 6.8,
                "props": {"text": "Panjang"},
                "reason": "Durasi agak panjang",
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 15.0,
                "end": 17.5,
                "props": {"text": "Kelewat"},
                "reason": "Durasi lewat 1.5x max",
            },
        ])
        rep = fxplan.validate(edl, plan)
        items = {it["id"]: it for it in rep["clips"][0]["items"]}
        self.assertEqual(items["p1"]["status"], "accepted_with_warnings")
        self.assertTrue(any("durasi" in w.lower() or "panjang" in w.lower() for w in items["p1"]["warnings"]))

        self.assertEqual(items["p2"]["status"], "rejected")
        self.assertTrue(any("durasi" in e.lower() or "max" in e.lower() for e in items["p2"]["errors"]))

    # -----------------------------------------------------------------------
    # Aturan 9: Kontrak EDL Overlay & Validasi Skema Report & Immutability
    # -----------------------------------------------------------------------
    def test_report_and_overlay_conform_to_schemas(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 5.0,
                "end": 5.7,
                "props": {"text": "Lolos"},
                "reason": "Aksen kata",
            },
            {
                "id": "p2",
                "type": "zoom_through_text",
                "start": 5.2,
                "end": 5.9,
                "props": {"text": "Tolak"},
                "reason": "Konflik",
            },
        ])
        rep = fxplan.validate(edl, plan)

        # Lolos skema fx_plan_report
        undeclared = undeclared_keys(self.report_schema, rep)
        self.assertEqual(undeclared, [], f"Kunci laporan tak terdaftar: {undeclared}")
        missing = missing_required(self.report_schema, rep)
        self.assertEqual(missing, [], f"Field wajib laporan kurang: {missing}")

        # Item yang accepted memiliki overlay yang sah menurut edl.schema.json
        accepted_item = rep["clips"][0]["items"][0]
        ov = accepted_item["overlay"]
        self.assertIsNotNone(ov)
        self.assertNotIn("id", ov)
        self.assertNotIn("reason", ov)
        self.assertNotIn("status", ov)
        self.assertIn("type", ov)
        self.assertIn("start", ov)
        self.assertIn("end", ov)
        self.assertIn("props", ov)

        # Item yang rejected memiliki overlay = None
        rejected_item = rep["clips"][0]["items"][1]
        self.assertIsNone(rejected_item["overlay"])

    def test_immutability_and_determinism(self) -> None:
        edl = self._make_edl()
        plan = self._make_plan([
            {
                "id": "p1",
                "type": "zoom_through_text",
                "start": 5.0,
                "end": 5.7,
                "props": {"text": "A"},
                "reason": "Deterministik",
            }
        ])
        edl_before = copy.deepcopy(edl)
        plan_before = copy.deepcopy(plan)

        rep1 = fxplan.validate(edl, plan)
        rep2 = fxplan.validate(edl, plan)

        self.assertEqual(rep1, rep2)
        self.assertEqual(edl, edl_before)
        self.assertEqual(plan, plan_before)

    def test_rule10_card_overlay_intersects_caption_zone(self) -> None:
        edl = self._make_edl(
            captions=[
                {
                    "start": 5.0,
                    "end": 8.0,
                    "text": "Tahu nggak kenapa ini terjadi?",
                    "words": [
                        {"w": "Tahu", "start": 5.0, "end": 5.5},
                        {"w": "nggak", "start": 5.6, "end": 6.2},
                        {"w": "kenapa", "start": 6.3, "end": 6.9},
                        {"w": "ini", "start": 7.0, "end": 7.4},
                        {"w": "terjadi?", "start": 7.5, "end": 8.0},
                    ],
                }
            ]
        )
        plan = self._make_plan([
            {
                "id": "card_warn",
                "type": "checklist",
                "start": 5.0,
                "end": 9.0,
                "rect": {"x": 60.0, "y": 1300.0, "w": 960.0, "h": 320.0},
                "props": {
                    "title": "Daftar Alasan",
                    "items": [
                        {"text": "Poin pertama", "done_at": 6.0},
                        {"text": "Poin kedua", "done_at": 7.5},
                    ],
                },
                "reason": "Uji irisan caption",
            }
        ])
        rep = fxplan.validate(edl, plan)
        self.assertEqual(undeclared_keys(self.report_schema, rep), [])
        self.assertEqual(missing_required(self.report_schema, rep), [])
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted_with_warnings")
        self.assertIsNotNone(item["overlay"])
        self.assertEqual(rep["summary"]["accepted_with_warnings"], 1)
        self.assertEqual(rep["summary"]["accepted"], 0)
        self.assertTrue(
            any("kotak caption" in w and "%" in w and "frasa [" in w for w in item["warnings"]),
            msg=str(item["warnings"]),
        )

    def test_rule10_card_overlay_disjoint_time_no_caption_warning(self) -> None:
        edl = self._make_edl(
            reframe={"face_track": [{"t": 0.0, "faces": [{"x": 450.0, "y": 300.0, "w": 180.0, "h": 250.0}]}]},
            captions=[
                {
                    "start": 1.0,
                    "end": 3.0,
                    "text": "Frasa awal",
                    "words": [
                        {"w": "Frasa", "start": 1.0, "end": 1.8},
                        {"w": "awal", "start": 2.0, "end": 3.0},
                    ],
                }
            ]
        )
        plan = self._make_plan([
            {
                "id": "card_ok",
                "type": "checklist",
                "start": 15.0,
                "end": 20.0,
                "rect": {"x": 60.0, "y": 1300.0, "w": 960.0, "h": 320.0},
                "props": {
                    "title": "Daftar Alasan",
                    "items": [
                        {"text": "Poin pertama", "done_at": 16.0},
                        {"text": "Poin kedua", "done_at": 18.0},
                    ],
                },
                "reason": "Waktu tidak beririsan",
            }
        ])
        rep = fxplan.validate(edl, plan)
        self.assertEqual(undeclared_keys(self.report_schema, rep), [])
        self.assertEqual(missing_required(self.report_schema, rep), [])
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted")
        self.assertFalse(any("kotak caption" in w for w in item["warnings"]))

    def test_rule10_tier1_captions_without_words_skipped_gracefully(self) -> None:
        edl = self._make_edl(
            reframe={"face_track": [{"t": 0.0, "faces": [{"x": 450.0, "y": 300.0, "w": 180.0, "h": 250.0}]}]},
            captions=[
                {
                    "start": 5.0,
                    "end": 8.0,
                    "text": "Caption tier-1 tanpa kata",
                }
            ]
        )
        plan = self._make_plan([
            {
                "id": "card_tier1",
                "type": "checklist",
                "start": 5.0,
                "end": 9.0,
                "rect": {"x": 60.0, "y": 1300.0, "w": 960.0, "h": 320.0},
                "props": {
                    "title": "Daftar Alasan",
                    "items": [
                        {"text": "Poin pertama", "done_at": 6.0},
                        {"text": "Poin kedua", "done_at": 7.5},
                    ],
                },
                "reason": "Uji tier-1 tanpa words",
            }
        ])
        rep = fxplan.validate(edl, plan)
        self.assertEqual(undeclared_keys(self.report_schema, rep), [])
        self.assertEqual(missing_required(self.report_schema, rep), [])
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted")
        self.assertFalse(any("kotak caption" in w for w in item["warnings"]))

    def test_rule10_phone_frame_intersects_caption_zone(self) -> None:
        edl = self._make_edl(
            captions=[
                {
                    "start": 5.0,
                    "end": 8.0,
                    "text": "Buka aplikasi sekarang juga",
                    "words": [
                        {"w": "Buka", "start": 5.0, "end": 5.5},
                        {"w": "aplikasi", "start": 5.6, "end": 6.3},
                        {"w": "sekarang", "start": 6.4, "end": 7.1},
                        {"w": "juga", "start": 7.2, "end": 8.0},
                    ],
                }
            ]
        )
        plan = self._make_plan([
            {
                "id": "phone_warn",
                "type": "phone_frame",
                "start": 5.0,
                "end": 10.0,
                "rect": {"x": 180.0, "y": 1100.0, "w": 720.0, "h": 700.0},
                "props": {
                    "title": "Aplikasi Ponsel",
                    "lines": ["Pesan 1", "Pesan 2", "Pesan 3"],
                },
                "reason": "Ponsel tumpang tindih caption",
            }
        ])
        rep = fxplan.validate(edl, plan)
        self.assertEqual(undeclared_keys(self.report_schema, rep), [])
        self.assertEqual(missing_required(self.report_schema, rep), [])
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted_with_warnings")
        self.assertTrue(any("kotak caption" in w for w in item["warnings"]))

    def test_load_plan_and_report_markdown(self) -> None:
        import tempfile
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as tf:
            json.dump({"version": 1, "mode": "suggest", "clips": []}, tf)
            tf.flush()
            loaded = fxplan.load_plan(tf.name)
            self.assertEqual(loaded["version"], 1)

        rep = {
            "version": 1,
            "edl": "edl.json",
            "plan": "fx_plan.json",
            "clips": [
                {
                    "clip_id": "clip_04",
                    "duration": 50.0,
                    "items": [
                        {
                            "id": "p1",
                            "status": "accepted",
                            "errors": [],
                            "warnings": [],
                            "overlay": {"type": "zoom_through_text", "start": 1.0, "end": 1.7},
                            "reason": "Uji md",
                            "moment": "m001",
                        }
                    ],
                }
            ],
            "summary": {"accepted": 1, "accepted_with_warnings": 0, "rejected": 0},
        }
        md = fxplan.report_markdown(rep)
        self.assertIn("# Laporan Pengesahan Rencana Efek", md)
        self.assertIn("clip_04", md)
        self.assertIn("p1", md)


if __name__ == "__main__":
    unittest.main()
