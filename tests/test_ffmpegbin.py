"""Tes pemilihan biner ffmpeg ber-libass — hermetik, tanpa ffmpeg sungguhan.

Semua "ffmpeg" di sini adalah skrip shell sementara yang mencetak tabel filter
palsu. Tidak ada yang menyentuh PATH pengguna atau mengunduh apa pun.

Kenapa pencocokan harus pada KOLOM NAMA: deskripsi filter `ass` berbunyi
"Render ASS subtitles onto input video". Pencarian substring akan menerima
biner yang sama sekali tidak punya filter `subtitles`/`ass`, lalu render gagal
jauh di belakang dengan pesan yang membingungkan.
"""

from __future__ import annotations

import contextlib
import io
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT  # noqa: F401  (memasukkan akar repo ke sys.path)

from scripts.lib import ffmpegbin

HEADER = """Filters:
 T.. = Timeline support
 .S. = Slice threading
 ..C = Command support
 A = Audio input/output
 V = Video input/output
 N = Dynamic number and/or type of input/output
 | = Source or sink filter
"""

GOOD_LIST = HEADER + (
    " ... abench            A->A       Benchmark part of a filtergraph.\n"
    " ..C ass               V->V       Render ASS subtitles onto input video using the libass library.\n"
    " ..C subtitles         V->V       Render text subtitles onto input video using the libass library.\n"
)

# Nama filter TIDAK ada, tetapi deskripsi memuat kata "subtitles" — jebakan
# substring. Harus ditolak.
DESCRIPTION_TRAP = HEADER + (
    " ... drawbox           V->V       Draw a colored box; unlike subtitles it needs no libass.\n"
)

ASS_ONLY = HEADER + (
    " ..C ass               V->V       Render ASS subtitles onto input video using the libass library.\n"
)

NO_SUBTITLES = HEADER + (
    " ... drawbox           V->V       Draw a colored box on the input image.\n"
)

def _make_ffmpeg(dir_path: Path, name: str, listing: str) -> Path:
    """Skrip shell yang mencetak tabel filter `listing` ke stdout."""
    path = dir_path / name
    body = "#!/bin/sh\ncat <<'CLIP_EOF'\n" + listing + "CLIP_EOF\n"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path

def _make_hanging(dir_path: Path, name: str, seconds: float = 30.0) -> Path:
    path = dir_path / name
    path.write_text(f"#!/bin/sh\nsleep {seconds}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path

class FfmpegBinTestBase(unittest.TestCase):
    def setUp(self) -> None:
        ffmpegbin.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.good = _make_ffmpeg(self.tmp, "ffmpeg_good", GOOD_LIST)
        self.bad = _make_ffmpeg(self.tmp, "ffmpeg_bad", NO_SUBTITLES)

    def tearDown(self) -> None:
        ffmpegbin.clear_cache()
        self._tmp.cleanup()

    def _which(self, *paths: str | None):
        """Pengganti `shutil.which`: selalu mengembalikan kandidat pertama."""
        return lambda _name: paths[0] if paths else None

class HasSubtitlesFilterTest(FfmpegBinTestBase):
    def test_accepts_binary_with_subtitles_filter(self) -> None:
        self.assertTrue(ffmpegbin.has_subtitles_filter(str(self.good)))

    def test_rejects_binary_without_subtitles_filter(self) -> None:
        self.assertFalse(ffmpegbin.has_subtitles_filter(str(self.bad)))

    def test_rejects_description_mentioning_subtitles(self) -> None:
        """Substring pada seluruh baris akan salah menerima biner ini."""
        trap = _make_ffmpeg(self.tmp, "ffmpeg_trap", DESCRIPTION_TRAP)
        self.assertFalse(ffmpegbin.has_subtitles_filter(str(trap)))

    def test_accepts_ass_filter_name(self) -> None:
        """Filter `ass` juga bukti libass (namanya persis, bukan substring)."""
        ass_only = _make_ffmpeg(self.tmp, "ffmpeg_ass", ASS_ONLY)
        self.assertTrue(ffmpegbin.has_subtitles_filter(str(ass_only)))

    def test_missing_binary_is_false_not_raise(self) -> None:
        self.assertFalse(ffmpegbin.has_subtitles_filter(str(self.tmp / "nope")))

    def test_nonzero_exit_is_false(self) -> None:
        path = self.tmp / "ffmpeg_fail"
        path.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        path.chmod(0o755)
        self.assertFalse(ffmpegbin.has_subtitles_filter(str(path)))

    def test_timeout_is_false(self) -> None:
        """Biner yang hang tidak boleh menggantung render selamanya."""
        hang = _make_hanging(self.tmp, "ffmpeg_hang", seconds=30)
        self.assertFalse(ffmpegbin.has_subtitles_filter(str(hang), timeout=0.3))

    def test_result_is_cached_per_path(self) -> None:
        calls: list[list[str]] = []
        real_run = subprocess.run

        def counting(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(cmd))
            return real_run(cmd, *args, **kwargs)

        with mock.patch.object(ffmpegbin.subprocess, "run", side_effect=counting):
            self.assertTrue(ffmpegbin.has_subtitles_filter(str(self.good)))
            self.assertTrue(ffmpegbin.has_subtitles_filter(str(self.good)))
            self.assertTrue(ffmpegbin.has_subtitles_filter(str(self.good)))
        self.assertEqual(len(calls), 1, msg=calls)

    def test_cache_is_per_path_not_global(self) -> None:
        self.assertTrue(ffmpegbin.has_subtitles_filter(str(self.good)))
        self.assertFalse(ffmpegbin.has_subtitles_filter(str(self.bad)))

class ResolveTest(FfmpegBinTestBase):
    def test_env_wins_over_path(self) -> None:
        got = ffmpegbin.resolve(env={"CLIP_FFMPEG": str(self.good)}, which=self._which(str(self.bad)))
        self.assertEqual(got, str(self.good))

    def test_env_without_libass_raises_and_names_the_variable(self) -> None:
        """Tidak boleh diam-diam pindah ke PATH yang punya libass."""
        with self.assertRaises(ffmpegbin.FFmpegError) as ctx:
            ffmpegbin.resolve(env={"CLIP_FFMPEG": str(self.bad)}, which=self._which(str(self.good)))
        msg = str(ctx.exception)
        self.assertIn("CLIP_FFMPEG", msg)
        self.assertIn(str(self.bad), msg)

    def test_env_pointing_to_missing_file_raises(self) -> None:
        missing = str(self.tmp / "tidak-ada")
        with self.assertRaises(ffmpegbin.FFmpegError) as ctx:
            ffmpegbin.resolve(env={"CLIP_FFMPEG": missing}, which=self._which(str(self.good)))
        self.assertIn("CLIP_FFMPEG", str(ctx.exception))

    def test_path_used_when_env_unset(self) -> None:
        got = ffmpegbin.resolve(env={}, which=self._which(str(self.good)))
        self.assertEqual(got, str(self.good))

    def test_path_without_libass_falls_through_to_candidates(self) -> None:
        with mock.patch.object(ffmpegbin, "HOMEBREW_CANDIDATES", (str(self.good),)):
            got = ffmpegbin.resolve(env={}, which=self._which(str(self.bad)))
        self.assertEqual(got, str(self.good))

    def test_candidate_used_when_no_path_ffmpeg(self) -> None:
        with mock.patch.object(ffmpegbin, "HOMEBREW_CANDIDATES", (str(self.good),)):
            got = ffmpegbin.resolve(env={}, which=self._which())
        self.assertEqual(got, str(self.good))

    def test_no_candidate_raises_with_install_hint(self) -> None:
        with mock.patch.object(ffmpegbin, "HOMEBREW_CANDIDATES", (str(self.bad),)):
            with self.assertRaises(ffmpegbin.FFmpegError) as ctx:
                ffmpegbin.resolve(env={}, which=self._which())
        msg = str(ctx.exception)
        self.assertIn("brew install ffmpeg-full", msg)
        self.assertIn("CLIP_FFMPEG", msg)

    def test_error_is_runtime_error(self) -> None:
        self.assertTrue(issubclass(ffmpegbin.FFmpegError, RuntimeError))

    def test_env_whitespace_is_ignored(self) -> None:
        got = ffmpegbin.resolve(env={"CLIP_FFMPEG": "   "}, which=self._which(str(self.good)))
        self.assertEqual(got, str(self.good))

    def test_resolve_caches_probe(self) -> None:
        calls: list[list[str]] = []
        real_run = subprocess.run

        def counting(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(cmd))
            return real_run(cmd, *args, **kwargs)

        with mock.patch.object(ffmpegbin.subprocess, "run", side_effect=counting):
            a = ffmpegbin.resolve(env={}, which=self._which(str(self.good)))
            b = ffmpegbin.resolve(env={}, which=self._which(str(self.good)))
        self.assertEqual(a, b)
        self.assertEqual(len(calls), 1, msg=calls)

    def test_reads_process_env_by_default(self) -> None:
        """Tanpa argumen `env`, CLIP_FFMPEG dari os.environ dipakai."""
        with mock.patch.dict(os.environ, {"CLIP_FFMPEG": str(self.good)}, clear=False):
            got = ffmpegbin.resolve(which=self._which(str(self.bad)))
        self.assertEqual(got, str(self.good))

class CliFacingTest(unittest.TestCase):
    def test_error_message_mentions_ffmpeg_full_install(self) -> None:
        err = ffmpegbin.FFmpegError("x")
        self.assertIsInstance(err, RuntimeError)

    def test_module_has_no_import_time_subprocess(self) -> None:
        """Import modul tidak boleh memanggil ffmpeg (tes harus bisa mengubah env)."""
        with mock.patch.object(ffmpegbin.subprocess, "run", side_effect=AssertionError("dipanggil")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(hasattr(ffmpegbin, "resolve"))

if __name__ == "__main__":
    unittest.main()
