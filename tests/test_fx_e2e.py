from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from tests.ffmpeg_libass import find_ffmpeg_with_libass
from tests.test_fxapply_render import _frame_rgb, _make_source

from scripts import cli, render
from scripts.lib import jsonio

_FFMPEG = find_ffmpeg_with_libass()
SKIP_REASON = "tidak ada ffmpeg dengan filter 'subtitles' (libass)"


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class TestFxSuggestE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="fx_suggest_e2e_")
        self.wd = (Path(self._tmp) / "work").resolve()
        self.wd.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))

        self.src_path = self.wd / "src.mp4"
        _make_source(self.src_path)

        self.edl: dict[str, Any] = {
            "version": "0.1.0",
            "source": {
                "path": "src.mp4",
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "audio_rate": 48000,
            },
            "output": {
                "fps": 30.0,
                "width": 1080,
                "height": 1920,
                "loudness_lufs": -14.0,
                "true_peak_db": -1.0,
            },
            "clips": [
                {
                    "id": "clip_01",
                    "segments": [{"src_start": 0.0, "src_end": 5.0, "speed": 1.0}],
                    "caption_style": "kinetic",
                    "reframe": {"mode": "center"},
                    "punch": [],
                    "progress": False,
                    "captions": [
                        {
                            "start": 1.0,
                            "end": 3.0,
                            "text": "Ada 100 orang yang hadir",
                            "words": [
                                {"w": "Ada", "start": 1.0, "end": 1.3},
                                {"w": "100", "start": 1.4, "end": 1.8},
                                {"w": "orang", "start": 1.9, "end": 2.2},
                                {"w": "yang", "start": 2.3, "end": 2.6},
                                {"w": "hadir", "start": 2.7, "end": 3.0},
                            ],
                        }
                    ],
                    "overlays": [],
                }
            ],
        }
        self.edl_path = self.wd / "edl.json"
        jsonio.write_json(self.edl_path, self.edl)

        self.out_dir = self.wd / "out"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.canary_file = self.out_dir / "canary.txt"
        self.canary_file.write_text("canary_out_untouched", encoding="utf-8")
        self.canary_hash_initial = hashlib.sha256(self.canary_file.read_bytes()).hexdigest()

    def test_full_suggest_lifecycle_via_cli(self) -> None:
        edl_hash_initial = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()

        # Step 0: Render baseline without overlay
        t0 = time.perf_counter()
        baseline_path = self.wd / "baseline_clip_01.mp4"
        edl_baseline = jsonio.read_json(self.edl_path)
        edl_baseline["source"]["path"] = str(self.src_path)
        render.render_clip(edl_baseline, edl_baseline["clips"][0], self.wd, baseline_path)
        dur_baseline = time.perf_counter() - t0

        # Step 1: fx-candidates
        t0 = time.perf_counter()
        code_candidates = cli.main(["fx-candidates", str(self.wd)])
        dur_candidates = time.perf_counter() - t0
        self.assertEqual(code_candidates, 0)
        cands_path = self.wd / "fx_candidates.json"
        self.assertTrue(cands_path.is_file())
        cands = jsonio.read_json(cands_path)
        self.assertEqual(len(cands.get("clips", [])), 1)
        moments = cands["clips"][0].get("moments", [])
        self.assertGreater(len(moments), 0)
        edl_hash_after_candidates = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_initial, edl_hash_after_candidates)

        # Step 2: Write fx_plan.json
        t0 = time.perf_counter()
        m_id = moments[0]["id"]
        plan = {
            "version": 1,
            "mode": "suggest",
            "clips": [
                {
                    "clip_id": "clip_01",
                    "items": [
                        {
                            "id": "p1",
                            "type": "zoom_through_text",
                            "start": 1.4,
                            "end": 2.1,
                            "props": {"text": "100 ORANG"},
                            "reason": "momen angka kunci",
                            "moment": m_id,
                        },
                        {
                            "id": "p2",
                            "type": "zoom_through_text",
                            "start": 1.5,
                            "end": 2.2,
                            "props": {"text": "TOLAK"},
                            "reason": "tumpang tindih dengan p1",
                        },
                    ],
                }
            ],
        }
        jsonio.write_json(self.wd / "fx_plan.json", plan)
        dur_write_plan = time.perf_counter() - t0

        # Step 3: fx-validate
        t0 = time.perf_counter()
        code_validate = cli.main(["fx-validate", str(self.wd)])
        dur_validate = time.perf_counter() - t0
        self.assertEqual(code_validate, 0)
        rep_path = self.wd / "fx_plan.report.json"
        self.assertTrue(rep_path.is_file())
        rep = jsonio.read_json(rep_path)
        self.assertEqual(rep["summary"]["accepted"], 1)
        self.assertEqual(rep["summary"]["rejected"], 1)
        edl_hash_after_validate = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_initial, edl_hash_after_validate)

        # Step 4: fx-preview
        t0 = time.perf_counter()
        code_preview = cli.main(["fx-preview", str(self.wd)])
        dur_preview = time.perf_counter() - t0
        self.assertEqual(code_preview, 0)
        preview_clip = self.wd / "fx_preview" / "clip_01.fx_preview.mp4"
        preview_edl = self.wd / "fx_preview" / "edl.fx_preview.json"
        contact_sheet = self.wd / "fx_preview" / "contact_sheet.png"
        contact_json = self.wd / "fx_preview" / "contact_sheet.json"
        self.assertTrue(preview_clip.is_file())
        self.assertTrue(preview_edl.is_file())
        self.assertTrue(contact_sheet.is_file())
        self.assertTrue(contact_json.is_file())
        self.assertGreater(preview_clip.stat().st_size, 0)
        self.assertGreater(contact_sheet.stat().st_size, 0)
        edl_hash_after_preview = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_initial, edl_hash_after_preview)
        canary_hash_after_preview = hashlib.sha256(self.canary_file.read_bytes()).hexdigest()
        self.assertEqual(self.canary_hash_initial, canary_hash_after_preview)
        self.assertEqual(list(self.out_dir.iterdir()), [self.canary_file])

        # Step 5: fx-apply without approve
        t0 = time.perf_counter()
        code_dry_apply = cli.main(["fx-apply", str(self.wd)])
        dur_dry_apply = time.perf_counter() - t0
        self.assertEqual(code_dry_apply, 2)
        edl_hash_after_dry_apply = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_initial, edl_hash_after_dry_apply)
        self.assertFalse((self.wd / "edl.json.bak_fx").exists())

        # Step 6: fx-apply with approve
        t0 = time.perf_counter()
        code_apply = cli.main(["fx-apply", str(self.wd), "--approve"])
        dur_apply = time.perf_counter() - t0
        self.assertEqual(code_apply, 0)
        backup_path = self.wd / "edl.json.bak_fx"
        self.assertTrue(backup_path.is_file())
        backup_hash = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_initial, backup_hash)

        applied_edl = jsonio.read_json(self.edl_path)
        edl_hash_after_apply = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertNotEqual(edl_hash_initial, edl_hash_after_apply)
        self.assertEqual(len(applied_edl["clips"][0]["overlays"]), 1)
        self.assertEqual(applied_edl["clips"][0]["overlays"][0]["type"], "zoom_through_text")
        applied_no_ov = jsonio.read_json(self.edl_path)
        applied_no_ov["clips"][0]["overlays"] = []
        orig_edl = jsonio.read_json(backup_path)
        self.assertEqual(applied_no_ov, orig_edl)

        # Step 7: normal render
        t0 = time.perf_counter()
        code_render = cli.main(["render", str(self.wd)])
        dur_render = time.perf_counter() - t0
        self.assertEqual(code_render, 0)
        rendered_clip = self.wd / "out" / "clip_01.mp4"
        self.assertTrue(rendered_clip.is_file())
        frame_base = _frame_rgb(baseline_path, 52)
        frame_fx = _frame_rgb(rendered_clip, 52)
        self.assertNotEqual(frame_base, frame_fx)
        edl_hash_after_render = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_after_apply, edl_hash_after_render)

        # Step 8: fx-undo
        t0 = time.perf_counter()
        code_undo = cli.main(["fx-undo", str(self.wd)])
        dur_undo = time.perf_counter() - t0
        self.assertEqual(code_undo, 0)
        edl_hash_after_undo = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_initial, edl_hash_after_undo)

        durations = {
            "baseline_render": dur_baseline,
            "fx_candidates": dur_candidates,
            "write_plan": dur_write_plan,
            "fx_validate": dur_validate,
            "fx_preview": dur_preview,
            "fx_apply_dry": dur_dry_apply,
            "fx_apply_approved": dur_apply,
            "render_normal": dur_render,
            "fx_undo": dur_undo,
        }
        for k, v in durations.items():
            print(f"E2E Timing [{k}]: {v:.3f}s")


if __name__ == "__main__":
    unittest.main()
