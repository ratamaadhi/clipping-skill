"""Flag CLI `build-edl --motion {1,2}`.

Tier-1 tetap default; tier-2 hanya muncul bila diminta.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_work

from scripts import cli
from scripts.lib import jsonio


def _parse(argv: list[str]):
    return cli.build_parser().parse_args(argv)


class MotionFlagParserTest(unittest.TestCase):
    def test_default_is_tier1(self) -> None:
        args = _parse(["build-edl", "work/x"])
        self.assertEqual(args.motion, 1)

    def test_accepts_tier1_and_tier2(self) -> None:
        for value in ("1", "2"):
            args = _parse(["build-edl", "work/x", "--motion", value])
            self.assertEqual(args.motion, int(value))

    def test_rejects_other_values(self) -> None:
        for bad in ("0", "3", "-1", "dua"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                _parse(["build-edl", "work/x", "--motion", bad])

    def test_other_build_edl_flags_unchanged(self) -> None:
        args = _parse(["build-edl", "work/x", "--top", "7", "--force"])
        self.assertEqual(args.top, 7)
        self.assertTrue(args.force)


class BuildEdlCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = make_work(Path(cls._tmp.name), top_n=10, top=3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _run(self, *extra: str) -> dict:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["build-edl", str(self.wd), *extra])
        self.assertEqual(code, 0, msg=out.getvalue())
        return jsonio.read_json(self.wd / "edl.json")

    def test_without_motion_flag_writes_tier1(self) -> None:
        edl = self._run()
        for clip in edl["clips"]:
            self.assertNotIn("caption_style", clip, msg=clip["id"])
            for cap in clip["captions"]:
                self.assertNotIn("words", cap, msg=clip["id"])
        self.assertEqual(edl["version"], "0.1.0")

    def test_motion_1_matches_no_flag(self) -> None:
        a = self._run("--motion", "1")
        b = self._run()
        self.assertEqual(a, b)

    def test_motion_2_writes_words_and_caption_style(self) -> None:
        edl = self._run("--motion", "2")
        for clip in edl["clips"]:
            self.assertEqual(clip["caption_style"], "kinetic", msg=clip["id"])
            for cap in clip["captions"]:
                self.assertIn("words", cap, msg=f"{clip['id']} {cap['text']!r}")
                self.assertTrue(cap["words"], msg=f"{clip['id']} {cap['text']!r}")
        self.assertEqual(edl["version"], "0.1.0")
        # tier-2 lewat CLI tetap menulis EDL yang bisa dipakai render
        self.assertTrue((self.wd / "report.md").exists())

    def test_motion_2_keeps_captions_identical(self) -> None:
        tier1 = self._run()
        tier2 = self._run("--motion", "2")
        for c1, c2 in zip(tier1["clips"], tier2["clips"]):
            self.assertEqual(len(c1["captions"]), len(c2["captions"]), msg=c1["id"])
            for a, b in zip(c1["captions"], c2["captions"]):
                for field in ("start", "end", "text", "emphasis"):
                    self.assertEqual(a.get(field), b.get(field), msg=f"{c1['id']} {field}")


if __name__ == "__main__":
    unittest.main()
