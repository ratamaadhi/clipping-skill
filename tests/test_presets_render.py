"""Tes integrasi preset `zoom_through_text`: perintah, piksel, font, lapisan.

Dua kelompok:

* `PresetFilterContractTest` — ffmpeg DI-PATCH, tidak menjalankan proses.
  Mengunci urutan filter (overlay tier-1 -> preset -> pratinjau -> caption),
  nama berkas ASS, escape `fontsdir`, konversi `PresetError` -> `RenderError`,
  dan mekanisme peringatan font hilang. Kelas ini SELALU jalan.
* `PresetPixelTest` + `CaptionLayerTest` — ffmpeg ber-libass sungguhan pada
  klip hitam sintetis 3 s @30 dengan audio (pola `tests/test_kinetic_render.py`).
  Membuktikan skala tumbuh, alfa memudar ke latar, piksel di luar jendela
  identik dengan render tanpa preset, font bundel benar-benar dipakai, dan
  caption tetap di lapisan atas preset.

Tanpa ffmpeg ber-libass, kelompok kedua SKIP dengan pesan jujur; kelompok
pertama tetap membuktikan kontrak perintah.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.helpers import ROOT

from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts import presets
from scripts import render
from scripts.lib import fontmetrics

FONT_DIR = (ROOT / "assets" / "fonts").resolve()
FONT_FILE = FONT_DIR / "DMSerifDisplay-Italic.ttf"
TYPE = "zoom_through_text"

SRC_W, SRC_H = 1920, 1080
SRC_FPS = 30
SRC_DUR = 4.0
FPS = 30
OUT_W, OUT_H = 1080, 1920
CLIP_DUR = 3.0

START = 0.5
DUR = 0.7
PRESET_TEXT = "5 JAM"

# Ambang "tinta": salah satu kanal > 20, sama dengan oracle shapes. Cukup rendah
# untuk menangkap tinta yang sedang memudar (alfa 8% -> 20) tetapi memisahkan
# dari hitam.
INK_MIN = 20
# Latar hitam setelah event boleh berbeda paling banyak 4 pada kanal terang.
BACKGROUND_MAX = 4

_FFMPEG = find_ffmpeg_with_libass()
_FFPROBE = str(Path(_FFMPEG).with_name("ffprobe")) if _FFMPEG else None
if _FFPROBE and not Path(_FFPROBE).exists():
    _FFPROBE = shutil.which("ffprobe")

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` atau set env CLIP_FFMPEG ke path ffmpeg berlibas."
)


# ---------------------------------------------------------------------------
# Fixture EDL/klip
# ---------------------------------------------------------------------------

EDL: dict[str, Any] = {
    "version": "0.1.0",
    "source": {
        "path": "src.mp4",
        "width": SRC_W,
        "height": SRC_H,
        "fps": float(SRC_FPS),
        "audio_rate": 48000,
    },
    "output": {"fps": float(FPS), "loudness_lufs": -14.0, "true_peak_db": -1.0},
}


def _preset_overlay(**props: Any) -> dict[str, Any]:
    merged = {"text": PRESET_TEXT}
    merged.update(props)
    return {
        "type": TYPE,
        "start": START,
        "end": CLIP_DUR,
        "props": merged,
    }


def _clip(*, overlays: list | None = None, captions: list | None = None,
          overlays_present: bool = True) -> dict[str, Any]:
    clip: dict[str, Any] = {
        "id": "clip_01",
        "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
        "reframe": {"mode": "center"},
        "punch": [],
        "progress": False,
        "captions": captions or [],
    }
    if overlays_present:
        clip["overlays"] = overlays or []
    return clip


# ---------------------------------------------------------------------------
# Kontrak filter (ffmpeg di-patch; selalu jalan)
# ---------------------------------------------------------------------------

class PresetFilterContractTest(unittest.TestCase):
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
        for patch in self._patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        self._tmp.cleanup()

    def _render(self, clip: dict[str, Any], **kwargs: Any) -> list[str]:
        render.render_clip(EDL, clip, self.wd, self.wd / "out" / "clip_01.mp4", **kwargs)
        self.assertEqual(len(self.cmds), 1)
        return self.cmds[0]

    @staticmethod
    def _filter_complex(cmd: list[str]) -> str:
        return cmd[cmd.index("-filter_complex") + 1]

    def _fx_path(self) -> Path:
        return self.wd / "captions" / "clip_01.fx.ass"

    def test_fx_ass_is_written_and_equals_module_output(self) -> None:
        clip = _clip(overlays=[_preset_overlay()])
        self._render(clip)
        expected, warnings = presets.build_fx_ass(clip, fps=FPS)
        self.assertEqual(warnings, [])
        self.assertIsNotNone(expected)
        self.assertTrue(self._fx_path().is_file())
        self.assertEqual(self._fx_path().read_text(encoding="utf-8"), expected)

    def test_fx_filter_comes_after_panels_and_before_caption(self) -> None:
        clip = _clip(overlays=[_preset_overlay()])
        with mock.patch.object(render.motion, "_font_path", return_value="/fonts/x.ttf"):
            clip["overlays"] = [
                {"type": "vs", "start": 0.2, "end": 2.5, "left": "Kopi", "right": "Teh"},
                _preset_overlay(),
            ]
            cmd = self._render(clip)
        fc = self._filter_complex(cmd)
        fx = fc.index("subtitles=captions/clip_01.fx.ass")
        caption = fc.index("subtitles=captions/clip_01.ass")
        panel = fc.index("drawtext=fontfile=/fonts/x.ttf")
        self.assertLess(panel, fx)
        self.assertLess(fx, caption)
        # Caption tetap filter terakhir.
        self.assertEqual(fc.rindex("subtitles="), caption)

    def test_fx_fontsdir_is_absolute_bundled_and_escaped(self) -> None:
        clip = _clip(overlays=[_preset_overlay()])
        cmd = self._render(clip)
        fc = self._filter_complex(cmd)
        escaped = render.escape_filter_value(str(FONT_DIR))
        self.assertIn(
            f"subtitles=captions/clip_01.fx.ass:fontsdir={escaped}", fc
        )
        self.assertTrue(FONT_DIR.is_absolute())

    def test_explicit_fx_fontsdir_wins(self) -> None:
        clip = _clip(overlays=[_preset_overlay()])
        cmd = self._render(clip, fx_fontsdir="/tmp/a b:c")
        fc = self._filter_complex(cmd)
        self.assertIn(
            "fontsdir=" + render.escape_filter_value("/tmp/a b:c"), fc
        )

    def test_fx_comes_before_preview(self) -> None:
        clip = _clip(overlays=[_preset_overlay()])
        cmd = self._render(clip, preview=True)
        fc = self._filter_complex(cmd)
        self.assertLess(
            fc.index("subtitles=captions/clip_01.fx.ass"),
            fc.index("scale=540:960:flags=bilinear"),
        )
        self.assertLess(fc.index("scale=540:960"), fc.index("subtitles=captions/clip_01.ass"))

    def test_clip_without_preset_has_no_fx_file_or_filter(self) -> None:
        cmd = self._render(_clip())
        self.assertFalse(self._fx_path().exists())
        self.assertNotIn(".fx.ass", self._filter_complex(cmd))

    def test_clip_with_only_vs_overlay_has_no_fx_filter(self) -> None:
        clip = _clip(overlays=[
            {"type": "vs", "start": 0.2, "end": 2.5, "left": "Kopi", "right": "Teh"}
        ])
        with mock.patch.object(render.motion, "_font_path", return_value="/fonts/x.ttf"):
            cmd = self._render(clip)
        self.assertFalse(self._fx_path().exists())
        self.assertNotIn(".fx.ass", self._filter_complex(cmd))

    def test_preset_error_becomes_render_error_naming_clip(self) -> None:
        clip = _clip(overlays=[_preset_overlay(duration=99.0)])
        with self.assertRaises(render.RenderError) as ctx:
            self._render(clip)
        message = str(ctx.exception)
        self.assertIn("clip_01", message)
        self.assertIn("duration", message)
        self.assertEqual(self.cmds, [])

    def test_missing_font_prints_warning_and_skips_preset(self) -> None:
        clip = _clip(overlays=[_preset_overlay()])
        stderr = io.StringIO()
        with mock.patch.object(render.presets, "BUNDLED_FONT", "assets/fonts/TidakAda.ttf"):
            with contextlib.redirect_stderr(stderr):
                cmd = self._render(clip)
        text = stderr.getvalue()
        self.assertIn("PERINGATAN:", text)
        self.assertIn("font", text.lower())
        self.assertFalse(self._fx_path().exists())
        self.assertNotIn(".fx.ass", self._filter_complex(cmd))


# ---------------------------------------------------------------------------
# Render nyata
# ---------------------------------------------------------------------------

def _ffmpeg_bin() -> str:
    assert _FFMPEG is not None
    return _FFMPEG


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AssertionError(
            f"perintah gagal ({proc.returncode}): {' '.join(cmd)}\n"
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


def _probe(path: Path) -> dict[str, Any]:
    assert _FFPROBE is not None
    proc = _run([
        _FFPROBE, "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ])
    data = json.loads(proc.stdout.decode("utf-8"))
    out: dict[str, Any] = {}
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind in out:
            continue
        out[kind] = stream
    return out


def _frame_rgb(path: Path, index: int) -> bytes:
    """Satu frame `index` sebagai rgb24; dipotong setelah subtitles (urutan tes)."""
    vf = (
        f"trim=start_frame={index}:end_frame={index + 1},"
        f"setpts=PTS-STARTPTS"
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.raw"
        _run([
            _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-vf", vf, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ])
        return out.read_bytes()


def _ink_bbox(data: bytes, width: int = OUT_W, height: int = OUT_H,
              threshold: int = INK_MIN) -> tuple[int, int, int, int] | None:
    """Bbox piksel dengan salah satu kanal > `threshold` pada frame penuh."""
    stride = width * 3
    min_x = min_y = 10**9
    max_x = max_y = -1
    for y in range(height):
        row = data[y * stride:(y + 1) * stride]
        if max(row) <= threshold:
            continue
        for x in range(width):
            i = x * 3
            if max(row[i], row[i + 1], row[i + 2]) > threshold:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return None
    return min_x, min_y, max_x, max_y


def _ink_width(data: bytes) -> int:
    bbox = _ink_bbox(data)
    if bbox is None:
        return 0
    return bbox[2] - bbox[0] + 1


def _peak_brightness(data: bytes) -> int:
    """Puncak kanal terang di seluruh frame (cukup `max` bytewise)."""
    return max(data)


def _count_core_yellow(data: bytes, region: tuple[int, int, int, int]) -> int:
    """Piksel inti kuning aksen caption (255,229,0) di daerah (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    count = 0
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = data[base:base + (x1 - x0) * 3]
        for x in range(x1 - x0):
            i = x * 3
            r, g, b = row[i], row[i + 1], row[i + 2]
            if r >= 240 and g >= 190 and b <= 40:
                count += 1
    return count


def _count_reddish(data: bytes, region: tuple[int, int, int, int]) -> int:
    """Piksel dominan merah (preset) di daerah yang sama."""
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    count = 0
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = data[base:base + (x1 - x0) * 3]
        for x in range(x1 - x0):
            i = x * 3
            r, g, b = row[i], row[i + 1], row[i + 2]
            if r >= 150 and g <= 90 and b <= 90:
                count += 1
    return count


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class PresetPixelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")

        cls.clip_fx = _clip(overlays=[_preset_overlay()])
        cls.clip_plain = _clip()

        cls.out_fx = cls.wd / "out" / "clip_fx.mp4"
        cls.out_plain = cls.wd / "out" / "clip_plain.mp4"
        render.render_clip(EDL, cls.clip_fx, cls.wd, cls.out_fx)
        render.render_clip(EDL, cls.clip_plain, cls.wd, cls.out_plain)

        cls.empty_fonts = cls.wd / "empty_fonts"
        cls.empty_fonts.mkdir()
        cls.out_fallback = cls.wd / "out" / "clip_fallback.mp4"
        render.render_clip(
            EDL, cls.clip_fx, cls.wd, cls.out_fallback,
            fx_fontsdir=str(cls.empty_fonts),
        )

        cls.probe_fx = _probe(cls.out_fx)
        cls.probe_plain = _probe(cls.out_plain)
        cls.ass_fx = (cls.wd / "captions" / "clip_01.fx.ass").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # -- (a) durasi/frame tidak berubah ----------------------------------

    def test_frame_count_is_identical(self) -> None:
        want = round(CLIP_DUR * FPS)
        self.assertEqual(int(self.probe_plain["video"]["nb_frames"]), want)
        self.assertEqual(int(self.probe_fx["video"]["nb_frames"]), want)

    def test_audio_duration_within_one_aac_frame(self) -> None:
        a = float(self.probe_fx["audio"]["duration"])
        b = float(self.probe_plain["audio"]["duration"])
        self.assertLessEqual(abs(a - b), 1.0 / 48.0, msg=f"preset {a:.4f}s vs tanpa {b:.4f}s")

    def test_preset_ass_single_dialogue_with_font_family(self) -> None:
        self.assertEqual(self.ass_fx.count("Dialogue:"), 1)
        self.assertIn("Style: Serif,DM Serif Display,", self.ass_fx)
        self.assertIn("\\fscx80\\fscy80", self.ass_fx)
        self.assertIn("\\t(0,700,2,\\fscx320\\fscy320)", self.ass_fx)

    # -- (b) sebelum start identik ---------------------------------------

    def test_pixels_before_start_are_identical(self) -> None:
        index = round((START - 0.1) * FPS)
        self.assertEqual(_frame_rgb(self.out_fx, index), _frame_rgb(self.out_plain, index))

    # -- (c) skala tumbuh monoton ----------------------------------------

    def test_ink_width_grows_monotonically(self) -> None:
        widths: list[int] = []
        for k in range(1, 6):
            t = START + k * (DUR / 6.0)
            frame = _frame_rgb(self.out_fx, round(t * FPS))
            widths.append(_ink_width(frame))
        self.assertTrue(all(w > 0 for w in widths), msg=f"lebar: {widths}")
        for left, right in zip(widths, widths[1:]):
            self.assertGreaterEqual(
                right, left - 2,
                msg=f"lebar tinta tidak naik monoton (toleransi 2 px): {widths}",
            )
        self.assertGreater(
            widths[-1], widths[0] + 100,
            msg=f"tinta akhir tidak jauh lebih lebar dari awal: {widths}",
        )
        self.assertGreater(widths[-1], widths[0])

    # -- (d) alfa memudar ke latar ---------------------------------------

    def test_fade_peak_decreases_and_reaches_background(self) -> None:
        peaks: list[int] = []
        for frac in (0.65, 0.725, 0.8, 0.875, 0.95):
            t = START + DUR * frac
            peaks.append(_peak_brightness(_frame_rgb(self.out_fx, round(t * FPS))))
        for left, right in zip(peaks, peaks[1:]):
            self.assertLessEqual(
                right, left, msg=f"puncak tidak turun monoton: {peaks}"
            )
        self.assertLess(peaks[-1], peaks[0], msg=f"tanpa penurunan berarti: {peaks}")

        after = round((START + DUR + 2.0 / FPS) * FPS)
        self.assertLessEqual(
            _peak_brightness(_frame_rgb(self.out_fx, after)), BACKGROUND_MAX,
            msg="tinta masih terlihat 2 frame sesudah event selesai",
        )

    # -- (e) sesudah event identik ---------------------------------------

    def test_pixels_after_event_are_identical(self) -> None:
        for offset in (2.0 / FPS, 0.5):
            with self.subTest(offset=offset):
                index = round((START + DUR + offset) * FPS)
                self.assertEqual(
                    _frame_rgb(self.out_fx, index), _frame_rgb(self.out_plain, index),
                    msg=f"frame {index} (t={index / FPS:.3f}s) berbeda",
                )

    # -- (f) kontrol font bundel -----------------------------------------

    def test_bundled_font_differs_from_system_fallback(self) -> None:
        index = round((START + 3 * DUR / 6.0) * FPS)
        bundled = _frame_rgb(self.out_fx, index)
        fallback = _frame_rgb(self.out_fallback, index)
        bbox_bundled = _ink_bbox(bundled)
        bbox_fallback = _ink_bbox(fallback)
        self.assertIsNotNone(bbox_bundled, msg="render font bundel tanpa tinta")
        self.assertIsNotNone(bbox_fallback, msg="render fallback tanpa tinta")
        assert bbox_bundled is not None and bbox_fallback is not None
        width_bundled = bbox_bundled[2] - bbox_bundled[0] + 1
        width_fallback = bbox_fallback[2] - bbox_fallback[0] + 1
        pixel_diff = sum(1 for a, b in zip(bundled, fallback) if a != b)

        # Oracle metrik: lebar tinta harus mengikuti `fontmetrics` DM Serif
        # Display Italic pada skala `\t` di frame ini (accel=2 -> x^2). Ini
        # menangkap `Fontsize` tanpa `cell_height_ratio` dan font sistem yang
        # kebetulan punya bentuk mirip. Toleransi 6% menampung bearing italic
        # dan pembulatan piksel.
        font = fontmetrics.Font.load(FONT_FILE)
        t_frame = index / FPS
        fraction = min(1.0, max(0.0, (t_frame - START) / DUR))
        scale = 0.80 + 2.40 * (fraction ** 2.0)
        predicted = font.width(PRESET_TEXT, 160.0) * scale
        self.assertAlmostEqual(
            width_bundled / predicted, 1.0, delta=0.06,
            msg=(
                f"lebar tinta {width_bundled} px vs prediksi fontmetrics "
                f"{predicted:.1f} px (rasio {width_bundled / predicted:.4f}); "
                f"Fontsize/font bundel tidak sesuai"
            ),
        )

        differs = abs(width_bundled - width_fallback) >= 5 or pixel_diff >= 2000
        if not differs:
            self.skipTest(
                "font sistem kebetulan identik dengan DM Serif Display Italic "
                f"(lebar {width_bundled} vs {width_fallback}, beda byte {pixel_diff}); "
                "kontrol tidak bisa membedakan, bukan bukti lulus."
            )
        self.assertTrue(
            differs,
            msg=(
                f"render fallback tidak bisa dibedakan: lebar {width_bundled} vs "
                f"{width_fallback}, beda byte {pixel_diff}"
            ),
        )


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class CaptionLayerTest(unittest.TestCase):
    """Caption kinetic harus digambar SESUDAH preset (filter terakhir)."""

    CAPTION = {
        "start": 0.30,
        "end": 1.60,
        "text": "JAM",
        "emphasis": "JAM",
        "words": [{"w": "JAM", "start": 0.30, "end": 1.60}],
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")

        # rect 800x300 berpusat di (540,1400): sama dengan pusat kata kinetic.
        overlay = {
            "type": TYPE,
            "start": START,
            "end": CLIP_DUR,
            "rect": {"x": 140, "y": 1250, "w": 800, "h": 300},
            "props": {"text": "JAM", "colour": "#FF0000"},
        }
        cls.clip_with = _clip(
            overlays=[overlay], captions=[dict(cls.CAPTION)]
        )
        cls.clip_with["caption_style"] = "kinetic"
        cls.clip_without = _clip(captions=[dict(cls.CAPTION)])
        cls.clip_without["caption_style"] = "kinetic"

        cls.out_with = cls.wd / "out" / "with.mp4"
        cls.out_without = cls.wd / "out" / "without.mp4"
        render.render_clip(EDL, cls.clip_with, cls.wd, cls.out_with)
        render.render_clip(EDL, cls.clip_without, cls.wd, cls.out_without)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_caption_ink_stays_on_top_of_preset(self) -> None:
        t = 1.0  # preset alfa ~0,71 (masih pekat), caption sudah settle
        index = round(t * FPS)
        region = (400, 1340, 680, 1460)

        without = _frame_rgb(self.out_without, index)
        with_preset = _frame_rgb(self.out_with, index)

        caption_only = _count_core_yellow(without, region)
        combined = _count_core_yellow(with_preset, region)
        red = _count_reddish(with_preset, region)

        self.assertGreater(caption_only, 100, msg="caption kuning tidak terlihat")
        self.assertGreater(red, 1000, msg="preset merah tidak terlihat")
        self.assertGreaterEqual(
            combined, int(caption_only * 0.9),
            msg=(
                f"caption tertutup preset: piksel kuning {combined} vs {caption_only} "
                f"(preset merah {red}); caption harus jadi filter terakhir"
            ),
        )


if __name__ == "__main__":
    unittest.main()
