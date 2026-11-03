"""Validasi schema untuk fx_candidates.schema.json."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import ROOT
from tests.test_schema_drift import missing_required, undeclared_keys

SCHEMA_PATH = ROOT / "schema" / "fx_candidates.schema.json"


def load_fx_schema() -> dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class FxCandidatesSchemaTest(unittest.TestCase):
    """Pengujian schema fx_candidates dan penjelajah drift."""

    def setUp(self) -> None:
        self.schema = load_fx_schema()

    def test_schema_loads_and_has_defs(self) -> None:
        self.assertEqual(self.schema.get("title"), "FxCandidates")
        self.assertIn("$defs", self.schema)
        self.assertIn("ClipCandidates", self.schema["$defs"])
        self.assertIn("Moment", self.schema["$defs"])
        self.assertIn("EffectFit", self.schema["$defs"])

    def test_valid_synthetic_fx_candidates_passes(self) -> None:
        doc = {
            "version": "0.1.0",
            "clips": [
                {
                    "clip_id": "clip_01",
                    "duration": 30.0,
                    "fps": 30.0,
                    "time_precision": "word",
                    "hook_window": [0.0, 2.0],
                    "shots": [
                        {
                            "t0": 0.0,
                            "t1": 30.0,
                            "shot_kind": "close_up",
                            "face_height_ratio": 0.45,
                            "face_bbox": {"x": 200.0, "y": 300.0, "w": 400.0, "h": 864.0},
                        }
                    ],
                    "moments": [
                        {
                            "id": "m001",
                            "t0": 5.0,
                            "t1": 7.0,
                            "trigger_duration": 2.0,
                            "trigger": "number",
                            "text": "100 persen berhasil",
                            "confidence": 0.95,
                            "evidence": {"matched": "100 persen"},
                            "shot_kind": "close_up",
                            "in_hook_window": False,
                            "near_punch": False,
                            "available_window": {
                                "start": 5.0,
                                "end": 29.6,
                                "limited_by": "clip_end",
                            },
                            "fits": {
                                "zoom_through_text": {
                                    "ok": True,
                                    "reason": "efek tidak membutuhkan area bebas",
                                    "rect": None,
                                    "suggested_window": {"start": 5.0, "end": 5.7},
                                },
                                "checklist": {
                                    "ok": False,
                                    "reason": "close_up: tidak ada slot bebas untuk kartu",
                                    "rect": None,
                                    "suggested_window": None,
                                },
                            },
                        }
                    ],
                    "existing_overlays": [],
                    "notes": ["Semua momen lolos batas"],
                }
            ],
        }

        undeclared = undeclared_keys(self.schema, doc)
        self.assertEqual(undeclared, [], f"Kunci tak terdaftar: {undeclared}")

        missing = missing_required(self.schema, doc)
        self.assertEqual(missing, [], f"Field wajib kurang: {missing}")

    def test_undeclared_key_rejected(self) -> None:
        doc = {
            "version": "0.1.0",
            "clips": [],
            "kunci_liar": 123,
        }
        undeclared = undeclared_keys(self.schema, doc)
        self.assertIn("kunci_liar", undeclared)


if __name__ == "__main__":
    unittest.main()
