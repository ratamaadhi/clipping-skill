"""Flag CLI `render --preview` dan penanganan galat ffmpeg/render di batas CLI.

`tests/test_cli_flags.py` tidak disentuh: tes ini hanya menambah cakupan untuk
Langkah 3b-ii.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT  # noqa: F401  (memasukkan akar repo ke sys.path)

from scripts import cli
from scripts import render
from scripts.lib import ffmpegbin
from scripts.lib import jsonio

def _parse(argv: list[str]):  # type: ignore[no-untyped-def]
    return cli.build_parser().parse_args(argv)

class PreviewParserTest(unittest.TestCase):
    def test_default_is_false(self) -> None:
        args = _parse(["render", "work/x"])
        self.assertFalse(args.preview)

    def test_flag_sets_true(self) -> None:
        args = _parse(["render", "work/x", "--preview"])
        self.assertTrue(args.preview)

    def test_other_render_flags_unchanged(self) -> None:
        args = _parse([
            "render", "work/x", "--top", "2", "--crf", "18",
            "--preset", "fast", "--fontsdir", "/f", "--force",
        ])
        self.assertEqual((args.top, args.crf, args.preset, args.fontsdir),
                         (2, 18, "fast", "/f"))
        self.assertTrue(args.force)
        self.assertFalse(args.preview)

class PreviewForwardingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = Path(self._tmp.name)
        jsonio.write_json(self.wd / "edl.json", {"clips": []})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["render", str(self.wd), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_preview_flag_reaches_render_all(self) -> None:
        seen: list[dict] = []

        def fake(wd, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(kwargs)
            return []

        with mock.patch.object(cli.render, "render_all", side_effect=fake):
            code, _out, _err = self._run("--preview")
            self.assertEqual(code, 0)
            self._run()
        self.assertTrue(seen[0]["preview"])
        self.assertFalse(seen[1]["preview"])

    def test_render_error_is_one_line_and_nonzero(self) -> None:
        with mock.patch.object(cli.render, "render_all",
                               side_effect=render.RenderError("clip_01: rusak")):
            code, _out, err = self._run()
        self.assertNotEqual(code, 0)
        self.assertIn("clip_01: rusak", err)
        self.assertEqual(len(err.strip().splitlines()), 1, msg=err)

    def test_ffmpeg_error_is_one_line_and_nonzero(self) -> None:
        with mock.patch.object(cli.render, "render_all",
                               side_effect=ffmpegbin.FFmpegError("tidak ada libass")):
            code, _out, err = self._run()
        self.assertNotEqual(code, 0)
        self.assertIn("tidak ada libass", err)
        self.assertEqual(len(err.strip().splitlines()), 1, msg=err)

    def test_ffmpeg_error_is_caught_specifically(self) -> None:
        """FFmpegError bukan Exception generik: CLI harus menangkapnya sendiri."""
        with mock.patch.object(cli.render, "render_all",
                               side_effect=ffmpegbin.FFmpegError("x")):
            code, _out, err = self._run()
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("ERROR:"), msg=err)

if __name__ == "__main__":
    unittest.main()
