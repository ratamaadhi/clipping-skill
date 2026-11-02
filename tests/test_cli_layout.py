"""Subperintah `python3 -m scripts.cli layout` (Langkah 4b-1)."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tests.test_schema_layout import _clip_doc
from tests.test_schema_drift import load_schema, missing_required, undeclared_keys

from scripts import cli
from scripts.lib import jsonio

WORDS_A = [
    {"w": "Halo", "start": 0.0, "end": 0.4},
    {"w": "dunia", "start": 0.4, "end": 0.8},
]
WORDS_B = [
    {"w": "Apa", "start": 1.5, "end": 1.8},
    {"w": "kabar", "start": 1.8, "end": 2.3},
]


def _clip(
    *,
    kinetic: bool = True,
    face_track: list | None = None,
    overlays: list | None = None,
) -> dict:
    clip = {
        "id": "clip_00",
        "segments": [{
            "src_start": 0.0, "src_end": 10.0, "speed": 1.0, "out_start": 0.0,
        }],
        "captions": [
            {"start": 0.0, "end": 0.8, "text": "Halo dunia", "words": WORDS_A},
            {"start": 1.5, "end": 2.3, "text": "Apa kabar", "words": WORDS_B},
        ],
        "reframe": {"mode": "center", "bias_x": 0.0, "bias_y": 0.0},
        "punch": [{"t": 0.0, "scale": 1.0}, {"t": 3.0, "scale": 1.2}],
        "progress": True,
        "overlays": overlays or [],
    }
    if kinetic:
        clip["caption_style"] = "kinetic"
    if face_track is not None:
        clip["reframe"] = {
            "mode": "center", "bias_x": 0.0, "bias_y": 0.0,
            "face_track": face_track,
        }
    return clip


def _write_work(wd: Path, clip: dict) -> None:
    wd.mkdir(parents=True, exist_ok=True)
    jsonio.write_json(wd / "edl.json", {
        "version": "0.1.0",
        "source": {
            "path": "synthetic://x", "duration": 10.0, "fps": 30.0,
            "width": 1920, "height": 1080, "audio_rate": 48000,
            "loudness_lufs": -18.0,
        },
        "output": {
            "width": 1080, "height": 1920, "fps": 30.0,
            "loudness_lufs": -14.0, "true_peak_db": -1.0,
        },
        "clips": [clip],
    })


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class LayoutParserTest(unittest.TestCase):
    def test_defaults(self) -> None:
        args = cli.build_parser().parse_args(["layout", "work/x"])
        self.assertEqual(args.fps, 30.0)
        self.assertFalse(args.no_write)

    def test_flags(self) -> None:
        args = cli.build_parser().parse_args(
            ["layout", "work/x", "--fps", "25", "--no-write"]
        )
        self.assertEqual(args.fps, 25.0)
        self.assertTrue(args.no_write)


class LayoutCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _validate(self, layout_out: dict) -> None:
        doc = _clip_doc(layout_out)
        self.assertEqual(undeclared_keys(self.schema, doc), [])
        self.assertEqual(missing_required(self.schema, doc), [])

    def test_kinetic_with_face_track_writes_schema_valid_layout_and_audit(self) -> None:
        wd = self.root / "a"
        face_track = [
            {"t": 0.0, "faces": [{"x": 0.0, "y": 1200.0, "w": 1080.0, "h": 520.0}]},
        ]
        _write_work(wd, _clip(face_track=face_track))
        code, out, _ = _run("layout", str(wd))
        self.assertEqual(code, 0, msg=out)

        edl = jsonio.read_json(wd / "edl.json")
        layout_out = edl["clips"][0]["layout"]
        self._validate(layout_out)
        self.assertTrue(layout_out["caption"])
        # Wajah menutup bawah -> caption pindah ke kandidat atas.
        self.assertEqual(layout_out["caption"][0]["y"], 330.0)
        self.assertTrue(layout_out["caption"][0]["reason"].startswith("clear"))
        self.assertIn("caption∩wajah:", out)
        self.assertIn("overlay∩wajah:", out)
        self.assertIn("caption∩overlay:", out)
        self.assertIn("t=", out)
        self.assertIn("scale=", out)

    def test_no_write_leaves_file_identical(self) -> None:
        wd = self.root / "b"
        _write_work(wd, _clip(face_track=[{"t": 0.0, "faces": []}]))
        before = (wd / "edl.json").read_bytes()
        code, out, _ = _run("layout", str(wd), "--no-write")
        self.assertEqual(code, 0, msg=out)
        self.assertEqual((wd / "edl.json").read_bytes(), before)

    def test_non_kinetic_clip_untouched(self) -> None:
        wd = self.root / "c"
        _write_work(wd, _clip(kinetic=False))
        before = (wd / "edl.json").read_bytes()
        code, out, _ = _run("layout", str(wd))
        self.assertEqual(code, 0, msg=out)
        self.assertEqual((wd / "edl.json").read_bytes(), before)
        self.assertNotIn("layout", jsonio.read_json(wd / "edl.json")["clips"][0])
        self.assertIn("dilewati", out)
        self.assertIn("phrase", out)

    def test_kinetic_without_face_track_uses_no_face_track_reason(self) -> None:
        wd = self.root / "d"
        _write_work(wd, _clip(face_track=None))
        code, out, _ = _run("layout", str(wd))
        self.assertEqual(code, 0, msg=out)
        layout_out = jsonio.read_json(wd / "edl.json")["clips"][0]["layout"]
        self._validate(layout_out)
        self.assertTrue(layout_out["caption"])
        self.assertTrue(
            all(e["reason"] == "no_face_track" for e in layout_out["caption"])
        )

    def test_overlays_with_rect_placed_without_rect_skipped_with_note(self) -> None:
        wd = self.root / "e"
        overlays = [
            {"type": "ui_panel", "start": 0.2, "end": 2.0,
             "rect": {"x": 0, "y": 0, "w": 400, "h": 200}},
            {"type": "vs", "start": 0.5, "end": 3.5, "left": "A", "right": "B"},
        ]
        _write_work(wd, _clip(face_track=[], overlays=overlays))
        code, out, _ = _run("layout", str(wd))
        self.assertEqual(code, 0, msg=out)
        layout_out = jsonio.read_json(wd / "edl.json")["clips"][0]["layout"]
        self._validate(layout_out)
        self.assertEqual(len(layout_out["overlays"]), 1)
        entry = layout_out["overlays"][0]
        self.assertEqual(entry["index"], 0)
        self.assertIsNotNone(entry["rect"])
        self.assertTrue(entry["reason"].startswith("slot="))
        self.assertIn("overlay[1]", out)
        self.assertIn("rect", out.split("overlay[1]")[1].splitlines()[0])

    def test_deterministic(self) -> None:
        wd = self.root / "f"
        face_track = [
            {"t": 0.0, "faces": [{"x": 100.0, "y": 300.0, "w": 400.0, "h": 420.0}]},
            {"t": 4.0, "faces": []},
        ]
        _write_work(wd, _clip(face_track=face_track))
        _run("layout", str(wd))
        first = (wd / "edl.json").read_bytes()
        _run("layout", str(wd))
        second = (wd / "edl.json").read_bytes()
        self.assertEqual(first, second)

    def test_does_not_write_when_work_missing(self) -> None:
        code, _, err = _run("layout", str(self.root / "nope"))
        self.assertNotEqual(code, 0)
        self.assertIn("ERROR", err)


if __name__ == "__main__":
    unittest.main()
