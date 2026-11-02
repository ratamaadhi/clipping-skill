"""Tes integrasi preset `phone_frame` lewat `render.render_clip` (Langkah 5b-7).

Memastikan preset `phone_frame` terintegrasi utuh ke alur render:
* Dokumen fx dihasilkan oleh `presets.build_fx_ass`;
* (a) sebelum `start` piksel IDENTIK dengan render tanpa preset;
* (b) bbox badan ponsel = rect teoretis ±2 px pada frame penuh;
* (c) baris pertama muncul pada frame teoretis ±0;
* (d) sesudah `end + EXIT + 2 frame` piksel IDENTIK;
* (e) jumlah frame dan durasi audio sama dengan tanpa preset;
* (f) caption tetap di lapisan atas.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.ffmpeg_libass import find_ffmpeg_with_libass
from tests.helpers import ROOT

from scripts import presets
from scripts import presets_phone
from scripts import render

_FFMPEG = find_ffmpeg_with_libass()
SKIP_REASON = "tidak ada ffmpeg dengan filter 'subtitles' (libass)."

ARCHIVO_FILE = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"

FPS = 30
SRC_FPS = 30
SRC_W = 1920
SRC_H = 1080
OUT_W = 1080
OUT_H = 1920
CLIP_DUR = 4.0

START = 0.4
END = 3.6
TITLE = "NOTIFIKASI"
LINES = ["Transfer masuk Rp 50rb", "Dari Budi Santoso", "Sisa saldo Rp 1.5jt"]
ACCENT = "#FFD60A"

START_FRAME = round(START * FPS)                       # 12
ENTRY_FRAMES = round(presets_phone.PHONE_ENTRY * FPS)  # 11
ENTRY_FRAME = START_FRAME + ENTRY_FRAMES               # 23

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


def _ffmpeg_bin() -> str:
    assert _FFMPEG is not None
    return _FFMPEG


def _run(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess:
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
        f"color=c=black:s={SRC_W}x{SRC_H}:r={SRC_FPS}:d={CLIP_DUR:g}",
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={CLIP_DUR:g}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(path),
    ])


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = Path(_ffmpeg_bin()).with_name("ffprobe")
    proc = _run([
        str(ffprobe), "-v", "error",
        "-show_entries", "stream=nb_frames,duration,codec_type",
        "-of", "json", str(path),
    ])
    data = json.loads(proc.stdout.decode("utf-8"))
    streams = data.get("streams", [])
    video = next(s for s in streams if s.get("codec_type") == "video")
    audio = next(s for s in streams if s.get("codec_type") == "audio")
    return {"video": video, "audio": audio}


def _frame_rgb(path: Path, index: int) -> bytes:
    vf = f"trim=start_frame={index}:end_frame={index + 1},setpts=PTS-STARTPTS"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.raw"
        _run([
            _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-vf", vf, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ])
        return out.read_bytes()


def _px(data: bytes, x: int, y: int) -> tuple[int, int, int]:
    base = (y * OUT_W + x) * 3
    return data[base], data[base + 1], data[base + 2]


def _scan_bbox(
    data: bytes, region: tuple[int, int, int, int], threshold: int = 8
) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    min_x = min_y = 10**9
    max_x = max_y = -1
    for y in range(max(0, y0), min(OUT_H, y1)):
        base = y * stride + max(0, x0) * 3
        row = data[base:base + (min(OUT_W, x1) - max(0, x0)) * 3]
        for x in range(min(OUT_W, x1) - max(0, x0)):
            i = x * 3
            if max(row[i], row[i + 1], row[i + 2]) > threshold:
                gx = max(0, x0) + x
                if gx < min_x:
                    min_x = gx
                if gx > max_x:
                    max_x = gx
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return None
    return min_x, min_y, max_x, max_y


def _count_bright(
    data: bytes, region: tuple[int, int, int, int], threshold: int = 100
) -> int:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    count = 0
    for y in range(max(0, y0), min(OUT_H, y1)):
        base = y * stride + max(0, x0) * 3
        row = data[base:base + (min(OUT_W, x1) - max(0, x0)) * 3]
        for x in range(min(OUT_W, x1) - max(0, x0)):
            i = x * 3
            if max(row[i], row[i + 1], row[i + 2]) > threshold:
                count += 1
    return count


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class PhoneFrameIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        cls.src_mp4 = cls.wd / "src.mp4"
        _make_source(cls.src_mp4)

        cls.caption_item = {
            "start": 0.5,
            "end": 2.5,
            "text": "KAPSI DI LAPISAN ATAS",
            "words": [{"word": "KAPSI", "start": 0.5, "end": 1.0}],
        }

        cls.phone_overlay = {
            "type": "phone_frame",
            "start": START,
            "end": END,
            "props": {
                "title": TITLE,
                "lines": list(LINES),
                "accent": ACCENT,
                "side": "right",
            },
        }

        cls.clip_fx = {
            "id": "clip_phone_fx",
            "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
            "reframe": {"mode": "center"},
            "punch": [],
            "progress": False,
            "captions": [cls.caption_item],
            "overlays": [cls.phone_overlay],
        }

        cls.clip_plain = {
            "id": "clip_phone_plain",
            "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
            "reframe": {"mode": "center"},
            "punch": [],
            "progress": False,
            "captions": [cls.caption_item],
            "overlays": [],
        }

        cls.out_fx = cls.wd / "out" / "clip_fx.mp4"
        cls.out_plain = cls.wd / "out" / "clip_plain.mp4"
        render.render_clip(EDL, cls.clip_fx, cls.wd, cls.out_fx)
        render.render_clip(EDL, cls.clip_plain, cls.wd, cls.out_plain)

        cls.probe_fx = _probe(cls.out_fx)
        cls.probe_plain = _probe(cls.out_plain)
        cls._cache: dict[tuple[str, int], bytes] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _frame(self, kind: str, index: int) -> bytes:
        key = (kind, index)
        if key not in self._cache:
            p = self.out_fx if kind == "fx" else self.out_plain
            self._cache[key] = _frame_rgb(p, index)
        return self._cache[key]

    def test_a_pixels_before_start_are_identical(self) -> None:
        """(a) Sebelum start (frame 10), piksel IDENTIK dengan render tanpa preset."""
        frame_idx = START_FRAME - 2  # frame 10 (t = 0.33 s, start = 0.40 s)
        self.assertEqual(
            self._frame("fx", frame_idx),
            self._frame("plain", frame_idx),
            msg="piksel sebelum start berbeda antara render dengan preset vs tanpa preset",
        )

    def test_b_phone_body_bbox_matches_theoretical_on_full_frame(self) -> None:
        """(b) Bbox badan ponsel = rect teoretis ±2 px pada frame penuh."""
        full_frame_idx = ENTRY_FRAME + 2  # frame 25
        frame = self._frame("fx", full_frame_idx)
        # Scan zona atas kanvas (y < 1200) agar terbebas dari caption di zona bawah
        bbox = _scan_bbox(frame, (0, 0, OUT_W, 1200), threshold=8)
        self.assertIsNotNone(bbox, msg="badan ponsel tidak terlihat pada frame penuh")
        assert bbox is not None

        # Teoretis side='right', 3 baris: x=640, y=250, w=380, h=660 -> (640, 250, 1019, 909)
        want_bbox = (640, 250, 640 + 380 - 1, 250 + 660 - 1)
        for ch, (got, want) in enumerate(zip(bbox, want_bbox)):
            self.assertLessEqual(
                abs(got - want), 2,
                msg=f"koordinat bbox {ch} badan {got} vs teoretis {want} (bbox={bbox})",
            )

    def test_c_first_line_appears_at_exact_theoretical_frame(self) -> None:
        """(c) Baris pertama muncul pada frame teoretis ±0 frame."""
        entry_frame = START_FRAME + round(presets_phone.PHONE_ENTRY * FPS)

        screen_x = 640 + presets_phone.PHONE_SCREEN_INSET
        content_x = screen_x + presets_phone.PHONE_PAD_X
        bullet_cx = int(round(content_x + presets_phone.PHONE_BULLET_RADIUS))
        text_x = int(round(content_x + 2.0 * presets_phone.PHONE_BULLET_RADIUS + presets_phone.PHONE_BULLET_GAP))

        header_bottom = (
            250 + presets_phone.PHONE_SCREEN_INSET
            + presets_phone.PHONE_TITLE_PAD_TOP
            + presets_phone.PHONE_TITLE_H
            + presets_phone.PHONE_UNDERLINE_GAP
            + presets_phone.PHONE_UNDERLINE_H
        )
        first_line_top = header_bottom + presets_phone.PHONE_GAP_UNDERLINE_LINES
        row_cy = int(round(first_line_top + presets_phone.PHONE_LINE_ROW_H / 2.0))
        text_region = (text_x, row_cy - 16, text_x + 180, row_cy + 16)

        # Frame sebelum kemunculan (entry_frame - 1 = frame 21): teks baris 0 belum ada (0 piksel)
        frame_before = self._frame("fx", entry_frame - 1)
        bright_before = _count_bright(frame_before, text_region, threshold=100)
        self.assertEqual(
            bright_before, 0,
            msg=f"teks baris 0 sudah terlihat sebelum frame teoretis (frame {entry_frame - 1})",
        )

        # Frame setelah fade-in (entry_frame + 4 = frame 26): teks baris 0 terlihat jelas
        frame_visible = self._frame("fx", entry_frame + 4)
        bright_visible = _count_bright(frame_visible, text_region, threshold=100)
        self.assertGreater(
            bright_visible, 50,
            msg=f"teks baris 0 belum terlihat setelah fade-in pada frame {entry_frame + 4}",
        )

        # Bullet aksen berwarna kuning #FFD60A (R=255, G=214, B=10) ±6
        bullet_px = _px(frame_visible, bullet_cx, row_cy)
        self.assertAlmostEqual(bullet_px[0], 255, delta=18)
        self.assertAlmostEqual(bullet_px[1], 214, delta=10)
        self.assertLessEqual(bullet_px[2], 25)

    def test_d_pixels_after_exit_are_identical(self) -> None:
        """(d) Sesudah end + EXIT + 2 frame (frame 116), piksel IDENTIK dengan render tanpa preset."""
        # END = 3.6, EXIT = 0.20, + 2/30 -> frame 116
        exit_index = round((END + presets_phone.PHONE_EXIT + 2.0 / FPS) * FPS)
        self.assertEqual(
            self._frame("fx", exit_index),
            self._frame("plain", exit_index),
            msg="piksel setelah exit berbeda antara render dengan preset vs tanpa preset",
        )

    def test_e_frame_count_and_audio_duration_are_identical(self) -> None:
        """(e) Jumlah frame dan durasi audio sama dengan tanpa preset."""
        want_frames = round(CLIP_DUR * FPS)
        self.assertEqual(int(self.probe_fx["video"]["nb_frames"]), want_frames)
        self.assertEqual(int(self.probe_plain["video"]["nb_frames"]), want_frames)

        dur_fx = float(self.probe_fx["audio"]["duration"])
        dur_plain = float(self.probe_plain["audio"]["duration"])
        self.assertLessEqual(
            abs(dur_fx - dur_plain), 1.0 / 48.0,
            msg=f"durasi audio selisih {abs(dur_fx - dur_plain)} > 1/48 s",
        )

    def test_f_caption_is_in_top_layer(self) -> None:
        """(f) Caption tetap di lapisan atas (filter subtitles fx mendahului subtitles caption)."""
        fx_ass_path = self.wd / "captions" / f"{self.clip_fx['id']}.fx.ass"
        caption_ass_path = self.wd / "captions" / f"{self.clip_fx['id']}.ass"
        self.assertTrue(fx_ass_path.exists(), "dokumen fx ASS harus ada")
        self.assertTrue(caption_ass_path.exists(), "dokumen caption ASS harus ada")

        # Pada t = 1.0 s (frame 30), caption aktif di sepertiga bawah kanvas
        frame_caption = self._frame("fx", 30)
        # Caption region di y: 1300..1800 memiliki piksel terang
        caption_bright = _count_bright(frame_caption, (100, 1300, 980, 1800), threshold=150)
        self.assertGreater(
            caption_bright, 50,
            msg="teks caption harus terlihat di zona caption pada frame 30",
        )
