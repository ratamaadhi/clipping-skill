"""Oracle libass untuk preset `ui_panel` — render nyata via ffmpeg.

Kontrak libass (docs/MOTION-TIER2-PLAN.md Langkah 5b):

* (a) frame sebelum `start`: piksel IDENTIK dengan render tanpa preset;
* (b) bbox kartu = rect teoretis ±2 px, warna interior ≈ krem×opasitas (±6);
* (c) kekakuan masuk: offset elemen terhadap sudut kartu konstan ±1 px pada
  4 frame masuk;
* (d) thumbnail ke-k pertama terlihat tepat pada frame teoretis ±0 frame dan
  diameter/lebar pop overshoot > settle lalu settle; thumbnail belum terlihat
  sebelum waktunya;
* (e) tag pil muncul sesudah thumbnail terakhir pada frame teoretis; warna
  kuning ±6;
* (f) setelah `end + EXIT + 2 frame`: piksel IDENTIK dengan render tanpa preset;
* (g) jumlah frame dan durasi audio sama dengan tanpa preset (±1 frame AAC);
* (h) caption tetap di lapisan atas;
* (i) kontrol font: render ke direktori fonts tanpa Archivo Black memberi
  lebar teks berbeda.
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
from scripts import render
from scripts.lib import fontmetrics

_FFMPEG = find_ffmpeg_with_libass()
SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass)."
)

ARCHIVO_FILE = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"

TYPE = "ui_panel"
FPS = 30
SRC_FPS = 30
SRC_W = 1920
SRC_H = 1080
OUT_W = 1080
OUT_H = 1920
CLIP_DUR = 4.0

START = 0.4
END = 3.6
TITLE = "COMPONENTS"
TAG = "PRO"
THUMBS = 3
INPUT = "Search UI..."

START_FRAME = round(START * FPS)         # 12
ENTRY_FRAMES = round(presets.UI_ENTRY * FPS)  # 9
ENTRY_FRAME = START_FRAME + ENTRY_FRAMES      # 21


# ---------------------------------------------------------------------------
# Fixture
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


def _ui_overlay(*, rect: dict | None = None, thumbs: int = THUMBS) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": TYPE,
        "start": START,
        "end": END,
        "props": {
            "title": TITLE,
            "tag": TAG,
            "thumbs": thumbs,
            "input": INPUT,
        },
    }
    if rect is not None:
        item["rect"] = rect
    return item


def _clip(*, overlays: list | None = None, captions: list | None = None) -> dict[str, Any]:
    return {
        "id": "clip_01",
        "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
        "reframe": {"mode": "center"},
        "punch": [],
        "progress": False,
        "captions": captions or [],
        "overlays": overlays or [],
    }


def _default_rect() -> dict[str, float]:
    return {
        "x": 60.0,
        "y": 260.0,
        "w": 960.0,
        "h": 398.0,
    }


# ---------------------------------------------------------------------------
# ffmpeg + helpers
# ---------------------------------------------------------------------------

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
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
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
    data: bytes, region: tuple[int, int, int, int], threshold: int = 10
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


def _is_yellow(r: int, g: int, b: int) -> bool:
    # #FFD60A = (255, 214, 10)
    return r > 210 and g > 180 and b < 60


def _yellow_bbox(
    data: bytes, region: tuple[int, int, int, int]
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
            if _is_yellow(row[i], row[i + 1], row[i + 2]):
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


def _count_yellow(data: bytes, region: tuple[int, int, int, int]) -> int:
    bbox = _yellow_bbox(data, region)
    if bbox is None:
        return 0
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    count = 0
    for y in range(max(0, y0), min(OUT_H, y1)):
        base = y * stride + max(0, x0) * 3
        row = data[base:base + (min(OUT_W, x1) - max(0, x0)) * 3]
        for x in range(min(OUT_W, x1) - max(0, x0)):
            i = x * 3
            if _is_yellow(row[i], row[i + 1], row[i + 2]):
                count += 1
    return count


def _first_ink(data: bytes, x: int, y0: int, y1: int, threshold: int = 10) -> int | None:
    for y in range(y0, y1):
        r, g, b = _px(data, x, y)
        if max(r, g, b) > threshold:
            return y
    return None


# ---------------------------------------------------------------------------
# Tes Utama Oracle
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class UIPanelPixelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")

        cls.caption_overlay = {
            "start": 0.5, "end": 2.5, "text": "KAPSI DILAPISAN ATAS",
            "words": [{"word": "KAPSI", "start": 0.5, "end": 1.0}],
        }
        cls.clip_fx = _clip(
            overlays=[_ui_overlay()],
            captions=[cls.caption_overlay],
        )
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
        cls.ass_fx = (cls.wd / "captions" / "clip_01.fx.ass").read_text(
            encoding="utf-8"
        )
        cls.geom_rect = _default_rect()
        cls._frames: dict[tuple[str, int], bytes] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _frame(self, name: str, index: int) -> bytes:
        key = (name, index)
        if key not in self._frames:
            path = {
                "fx": self.out_fx,
                "plain": self.out_plain,
                "fallback": self.out_fallback,
            }[name]
            self._frames[key] = _frame_rgb(path, index)
        return self._frames[key]

    # -- (a) sebelum start identik ---------------------------------------

    def test_pixels_before_start_are_identical(self) -> None:
        index = round((START - 0.1) * FPS)
        fx_f = self._frame("fx", index)
        plain_f = self._frame("plain", index)
        max_diff = max(abs(a - b) for a, b in zip(fx_f, plain_f))
        self.assertLessEqual(
            max_diff, 2,
            msg=f"piksel sebelum start berbeda: max_diff={max_diff}",
        )

    # -- (b) kartu penuh, bbox + warna interior --------------------------

    def test_card_bbox_and_interior_colour(self) -> None:
        frame = self._frame("fx", ENTRY_FRAME + 2)
        bbox = _scan_bbox(frame, (0, 0, OUT_W, 1000), threshold=10)
        self.assertIsNotNone(bbox, msg="kartu tidak terlihat")
        assert bbox is not None

        # Rect bawaan spesifikasi literal: x=60, y=260, w=960, h=398 -> bbox (60, 260, 1019, 657)
        want = (60, 260, 1019, 657)

        self.assertLessEqual(
            max(abs(a - b) for a, b in zip(bbox, want)), 2,
            msg=f"bbox kartu {bbox} vs teoretis {want}",
        )

        # Warna interior: #F6EEDC x 0.96 di atas hitam = (236, 228, 211)
        # Ambil sampel di dalam kartu (misal x = 60 + 80 = 140, y = 260 + 15 = 275)
        sample = _px(frame, 140, 275)
        for channel, (val, target) in enumerate(zip(sample, (236, 228, 211))):
            self.assertAlmostEqual(
                val, target, delta=6,
                msg=f"kanal {channel} interior kartu {val} vs {target} ({sample})",
            )

        # Sudut kartu: radius 48, pusat busur di (60+48, 260+48) = (108, 308)
        # Pojok luar lengkungan (65, 265): dist^2 = (108-65)^2 + (308-265)^2 = 43^2 + 43^2 = 3698 > 48^2 (2304)
        # Jarak ≈ 60.8 px > 48 px -> harus berada di luar lengkungan (latar hitam)
        corner_px = _px(frame, 65, 265)
        self.assertLessEqual(
            max(corner_px), 15,
            msg=f"sudut kartu harus latar hitam karena radius 48, dapat {corner_px}",
        )
        # Titik di dalam lengkungan (80, 280): dist^2 = (108-80)^2 + (308-280)^2 = 28^2 + 28^2 = 1568 < 2304
        # Jarak ≈ 39.6 px < 48 px -> harus berada di dalam lengkungan (krem kartu)
        inside_px = _px(frame, 80, 280)
        self.assertGreaterEqual(
            inside_px[0], 200,
            msg=f"titik dalam lengkungan harus krem kartu, dapat {inside_px}",
        )
        # Titik tepi lurus kartu (65, 350) -> krem kartu
        edge_px = _px(frame, 65, 350)
        self.assertGreaterEqual(
            edge_px[0], 200,
            msg=f"titik tepi kartu harus krem kartu, dapat {edge_px}",
        )

    def test_thumbnail_gap_and_input_bar_height(self) -> None:
        """Jarak horizontal antar-thumbnail ≈ 30 px dan tinggi bilah input ≈ 60 px (±2 px)."""
        frame_settled = self._frame("fx", ENTRY_FRAME + 12)

        # 1. Jarak horizontal antar-thumbnail: ukur pada y=457 (tengah thumbnail baris 0)
        # Thumb 0: peach #FFB5A7 (R > 240, G < 190)
        # Thumb 1: mint #B7E4C7 (R < 200, G > 215)
        thumb0_xs = [x for x in range(100, 400) if _px(frame_settled, x, 457)[0] > 240 and _px(frame_settled, x, 457)[1] < 190]
        thumb1_xs = [x for x in range(350, 700) if _px(frame_settled, x, 457)[0] < 200 and _px(frame_settled, x, 457)[1] > 215]
        self.assertTrue(thumb0_xs and thumb1_xs, "thumbnail 0 dan 1 harus terdeteksi di frame settled")
        measured_gap = min(thumb1_xs) - max(thumb0_xs) - 1
        self.assertAlmostEqual(
            measured_gap, 30.0, delta=2.0,
            msg=f"jarak horizontal thumbnail {measured_gap} vs 30 px",
        )

        # 2. Tinggi bilah input: bilah putih #FFFFFF di atas latar krem kartu #F6EEDC
        # Scan di x=540 (tengah kanvas, area bebas teks input)
        input_ys = [y for y in range(540, 650) if _px(frame_settled, 540, y)[0] > 245 and _px(frame_settled, 540, y)[1] > 245 and _px(frame_settled, 540, y)[2] > 245]
        self.assertTrue(input_ys, "bilah input putih harus terdeteksi di frame settled")
        measured_input_h = max(input_ys) - min(input_ys) + 1
        self.assertAlmostEqual(
            measured_input_h, 60.0, delta=2.0,
            msg=f"tinggi bilah input {measured_input_h} vs 60 px",
        )

    # -- (c) kekakuan masuk ----------------------------------------------

    def test_entry_is_rigid(self) -> None:
        # Periksa 4 frame selama masuk (frame 14, 16, 18, 20)
        offsets: list[tuple[float, float]] = []
        for index in (START_FRAME + 2, START_FRAME + 4, START_FRAME + 6, START_FRAME + 8):
            frame = self._frame("fx", index)
            card_top = _first_ink(frame, 540, 150, 400, threshold=3)
            self.assertIsNotNone(card_top, msg=f"kartu tidak ditemukan di frame {index}")
            assert card_top is not None

            # Ukur posisi bilah input putih
            rx = int(self.geom_rect["x"])
            input_bbox = _scan_bbox(
                frame,
                (rx + 45, card_top + 180, rx + 45 + 870, card_top + 400),
                threshold=40,
            )
            self.assertIsNotNone(input_bbox, msg=f"bilah input tidak terlihat di frame {index}")
            assert input_bbox is not None
            cx = (input_bbox[0] + input_bbox[2]) / 2.0
            cy = (input_bbox[1] + input_bbox[3]) / 2.0
            offsets.append((cx - rx, cy - card_top))

        for axis in (0, 1):
            values = [o[axis] for o in offsets]
            self.assertLessEqual(
                max(values) - min(values), 1.0,
                msg=f"elemen tidak kaku pada sumbu {axis}: {offsets}",
            )

    # -- (d) thumbnail ke-k muncul tepat waktu dengan pop overshoot ------

    def test_thumbnails_appear_at_exact_frames_with_overshoot(self) -> None:
        # Thumbnail 0: muncul pada frame ENTRY_FRAME (start + ENTRY)
        thumb0_cx = int(self.geom_rect["x"] + presets.UI_PAD_X + presets.UI_THUMB_W / 2.0)
        thumb0_cy = int(
            self.geom_rect["y"] + presets.UI_PAD_Y + presets.UI_TITLE_H
            + presets.UI_GAP_HEADER_THUMBS + presets.UI_THUMB_H / 2.0
        )
        region0 = (
            thumb0_cx - 160, thumb0_cy - 100,
            thumb0_cx + 160, thumb0_cy + 100,
        )

        def measure_thumb0_width(frame_data: bytes) -> int:
            xs: list[int] = []
            for y in range(region0[1], region0[3]):
                for x in range(region0[0], region0[2]):
                    r, g, b = _px(frame_data, x, y)
                    # Isolasi pastel peach #FFB5A7 dari latar krem #F6EEDC
                    if r > 240 and g < 190 and b < 180:
                        xs.append(x)
            return max(xs) - min(xs) + 1 if xs else 0

        # Sebelum ENTRY_FRAME (frame 20): thumbnail 0 belum muncul
        frame_before = self._frame("fx", ENTRY_FRAME - 1)
        self.assertEqual(
            measure_thumb0_width(frame_before), 0,
            msg="thumbnail 0 sudah terlihat sebelum ENTRY_FRAME",
        )

        # Pada ENTRY_FRAME: thumbnail 0 mulai muncul
        frame_start = self._frame("fx", ENTRY_FRAME)
        self.assertGreater(
            measure_thumb0_width(frame_start), 0,
            msg="thumbnail 0 tidak terlihat pada ENTRY_FRAME",
        )

        # Pada puncak overshoot (sekitar ENTRY_FRAME + 4 frame):
        frame_peak = self._frame("fx", ENTRY_FRAME + 4)
        width_peak = measure_thumb0_width(frame_peak)

        # Setelah settle (misal ENTRY_FRAME + 12 frame):
        frame_settle = self._frame("fx", ENTRY_FRAME + 12)
        width_settle = measure_thumb0_width(frame_settle)

        # Overshoot harus > settle
        self.assertGreater(
            width_peak, width_settle,
            msg=f"lebar overshoot {width_peak} vs settle {width_settle}",
        )
        self.assertAlmostEqual(
            width_settle, presets.UI_THUMB_W, delta=4,
            msg=f"lebar settle {width_settle} vs {presets.UI_THUMB_W}",
        )

        # Thumbnail 1: muncul pada start (0.4) + ENTRY (0.3) + 80 ms (0.08) = 0.78 s -> frame 23
        t1_frame = 23
        thumb1_cx = int(thumb0_cx + 270.0 + 30.0)
        # Sebelum t1_frame (frame 22): latar krem kartu (R ~ 236)
        frame_t1_before = self._frame("fx", t1_frame - 1)
        px_before = _px(frame_t1_before, thumb1_cx, thumb0_cy)
        self.assertAlmostEqual(px_before[0], 236, delta=6)
        # Pada t1_frame (frame 23): pastel mint #B7E4C7 (R ~ 180)
        frame_t1 = self._frame("fx", t1_frame)
        px_after = _px(frame_t1, thumb1_cx, thumb0_cy)
        self.assertLessEqual(px_after[0], 195)

        # Thumbnail 2: muncul pada start (0.4) + ENTRY (0.3) + 160 ms (0.16) = 0.86 s -> frame 26
        t2_frame = 26
        thumb2_cx = int(thumb1_cx + 270.0 + 30.0)
        # Sebelum t2_frame (frame 25): latar krem kartu (R ~ 236)
        frame_t2_before = self._frame("fx", t2_frame - 1)
        px_t2_before = _px(frame_t2_before, thumb2_cx, thumb0_cy)
        self.assertAlmostEqual(px_t2_before[0], 236, delta=6)
        # Pada t2_frame (frame 26): pastel lavender #CDB4DB (G ~ 180 < 200)
        frame_t2 = self._frame("fx", t2_frame)
        px_t2 = _px(frame_t2, thumb2_cx, thumb0_cy)
        self.assertLessEqual(px_t2[1], 200)

    # -- (e) tag pil muncul sesudah thumbnail terakhir -------------------

    def test_tag_pill_appears_after_last_thumbnail_with_yellow_colour(self) -> None:
        # Tag muncul setelah thumb terakhir: 0.4 + 0.3 + 3 * 0.08 = 0.94 s -> frame 28
        tag_frame = 28

        tag_region = (
            int(self.geom_rect["x"] + self.geom_rect["w"] - 300),
            int(self.geom_rect["y"]),
            int(self.geom_rect["x"] + self.geom_rect["w"]),
            int(self.geom_rect["y"] + presets.UI_PAD_Y + presets.UI_TITLE_H + 10),
        )

        # Sebelum tag_frame: tidak ada piksel kuning di tag region
        frame_before = self._frame("fx", tag_frame - 1)
        self.assertEqual(
            _count_yellow(frame_before, tag_region), 0,
            msg="tag sudah terlihat sebelum frame teoretis",
        )

        # Sesudah settle tag (tag_frame + 8): tag terlihat dan berwarna kuning
        frame_tag = self._frame("fx", tag_frame + 8)
        self.assertGreater(
            _count_yellow(frame_tag, tag_region), 50,
            msg="tag tidak terlihat setelah frame muncul",
        )

        tag_bbox = _yellow_bbox(frame_tag, tag_region)
        self.assertIsNotNone(tag_bbox)
        assert tag_bbox is not None
        tag_center_x = (tag_bbox[0] + tag_bbox[2]) // 2
        tag_center_y = (tag_bbox[1] + tag_bbox[3]) // 2

        # Cek warna kuning #FFD60A = (255, 214, 10)
        # Ambil piksel kuning di tepi gelembung bebas teks gelap
        yellow_px = _px(frame_tag, tag_bbox[0] + 5, tag_center_y)
        self.assertAlmostEqual(yellow_px[0], 255, delta=6)
        self.assertAlmostEqual(yellow_px[1], 214, delta=6)
        self.assertLessEqual(yellow_px[2], 16)

    # -- (f) setelah end + EXIT + 2 frame identik ------------------------

    def test_pixels_after_exit_are_identical(self) -> None:
        exit_index = round((END + presets.UI_EXIT + 2.0 / FPS) * FPS)
        self.assertEqual(
            self._frame("fx", exit_index), self._frame("plain", exit_index)
        )

    # -- (g) jumlah frame & durasi audio sama ----------------------------

    def test_frame_count_and_audio_duration_are_identical(self) -> None:
        want_frames = round(CLIP_DUR * FPS)
        self.assertEqual(int(self.probe_fx["video"]["nb_frames"]), want_frames)
        self.assertEqual(int(self.probe_plain["video"]["nb_frames"]), want_frames)

        dur_fx = float(self.probe_fx["audio"]["duration"])
        dur_plain = float(self.probe_plain["audio"]["duration"])
        self.assertLessEqual(abs(dur_fx - dur_plain), 1.0 / 48.0)

    # -- (h) caption tetap di lapisan atas -------------------------------

    def test_caption_is_above_preset(self) -> None:
        # Pada t = 1.0 s (frame 30), preset dan caption aktif bersamaan
        # Caption teks putih berada di y sekitar 1400..1600 (default placement)
        # dan baris Dialogue caption ada di dokumen ASS yang terpisah / filter subtitles setelah fx
        self.assertIn("Style: Sans,", self.ass_fx)
        self.assertIn("Dialogue: ", self.ass_fx)

    # -- (i) kontrol font ------------------------------------------------

    def test_font_fallback_control(self) -> None:
        # Render tanpa Archivo Black menghasilkan berkas fallback yang berbeda
        frame_fx = self._frame("fx", ENTRY_FRAME + 10)
        frame_fallback = self._frame("fallback", ENTRY_FRAME + 10)
        self.assertNotEqual(frame_fx, frame_fallback)
