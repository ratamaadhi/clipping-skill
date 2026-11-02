"""Tes integrasi render dengan ffmpeg DI-PATCH: tidak ada proses yang dijalankan.

Yang diuji di sini adalah KONTRAK perintah: penulis ASS mana yang dipakai,
`fontsdir` apa yang diteruskan, dan fragmen filter pratinjau. Hasil piksel
diuji terpisah di `tests/test_kinetic_render.py` dengan ffmpeg sungguhan.

Klip kinetic memakai skenario yang sama dengan oracle libass
(`Pertama, pasti nenekmu bangga.`, empat kata, satu emphasis) supaya angka
`Fontsize` 113,15 di sini merujuk pada cacat R3 yang sudah diperbaiki.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.ffmpeg_libass import find_ffmpeg_with_libass
from tests.helpers import ROOT

from scripts import captions as cap_mod
from scripts import kinetic as kinetic_mod
from scripts import render
from scripts.lib import jsonio

FONT_DIR = (ROOT / "assets" / "fonts").resolve()

EDL: dict[str, Any] = {
    "version": "0.1.0",
    "source": {
        "path": "src.mp4",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "audio_rate": 48000,
    },
    "output": {"fps": 30.0, "loudness_lufs": -14.0, "true_peak_db": -1.0},
}

KINETIC_CAPTIONS = [
    {
        "start": 1.02,
        "end": 2.34,
        "text": "Pertama, pasti nenekmu bangga.",
        "emphasis": "pasti",
        "words": [
            {"w": "Pertama,", "start": 1.02, "end": 1.34},
            {"w": "pasti", "start": 1.38, "end": 1.58},
            {"w": "nenekmu", "start": 1.62, "end": 1.94},
            {"w": "bangga.", "start": 2.02, "end": 2.34},
        ],
    }
]

PHRASE_CAPTIONS = [
    {"start": 0.2, "end": 1.6, "text": "Kopi atau teh", "emphasis": "teh"},
]

def _clip(**overrides: Any) -> dict[str, Any]:
    clip: dict[str, Any] = {
        "id": "clip_01",
        "segments": [{"src_start": 0.0, "src_end": 3.0, "speed": 1.0}],
        "reframe": {"mode": "center"},
        "punch": [],
        "progress": False,
        "captions": PHRASE_CAPTIONS,
    }
    clip.update(overrides)
    return clip

class RenderWithPatchedFfmpeg(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = Path(self._tmp.name).resolve()
        (self.wd / "src.mp4").write_bytes(b"")
        self.cmds: list[list[str]] = []

        def run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
            self.cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        self._patches = [
            mock.patch.object(render.subprocess, "run", side_effect=run),
            mock.patch.object(render.ffmpegbin, "resolve", return_value="/fake/ffmpeg"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _render(self, clip: dict[str, Any], out: str = "out.mp4", **kwargs: Any) -> list[str]:
        render.render_clip(EDL, clip, self.wd, self.wd / "out" / out, **kwargs)
        self.assertEqual(len(self.cmds), 1)
        return self.cmds[0]

    def _ass(self, clip_id: str = "clip_01") -> str:
        return (self.wd / "captions" / f"{clip_id}.ass").read_text(encoding="utf-8")

    @staticmethod
    def _filter_complex(cmd: list[str]) -> str:
        return cmd[cmd.index("-filter_complex") + 1]

class KineticWriterTest(RenderWithPatchedFfmpeg):
    def test_kinetic_ass_has_kinetic_style_and_pos(self) -> None:
        cmd = self._render(_clip(caption_style="kinetic", captions=KINETIC_CAPTIONS))
        ass = self._ass()
        self.assertIn("Style: Kinetic", ass)
        self.assertIn("\\an5\\pos", ass)
        self.assertEqual(ass.count("Dialogue:"), 4, msg=ass)
        self.assertEqual(cmd[0], "/fake/ffmpeg")

    def test_kinetic_fontsize_is_em_times_cell_height_ratio(self) -> None:
        self._render(_clip(caption_style="kinetic", captions=KINETIC_CAPTIONS))
        style = [ln for ln in self._ass().splitlines() if ln.startswith("Style: Kinetic,")][0]
        fontsize = float(style[len("Style: "):].split(",")[2])
        self.assertAlmostEqual(fontsize, 113.15, places=2, msg=style)

    def test_kinetic_passes_absolute_bundled_fontsdir(self) -> None:
        cmd = self._render(_clip(caption_style="kinetic", captions=KINETIC_CAPTIONS))
        fc = self._filter_complex(cmd)
        self.assertIn(f"fontsdir={FONT_DIR}", fc)
        self.assertTrue(FONT_DIR.is_absolute())
        self.assertIn("subtitles=captions/clip_01.ass", fc)

    def test_explicit_fontsdir_wins_for_kinetic(self) -> None:
        cmd = self._render(
            _clip(caption_style="kinetic", captions=KINETIC_CAPTIONS), fontsdir="/custom/fonts"
        )
        self.assertIn("fontsdir=/custom/fonts", self._filter_complex(cmd))
        self.assertNotIn(str(FONT_DIR), self._filter_complex(cmd))

    def test_kinetic_preview_keeps_playres_1080x1920(self) -> None:
        self._render(_clip(caption_style="kinetic", captions=KINETIC_CAPTIONS), preview=True)
        ass = self._ass()
        self.assertIn("PlayResX: 1080", ass)
        self.assertIn("PlayResY: 1920", ass)

class PhraseWriterTest(RenderWithPatchedFfmpeg):
    def test_phrase_ass_is_byte_identical_to_old_writer(self) -> None:
        self._render(_clip())
        want = cap_mod.build_ass(PHRASE_CAPTIONS)
        self.assertEqual(self._ass(), want)

    def test_phrase_has_no_fontsdir(self) -> None:
        cmd = self._render(_clip())
        fc = self._filter_complex(cmd)
        self.assertIn("subtitles=captions/clip_01.ass", fc)
        self.assertNotIn("fontsdir=", fc)

    def test_phrase_explicit_fontsdir_still_passed(self) -> None:
        cmd = self._render(_clip(), fontsdir="/x")
        self.assertIn("fontsdir=/x", self._filter_complex(cmd))

class StyleValidationTest(RenderWithPatchedFfmpeg):
    def test_unknown_style_raises(self) -> None:
        with self.assertRaises(render.RenderError) as ctx:
            self._render(_clip(caption_style="zzz"))
        self.assertIn("zzz", str(ctx.exception))
        self.assertEqual(self.cmds, [], msg="tidak boleh memanggil ffmpeg")

    def test_kinetic_without_words_raises_with_caption_index(self) -> None:
        caps = [
            {"start": 0.0, "end": 1.0, "text": "punya kata",
             "words": [{"w": "punya", "start": 0.0, "end": 0.4}]},
            {"start": 1.2, "end": 2.0, "text": "tanpa kata"},
        ]
        with self.assertRaises(render.RenderError) as ctx:
            self._render(_clip(caption_style="kinetic", captions=caps))
        msg = str(ctx.exception)
        self.assertIn("clip_01", msg)
        self.assertIn("1", msg)
        self.assertIn("words", msg)
        self.assertEqual(self.cmds, [], msg="tidak boleh memanggil ffmpeg")

    def test_kinetic_with_empty_words_raises(self) -> None:
        caps = [{"start": 0.0, "end": 1.0, "text": "kosong", "words": []}]
        with self.assertRaises(render.RenderError):
            self._render(_clip(caption_style="kinetic", captions=caps))

class EscapeFontsdirTest(unittest.TestCase):
    """Escape nilai opsi filtergraph: dua lapis parser ffmpeg (opsi + graph)."""

    def test_escapes_filtergraph_special_characters(self) -> None:
        # Spasi: satu backslash per lapis (spasi bukan pemisah opsi, jadi
        # lapis-1 tidak menambah). Titik dua: `\:` -> `\\\:` setelah lapis-2.
        got = render.escape_filter_value("/tmp/a b:c'd,e[f]g\\h")
        self.assertEqual(got, "/tmp/a\\ b\\\\\\:c\\\\\\'d\\,e\\[f\\]g\\\\\\\\h")

    def test_plain_path_unchanged(self) -> None:
        self.assertEqual(render.escape_filter_value("/x"), "/x")

    def test_escaped_value_actually_parses_in_ffmpeg(self) -> None:
        """Bukti empiris: satu lapis escape DITOLAK ffmpeg, dua lapis diterima.

        Tanpa ffmpeg ber-libass tes ini di-skip; nilainya ada di
        `tests/test_kinetic_render.py` yang merender sungguhan.
        """
        ffmpeg = find_ffmpeg_with_libass()
        if ffmpeg is None:
            self.skipTest("tidak ada ffmpeg ber-libass")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            font_dir = root / "fonts dir:with colon"
            font_dir.mkdir()
            font = FONT_DIR / "ArchivoBlack-Regular.ttf"
            shutil.copy(font, font_dir / font.name)
            ass = root / "clip.ass"
            ass.write_text(
                kinetic_mod.build_ass(_clip(caption_style="kinetic",
                                            captions=KINETIC_CAPTIONS)),
                encoding="utf-8",
            )
            sub = (
                f"subtitles={render.escape_filter_value(str(ass))}"
                f":fontsdir={render.escape_filter_value(str(font_dir))}"
            )
            out = root / "frame.raw"
            proc = subprocess.run(
                [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=3",
                 "-vf", sub + ",trim=start_frame=48:end_frame=49,setpts=PTS-STARTPTS",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", str(out)],
                capture_output=True, timeout=120, check=False,
            )
            self.assertEqual(
                proc.returncode, 0,
                msg=proc.stderr.decode("utf-8", errors="replace")[:800],
            )
            self.assertTrue(out.is_file())

    def test_escaped_fontsdir_in_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp).resolve()
            (wd / "src.mp4").write_bytes(b"")
            cmds: list[list[str]] = []

            def run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
                cmds.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(render.subprocess, "run", side_effect=run), \
                    mock.patch.object(render.ffmpegbin, "resolve", return_value="/fake/ffmpeg"):
                render.render_clip(
                    EDL, _clip(caption_style="kinetic", captions=KINETIC_CAPTIONS),
                    wd, wd / "out" / "clip_01.mp4", fontsdir="/tmp/a b:c",
                )
            fc = cmds[0][cmds[0].index("-filter_complex") + 1]
            self.assertIn(f"fontsdir={render.escape_filter_value('/tmp/a b:c')}", fc)
            self.assertIn("fontsdir=/tmp/a\\ b\\\\\\:c", fc)

class PreviewFilterTest(RenderWithPatchedFfmpeg):
    def test_preview_inserts_scale_and_fps_before_subtitles(self) -> None:
        cmd = self._render(_clip(), preview=True)
        fc = self._filter_complex(cmd)
        self.assertIn("scale=540:960:flags=bilinear", fc)
        self.assertIn("fps=15", fc)
        self.assertLess(fc.index("scale=540:960"), fc.index("subtitles="))

    def test_preview_encoder_flags(self) -> None:
        cmd = self._render(_clip(), preview=True)
        self.assertEqual(cmd[cmd.index("-preset") + 1], "ultrafast")
        self.assertEqual(cmd[cmd.index("-crf") + 1], "30")
        self.assertEqual(cmd[cmd.index("-r") + 1], "15")

    def test_preview_comes_after_overlays(self) -> None:
        clip = _clip(overlays=[{"type": "vs", "start": 0.5, "end": 2.5,
                                "left": "Kopi", "right": "Teh"}])
        with mock.patch.object(render.motion, "_font_path", return_value="/fonts/x.ttf"):
            cmd = self._render(clip, preview=True)
        fc = self._filter_complex(cmd)
        self.assertLess(fc.index("drawtext=fontfile=/fonts/x.ttf"), fc.index("scale=540:960"))
        self.assertLess(fc.index("scale=540:960"), fc.index("subtitles="))

    def test_non_preview_has_none_of_preview_markers(self) -> None:
        cmd = self._render(_clip(), preview=False)
        fc = self._filter_complex(cmd)
        self.assertNotIn("scale=540:960", fc)
        self.assertNotIn("fps=15", fc)
        self.assertNotEqual(cmd[cmd.index("-preset") + 1], "ultrafast")
        self.assertNotEqual(cmd[cmd.index("-crf") + 1], "30")
        self.assertNotEqual(cmd[cmd.index("-r") + 1], "15")

    def test_preview_keeps_target_resolution_scale(self) -> None:
        """Scale 1080x1920 tetap ada; pratinjau mengecil SETELAH itu."""
        cmd = self._render(_clip(), preview=True)
        fc = self._filter_complex(cmd)
        self.assertIn("scale=1080:1920:flags=lanczos", fc)
        self.assertLess(fc.index("scale=1080:1920"), fc.index("scale=540:960"))

class RenderAllPreviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = Path(self._tmp.name).resolve()
        (self.wd / "src.mp4").write_bytes(b"")
        jsonio.write_json(self.wd / "edl.json", {**EDL, "clips": [_clip()]})
        self.paths: list[Path] = []

        def fake_render(edl, clip, work_dir, out_path, **_kwargs):  # type: ignore[no-untyped-def]
            self.paths.append(Path(out_path))
            return Path(out_path)

        self._patch = mock.patch.object(render, "render_clip", side_effect=fake_render)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_preview_output_name_is_preview_mp4(self) -> None:
        out = render.render_all(self.wd, preview=True)
        self.assertEqual(out, [self.wd / "out" / "clip_01.preview.mp4"])

    def test_preview_never_overwrites_final_name(self) -> None:
        render.render_all(self.wd, preview=True)
        render.render_all(self.wd, preview=False)
        self.assertEqual(
            [p.name for p in self.paths], ["clip_01.preview.mp4", "clip_01.mp4"]
        )

    def test_preview_flag_forwarded_to_render_clip(self) -> None:
        calls: list[dict[str, Any]] = []

        def fake(edl, clip, work_dir, out_path, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return Path(out_path)

        with mock.patch.object(render, "render_clip", side_effect=fake):
            render.render_all(self.wd, preview=True)
            render.render_all(self.wd)
        self.assertTrue(calls[0].get("preview"))
        self.assertFalse(calls[1].get("preview", False))

if __name__ == "__main__":
    unittest.main()
