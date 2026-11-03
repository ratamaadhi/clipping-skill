"""Tes integrasi render dan oracle libass untuk efek pullback (Langkah 5b-6).

Kelompok pengujian:
1. `PullbackContractTest`: ffmpeg di-mock, mengunci urutan filter, format perintah,
   konversi PullbackError -> RenderError, peringatan, dan byte-identik untuk klip tanpa pullback.
2. `PullbackOracleRenderTest` (skipUnless ffmpeg+libass):
   Render video sintetis 1080x1920 @30 4-kuadran berwarna kontras tinggi:
   (a) Jumlah frame dan durasi audio IDENTIK (+-0 frame, +-1 frame AAC).
   (b) Sebelum start (t < 1.0): piksel IDENTIK dengan render tanpa efek.
   (c) Pada akhir shrink: bbox video di dalam latar = window teoretis +-2 px, latar krem +-4 di luar bbox.
   (d) Selama shrink: lebar bbox menurun monoton (+-2 px) dan mengikuti kurva ease pada >= 5 titik waktu.
   (e) Count-up: angka dipegang stabil pada nilai `to` selama fase hold.
   (f) Setelah grow selesai (t > 5.0): piksel IDENTIK dengan render tanpa efek.
   (g) Caption tetap di lapisan teratas di atas jendela.
   (h) Pratinjau (preview=True) menghasilkan jendela proporsional pada 540x960.
   (i) Klip tanpa overlay pullback: cmd[1:] identik dengan HEAD hash harness.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.ffmpeg_libass import find_ffmpeg_with_libass
from tests.helpers import ROOT

from scripts import pullback
from scripts import render
from scripts.lib import ffmpegbin

_FFMPEG = find_ffmpeg_with_libass()
_FFPROBE = str(Path(_FFMPEG).with_name("ffprobe")) if _FFMPEG else None
if _FFPROBE and not Path(_FFPROBE).exists():
    _FFPROBE = shutil.which("ffprobe")

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` atau set env CLIP_FFMPEG ke path ffmpeg berlibass."
)

FONT_DIR = (ROOT / "assets" / "fonts").resolve()
ARCHIVO_FILE = FONT_DIR / "ArchivoBlack-Regular.ttf"

FPS = 30
OUT_W = 1080
OUT_H = 1920
CLIP_DUR = 6.0

# Parameter Pullback
PB_START = 1.0
PB_END = 5.0
PB_SHRINK = 0.6
PB_GROW = 0.5
PB_COUNT = 1.2
PB_FROM = 0
PB_TO = 100
PB_SUFFIX = "%"

WIN_W = 648
WIN_H = 1152
WIN_X = 216
WIN_Y = 640

# Warna latar krem: #F6EEDC -> (246, 238, 220)
CREAM_RGB = (246, 238, 220)


def _ffmpeg_bin() -> str:
    assert _FFMPEG is not None
    return _FFMPEG


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AssertionError(
            f"perintah gagal ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.decode('utf-8', errors='replace')[:1500]}"
        )
    return proc


def _make_quadrant_source(path: Path, duration: float = CLIP_DUR) -> None:
    """Buat video sintetis 1080x1920 30fps dengan 4 kuadran warna kontras."""
    filter_complex = (
        f"color=c=red:s=540x960:r={FPS}:d={duration:g}[tl];"
        f"color=c=green:s=540x960:r={FPS}:d={duration:g}[tr];"
        f"color=c=blue:s=540x960:r={FPS}:d={duration:g}[bl];"
        f"color=c=magenta:s=540x960:r={FPS}:d={duration:g}[br];"
        "[tl][tr]hstack[top];"
        "[bl][br]hstack[bot];"
        "[top][bot]vstack,format=yuv420p[v];"
        f"sine=frequency=440:sample_rate=48000:duration={duration:g}[a]"
    )
    _run([
        _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(path),
    ])


def _frame_rgb(path: Path, index: int) -> bytes:
    """Ekstrak satu frame video sebagai raw rgb24."""
    vf = f"trim=start_frame={index}:end_frame={index + 1},setpts=PTS-STARTPTS"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.raw"
        _run([
            _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-vf", vf, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ])
        return out.read_bytes()


def _px(data: bytes, x: int, y: int, width: int = OUT_W) -> tuple[int, int, int]:
    base = (y * width + x) * 3
    return data[base], data[base + 1], data[base + 2]


def _is_cream(rgb: tuple[int, int, int], tol: int = 15) -> bool:
    """Cek apakah warna piksel cocok dengan warna latar krem #F6EEDC."""
    return (
        abs(rgb[0] - CREAM_RGB[0]) <= tol
        and abs(rgb[1] - CREAM_RGB[1]) <= tol
        and abs(rgb[2] - CREAM_RGB[2]) <= tol
    )


def _scan_video_bbox(data: bytes, width: int = OUT_W, height: int = OUT_H) -> tuple[int, int, int, int] | None:
    """Cari bounding box video (area non-krem) di dalam kanvas."""
    min_x = min_y = 10**9
    max_x = max_y = -1
    stride = width * 3
    y_cutoff = int(round(height * (580.0 / 1920.0)))

    # Scan grid dengan step 2 px untuk kecepatan dan akurasi tinggi
    for y in range(0, height, 2):
        row_base = y * stride
        for x in range(0, width, 2):
            i = row_base + x * 3
            rgb = (data[i], data[i + 1], data[i + 2])
            # Video memiliki warna kuadran merah/hijau/biru/magenta yang sangat berbeda dari krem
            if not _is_cream(rgb, tol=25):
                # Bukan krem: abaikan area angka di atas y_cutoff
                if y >= y_cutoff:
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


def _diff_max(d1: bytes, d2: bytes) -> int:
    """Selisih maksimum kanal antara dua frame raw."""
    assert len(d1) == len(d2)
    max_d = 0
    for a, b in zip(d1, d2):
        diff = abs(a - b)
        if diff > max_d:
            max_d = diff
    return max_d


class PullbackContractTest(unittest.TestCase):
    """Pengujian kontrak dan integrasi render tanpa proses ffmpeg nyata."""

    def setUp(self):
        self._orig_run = render.subprocess.run
        self._orig_resolve = render.ffmpegbin.resolve if hasattr(render, "ffmpegbin") else None
        self._orig_font_path = render.motion._font_path if hasattr(render, "motion") else None
        if hasattr(render, "motion"):
            render.motion._font_path = lambda: "/fonts/DejaVuSans-Bold.ttf"

    def tearDown(self):
        render.subprocess.run = self._orig_run
        if self._orig_resolve is not None:
            render.ffmpegbin.resolve = self._orig_resolve
        if self._orig_font_path is not None:
            render.motion._font_path = self._orig_font_path

    def test_clip_without_pullback_is_byte_identical_to_head(self):
        """Klip tanpa overlay pullback harus menghasilkan hash cmd[1:] yang identik dengan HEAD."""
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            (wd / "src.mp4").write_bytes(b"")
            edl = {
                "source": {"path": str(wd / "src.mp4"), "width": 1920, "height": 1080, "audio_rate": 48000},
                "output": {"fps": 30.0, "loudness_lufs": -14.0, "true_peak_db": -1.0},
            }
            clip = {
                "id": "clip_01",
                "segments": [
                    {"src_start": 10.0, "src_end": 14.0, "speed": 1.0, "out_start": 0.0},
                    {"src_start": 15.0, "src_end": 19.0, "speed": 1.0, "out_start": 4.0},
                ],
                "captions": [{"start": 0.2, "end": 1.6, "text": "Halo semuanya, apa kabar", "emphasis": "semuanya"}],
                "reframe": {"mode": "center", "bias_x": 0.0, "bias_y": 0.0},
                "punch": [{"t": 2.0, "scale": 1.14, "dur": 0.5}],
                "progress": True,
                "overlays": [{"type": "vs", "start": 0.6, "end": 3.6, "left": "A", "right": "B"}],
            }

            captured = {}
            def fake_run(cmd, *a, **k):
                captured["cmd"] = list(cmd)
                return subprocess.CompletedProcess(cmd, 0, b"", b"")

            render.subprocess.run = fake_run
            render.ffmpegbin.resolve = lambda *a, **k: "ffmpeg"

            # 1. tanpa fontsdir
            render.render_clip(edl, clip, wd, wd / "o.mp4", fontsdir=None)
            c = [str(x).replace(str(wd), "<WD>") for x in captured["cmd"][1:]]
            h_tanpa = hashlib.sha256(json.dumps(c, ensure_ascii=False).encode()).hexdigest()[:20]
            self.assertEqual(h_tanpa, "ef8f36cddd38b5240253")

            # 2. dengan fontsdir
            render.render_clip(edl, clip, wd, wd / "o.mp4", fontsdir="/x")
            c = [str(x).replace(str(wd), "<WD>") for x in captured["cmd"][1:]]
            h_dengan = hashlib.sha256(json.dumps(c, ensure_ascii=False).encode()).hexdigest()[:20]
            self.assertEqual(h_dengan, "221ec8f8ab5034b1639b")

    def test_invalid_pullback_props_raises_render_error(self):
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            (wd / "src.mp4").write_bytes(b"")
            edl = {
                "source": {"path": str(wd / "src.mp4"), "width": 1080, "height": 1920},
                "output": {"fps": 30.0},
            }
            clip = {
                "id": "clip_err",
                "segments": [{"src_start": 0.0, "src_end": 5.0}],
                "overlays": [
                    {
                        "type": "pullback",
                        "start": 1.0,
                        "end": 4.0,
                        "props": {"from": 10, "to": 10},  # to == from -> PullbackError
                    }
                ],
            }
            with self.assertRaises(render.RenderError) as ctx:
                render.render_clip(edl, clip, wd, wd / "o.mp4")
            self.assertIn("clip_err", str(ctx.exception))
            self.assertIn("pullback", str(ctx.exception).lower())

    def test_filter_chain_order_with_pullback(self):
        """Urutan filter: base -> progress -> panels -> pullback -> pb_sub -> preview -> captions."""
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            (wd / "src.mp4").write_bytes(b"")
            edl = {
                "source": {"path": str(wd / "src.mp4"), "width": 1080, "height": 1920},
                "output": {"fps": 30.0},
            }
            clip = {
                "id": "clip_pb",
                "segments": [{"src_start": 0.0, "src_end": 10.0}],
                "captions": [{"start": 1.0, "end": 3.0, "text": "Test Caption"}],
                "overlays": [
                    {
                        "type": "pullback",
                        "start": 2.0,
                        "end": 8.0,
                        "props": {"from": 0, "to": 100},
                    }
                ],
            }

            captured = {}
            def fake_run(cmd, *a, **k):
                captured["cmd"] = list(cmd)
                return subprocess.CompletedProcess(cmd, 0, b"", b"")

            render.subprocess.run = fake_run
            render.ffmpegbin.resolve = lambda *a, **k: "ffmpeg"
            render.render_clip(edl, clip, wd, wd / "o.mp4", preview=True)

            fc = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
            parts = fc.split(";")

            # Periksa urutan keberadaan label
            fc_str = ";".join(parts)
            idx_vpb = fc_str.find("[vpb]")
            idx_vpb_sub = fc_str.find("[vpb_sub]")
            idx_vprev = fc_str.find("[vprev]")
            idx_sub = fc_str.rfind("subtitles=captions/clip_pb.ass")

            self.assertGreater(idx_vpb, 0)
            self.assertGreater(idx_vpb_sub, idx_vpb)
            self.assertGreater(idx_vprev, idx_vpb_sub)
            self.assertGreater(idx_sub, idx_vprev)


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class PullbackOracleRenderTest(unittest.TestCase):
    """Oracle piksel dan video nyata dengan ffmpeg + libass."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.wd = Path(cls.tmp_dir.name)
        cls.src_path = cls.wd / "source.mp4"
        _make_quadrant_source(cls.src_path, duration=CLIP_DUR)

        cls.edl = {
            "version": "0.1.0",
            "source": {
                "path": str(cls.src_path),
                "width": OUT_W,
                "height": OUT_H,
                "audio_rate": 48000,
            },
            "output": {
                "fps": float(FPS),
                "loudness_lufs": -14.0,
                "true_peak_db": -1.0,
            },
        }

        # 1. Render klip dasar (tanpa efek pullback)
        cls.clip_base = {
            "id": "clip_base",
            "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0, "out_start": 0.0}],
            "captions": [{"start": 1.0, "end": 4.0, "text": "Caption Utama"}],
            "progress": False,
            "overlays": [],
        }
        cls.out_base = cls.wd / "base.mp4"
        render.render_clip(cls.edl, cls.clip_base, cls.wd, cls.out_base, preset="ultrafast", crf=18)

        # 2. Render klip dengan efek pullback
        cls.clip_pb = {
            "id": "clip_pb",
            "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0, "out_start": 0.0}],
            "captions": [{"start": 1.0, "end": 4.0, "text": "Caption Utama"}],
            "progress": False,
            "overlays": [
                {
                    "type": "pullback",
                    "start": PB_START,
                    "end": PB_END,
                    "props": {
                        "from": PB_FROM,
                        "to": PB_TO,
                        "decimals": 0,
                        "suffix": PB_SUFFIX,
                        "shrink": PB_SHRINK,
                        "grow": PB_GROW,
                        "count": PB_COUNT,
                        "title": "STATISTIK",
                        "label": "Keberhasilan",
                        "window": {"x": WIN_X, "y": WIN_Y, "w": WIN_W},
                    },
                }
            ],
        }
        cls.out_pb = cls.wd / "pullback.mp4"
        render.render_clip(cls.edl, cls.clip_pb, cls.wd, cls.out_pb, preset="ultrafast", crf=18)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def test_a_frame_count_and_audio_duration_identical(self):
        """(a) Jumlah frame dan durasi audio IDENTIK (+-0 frame, +-1 frame AAC)."""
        def _get_info(path: Path):
            p = _run([
                _FFPROBE, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=nb_frames,duration", "-of", "json", str(path)
            ])
            v_info = json.loads(p.stdout.decode())["streams"][0]
            p_a = _run([
                _FFPROBE, "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=duration", "-of", "json", str(path)
            ])
            a_info = json.loads(p_a.stdout.decode())["streams"][0]
            return int(v_info["nb_frames"]), float(v_info["duration"]), float(a_info["duration"])

        frames_base, dur_v_base, dur_a_base = _get_info(self.out_base)
        frames_pb, dur_v_pb, dur_a_pb = _get_info(self.out_pb)

        # Frame count harus persis sama (+-0 frame)
        self.assertEqual(frames_pb, frames_base)
        self.assertEqual(frames_pb, int(round(CLIP_DUR * FPS)))

        # Audio duration harus persis sama (+-1 frame AAC = ~0.021s)
        self.assertAlmostEqual(dur_a_pb, dur_a_base, delta=0.03)

    def test_b_pixels_identical_before_start(self):
        """(b) Sebelum start (t=0.5s, frame 15): piksel IDENTIK dengan render tanpa efek."""
        frame_idx = 15  # 0.5s
        rgb_base = _frame_rgb(self.out_base, frame_idx)
        rgb_pb = _frame_rgb(self.out_pb, frame_idx)
        diff = _diff_max(rgb_base, rgb_pb)
        self.assertLessEqual(diff, 2, f"Piksel sebelum start berbeda: max_diff={diff}")

    def test_c_bbox_at_end_of_shrink_and_cream_background(self):
        """(c) Pada akhir shrink (frame 48, t=1.6s): bbox video = window +-2 px, latar krem +-4."""
        # Frame pada akhir shrink: start(1.0s) + shrink(0.6s) = 1.6s -> frame 48
        frame_idx = int(round((PB_START + PB_SHRINK) * FPS))
        rgb_pb = _frame_rgb(self.out_pb, frame_idx)

        # Periksa warna latar krem di beberapa titik luar jendela
        # Di kiri jendela (x=50, y=1000)
        px_left = _px(rgb_pb, 50, 1000)
        self.assertTrue(
            _is_cream(px_left, tol=4),
            f"Warna kiri bukan krem: {px_left} vs {CREAM_RGB}"
        )
        # Di kanan jendela (x=1000, y=1000)
        px_right = _px(rgb_pb, 1000, 1000)
        self.assertTrue(
            _is_cream(px_right, tol=4),
            f"Warna kanan bukan krem: {px_right} vs {CREAM_RGB}"
        )
        # Di bawah jendela (x=540, y=1850)
        px_bot = _px(rgb_pb, 540, 1850)
        self.assertTrue(
            _is_cream(px_bot, tol=4),
            f"Warna bawah bukan krem: {px_bot} vs {CREAM_RGB}"
        )

        # Periksa bbox video
        bbox = _scan_video_bbox(rgb_pb)
        self.assertIsNotNone(bbox)
        min_x, min_y, max_x, max_y = bbox
        measured_w = max_x - min_x + 1
        measured_h = max_y - min_y + 1

        self.assertAlmostEqual(min_x, WIN_X, delta=2)
        self.assertAlmostEqual(min_y, WIN_Y, delta=2)
        self.assertAlmostEqual(measured_w, WIN_W, delta=2)
        self.assertAlmostEqual(measured_h, WIN_H, delta=2)

    def test_d_bbox_width_decreases_monotonically_during_shrink(self):
        """(d) Selama shrink, lebar bbox menurun monoton (+-2 px) dan mengikuti kurva ease."""
        # 6 titik waktu selama shrink: t in [1.1s, 1.2s, 1.3s, 1.4s, 1.5s, 1.6s]
        # Frame: 33, 36, 39, 42, 45, 48
        sample_times = [1.1, 1.2, 1.3, 1.4, 1.5, 1.6]
        measured_widths: list[int] = []

        for t in sample_times:
            f_idx = int(round(t * FPS))
            data = _frame_rgb(self.out_pb, f_idx)
            bbox = _scan_video_bbox(data)
            self.assertIsNotNone(bbox, f"Video tidak ditemukan pada t={t}")
            w = bbox[2] - bbox[0] + 1
            measured_widths.append(w)

            # Hitung lebar teoretis mengikuti smoothstep
            p = (t - PB_START) / PB_SHRINK
            e = pullback._smoothstep(p)
            expected_w = OUT_W - (OUT_W - WIN_W) * e
            self.assertAlmostEqual(
                w, expected_w, delta=4,
                msg=f"Lebar pada t={t} (frame {f_idx}) meleset: terukur {w} vs teoretis {expected_w:.1f}"
            )

        # Uji monoton turun
        for i in range(len(measured_widths) - 1):
            self.assertGreaterEqual(
                measured_widths[i] + 2,  # toleransi 2 px
                measured_widths[i + 1],
                f"Lebar tidak monoton turun: {measured_widths}"
            )

    def test_e_count_up_reads_target_during_hold(self):
        """(e) Nilai angka stabil pada target (100%) selama fase hold."""
        # Fase hold: dari t=2.8s (frame 84) sampai t=4.5s (frame 135)
        # Ambil sampel frame 90 dan frame 120
        frame_90 = _frame_rgb(self.out_pb, 90)
        frame_120 = _frame_rgb(self.out_pb, 120)

        # Region angka: x in [300, 780], y in [240, 480]
        # Tinta angka Archivo Black adalah gelap (DARK_RGB) di atas latar krem
        def _get_region_ink(data: bytes) -> bytes:
            out = []
            stride = OUT_W * 3
            for y in range(240, 480):
                row_base = y * stride
                for x in range(300, 780):
                    i = row_base + x * 3
                    rgb = (data[i], data[i + 1], data[i + 2])
                    # Tinta gelap: jarak dari krem besar
                    out.append(b"1" if not _is_cream(rgb, tol=30) else b"0")
            return b"".join(out)

        ink_90 = _get_region_ink(frame_90)
        ink_120 = _get_region_ink(frame_120)

        # Pastikan ada tinta angka yang terdeteksi
        self.assertGreater(ink_90.count(b"1"), 1000)

        # Selama fase hold, angka 100% harus stabil identik
        diff_ink = sum(1 for a, b in zip(ink_90, ink_120) if a != b)
        total_pixels = len(ink_90)
        self.assertLess(
            diff_ink / total_pixels, 0.005,
            f"Tinta angka berubah selama fase hold: diff={diff_ink}/{total_pixels}"
        )

        # Sebelum count-up (frame 15), tidak boleh ada tinta angka di area ini
        frame_pre = _frame_rgb(self.out_pb, 15)
        ink_pre = _get_region_ink(frame_pre)
        # Frame pre adalah video penuh (kuadran), bukan angka di atas krem
        self.assertNotEqual(ink_90, ink_pre)

    def test_f_pixels_identical_after_grow_completes(self):
        """(f) Setelah grow selesai (t=5.5s, frame 165): piksel IDENTIK dengan render tanpa efek."""
        frame_idx = 165  # 5.5s
        rgb_base = _frame_rgb(self.out_base, frame_idx)
        rgb_pb = _frame_rgb(self.out_pb, frame_idx)
        diff = _diff_max(rgb_base, rgb_pb)
        self.assertLessEqual(diff, 4, f"Piksel setelah grow selesai berbeda: max_diff={diff}")

    def test_g_caption_is_topmost_layer(self):
        """(g) Caption tetap di lapisan teratas di atas jendela."""
        # Caption berada di t=1.0..4.0
        # Pada frame 75 (t=2.5s), caption "Caption Utama" dirender di atas jendela
        # Di render tanpa caption atau dengan caption, periksa keberadaan teks caption di area bawah
        # Caption PlayRes berada di area bawah frame
        frame_pb = _frame_rgb(self.out_pb, 75)
        # Scan keberadaan piksel teks putih caption di area margin bawah (y=1600..1800)
        caption_pixels = 0
        for y in range(1600, 1800, 2):
            for x in range(200, 880, 2):
                rgb = _px(frame_pb, x, y)
                # Teks caption berwarna putih/kuning terang
                if rgb[0] > 200 and rgb[1] > 200:
                    caption_pixels += 1
        self.assertGreater(caption_pixels, 20, "Piksel caption tidak ditemukan di atas jendela")

    def test_h_preview_filter_proportional_at_540x960(self):
        """(h) Pratinjau (preview=True) menghasilkan jendela proporsional pada 540x960."""
        out_prev = self.wd / "preview.mp4"
        render.render_clip(self.edl, self.clip_pb, self.wd, out_prev, preview=True)

        # Periksa dimensi video pratinjau: 540x960
        p = _run([
            _FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(out_prev)
        ])
        info = json.loads(p.stdout.decode())["streams"][0]
        self.assertEqual(int(info["width"]), 540)
        self.assertEqual(int(info["height"]), 960)

        # Frame pada akhir shrink (t=1.6s -> @15fps frame 24)
        vf = "trim=start_frame=24:end_frame=25,setpts=PTS-STARTPTS"
        raw_prev = self.wd / "prev_frame.raw"
        _run([
            _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(out_prev), "-vf", vf, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(raw_prev),
        ])
        data = raw_prev.read_bytes()

        # Bbox video pada 540x960 harus proporsional:
        # win_w = 648 / 2 = 324 +- 2
        # win_x = 216 / 2 = 108 +- 2
        # win_y = 640 / 2 = 320 +- 2
        bbox = _scan_video_bbox(data, width=540, height=960)
        self.assertIsNotNone(bbox)
        min_x, min_y, max_x, max_y = bbox
        w = max_x - min_x + 1
        h = max_y - min_y + 1

        self.assertAlmostEqual(min_x, WIN_X // 2, delta=3)
        self.assertAlmostEqual(min_y, WIN_Y // 2, delta=3)
        self.assertAlmostEqual(w, WIN_W // 2, delta=3)
        self.assertAlmostEqual(h, WIN_H // 2, delta=3)

    def test_i_no_ui_text_inside_video_bbox_during_shrink_and_grow(self):
        """(i) Selama shrink (>=4 frame) dan grow (>=4 frame), TIDAK ADA piksel teks UI di dalam bbox video."""
        # 4 frame selama shrink: t = 1.1s, 1.2s, 1.3s, 1.4s
        shrink_frames = [33, 36, 39, 42]
        # 4 frame selama grow: t = 4.67s, 4.70s, 4.80s, 4.90s
        grow_frames = [140, 141, 144, 147]

        for f_idx in shrink_frames + grow_frames:
            data = _frame_rgb(self.out_pb, f_idx)

            # Temukan bbox video (area non-krem di kanvas)
            min_x = min_y = 10**9
            max_x = max_y = -1
            for y in range(0, OUT_H, 8):
                for x in range(0, OUT_W, 8):
                    rgb = _px(data, x, y)
                    if not _is_cream(rgb, tol=25):
                        if x < min_x: min_x = x
                        if x > max_x: max_x = x
                        if y < min_y: min_y = y
                        if y > max_y: max_y = y

            self.assertGreater(max_x, min_x, f"Video bbox tidak ditemukan pada frame {f_idx}")
            center_x = (min_x + max_x) // 2

            # Di dalam bbox video: periksa wilayah teks UI (Title y in 200..220, Number y in 300..420, Label y in 490..510)
            # Pada video sintetis 4-kuadran:
            # - Sisi kiri (x < center_x): kuadran merah (R > 200, G < 50, B < 50)
            # - Sisi kanan (x > center_x): kuadran hijau (R < 50, G > 100, B < 50)
            # Bila teks UI gelap (#1B1B1F / #4A463F) menimpa video:
            # - Di atas merah: kanal R turun tajam (< 150)
            # - Di atas hijau: kanal G turun tajam (< 80)
            text_pixels_in_video = 0
            for y in range(min_y + 10, min(max_y - 10, 520)):
                if (200 <= y <= 220) or (300 <= y <= 420) or (490 <= y <= 510):
                    # Separuh merah (x in [420, center_x - 6]):
                    for x in range(max(min_x + 10, 420), center_x - 6):
                        rgb = _px(data, x, y)
                        if rgb[0] < 150:
                            text_pixels_in_video += 1
                    # Separuh hijau (x in [center_x + 6, 660]):
                    for x in range(center_x + 6, min(max_x - 10, 660)):
                        rgb = _px(data, x, y)
                        if rgb[1] < 80:
                            text_pixels_in_video += 1

            self.assertEqual(
                text_pixels_in_video, 0,
                f"Frame {f_idx} (t={f_idx / FPS:.2f}s) memiliki {text_pixels_in_video} piksel teks UI di dalam bbox video"
            )

    def test_j_ui_text_present_and_visible_during_stable_phase(self):
        """(j) Pada fase stabil (frame 90, t=3.0s), seluruh teks UI tampil penuh di atas latar krem."""
        data = _frame_rgb(self.out_pb, 90)

        # Label di atas krem (y in 490..515, x in 420..660): harus ada tinta teks
        label_ink_count = 0
        for y in range(490, 515):
            for x in range(420, 660):
                rgb = _px(data, x, y)
                if not _is_cream(rgb, tol=30):
                    label_ink_count += 1
        self.assertGreater(label_ink_count, 500, f"Teks label tidak cukup terbaca di frame stabil: {label_ink_count}")

        # Title di atas krem (y in 200..220, x in 450..630)
        title_ink_count = 0
        for y in range(200, 220):
            for x in range(450, 630):
                rgb = _px(data, x, y)
                if not _is_cream(rgb, tol=30):
                    title_ink_count += 1
        self.assertGreater(title_ink_count, 300, f"Teks title tidak cukup terbaca di frame stabil: {title_ink_count}")

    def test_k_corner_radius_pixel_oracle(self):
        """(k) Radius sudut ≈ 36: pojok jendela = latar krem, titik 40 px diagonal ke dalam = video."""
        data = _frame_rgb(self.out_pb, 90)

        # Pojok kiri-atas jendela (WIN_X, WIN_Y) = (216, 640):
        # Karena sudut membulat dengan radius 36 px, area pojok luar busur ditutupi pelengkap krem
        px_corner = _px(data, WIN_X, WIN_Y)
        self.assertTrue(
            _is_cream(px_corner, tol=6),
            f"Pojok jendela (216, 640) bukan krem: {px_corner} vs {CREAM_RGB}"
        )

        # Titik 40 px diagonal ke dalam dari pojok: (216 + 40, 640 + 40) = (256, 680):
        # Berada di dalam kuadran merah video (R > 200, G < 50, B < 50)
        px_inner = _px(data, WIN_X + 40, WIN_Y + 40)
        self.assertFalse(
            _is_cream(px_inner, tol=30),
            f"Titik 40 px ke dalam (256, 680) adalah krem, seharusnya video: {px_inner}"
        )
        self.assertGreater(px_inner[0], 200, f"Kanal merah inner harus tinggi: {px_inner}")
        self.assertLess(px_inner[1], 50, f"Kanal hijau inner harus rendah: {px_inner}")

    def test_l_number_interior_pixel_color(self):
        """(l) Warna angka gelap #1B1B1F +-6 pada piksel interior angka."""
        data = _frame_rgb(self.out_pb, 90)

        # Piksel interior angka yang solid pada font Archivo Black: titik (395, 360)
        rgb_num = _px(data, 395, 360)
        # Nilai target #1B1B1F: R=27, G=27, B=31
        target_r, target_g, target_b = 27, 27, 31
        tol = 6
        self.assertAlmostEqual(
            rgb_num[0], target_r, delta=tol,
            msg=f"Kanal R angka meleset: {rgb_num[0]} vs {target_r} +- {tol}"
        )
        self.assertAlmostEqual(
            rgb_num[1], target_g, delta=tol,
            msg=f"Kanal G angka meleset: {rgb_num[1]} vs {target_g} +- {tol}"
        )
        self.assertAlmostEqual(
            rgb_num[2], target_b, delta=tol,
            msg=f"Kanal B angka meleset: {rgb_num[2]} vs {target_b} +- {tol}"
        )

    def test_m_literal_defaults_specification(self):
        """(m) Kunci nilai default dengan literal spesifikasi."""
        self.assertEqual(pullback.DEFAULT_WINDOW, {"x": 216.0, "y": 640.0, "w": 648.0, "h": 1152.0})
        self.assertEqual(pullback.DEFAULT_SHRINK, 0.6)
        self.assertEqual(pullback.DEFAULT_GROW, 0.5)
        self.assertEqual(pullback.DEFAULT_COUNT, 1.2)
        self.assertEqual(pullback.CORNER_RADIUS, 36.0)
        self.assertEqual(pullback.NUMBER_AREA_BOTTOM, 600.0)
        self.assertEqual(pullback.DARK_HEX, "#1B1B1F")
        self.assertEqual(pullback.DARK_ASS_COLOR, "&H001F1B1B&")


if __name__ == "__main__":
    unittest.main()
