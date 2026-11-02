from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

from scripts import cli
from scripts.fxapply import ApprovalRequired, FxApplyError, StaleReport
from scripts.lib import jsonio


class TestCliFxApply(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cli_fx_apply_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _make_work(
        self,
        edl_data: dict[str, Any] | None = None,
        report_data: dict[str, Any] | None = None,
    ) -> Path:
        wd = self.tmp / "work"
        wd.mkdir(parents=True, exist_ok=True)
        if edl_data is not None:
            jsonio.write_json(wd / "edl.json", edl_data)
        if report_data is not None:
            jsonio.write_json(wd / "fx_plan.report.json", report_data)
        return wd

    def _sample_edl(self) -> dict[str, Any]:
        return {
            "version": "0.1.0",
            "source": {"path": "src.mp4", "width": 1080, "height": 1920, "fps": 30.0},
            "clips": [
                {
                    "id": "clip_01",
                    "duration": 10.0,
                    "segments": [{"src_start": 0.0, "src_end": 10.0}],
                    "overlays": [],
                }
            ],
        }

    def _sample_report(self) -> dict[str, Any]:
        return {
            "version": 1,
            "edl": "edl.json",
            "plan": "fx_plan.json",
            "clips": [
                {
                    "clip_id": "clip_01",
                    "duration": 10.0,
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
                                "props": {"text": "A"},
                            },
                            "reason": "Alasan 1",
                            "moment": "m1",
                        },
                        {
                            "id": "p2",
                            "status": "accepted_with_warnings",
                            "errors": [],
                            "warnings": ["dekat zona margin"],
                            "overlay": {
                                "type": "checklist",
                                "start": 3.0,
                                "end": 6.0,
                                "rect": {"x": 60.0, "y": 1300.0, "w": 960.0, "h": 320.0},
                                "props": {"title": "T", "items": [{"text": "x", "done_at": 4.0}]},
                            },
                            "reason": "Alasan 2",
                            "moment": "m2",
                        },
                        {
                            "id": "p3",
                            "status": "rejected",
                            "errors": ["tumpang tindih"],
                            "warnings": [],
                            "overlay": None,
                            "reason": "Alasan 3",
                            "moment": "m3",
                        },
                    ],
                }
            ],
            "summary": {"accepted": 1, "accepted_with_warnings": 1, "rejected": 1},
        }

    def test_fx_preview_missing_report_fails_one_line(self) -> None:
        wd = self._make_work(self._sample_edl())
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = cli.main(["fx-preview", str(wd)])
        self.assertEqual(code, 1)
        err = buf_err.getvalue().strip()
        self.assertTrue(err.startswith("ERROR:"))
        self.assertIn("fx_plan.report.json", err)
        self.assertEqual(len(err.splitlines()), 1)

    def test_fx_preview_success_outputs_expected_info(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        edl_bytes_before = (wd / "edl.json").read_bytes()

        preview_result = {
            "clips": {"clip_01": str(wd / "fx_preview" / "clip_01.fx_preview.mp4")},
            "contact_sheet": str(wd / "fx_preview" / "contact_sheet.png"),
            "frames": [
                {"id": "p1", "type": "zoom_through_text", "time": 1.5, "clip": "clip_01"},
                {"id": "p2", "type": "checklist", "time": 4.5, "clip": "clip_01"},
            ],
        }

        with mock.patch("scripts.fxapply.preview", return_value=preview_result) as mock_prev:
            buf_out = io.StringIO()
            with redirect_stdout(buf_out):
                code = cli.main(["fx-preview", str(wd), "--only", "p1,p2"])
            self.assertEqual(code, 0)
            mock_prev.assert_called_once()
            _, kwargs = mock_prev.call_args
            self.assertEqual(kwargs.get("only"), ["p1", "p2"])
            self.assertTrue(kwargs.get("include_warnings"))

        out = buf_out.getvalue()
        self.assertIn("✓ fx-preview", out)
        self.assertIn("clip_01.fx_preview.mp4", out)
        self.assertIn("edl.fx_preview.json", out)
        self.assertIn("contact_sheet.png", out)
        self.assertIn("p1 (zoom_through_text) @ 1.50s", out)
        self.assertIn("p2 (checklist) @ 4.50s", out)

        self.assertEqual((wd / "edl.json").read_bytes(), edl_bytes_before)
        self.assertFalse((wd / "out").exists())

    def test_fx_preview_no_warnings_flag_passed(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        with mock.patch("scripts.fxapply.preview", return_value={"clips": {}, "frames": []}) as mock_prev:
            buf_out = io.StringIO()
            with redirect_stdout(buf_out):
                code = cli.main(["fx-preview", str(wd), "--no-warnings"])
            self.assertEqual(code, 0)
            mock_prev.assert_called_once()
            _, kwargs = mock_prev.call_args
            self.assertFalse(kwargs.get("include_warnings"))

    def test_fx_apply_without_approve_dry_run_exits_2_and_edl_untouched(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        edl_bytes_before = (wd / "edl.json").read_bytes()

        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = cli.main(["fx-apply", str(wd)])
        self.assertEqual(code, 2)
        out = buf_out.getvalue()
        self.assertIn("Rencana overlay yang AKAN diterapkan:", out)
        self.assertIn("p1", out)
        self.assertIn("zoom_through_text", out)
        self.assertIn("[1.00s - 2.00s]", out)
        self.assertIn("p2", out)
        self.assertIn("dekat zona margin", out)
        self.assertIn("--approve", out)
        self.assertIn("edl.json tidak diubah", out)

        self.assertEqual((wd / "edl.json").read_bytes(), edl_bytes_before)
        self.assertFalse((wd / "edl.json.bak_fx").exists())
        self.assertFalse((wd / "fx_plan.applied.json").exists())

    def test_fx_apply_with_approve_applies_and_creates_backup(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        edl_bytes_before = (wd / "edl.json").read_bytes()

        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = cli.main(["fx-apply", str(wd), "--approve"])
        self.assertEqual(code, 0)
        out = buf_out.getvalue()
        self.assertIn("✓ fx-apply", out)
        self.assertIn("Cadangan: edl.json.bak_fx", out)
        self.assertIn("Ditambahkan (2): p1, p2", out)

        self.assertTrue((wd / "edl.json.bak_fx").exists())
        self.assertEqual((wd / "edl.json.bak_fx").read_bytes(), edl_bytes_before)
        applied_edl = jsonio.read_json(wd / "edl.json")
        self.assertEqual(len(applied_edl["clips"][0]["overlays"]), 2)

    def test_fx_apply_only_flag_filters_selection(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = cli.main(["fx-apply", str(wd), "--only", "p1", "--approve"])
        self.assertEqual(code, 0)
        out = buf_out.getvalue()
        self.assertIn("Ditambahkan (1): p1", out)
        applied_edl = jsonio.read_json(wd / "edl.json")
        self.assertEqual(len(applied_edl["clips"][0]["overlays"]), 1)
        self.assertEqual(applied_edl["clips"][0]["overlays"][0]["type"], "zoom_through_text")

    def test_fx_apply_no_warnings_flag_excludes_warnings(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = cli.main(["fx-apply", str(wd), "--no-warnings", "--approve"])
        self.assertEqual(code, 0)
        out = buf_out.getvalue()
        self.assertIn("Ditambahkan (1): p1", out)
        applied_edl = jsonio.read_json(wd / "edl.json")
        self.assertEqual(len(applied_edl["clips"][0]["overlays"]), 1)
        self.assertEqual(applied_edl["clips"][0]["overlays"][0]["type"], "zoom_through_text")

    def test_fx_undo_restores_edl_byte_identical(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        edl_bytes_before = (wd / "edl.json").read_bytes()

        cli.main(["fx-apply", str(wd), "--approve"])
        self.assertNotEqual((wd / "edl.json").read_bytes(), edl_bytes_before)

        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = cli.main(["fx-undo", str(wd)])
        self.assertEqual(code, 0)
        out = buf_out.getvalue()
        self.assertIn("✓ fx-undo", out)
        self.assertIn("edl.json.bak_fx", out)

        self.assertEqual((wd / "edl.json").read_bytes(), edl_bytes_before)

    def test_fx_apply_error_handled_cleanly_without_traceback(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        with mock.patch("scripts.fxapply.apply", side_effect=FxApplyError("pesan galat kustom")):
            buf_err = io.StringIO()
            with redirect_stderr(buf_err):
                code = cli.main(["fx-apply", str(wd), "--approve"])
            self.assertEqual(code, 1)
            err = buf_err.getvalue().strip()
            self.assertEqual(len(err.splitlines()), 1)
            self.assertTrue(err.startswith("ERROR:"))
            self.assertIn("pesan galat kustom", err)

    def test_approval_required_exception_exits_code_2(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        with mock.patch("scripts.fxapply.apply", side_effect=ApprovalRequired("butuh approve")):
            buf_err = io.StringIO()
            with redirect_stderr(buf_err):
                code = cli.main(["fx-apply", str(wd), "--approve"])
            self.assertEqual(code, 2)
            err = buf_err.getvalue().strip()
            self.assertEqual(len(err.splitlines()), 1)
            self.assertTrue(err.startswith("ERROR:"))
            self.assertIn("butuh approve", err)

    def test_stale_report_exits_code_1_without_traceback(self) -> None:
        wd = self._make_work(self._sample_edl(), self._sample_report())
        with mock.patch("scripts.fxapply.check_fresh", side_effect=StaleReport("durasi klip basi")):
            buf_err = io.StringIO()
            with redirect_stderr(buf_err):
                code = cli.main(["fx-apply", str(wd), "--approve"])
            self.assertEqual(code, 1)
            err = buf_err.getvalue().strip()
            self.assertEqual(len(err.splitlines()), 1)
            self.assertTrue(err.startswith("ERROR:"))
            self.assertIn("durasi klip basi", err)


if __name__ == "__main__":
    unittest.main()
