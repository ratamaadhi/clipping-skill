"""Validasi skema JSON untuk fx_plan.schema.json dan fx_plan_report.schema.json."""

from __future__ import annotations

import json
import unittest
from typing import Any

from tests.helpers import ROOT
from tests.test_schema_drift import missing_required, undeclared_keys

PLAN_SCHEMA_PATH = ROOT / "schema" / "fx_plan.schema.json"
REPORT_SCHEMA_PATH = ROOT / "schema" / "fx_plan_report.schema.json"


def load_plan_schema() -> dict[str, Any]:
    with open(PLAN_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_report_schema() -> dict[str, Any]:
    with open(REPORT_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class FxPlanSchemaTest(unittest.TestCase):
    """Pengujian skema fx_plan.schema.json."""

    def setUp(self) -> None:
        self.schema = load_plan_schema()

    def test_valid_synthetic_plan_passes(self) -> None:
        doc = {
            "version": 1,
            "mode": "suggest",
            "clips": [
                {
                    "clip_id": "clip_04",
                    "items": [
                        {
                            "id": "p1",
                            "type": "checklist",
                            "start": 8.0,
                            "end": 13.0,
                            "props": {
                                "title": "Langkah Kerja",
                                "items": [
                                    {"text": "Persiapan", "done_at": 9.0},
                                    {"text": "Pelaksanaan", "done_at": 11.0},
                                ],
                            },
                            "rect": {"x": 60.0, "y": 260.0, "w": 960.0, "h": 320.0},
                            "reason": "Daftar 2 butir berurutan",
                            "moment": "m001",
                            "hook": False,
                        }
                    ],
                }
            ],
        }
        undeclared = undeclared_keys(self.schema, doc)
        self.assertEqual(undeclared, [], f"Kunci tak terdaftar: {undeclared}")
        missing = missing_required(self.schema, doc)
        self.assertEqual(missing, [], f"Field wajib kurang: {missing}")

    def test_plan_missing_reason_rejected(self) -> None:
        doc = {
            "version": 1,
            "mode": "suggest",
            "clips": [
                {
                    "clip_id": "clip_04",
                    "items": [
                        {
                            "id": "p1",
                            "type": "zoom_through_text",
                            "start": 3.0,
                            "end": 3.7,
                            "props": {"text": "Fokus!"},
                        }
                    ],
                }
            ],
        }
        missing = missing_required(self.schema, doc)
        self.assertIn("clips[0].items[0].reason", missing)

    def test_plan_undeclared_key_rejected(self) -> None:
        doc = {
            "version": 1,
            "mode": "suggest",
            "kunci_liar": "nilai",
            "clips": [],
        }
        undeclared = undeclared_keys(self.schema, doc)
        self.assertIn("kunci_liar", undeclared)


class FxPlanReportSchemaTest(unittest.TestCase):
    """Pengujian skema fx_plan_report.schema.json."""

    def setUp(self) -> None:
        self.schema = load_report_schema()

    def test_valid_synthetic_report_passes(self) -> None:
        doc = {
            "version": 1,
            "edl": "edl.json",
            "plan": "fx_plan.json",
            "clips": [
                {
                    "clip_id": "clip_04",
                    "duration": 52.0,
                    "items": [
                        {
                            "id": "p1",
                            "status": "accepted",
                            "errors": [],
                            "warnings": [],
                            "overlay": {
                                "type": "zoom_through_text",
                                "start": 2.82,
                                "end": 3.52,
                                "props": {"text": "nggak"},
                            },
                            "reason": "Penekanan kata kunci",
                            "moment": "m001",
                        },
                        {
                            "id": "p2",
                            "status": "rejected",
                            "errors": ["close-up: tidak ada area bebas"],
                            "warnings": [],
                            "overlay": None,
                            "reason": "Daftar langkah",
                            "moment": None,
                        },
                    ],
                }
            ],
            "summary": {
                "accepted": 1,
                "accepted_with_warnings": 0,
                "rejected": 1,
            },
        }
        undeclared = undeclared_keys(self.schema, doc)
        self.assertEqual(undeclared, [], f"Kunci tak terdaftar: {undeclared}")
        missing = missing_required(self.schema, doc)
        self.assertEqual(missing, [], f"Field wajib kurang: {missing}")

    def test_report_missing_summary_fields(self) -> None:
        doc = {
            "version": 1,
            "edl": "edl.json",
            "plan": "fx_plan.json",
            "clips": [],
            "summary": {
                "accepted": 1,
            },
        }
        missing = missing_required(self.schema, doc)
        self.assertIn("summary.accepted_with_warnings", missing)
        self.assertIn("summary.rejected", missing)


if __name__ == "__main__":
    unittest.main()
