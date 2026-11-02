"""Tes unit murni untuk scripts/fxapply.py.

Menguji pengesahan laporan, seleksi item, manipulasi EDL murni,
pemeriksaan kesegaran durasi, validasi skema overlay tanpa jsonschema,
penerapan atomik dan persetujuan, serta undo.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.helpers import ROOT

from scripts.lib import jsonio
from scripts import fxapply
from scripts.fxapply import (
    ApprovalRequired,
    FxApplyError,
    StaleReport,
    apply,
    apply_to_edl,
    check_fresh,
    load_report,
    preview,
    select,
    undo,
    validate_edl_overlays,
)


def _make_report(
    *,
    clips: list[dict[str, Any]] | None = None,
    summary: dict[str, int] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    if clips is None:
        clips = [
            {
                "clip_id": "clip_01",
                "duration": 5.0,
                "items": [
                    {
                        "id": "p1",
                        "status": "accepted",
                        "errors": [],
                        "warnings": [],
                        "overlay": {
                            "type": "zoom_through_text",
                            "start": 1.0,
                            "end": 2.0,
                            "props": {"text": "5 JAM"},
                        },
                        "reason": "momen angka kunci",
                        "moment": "m1",
                    },
                    {
                        "id": "p2",
                        "status": "accepted_with_warnings",
                        "errors": [],
                        "warnings": ["wajah dekat margin"],
                        "overlay": {
                            "type": "chart_grow",
                            "start": 2.5,
                            "end": 4.0,
                            "props": {"values": [10, 20, 30]},
                        },
                        "reason": "tren kenaikan",
                        "moment": "m2",
                    },
                    {
                        "id": "p3",
                        "status": "rejected",
                        "errors": ["menutup wajah pada close-up"],
                        "warnings": [],
                        "overlay": None,
                        "reason": "tidak lolos gerbang",
                        "moment": "m3",
                    },
                ],
            }
        ]
    if summary is None:
        summary = {"accepted": 1, "accepted_with_warnings": 1, "rejected": 1}
    rep: dict[str, Any] = {
        "version": 1,
        "edl": "edl.json",
        "plan": "fx_plan.json",
        "clips": clips,
        "summary": summary,
    }
    rep.update(overrides)
    return rep


def _make_edl(
    *,
    clip_id: str = "clip_01",
    duration: float = 5.0,
    overlays: list[dict[str, Any]] | None = None,
    include_vs: bool = False,
) -> dict[str, Any]:
    ovs = list(overlays or [])
    if include_vs:
        ovs.insert(
            0,
            {
                "type": "vs",
                "start": 0.2,
                "end": 1.8,
                "left": "Codex",
                "right": "Claude",
            },
        )
    return {
        "version": "0.1.0",
        "source": {
            "path": "src.mp4",
            "duration": 10.0,
            "fps": 30.0,
            "width": 1920,
            "height": 1080,
            "audio_rate": 48000,
        },
        "output": {
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "loudness_lufs": -14.0,
            "true_peak_db": -1.0,
        },
        "clips": [
            {
                "id": clip_id,
                "segments": [
                    {"src_start": 0.0, "src_end": duration, "speed": 1.0}
                ],
                "caption_style": "kinetic",
                "reframe": {"mode": "center"},
                "punch": [],
                "progress": False,
                "captions": [],
                "overlays": ovs,
            }
        ],
    }


class TestLoadReport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_load_valid_report(self) -> None:
        rep = _make_report()
        p = self.tmp / "fx_plan.report.json"
        jsonio.write_json(p, rep)
        loaded = load_report(p)
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(len(loaded["clips"]), 1)
        self.assertEqual(loaded["clips"][0]["items"][0]["id"], "p1")

    def test_missing_report_file_raises_fxapplyerror(self) -> None:
        with self.assertRaises(FxApplyError):
            load_report(self.tmp / "nonexistent.json")

    def test_missing_required_top_key_raises_fxapplyerror(self) -> None:
        rep = _make_report()
        del rep["summary"]
        p = self.tmp / "report.json"
        jsonio.write_json(p, rep)
        with self.assertRaises(FxApplyError) as ctx:
            load_report(p)
        self.assertIn("summary", str(ctx.exception))

    def test_invalid_status_raises_fxapplyerror_naming_clip_and_item(self) -> None:
        rep = _make_report()
        rep["clips"][0]["items"][0]["status"] = "pending"
        p = self.tmp / "report.json"
        jsonio.write_json(p, rep)
        with self.assertRaises(FxApplyError) as ctx:
            load_report(p)
        msg = str(ctx.exception)
        self.assertIn("clip_01", msg)
        self.assertIn("p1", msg)
        self.assertIn("pending", msg)

    def test_rejected_with_overlay_raises_fxapplyerror(self) -> None:
        rep = _make_report()
        rep["clips"][0]["items"][2]["overlay"] = {
            "type": "zoom_through_text",
            "start": 0.5,
            "end": 1.5,
        }
        p = self.tmp / "report.json"
        jsonio.write_json(p, rep)
        with self.assertRaises(FxApplyError) as ctx:
            load_report(p)
        msg = str(ctx.exception)
        self.assertIn("clip_01", msg)
        self.assertIn("p3", msg)
        self.assertIn("rejected", msg)

    def test_accepted_with_null_overlay_raises_fxapplyerror(self) -> None:
        rep = _make_report()
        rep["clips"][0]["items"][0]["overlay"] = None
        p = self.tmp / "report.json"
        jsonio.write_json(p, rep)
        with self.assertRaises(FxApplyError) as ctx:
            load_report(p)
        msg = str(ctx.exception)
        self.assertIn("clip_01", msg)
        self.assertIn("p1", msg)

    def test_extra_key_on_overlay_raises_fxapplyerror(self) -> None:
        rep = _make_report()
        rep["clips"][0]["items"][0]["overlay"]["unsupported_key"] = "bad"
        p = self.tmp / "report.json"
        jsonio.write_json(p, rep)
        with self.assertRaises(FxApplyError) as ctx:
            load_report(p)
        msg = str(ctx.exception)
        self.assertIn("clip_01", msg)
        self.assertIn("p1", msg)
        self.assertIn("unsupported_key", msg)

    def test_extra_key_on_rect_raises_fxapplyerror(self) -> None:
        rep = _make_report()
        rep["clips"][0]["items"][0]["overlay"]["rect"] = {
            "x": 10,
            "y": 20,
            "w": 100,
            "h": 200,
            "radius": 5,
        }
        p = self.tmp / "report.json"
        jsonio.write_json(p, rep)
        with self.assertRaises(FxApplyError) as ctx:
            load_report(p)
        msg = str(ctx.exception)
        self.assertIn("clip_01", msg)
        self.assertIn("p1", msg)
        self.assertIn("radius", msg)


class TestSelect(unittest.TestCase):
    def setUp(self) -> None:
        self.report = _make_report()

    def test_select_default_includes_accepted_and_warnings(self) -> None:
        sel = select(self.report)
        self.assertIn("clip_01", sel)
        ids = [item["id"] for item in sel["clip_01"]]
        self.assertEqual(ids, ["p1", "p2"])
        # Deep copied
        self.assertIsNot(sel["clip_01"][0]["overlay"], self.report["clips"][0]["items"][0]["overlay"])

    def test_select_without_warnings(self) -> None:
        sel = select(self.report, include_warnings=False)
        self.assertIn("clip_01", sel)
        ids = [item["id"] for item in sel["clip_01"]]
        self.assertEqual(ids, ["p1"])

    def test_select_only_restricts_to_ids(self) -> None:
        sel = select(self.report, only=["p2"])
        ids = [item["id"] for item in sel["clip_01"]]
        self.assertEqual(ids, ["p2"])

    def test_select_only_missing_id_raises_fxapplyerror(self) -> None:
        with self.assertRaises(FxApplyError) as ctx:
            select(self.report, only=["p999"])
        self.assertIn("p999", str(ctx.exception))

    def test_select_only_rejected_id_raises_fxapplyerror(self) -> None:
        with self.assertRaises(FxApplyError) as ctx:
            select(self.report, only=["p3"])
        self.assertIn("p3", str(ctx.exception))

    def test_select_only_warnings_when_disallowed_raises_fxapplyerror(self) -> None:
        with self.assertRaises(FxApplyError) as ctx:
            select(self.report, only=["p2"], include_warnings=False)
        self.assertIn("p2", str(ctx.exception))


class TestApplyToEdl(unittest.TestCase):
    def test_apply_adds_overlays_and_preserves_existing_vs(self) -> None:
        edl = _make_edl(include_vs=True)
        rep = _make_report()
        sel = select(rep)
        new_edl, info = apply_to_edl(edl, sel)

        # Input edl must NOT be mutated
        self.assertEqual(len(edl["clips"][0]["overlays"]), 1)
        self.assertEqual(edl["clips"][0]["overlays"][0]["type"], "vs")

        # Output edl has vs + 2 added overlays = 3
        ovs = new_edl["clips"][0]["overlays"]
        self.assertEqual(len(ovs), 3)
        self.assertEqual(ovs[0]["type"], "vs")
        self.assertEqual(ovs[1]["type"], "zoom_through_text")
        self.assertEqual(ovs[2]["type"], "chart_grow")
        self.assertEqual(info["added"], ["p1", "p2"])
        self.assertEqual(info["skipped"], [])

    def test_apply_sorts_overlays_by_start(self) -> None:
        edl = _make_edl()
        selection = {
            "clip_01": [
                {
                    "id": "late",
                    "overlay": {"type": "pullback", "start": 3.0, "end": 4.5, "props": {"title": "X"}},
                    "reason": "r1",
                },
                {
                    "id": "early",
                    "overlay": {"type": "zoom_through_text", "start": 0.5, "end": 1.2, "props": {"text": "A"}},
                    "reason": "r2",
                },
            ]
        }
        new_edl, info = apply_to_edl(edl, selection)
        ovs = new_edl["clips"][0]["overlays"]
        self.assertEqual([o["type"] for o in ovs], ["zoom_through_text", "pullback"])
        self.assertEqual(info["added"], ["late", "early"])

    def test_apply_idempotent_skips_duplicates(self) -> None:
        edl = _make_edl()
        rep = _make_report()
        sel = select(rep)
        new_edl1, info1 = apply_to_edl(edl, sel)
        self.assertEqual(len(info1["added"]), 2)
        self.assertEqual(info1["skipped"], [])

        # Apply second time to new_edl1
        new_edl2, info2 = apply_to_edl(new_edl1, sel)
        self.assertEqual(len(new_edl2["clips"][0]["overlays"]), 2)
        self.assertEqual(info2["added"], [])
        self.assertEqual(info2["skipped"], ["p1", "p2"])

    def test_apply_differing_props_not_treated_as_duplicate(self) -> None:
        edl = _make_edl(clip_id="clip_01")
        edl["clips"][0]["overlays"] = [
            {"type": "zoom_through_text", "start": 1.0, "end": 2.0, "props": {"text": "A"}}
        ]
        selection = {
            "clip_01": [
                {
                    "id": "p_diff_props",
                    "overlay": {"type": "zoom_through_text", "start": 1.0, "end": 2.0, "props": {"text": "B"}},
                    "reason": "props berbeda",
                }
            ]
        }
        new_edl, info = apply_to_edl(edl, selection)
        self.assertEqual(info["added"], ["p_diff_props"])
        self.assertEqual(info["skipped"], [])
        self.assertEqual(len(new_edl["clips"][0]["overlays"]), 2)

    def test_apply_differing_rect_not_treated_as_duplicate(self) -> None:
        edl = _make_edl(clip_id="clip_01")
        edl["clips"][0]["overlays"] = [
            {
                "type": "ui_panel",
                "start": 2.0,
                "end": 4.0,
                "rect": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 400.0},
                "props": {"title": "Panel A"},
            }
        ]
        selection = {
            "clip_01": [
                {
                    "id": "p_diff_rect",
                    "overlay": {
                        "type": "ui_panel",
                        "start": 2.0,
                        "end": 4.0,
                        "rect": {"x": 50.0, "y": 200.0, "w": 300.0, "h": 400.0},
                        "props": {"title": "Panel A"},
                    },
                    "reason": "rect berbeda",
                }
            ]
        }
        new_edl, info = apply_to_edl(edl, selection)
        self.assertEqual(info["added"], ["p_diff_rect"])
        self.assertEqual(info["skipped"], [])
        self.assertEqual(len(new_edl["clips"][0]["overlays"]), 2)

    def test_apply_truly_identical_overlay_skipped_as_duplicate(self) -> None:
        edl = _make_edl(clip_id="clip_01")
        edl["clips"][0]["overlays"] = [
            {
                "type": "ui_panel",
                "start": 2.0,
                "end": 4.0,
                "rect": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 400.0},
                "props": {"title": "Panel A"},
            }
        ]
        selection = {
            "clip_01": [
                {
                    "id": "p_identical",
                    "overlay": {
                        "type": "ui_panel",
                        "start": 2.0,
                        "end": 4.0,
                        "rect": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 400.0},
                        "props": {"title": "Panel A"},
                    },
                    "reason": "benar-benar identik",
                }
            ]
        }
        new_edl, info = apply_to_edl(edl, selection)
        self.assertEqual(info["added"], [])
        self.assertEqual(info["skipped"], ["p_identical"])
        self.assertEqual(len(new_edl["clips"][0]["overlays"]), 1)

    def test_apply_unknown_clip_id_raises_fxapplyerror(self) -> None:
        edl = _make_edl(clip_id="clip_01")
        selection = {
            "clip_999": [
                {
                    "id": "p1",
                    "overlay": {"type": "zoom_through_text", "start": 1.0, "end": 2.0},
                    "reason": "r",
                }
            ]
        }
        with self.assertRaises(FxApplyError) as ctx:
            apply_to_edl(edl, selection)
        self.assertIn("clip_999", str(ctx.exception))


class TestCheckFresh(unittest.TestCase):
    def test_check_fresh_matching_duration_passes(self) -> None:
        edl = _make_edl(duration=5.0)
        rep = _make_report()
        rep["clips"][0]["duration"] = 5.005  # diff 0.005 <= 0.01
        check_fresh(edl, rep)

    def test_check_fresh_duration_mismatch_raises_stalereport(self) -> None:
        edl = _make_edl(duration=5.0)
        rep = _make_report()
        rep["clips"][0]["duration"] = 5.05  # diff 0.05 > 0.01
        with self.assertRaises(StaleReport) as ctx:
            check_fresh(edl, rep)
        self.assertIn("clip_01", str(ctx.exception))
        self.assertIn("0.01", str(ctx.exception))

    def test_check_fresh_missing_clip_raises_stalereport(self) -> None:
        edl = _make_edl(clip_id="clip_02")
        rep = _make_report()
        with self.assertRaises(StaleReport) as ctx:
            check_fresh(edl, rep)
        self.assertIn("clip_01", str(ctx.exception))


class TestValidateEdlOverlays(unittest.TestCase):
    def test_validate_valid_overlays_passes(self) -> None:
        edl = _make_edl(
            overlays=[
                {
                    "type": "zoom_through_text",
                    "renderer": "ffmpeg",
                    "start": 0.5,
                    "end": 1.5,
                    "props": {"text": "A"},
                },
                {
                    "type": "checklist",
                    "start": 2.0,
                    "end": 3.5,
                    "rect": {"x": 100, "y": 200, "w": 400, "h": 600},
                    "props": {"items": ["item 1", "item 2"]},
                },
            ]
        )
        validate_edl_overlays(edl)

    def test_validate_undeclared_key_raises_fxapplyerror(self) -> None:
        edl = _make_edl(
            overlays=[
                {
                    "type": "zoom_through_text",
                    "start": 0.5,
                    "end": 1.5,
                    "bogus_key": True,
                }
            ]
        )
        with self.assertRaises(FxApplyError) as ctx:
            validate_edl_overlays(edl)
        self.assertIn("bogus_key", str(ctx.exception))

    def test_validate_missing_type_raises_fxapplyerror(self) -> None:
        edl = _make_edl(overlays=[{"start": 0.5, "end": 1.5}])
        with self.assertRaises(FxApplyError) as ctx:
            validate_edl_overlays(edl)
        self.assertIn("type", str(ctx.exception))

    def test_validate_invalid_renderer_raises_fxapplyerror(self) -> None:
        edl = _make_edl(
            overlays=[
                {
                    "type": "zoom_through_text",
                    "renderer": "invalid_engine",
                    "start": 0.5,
                    "end": 1.5,
                }
            ]
        )
        with self.assertRaises(FxApplyError) as ctx:
            validate_edl_overlays(edl)
        self.assertIn("renderer", str(ctx.exception))

    def test_validate_negative_start_raises_fxapplyerror(self) -> None:
        edl = _make_edl(
            overlays=[
                {
                    "type": "zoom_through_text",
                    "start": -0.5,
                    "end": 1.5,
                }
            ]
        )
        with self.assertRaises(FxApplyError) as ctx:
            validate_edl_overlays(edl)
        self.assertIn("start", str(ctx.exception))

    def test_validate_invalid_rect_raises_fxapplyerror(self) -> None:
        edl = _make_edl(
            overlays=[
                {
                    "type": "zoom_through_text",
                    "start": 0.5,
                    "end": 1.5,
                    "rect": {"x": 10, "y": 20, "w": -5, "h": 100},
                }
            ]
        )
        with self.assertRaises(FxApplyError) as ctx:
            validate_edl_overlays(edl)
        self.assertIn("rect", str(ctx.exception))


class TestApplyAndUndo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = Path(self._tmp.name).resolve()
        self.edl = _make_edl(include_vs=True)
        self.edl_path = self.wd / "edl.json"
        jsonio.write_json(self.edl_path, self.edl)
        self.report = _make_report()
        self.rep_path = self.wd / "fx_plan.report.json"
        jsonio.write_json(self.rep_path, self.report)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_apply_without_approval_raises_and_leaves_edl_untouched(self) -> None:
        before_bytes = self.edl_path.read_bytes()
        with self.assertRaises(ApprovalRequired) as ctx:
            apply(self.wd, self.rep_path, approve=False)
        self.assertIn("persetujuan", str(ctx.exception).lower())
        after_bytes = self.edl_path.read_bytes()
        self.assertEqual(before_bytes, after_bytes)
        self.assertFalse((self.wd / "edl.json.bak_fx").exists())

    def test_apply_calls_check_fresh(self) -> None:
        # If duration is stale, apply must raise StaleReport even with approve=True
        self.report["clips"][0]["duration"] = 99.0
        jsonio.write_json(self.rep_path, self.report)
        with self.assertRaises(StaleReport):
            apply(self.wd, self.rep_path, approve=True)

    def test_apply_calls_validate_edl_overlays(self) -> None:
        # Pre-existing invalid overlay in EDL must be caught by validate_edl_overlays
        self.edl["clips"][0]["overlays"].append(
            {"type": "zoom_through_text", "invalid_key_xyz": 123}
        )
        jsonio.write_json(self.edl_path, self.edl)
        with self.assertRaises(FxApplyError) as ctx:
            apply(self.wd, self.rep_path, approve=True)
        self.assertIn("invalid_key_xyz", str(ctx.exception))

    def test_apply_preserves_existing_vs_overlay(self) -> None:
        apply(self.wd, self.rep_path, approve=True)
        saved = jsonio.read_json(self.edl_path)
        ovs = saved["clips"][0]["overlays"]
        vs_matches = [o for o in ovs if o["type"] == "vs"]
        self.assertEqual(len(vs_matches), 1)

    def test_apply_sorts_overlays_by_start(self) -> None:
        apply(self.wd, self.rep_path, approve=True)
        saved = jsonio.read_json(self.edl_path)
        ovs = saved["clips"][0]["overlays"]
        starts = [float(o["start"]) for o in ovs]
        self.assertEqual(starts, sorted(starts))

    def test_apply_with_approval_creates_backup_and_modifies_only_overlays(self) -> None:
        before_doc = jsonio.read_json(self.edl_path)
        res = apply(self.wd, self.rep_path, approve=True)

        self.assertEqual(res["status"], "applied")
        self.assertEqual(res["added"], ["p1", "p2"])
        backup_file = self.wd / "edl.json.bak_fx"
        self.assertTrue(backup_file.is_file())
        self.assertEqual(jsonio.read_json(backup_file), before_doc)

        after_doc = jsonio.read_json(self.edl_path)
        # Structural check: only clips[0].overlays changed!
        before_copy = copy.deepcopy(before_doc)
        after_copy = copy.deepcopy(after_doc)
        del before_copy["clips"][0]["overlays"]
        del after_copy["clips"][0]["overlays"]
        self.assertEqual(before_copy, after_copy)

        # Check applied plan metadata
        applied_file = self.wd / "fx_plan.applied.json"
        self.assertTrue(applied_file.is_file())
        applied_data = jsonio.read_json(applied_file)
        self.assertEqual(applied_data["backup"], "edl.json.bak_fx")
        self.assertEqual(applied_data["added"], ["p1", "p2"])
        self.assertIn("applied_overlays", applied_data)

    def test_apply_numbered_backup(self) -> None:
        # 1st apply
        apply(self.wd, self.rep_path, only=["p1"], approve=True)
        self.assertTrue((self.wd / "edl.json.bak_fx").is_file())
        self.assertFalse((self.wd / "edl.json.bak_fx.1").exists())

        # 2nd apply with another item creates edl.json.bak_fx.1
        res2 = apply(self.wd, self.rep_path, only=["p2"], approve=True)
        self.assertTrue((self.wd / "edl.json.bak_fx.1").is_file())
        self.assertEqual(res2["backup"], "edl.json.bak_fx.1")

    def test_apply_idempotent(self) -> None:
        apply(self.wd, self.rep_path, approve=True)
        res2 = apply(self.wd, self.rep_path, approve=True)
        self.assertEqual(res2["status"], "already_applied")
        self.assertEqual(res2["added"], [])
        self.assertIn("p1", res2["skipped"])
        self.assertIn("p2", res2["skipped"])

    def test_apply_does_not_apply_rejected(self) -> None:
        apply(self.wd, self.rep_path, approve=True)
        saved = jsonio.read_json(self.edl_path)
        ov_types = [o["type"] for o in saved["clips"][0]["overlays"]]
        self.assertNotIn("tidak lolos gerbang", str(saved))
        # p3 is rejected, so only p1 (zoom_through_text) and p2 (chart_grow) plus vs are in EDL
        self.assertEqual(len(ov_types), 3)

    def test_apply_atomic_on_failure(self) -> None:
        before_bytes = self.edl_path.read_bytes()
        # Mock jsonio.write_json to raise during write to edl.json
        orig_write_json = jsonio.write_json

        def faulty_write_json(path, data):
            if Path(path).resolve() == self.edl_path.resolve():
                raise OSError("Disk write failed simulated")
            return orig_write_json(path, data)

        with mock.patch.object(jsonio, "write_json", side_effect=faulty_write_json):
            with self.assertRaises(OSError):
                apply(self.wd, self.rep_path, approve=True)

        after_bytes = self.edl_path.read_bytes()
        self.assertEqual(before_bytes, after_bytes)

    def test_undo_restores_byte_per_byte(self) -> None:
        orig_bytes = self.edl_path.read_bytes()
        apply(self.wd, self.rep_path, approve=True)
        self.assertNotEqual(self.edl_path.read_bytes(), orig_bytes)

        res = undo(self.wd)
        self.assertEqual(res["status"], "undone")
        self.assertEqual(self.edl_path.read_bytes(), orig_bytes)

    def test_undo_rejects_modified_edl(self) -> None:
        apply(self.wd, self.rep_path, approve=True)
        # Modify edl after apply
        mod_edl = jsonio.read_json(self.edl_path)
        mod_edl["clips"][0]["progress"] = True
        jsonio.write_json(self.edl_path, mod_edl)

        with self.assertRaises(FxApplyError) as ctx:
            undo(self.wd, force=False)
        self.assertIn("dimodifikasi", str(ctx.exception).lower())

        # With force=True, undo succeeds
        res = undo(self.wd, force=True)
        self.assertEqual(res["status"], "undone")


class TestPreviewErrors(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = Path(self._tmp.name)
        self.edl = _make_edl()
        self.edl_path = self.wd / "edl.json"
        jsonio.write_json(self.edl_path, self.edl)
        self.report = _make_report()
        self.rep_path = self.wd / "fx_plan.report.json"
        jsonio.write_json(self.rep_path, self.report)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_preview_missing_edl_raises_fxapplyerror(self) -> None:
        self.edl_path.unlink()
        with self.assertRaises(FxApplyError):
            preview(self.wd, self.rep_path)

    def test_preview_missing_report_raises_fxapplyerror(self) -> None:
        with self.assertRaises(FxApplyError):
            preview(self.wd, self.wd / "missing_report.json")

    def test_preview_stale_report_raises_stalereport(self) -> None:
        self.report["clips"][0]["duration"] = 99.0
        jsonio.write_json(self.rep_path, self.report)
        with self.assertRaises(StaleReport):
            preview(self.wd, self.rep_path)

    def test_preview_empty_selection_raises_fxapplyerror(self) -> None:
        # Report with only rejected items
        rep = _make_report(
            clips=[
                {
                    "clip_id": "clip_01",
                    "duration": 5.0,
                    "items": [
                        {
                            "id": "p3",
                            "status": "rejected",
                            "errors": ["bad"],
                            "warnings": [],
                            "overlay": None,
                            "reason": "r",
                            "moment": None,
                        }
                    ],
                }
            ],
            summary={"accepted": 0, "accepted_with_warnings": 0, "rejected": 1},
        )
        p = self.wd / "rej_report.json"
        jsonio.write_json(p, rep)
        with self.assertRaises(FxApplyError) as ctx:
            preview(self.wd, p)
        self.assertIn("tidak ada item", str(ctx.exception).lower())

    def test_preview_never_writes_edl_nor_out(self) -> None:
        # Mock render.render_clip to avoid actual ffmpeg execution in this unit test
        out_dir = self.wd / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "existing_out.mp4").write_bytes(b"untouchable")
        out_hash_before = hashlib.sha256(b"untouchable").hexdigest()
        edl_hash_before = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()

        def fake_render_clip(edl, clip, wd, out_path, **kwargs):
            out_p = Path(out_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_bytes(b"dummy_mp4")
            return out_p

        with mock.patch("scripts.render.render_clip", side_effect=fake_render_clip):
            with mock.patch("scripts.fxapply._generate_contact_sheet") as mock_cs:
                mock_cs.return_value = (str(self.wd / "fx_preview" / "contact_sheet.png"), [{"id": "p1"}])
                preview(self.wd, self.rep_path)

        # EDL must be untouched!
        self.assertEqual(hashlib.sha256(self.edl_path.read_bytes()).hexdigest(), edl_hash_before)
        # out/ must be untouched!
        self.assertEqual(hashlib.sha256((out_dir / "existing_out.mp4").read_bytes()).hexdigest(), out_hash_before)
        self.assertEqual(list(out_dir.iterdir()), [out_dir / "existing_out.mp4"])
