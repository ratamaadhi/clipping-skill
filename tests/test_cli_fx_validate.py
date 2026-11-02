"""Tes CLI untuk subperintah fx-validate (tests/test_cli_fx_validate.py)."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from scripts import cli
from scripts.lib import jsonio


class CliFxValidateTest(unittest.TestCase):
    """Pengujian subperintah CLI fx-validate."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cli_fx_val_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _make_work(
        self,
        edl_data: dict[str, Any] | None = None,
        plan_data: dict[str, Any] | None = None,
        candidates_data: dict[str, Any] | None = None,
    ) -> Path:
        wd = self.tmp / "work"
        wd.mkdir(parents=True, exist_ok=True)
        if edl_data is not None:
            jsonio.write_json(wd / "edl.json", edl_data)
        if plan_data is not None:
            jsonio.write_json(wd / "fx_plan.json", plan_data)
        if candidates_data is not None:
            jsonio.write_json(wd / "fx_candidates.json", candidates_data)
        return wd

    def test_fx_validate_basic_success_and_edl_untouched(self) -> None:
        edl_doc = {
            "version": "0.1.0",
            "clips": [
                {
                    "id": "clip_01",
                    "duration": 20.0,
                    "segments": [{"src_start": 0.0, "src_end": 20.0}],
                    "overlays": [],
                }
            ],
        }
        plan_doc = {
            "version": 1,
            "mode": "suggest",
            "clips": [
                {
                    "clip_id": "clip_01",
                    "items": [
                        {
                            "id": "p1",
                            "type": "zoom_through_text",
                            "start": 3.0,
                            "end": 3.7,
                            "props": {"text": "Aksen"},
                            "reason": "Penekanan awal",
                        },
                        {
                            "id": "p2",
                            "type": "zoom_through_text",
                            "start": 3.2,
                            "end": 3.9,
                            "props": {"text": "Tolak"},
                            "reason": "Tumpang tindih dengan p1",
                        },
                    ],
                }
            ],
        }
        wd = self._make_work(edl_doc, plan_doc)
        edl_bytes_before = (wd / "edl.json").read_bytes()

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cli.main(["fx-validate", str(wd)])

        # Keluar 0 walau ada penolakan (penolakan = hasil, bukan kegagalan sistem)
        self.assertEqual(ret, 0)
        out = buf.getvalue()
        self.assertIn("✓ fx-validate", out)
        self.assertIn("clip_01", out)
        self.assertIn("1 diterima", out)
        self.assertIn("1 ditolak", out)

        # Laporan JSON dan MD tertulis
        report_json_path = wd / "fx_plan.report.json"
        report_md_path = wd / "fx_plan.report.md"
        self.assertTrue(report_json_path.exists())
        self.assertTrue(report_md_path.exists())

        rep = jsonio.read_json(report_json_path)
        self.assertEqual(rep["summary"]["accepted"], 1)
        self.assertEqual(rep["summary"]["rejected"], 1)

        md = report_md_path.read_text(encoding="utf-8")
        self.assertIn("# Laporan Pengesahan Rencana Efek", md)
        self.assertIn("p1", md)
        self.assertIn("p2", md)

        # EDL TIDAK PERNAH DITULIS ATAU BERUBAH BYTE-FOR-BYTE
        edl_bytes_after = (wd / "edl.json").read_bytes()
        self.assertEqual(edl_bytes_before, edl_bytes_after)

    def test_fx_validate_missing_files_error(self) -> None:
        wd = self.tmp / "work_empty"
        wd.mkdir(parents=True, exist_ok=True)
        # edl.json tidak ada -> keluar != 0
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            ret = cli.main(["fx-validate", str(wd)])
        self.assertNotEqual(ret, 0)

    def test_fx_validate_corrupt_json_error(self) -> None:
        edl_doc = {"version": "0.1.0", "clips": []}
        wd = self._make_work(edl_doc)
        # Tulis fx_plan.json korup
        (wd / "fx_plan.json").write_text("{ini bukan json valid", encoding="utf-8")
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            ret = cli.main(["fx-validate", str(wd)])
        self.assertNotEqual(ret, 0)

    def test_fx_validate_candidates_flag_enriches_warnings(self) -> None:
        edl_doc = {
            "version": "0.1.0",
            "clips": [
                {
                    "id": "clip_01",
                    "duration": 20.0,
                    "segments": [{"src_start": 0.0, "src_end": 20.0}],
                    "overlays": [],
                }
            ],
        }
        plan_doc = {
            "version": 1,
            "mode": "suggest",
            "clips": [
                {
                    "clip_id": "clip_01",
                    "items": [
                        {
                            "id": "p1",
                            "type": "zoom_through_text",
                            "start": 3.0,
                            "end": 3.7,
                            "props": {"text": "Aksen"},
                            "reason": "Momen gaib",
                            "moment": "m999",
                        }
                    ],
                }
            ],
        }
        cand_doc = {
            "version": "0.1.0",
            "clips": [
                {
                    "clip_id": "clip_01",
                    "moments": [{"id": "m001"}],
                }
            ],
        }
        wd = self._make_work(edl_doc, plan_doc)
        cand_file = wd / "custom_candidates.json"
        jsonio.write_json(cand_file, cand_doc)

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cli.main(["fx-validate", str(wd), "--candidates", str(cand_file)])
        self.assertEqual(ret, 0)

        rep = jsonio.read_json(wd / "fx_plan.report.json")
        item = rep["clips"][0]["items"][0]
        self.assertEqual(item["status"], "accepted_with_warnings")
        self.assertTrue(any("m999" in w for w in item["warnings"]))


if __name__ == "__main__":
    unittest.main()
