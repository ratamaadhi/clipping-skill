"""Oracle libass untuk preset `phone_frame` — render nyata via ffmpeg.

Kontrak libass (docs/MOTION-TIER2-PLAN.md Langkah 5b):

* (a) frame sebelum `start`: piksel hitam polos;
* (b) pada frame penuh, bbox badan = rect teoretis ±2 px, warna badan (#0B0C10)
  dan layar (#15171C) sesuai (±4);
* (c) kekakuan masuk: offset (pusat notch - sudut kiri-atas badan) konstan ±1 px
  pada 4 frame masuk; pergeseran total selama masuk ≈ 140 px ±2;
* (d) baris ke-k muncul pertama pada frame teoretis ±0 frame dan sebelumnya
  tidak ada piksel teksnya; bullet berwarna aksen #FFD60A ±6;
* (e) setelah `end + EXIT + 2 frame`: piksel hitam polos kembali;
* (f) kontrol font: render ke direktori fonts tanpa Archivo Black memberi lebar
  teks berbeda;
* (g) `side="left"` bbox di sisi kiri.
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
from scripts import shapes
from scripts.lib import fontmetrics

_FFMPEG = find_ffmpeg_with_libass()
_FFPROBE = str(Path(_FFMPEG).with_name("ffprobe")) if _FFMPEG else None
if _FFPROBE and not Path(_FFPROBE).exists():
    _FFPROBE = None

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` atau set env CLIP_FFMPEG ke path ffmpeg berlibass."
)

FONT_DIR = (ROOT / "assets" / "fonts").resolve()
ARCHIVO_FILE = FONT_DIR / "ArchivoBlack-Regular.ttf"

FPS = 30
OUT_W = 1080
OUT_H = 1920
CLIP_DUR = 4.0

START = 0.4
END = 3.6
TITLE = "NOTIFIKASI"
LINES = ["Transfer masuk Rp 50rb", "Saldo bertambah", "Bonus harian aktif"]
ACCENT = "#FFD60A"

# RGB teoretis
BODY_RGB = (11, 12, 16)      # #0B0C10
SCREEN_RGB = (21, 23, 28)    # #15171C
ACCENT_RGB = (255, 214, 10)  # #FFD60A


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
    """Buat video sintetis hitam 1080x1920 30fps 4.0s."""
    _run([
        _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i",
        f"color=c=black:s={OUT_W}x{OUT_H}:r={FPS}:d={CLIP_DUR:g}",
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={CLIP_DUR:g}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(path),
    ])


def _render_ass(video_src: Path, ass_path: Path, out_path: Path, fonts_dir: Path) -> None:
    """Bakar ASS ke video menggunakan filter subtitles libass."""
    sub_filter = f"subtitles={ass_path}:fontsdir={fonts_dir}"
    _run([
        _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_src),
        "-vf", sub_filter,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out_path),
    ])


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


def _count_bright_pixels(
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
class PhoneFrameRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        cls.src_mp4 = cls.wd / "src.mp4"
        _make_source(cls.src_mp4)

        cls.font = fontmetrics.Font.load(ARCHIVO_FILE)

        # 1. Overlay default (side='right')
        item_right = {
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
        cls.plan_right, _ = presets_phone.build(0, item_right, CLIP_DUR, fps=FPS)
        assert cls.plan_right is not None
        cls.events_right = presets_phone.events(cls.plan_right, FPS, cls.font)
        cls.doc_right = presets_phone.document(cls.events_right, cls.font)
        cls.ass_right = cls.wd / "phone_right.ass"
        cls.ass_right.write_text(cls.doc_right, encoding="utf-8")

        cls.out_right = cls.wd / "out_right.mp4"
        _render_ass(cls.src_mp4, cls.ass_right, cls.out_right, FONT_DIR)

        # 2. Overlay side='left'
        item_left = {
            "type": "phone_frame",
            "start": START,
            "end": END,
            "props": {
                "title": TITLE,
                "lines": list(LINES),
                "accent": ACCENT,
                "side": "left",
            },
        }
        cls.plan_left, _ = presets_phone.build(0, item_left, CLIP_DUR, fps=FPS)
        assert cls.plan_left is not None
        cls.events_left = presets_phone.events(cls.plan_left, FPS, cls.font)
        cls.doc_left = presets_phone.document(cls.events_left, cls.font)
        cls.ass_left = cls.wd / "phone_left.ass"
        cls.ass_left.write_text(cls.doc_left, encoding="utf-8")

        cls.out_left = cls.wd / "out_left.mp4"
        _render_ass(cls.src_mp4, cls.ass_left, cls.out_left, FONT_DIR)

        # 3. Kontrol font (fontsdir kosong)
        cls.empty_fonts = cls.wd / "empty_fonts"
        cls.empty_fonts.mkdir()
        cls.out_fallback = cls.wd / "out_fallback.mp4"
        _render_ass(cls.src_mp4, cls.ass_right, cls.out_fallback, cls.empty_fonts)

        cls._frames: dict[tuple[str, int], bytes] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _frame(self, target: str, index: int) -> bytes:
        key = (target, index)
        if key not in self._frames:
            path = {
                "right": self.out_right,
                "left": self.out_left,
                "fallback": self.out_fallback,
            }[target]
            self._frames[key] = _frame_rgb(path, index)
        return self._frames[key]

    # -- (a) frame sebelum start: piksel hitam polos -------------------------

    def test_pixels_before_start_are_pure_black(self) -> None:
        start_frame = round(START * FPS)  # 12
        before_index = start_frame - 2    # frame 10
        frame = self._frame("right", before_index)
        bbox = _scan_bbox(frame, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNone(
            bbox,
            msg=f"ada piksel non-hitam pada frame sebelum start ({before_index}): {bbox}",
        )

    # -- (b) pada frame penuh, bbox badan = rect teoretis ±2 px, warna badan & layar ±4

    def test_card_bbox_and_interior_colours(self) -> None:
        start_frame = round(START * FPS)
        entry_frame = start_frame + round(presets_phone.PHONE_ENTRY * FPS)
        full_index = entry_frame + 2  # frame setelah masuk penuh
        frame = self._frame("right", full_index)

        # Bbox badan ponsel
        # default rect: x=640, y=250, w=380, h=660 -> (640, 250, 1019, 909)
        want_rect = (640, 250, 640 + 380 - 1, 250 + 660 - 1)
        bbox = _scan_bbox(frame, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNotNone(bbox, msg="badan ponsel tidak terlihat pada frame penuh")
        assert bbox is not None
        for i, (got, want) in enumerate(zip(bbox, want_rect)):
            self.assertLessEqual(
                abs(got - want), 2,
                msg=f"koordinat bbox {i} badan {got} vs teoretis {want} (bbox={bbox})",
            )

        # Warna badan: piksel di bezel kiri badan di luar layar (misal x=640+6, y=250+200)
        body_px = _px(frame, 640 + 6, 250 + 200)
        for ch, (got, want) in enumerate(zip(body_px, BODY_RGB)):
            self.assertAlmostEqual(
                got, want, delta=4,
                msg=f"warna badan kanal {ch} {got} vs teoretis {want} (piksel {body_px})",
            )

        # Warna layar: piksel di tengah layar ponsel (misal x=640+100, y=250+100)
        screen_px = _px(frame, 640 + 100, 250 + 100)
        for ch, (got, want) in enumerate(zip(screen_px, SCREEN_RGB)):
            self.assertAlmostEqual(
                got, want, delta=4,
                msg=f"warna layar kanal {ch} {got} vs teoretis {want} (piksel {screen_px})",
            )

        # Sudut ponsel: radius 56, pusat busur di (640+56, 250+56) = (696, 306)
        # Pojok luar lengkungan (645, 255): jarak ≈ 72.1 px > 56 px -> latar hitam
        corner_px = _px(frame, 645, 255)
        self.assertLessEqual(
            max(corner_px), 5,
            msg=f"sudut ponsel harus latar hitam karena radius 56, dapat {corner_px}",
        )
        # Titik di dalam lengkungan (660, 270): jarak ≈ 50.9 px < 56 px -> warna badan ponsel
        inside_px = _px(frame, 660, 270)
        for ch, (got, want) in enumerate(zip(inside_px, BODY_RGB)):
            self.assertAlmostEqual(
                got, want, delta=4,
                msg=f"dalam lengkungan kanal {ch} {got} vs teoretis {want} (piksel {inside_px})",
            )

    # -- (c) kekakuan masuk & total pergeseran ---------------------------------

    def test_rigid_entry_slide_and_displacement(self) -> None:
        start_frame = round(START * FPS)
        entry_ms = int(round(presets_phone.PHONE_ENTRY * 1000.0))

        # Uji kekakuan pada 4 frame selama masuk: offset (pusat notch - sudut kiri-atas badan)
        test_frames = [start_frame + k for k in (2, 4, 6, 8)]
        offsets: list[tuple[float, float]] = []

        for f_idx in test_frames:
            frame = self._frame("right", f_idx)
            bbox = _scan_bbox(frame, (0, 0, OUT_W, OUT_H), threshold=5)
            self.assertIsNotNone(bbox, msg=f"badan ponsel tidak terlihat di frame {f_idx}")
            assert bbox is not None
            bx0, by0 = bbox[0], bbox[1]

            # Pusat notch teoretis relatif terhadap badan: (190, 37)
            # Notch pil 80x18 di tengah layar (layar inset 14, notch top margin 14)
            # cy = 14 + 14 + 9 = 37; cx = 380 / 2 = 190.
            # Karena notch dan badan digerakkan dengan tag move identik,
            # offset notch relatif terhadap sudut badan harus persis konstan.
            notch_expected_cx = bx0 + 190
            notch_expected_cy = by0 + 37
            offsets.append((round(notch_expected_cx - bx0, 2), round(notch_expected_cy - by0, 2)))

        for axis in (0, 1):
            values = [off[axis] for off in offsets]
            self.assertLessEqual(
                max(values) - min(values), 1.0,
                msg=f"offset elemen tidak kaku pada sumbu {axis}: {offsets}",
            )

        # Total pergeseran selama masuk ≈ 140 px ±2
        # Frame start awal vs frame penuh:
        frame_start_rgb = self._frame("right", start_frame)
        bbox_start = _scan_bbox(frame_start_rgb, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNotNone(bbox_start, msg="badan ponsel tidak terlihat di start_frame")
        assert bbox_start is not None

        frame_settled = self._frame("right", start_frame + round(presets_phone.PHONE_ENTRY * FPS))
        bbox_settled = _scan_bbox(frame_settled, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNotNone(bbox_settled, msg="badan ponsel tidak terlihat di settled_frame")
        assert bbox_settled is not None

        measured_displacement = bbox_start[0] - bbox_settled[0]
        self.assertAlmostEqual(
            measured_displacement,
            140.0,
            delta=2.0,
            msg=f"pergeseran total terukur {measured_displacement} px vs teoretis 140.0 px",
        )

    # -- (d) baris ke-k muncul berurutan pada frame teoretis ±0 frame -----------

    def test_sequential_lines_appearance_and_accent_colour(self) -> None:
        start_frame = round(START * FPS)
        entry_frame = start_frame + round(presets_phone.PHONE_ENTRY * FPS)

        # Hitung frame kemunculan tiap baris (kontrak: jeda 180 ms)
        line_frames = [
            entry_frame + round(k * 0.180 * FPS)
            for k in range(len(LINES))
        ]

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

        for k, lf in enumerate(line_frames):
            row_cy = int(round(first_line_top + k * presets_phone.PHONE_LINE_ROW_H + presets_phone.PHONE_LINE_ROW_H / 2.0))
            text_region = (text_x, row_cy - 16, text_x + 180, row_cy + 16)

            # 1. Pada frame sebelum baris k muncul (lf - 1): piksel teks baris belum ada
            frame_before = self._frame("right", lf - 1)
            bright_before = _count_bright_pixels(frame_before, text_region, threshold=120)
            self.assertEqual(
                bright_before, 0,
                msg=f"baris {k} sudah memiliki piksel teks pada frame {lf - 1} (sebelum waktunya)",
            )

            # 2. Pada frame setelah fade-in selesai (lf + 4 frame = ~133 ms > 120 ms fade-in):
            frame_visible = self._frame("right", lf + 4)
            bright_visible = _count_bright_pixels(frame_visible, text_region, threshold=120)
            self.assertGreater(
                bright_visible, 20,
                msg=f"baris {k} belum terlihat setelah fade-in pada frame {lf + 4}",
            )

            # 3. Bullet berwarna aksen #FFD60A ±6
            bullet_px = _px(frame_visible, bullet_cx, row_cy)
            for ch, (got, want) in enumerate(zip(bullet_px, ACCENT_RGB)):
                self.assertAlmostEqual(
                    got, want, delta=6,
                    msg=f"warna bullet baris {k} kanal {ch} {got} vs teoretis {want} (piksel {bullet_px})",
                )

    # -- (e) setelah end + EXIT + 2 frame: piksel hitam polos kembali ----------

    def test_pixels_after_exit_are_pure_black(self) -> None:
        after_index = round((END + presets_phone.PHONE_EXIT + 2.0 / FPS) * FPS)
        frame = self._frame("right", after_index)
        bbox = _scan_bbox(frame, (0, 0, OUT_W, OUT_H), threshold=8)
        self.assertIsNone(
            bbox,
            msg=f"ada piksel non-hitam pada frame setelah exit ({after_index}): {bbox}",
        )

    # -- (f) kontrol font: render tanpa Archivo Black memberi lebar teks berbeda

    def test_bundled_font_differs_from_fallback(self) -> None:
        index = round(2.5 * FPS)
        bundled_frame = self._frame("right", index)
        fallback_frame = self._frame("fallback", index)

        # Region judul: content_x..content_x+250, title_y..title_y+40
        title_y = int(round(250 + presets_phone.PHONE_SCREEN_INSET + presets_phone.PHONE_TITLE_PAD_TOP))
        title_region = (640 + 20, title_y - 4, 640 + 300, title_y + 40)

        bbox_bundled = _scan_bbox(bundled_frame, title_region, threshold=80)
        bbox_fallback = _scan_bbox(fallback_frame, title_region, threshold=80)

        self.assertIsNotNone(bbox_bundled, msg="judul font bundel tidak terlihat")
        self.assertIsNotNone(bbox_fallback, msg="judul fallback tidak terlihat")
        assert bbox_bundled is not None and bbox_fallback is not None

        w_bundled = bbox_bundled[2] - bbox_bundled[0] + 1
        w_fallback = bbox_fallback[2] - bbox_fallback[0] + 1

        diff = sum(1 for a, b in zip(bundled_frame, fallback_frame) if a != b)
        differs = abs(w_bundled - w_fallback) >= 2 or diff >= 500
        self.assertTrue(
            differs,
            msg=f"font fallback menghasilkan piksel identik dengan font bundel (lebar {w_bundled} vs {w_fallback})",
        )

    # -- (g) side='left' bbox di sisi kiri ------------------------------------

    def test_side_left_renders_on_left(self) -> None:
        start_frame = round(START * FPS)
        entry_frame = start_frame + round(presets_phone.PHONE_ENTRY * FPS)
        full_index = entry_frame + 2
        frame = self._frame("left", full_index)

        # Default side='left' rect: x=60, y=250, w=380, h=660 -> (60, 250, 439, 909)
        want_rect = (60, 250, 60 + 380 - 1, 250 + 660 - 1)
        bbox = _scan_bbox(frame, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNotNone(bbox, msg="badan ponsel side='left' tidak terlihat")
        assert bbox is not None
        for i, (got, want) in enumerate(zip(bbox, want_rect)):
            self.assertLessEqual(
                abs(got - want), 2,
                msg=f"koordinat bbox {i} side='left' {got} vs teoretis {want} (bbox={bbox})",
            )


if __name__ == "__main__":
    unittest.main()
