"""Tes CLI untuk subperintah fx-catalog dan fx-candidates (tests/test_cli_fx.py)."""

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


class CliFxTest(unittest.TestCase):
    """Pengujian subperintah fx-catalog dan fx-candidates."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cli_fx_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _make_work(self, edl_data: dict[str, Any] | None = None) -> Path:
        wd = self.tmp / "work"
        wd.mkdir(parents=True, exist_ok=True)
        if edl_data is not None:
            jsonio.write_json(wd / "edl.json", edl_data)
        return wd

    def test_fx_catalog_text_output(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cli.main(["fx-catalog"])
        self.assertEqual(ret, 0)
        out = buf.getvalue()
        self.assertIn("# Katalog Efek Video (Tier-2)", out)
        self.assertIn("zoom_through_text", out)
        self.assertIn("checklist", out)
        self.assertIn("pullback", out)
        self.assertIn("Maksimum total overlay", out)

    def test_fx_catalog_json_output(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cli.main(["fx-catalog", "--json"])
        self.assertEqual(ret, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("budget", data)
        self.assertIn("effects", data)
        self.assertEqual(data["budget"]["MAX_OVERLAYS_PER_CLIP"], 3)
        self.assertIn("zoom_through_text", data["effects"])
        self.assertIn("pullback", data["effects"])

    def test_fx_candidates_synthetic_edl(self) -> None:
        edl_doc = {
            "version": "0.1.0",
            "clips": [
                {
                    "id": "clip_01",
                    "duration": 20.0,
                    "segments": [{"src_start": 0.0, "src_end": 20.0}],
                    "captions": [
                        {"start": 1.0, "end": 2.5, "text": "Tahu nggak kenapa?"},
                        {"start": 3.0, "end": 5.0, "text": "Ada 100 orang yang hadir"},
                        {"start": 6.0, "end": 9.0, "text": "Penjualan melonjak dari 10% ke 50%"},
                    ],
                }
            ],
        }
        wd = self._make_work(edl_doc)
        edl_bytes_before = (wd / "edl.json").read_bytes()

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cli.main(["fx-candidates", str(wd)])
        self.assertEqual(ret, 0)
        out = buf.getvalue()

        # Ringkasan tercetak
        self.assertIn("✓ fx-candidates", out)
        self.assertIn("clip_01", out)
        self.assertIn("number", out)

        # File fx_candidates.json tercipta
        cand_path = wd / "fx_candidates.json"
        self.assertTrue(cand_path.exists())
        cand_data = jsonio.read_json(cand_path)
        self.assertEqual(len(cand_data["clips"]), 1)
        self.assertEqual(cand_data["clips"][0]["clip_id"], "clip_01")
        self.assertGreater(len(cand_data["clips"][0]["moments"]), 0)

        # EDL tidak berubah sama sekali (byte-for-byte identik)
        edl_bytes_after = (wd / "edl.json").read_bytes()
        self.assertEqual(edl_bytes_before, edl_bytes_after)

    def test_fx_candidates_filter_clip_flag(self) -> None:
        edl_doc = {
            "version": "0.1.0",
            "clips": [
                {
                    "id": "clip_01",
                    "duration": 10.0,
                    "segments": [{"src_start": 0.0, "src_end": 10.0}],
                    "captions": [{"start": 3.0, "end": 5.0, "text": "Ada 100 orang"}],
                },
                {
                    "id": "clip_02",
                    "duration": 10.0,
                    "segments": [{"src_start": 0.0, "src_end": 10.0}],
                    "captions": [{"start": 3.0, "end": 5.0, "text": "Ada 200 orang"}],
                },
            ],
        }
        wd = self._make_work(edl_doc)

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cli.main(["fx-candidates", str(wd), "--clip", "clip_02"])
        self.assertEqual(ret, 0)

        cand_data = jsonio.read_json(wd / "fx_candidates.json")
        clip_ids = [c["clip_id"] for c in cand_data["clips"]]
        self.assertEqual(clip_ids, ["clip_02"], "Flag --clip harus menyaring klip")

    def test_fx_candidates_fails_when_edl_missing(self) -> None:
        wd = self._make_work(edl_data=None)  # tanpa edl.json
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            ret = cli.main(["fx-candidates", str(wd)])
        self.assertNotEqual(ret, 0)
        err_msg = buf_err.getvalue()
        self.assertIn("edl.json", err_msg)


if __name__ == "__main__":
    unittest.main()
