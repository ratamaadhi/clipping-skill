"""Tes render integrasi untuk scripts/fxapply.py pratinjau efek.

Memeriksa pembuatan video pratinjau 540x960 15fps, pembuatan lembar kontak
dan contact_sheet.json, integritas edl.json dan <work>/out/, perbedaan piksel
di dalam vs luar jendela tampil, serta resolusi jalur wd relatif.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import ROOT
from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts.lib import jsonio
from scripts import fxapply
from scripts.fxapply import FxApplyError, preview

_FFMPEG = find_ffmpeg_with_libass()
_FFPROBE = str(Path(_FFMPEG).with_name("ffprobe")) if _FFMPEG else None
if _FFPROBE and not Path(_FFPROBE).exists():
    _FFPROBE = shutil.which("ffprobe")

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` atau set env CLIP_FFMPEG ke path ffmpeg berlibass."
)

SRC_W, SRC_H = 1920, 1080
SRC_FPS = 30
SRC_DUR = 5.0
CLIP_DUR = 5.0


def _ffmpeg_bin() -> str:
    assert _FFMPEG is not None
    return _FFMPEG


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AssertionError(
            f"Perintah gagal ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.decode('utf-8', errors='replace')[:1500]}"
        )
    return proc


def _make_source(path: Path) -> None:
    _run([
        _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i",
        f"color=c=black:s={SRC_W}x{SRC_H}:r={SRC_FPS}:d={SRC_DUR:g}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={SRC_DUR:g}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(path),
    ])


def _probe_video(path: Path) -> dict[str, Any]:
    assert _FFPROBE is not None
    proc = _run([
        _FFPROBE, "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ])
    data = json.loads(proc.stdout.decode("utf-8"))
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return {}


def _frame_rgb(path: Path, frame_idx: int) -> bytes:
    vf = f"trim=start_frame={frame_idx}:end_frame={frame_idx + 1},setpts=PTS-STARTPTS"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.raw"
        _run([
            _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-vf", vf, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ])
        return out.read_bytes()


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class TestFxApplyRender(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = Path(self._tmp.name).resolve()
        self.src_path = self.wd / "src.mp4"
        _make_source(self.src_path)

        self.edl: dict[str, Any] = {
            "version": "0.1.0",
            "source": {
                "path": "src.mp4",
                "width": SRC_W,
                "height": SRC_H,
                "fps": float(SRC_FPS),
                "audio_rate": 48000,
            },
            "output": {"fps": 30.0, "width": 1080, "height": 1920, "loudness_lufs": -14.0, "true_peak_db": -1.0},
            "clips": [
                {
                    "id": "clip_01",
                    "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
                    "caption_style": "phrase",
                    "reframe": {"mode": "center"},
                    "punch": [],
                    "progress": False,
                    "captions": [],
                    "overlays": [],
                }
            ],
        }
        self.edl_path = self.wd / "edl.json"
        jsonio.write_json(self.edl_path, self.edl)

        # Work out directory with dummy file to verify out/ is untouched
        self.out_dir = self.wd / "out"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.out_file = self.out_dir / "preserve_me.txt"
        self.out_file.write_text("must not change", encoding="utf-8")
        self.out_hash_before = hashlib.sha256(self.out_file.read_bytes()).hexdigest()

        self.report: dict[str, Any] = {
            "version": 1,
            "edl": "edl.json",
            "plan": "fx_plan.json",
            "clips": [
                {
                    "clip_id": "clip_01",
                    "duration": CLIP_DUR,
                    "items": [
                        {
                            "id": "p1",
                            "status": "accepted",
                            "errors": [],
                            "warnings": [],
                            "overlay": {
                                "type": "zoom_through_text",
                                "start": 0.5,
                                "end": 1.5,
                                "props": {"text": "5 JAM"},
                            },
                            "reason": "angka kunci",
                            "moment": "m1",
                        },
                        {
                            "id": "p2",
                            "status": "accepted_with_warnings",
                            "errors": [],
                            "warnings": ["dekat tepi"],
                            "overlay": {
                                "type": "chart_grow",
                                "start": 2.0,
                                "end": 4.0,
                                "props": {"labels": ["A", "B", "C"], "values": [10, 20, 30], "tag": "+20%"},
                            },
                            "reason": "grafik tren",
                            "moment": "m2",
                        },
                    ],
                }
            ],
            "summary": {"accepted": 1, "accepted_with_warnings": 1, "rejected": 0},
        }
        self.rep_path = self.wd / "fx_plan.report.json"
        jsonio.write_json(self.rep_path, self.report)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_preview_generates_video_contact_sheet_and_leaves_edl_and_out_untouched(self) -> None:
        edl_hash_before = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()

        res = preview(self.wd, self.rep_path)

        # 1. Output files exist in fx_preview
        prev_dir = self.wd / "fx_preview"
        self.assertTrue(prev_dir.is_dir())
        clip_preview = prev_dir / "clip_01.fx_preview.mp4"
        self.assertTrue(clip_preview.is_file())
        edl_preview = prev_dir / "edl.fx_preview.json"
        self.assertTrue(edl_preview.is_file())
        cs_png = prev_dir / "contact_sheet.png"
        self.assertTrue(cs_png.is_file())
        cs_json = prev_dir / "contact_sheet.json"
        self.assertTrue(cs_json.is_file())

        # 2. Preview video dimensions and frame count (540x960, round(dur * 15))
        probe = _probe_video(clip_preview)
        self.assertEqual(int(probe["width"]), 540)
        self.assertEqual(int(probe["height"]), 960)
        expected_frames = round(CLIP_DUR * 15)  # 4.0 * 15 = 60
        nb_frames = int(probe.get("nb_frames") or 0)
        self.assertEqual(nb_frames, expected_frames)

        # 3. Contact sheet can be probed by ffprobe
        assert _FFPROBE is not None
        probe_proc = _run([
            _FFPROBE, "-v", "error", "-show_entries", "stream=width,height,codec_name",
            "-of", "json", str(cs_png)
        ])
        cs_info = json.loads(probe_proc.stdout.decode("utf-8"))
        self.assertTrue(len(cs_info.get("streams", [])) > 0)
        self.assertGreater(cs_info["streams"][0]["width"], 0)
        self.assertGreater(cs_info["streams"][0]["height"], 0)

        # 4. Contact sheet json records frames
        cs_data = jsonio.read_json(cs_json)
        self.assertIn("frames", cs_data)
        ids = [f["id"] for f in cs_data["frames"]]
        self.assertEqual(ids, ["p1", "p2"])

        # 5. edl.json and out/ are BYTE-PER-BYTE IDENTICAL before and after
        edl_hash_after = hashlib.sha256(self.edl_path.read_bytes()).hexdigest()
        self.assertEqual(edl_hash_before, edl_hash_after)

        out_hash_after = hashlib.sha256(self.out_file.read_bytes()).hexdigest()
        self.assertEqual(self.out_hash_before, out_hash_after)
        self.assertEqual(list(self.out_dir.iterdir()), [self.out_file])

    def test_preview_pixel_difference_inside_and_outside_window(self) -> None:
        from scripts import render

        # Render baseline preview without overlay
        baseline_path = self.wd / "baseline.mp4"
        edl_copy = jsonio.read_json(self.edl_path)
        edl_copy["source"]["path"] = str(self.src_path)
        render.render_clip(
            edl_copy,
            edl_copy["clips"][0],
            self.wd,
            baseline_path,
            preview=True,
        )

        # Run preview with overlay (p1 zoom_through_text: start 1.0, end 2.0)
        preview(self.wd, self.rep_path, only=["p1"])
        prev_path = self.wd / "fx_preview" / "clip_01.fx_preview.mp4"

        # Frame outside overlay window: t = 0.2s -> frame index round(0.2 * 15) = 3
        frame_out_base = _frame_rgb(baseline_path, 3)
        frame_out_prev = _frame_rgb(prev_path, 3)
        self.assertEqual(frame_out_base, frame_out_prev)

        # Frame inside overlay window: t = 1.0s -> frame index round(1.0 * 15) = 15
        frame_in_base = _frame_rgb(baseline_path, 15)
        frame_in_prev = _frame_rgb(prev_path, 15)
        self.assertNotEqual(frame_in_base, frame_in_prev)

    def test_preview_only_restricts_overlays(self) -> None:
        preview(self.wd, self.rep_path, only=["p1"])
        cs_data = jsonio.read_json(self.wd / "fx_preview" / "contact_sheet.json")
        ids = [f["id"] for f in cs_data["frames"]]
        self.assertEqual(ids, ["p1"])

    def test_preview_empty_selection_raises_fxapplyerror(self) -> None:
        with self.assertRaises(FxApplyError):
            preview(self.wd, self.rep_path, only=["p999"])

    def test_preview_relative_wd_works(self) -> None:
        # Move into parent directory and use relative path
        orig_cwd = os.getcwd()
        try:
            rel_name = os.path.relpath(str(self.wd), orig_cwd)
            res = preview(rel_name, str(Path(rel_name) / "fx_plan.report.json"), only=["p1"])
            self.assertTrue(Path(res["contact_sheet"]).is_file())
        finally:
            os.chdir(orig_cwd)
