"""Tes integrasi preset `checklist`: piksel, frame, kekakuan, lapisan.

Pola sama dengan `tests/test_presets_render.py`: klip hitam sintetis 4 s @30
dengan audio, dirender lewat `render.render_clip` (jalur produk), lalu frame
mentah dibaca kembali sebagai rgb24. Semua tes di-skip dengan pesan jujur bila
tidak ada ffmpeg berlibass (`tests/ffmpeg_libass.py`).

Yang dibuktikan HANYA bisa dilihat di piksel:
  (a) sebelum `start` identik dengan render tanpa preset;
  (b) bbox kartu = rect teoretis ±2 px, interior = #14161B x opasitas ±6;
  (c) kartu + elemen bergerak KAKU saat masuk (selisih posisi konstan ±1 px);
  (d) cincin abu -> hijau + centang putih TEPAT pada frame done_at, dengan
      overshoot pop (diameter hijau > diameter settle);
  (e) penghitung berganti tepat pada frame done_at, tidak di frame lain;
  (f) sesudah end + 0,20 s + 2 frame identik dengan tanpa preset;
  (g) jumlah frame + durasi audio tidak berubah;
  (h) caption tetap di lapisan atas kartu;
  (i) kontrol font: fontsdir tanpa Archivo Black memberi lebar teks berbeda.

Angka teoretis diturunkan dari konstanta `scripts.presets` yang sama dengan
implementasi, bukan dari string ASS: kalau tag berubah tetapi posisi piksel
tetap, tes ini tetap sah.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import ROOT

from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts import presets
from scripts import render
from scripts.lib import fontmetrics

FONT_DIR = (ROOT / "assets" / "fonts").resolve()
ARCHIVO_FILE = FONT_DIR / "ArchivoBlack-Regular.ttf"
TYPE = "checklist"

SRC_W, SRC_H = 1920, 1080
SRC_FPS = 30
FPS = 30
OUT_W, OUT_H = 1080, 1920
CLIP_DUR = 4.0

START = 0.4
END = 3.6
TITLE = "CHECKLIST"
ITEMS = [
    {"text": "Beli kopi", "done_at": 1.23},  # frame round(1.23*30) = 37
    {"text": "Rapat jam 9", "done_at": 2.0},  # frame 60
]
DONE_FRAMES = [round(item["done_at"] * FPS) for item in ITEMS if item["done_at"] is not None]

# Kartu bawaan: x=60, y=260, w=960, h=2*32 + 72 + 2*64 = 264.
CARD_RECT = (60, 260, 1019, 523)  # bbox piksel inklusif
CARD_INTERIOR = (1000, 504)
CARD_RGB = (round(0x14 * 0.86), round(0x16 * 0.86), round(0x1B * 0.86))

RING1 = (126, 396)  # pusat cincin butir 1 (lihat konstanta presets)
RING_RGB = (91, 97, 107)   # #5B616B
GREEN_RGB = (34, 197, 94)  # #22C55E

COUNTER_REGION = (840, 300, 980, 356)
TITLE_REGION = (100, 296, 500, 356)

_FFMPEG = find_ffmpeg_with_libass()
_FFPROBE = str(Path(_FFMPEG).with_name("ffprobe")) if _FFMPEG else None
if _FFPROBE and not Path(_FFPROBE).exists():
    _FFPROBE = None

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


def _checklist_overlay(**overrides: Any) -> dict[str, Any]:
    props: dict[str, Any] = {"title": TITLE, "items": [dict(i) for i in ITEMS]}
    item: dict[str, Any] = {
        "type": TYPE,
        "start": START,
        "end": END,
        "props": props,
    }
    item.update(overrides)
    return item


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
# ffmpeg + pembacaan frame
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
        f"color=c=black:s={SRC_W}x{SRC_H}:r={SRC_FPS}:d={CLIP_DUR:g}",
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={CLIP_DUR:g}",
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
    i = (y * OUT_W + x) * 3
    return data[i], data[i + 1], data[i + 2]


def _scan_bbox(
    data: bytes, region: tuple[int, int, int, int], threshold: int = 20
) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    min_x = min_y = 10**9
    max_x = max_y = -1
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = data[base:base + (x1 - x0) * 3]
        for x in range(x1 - x0):
            i = x * 3
            if max(row[i], row[i + 1], row[i + 2]) > threshold:
                gx = x0 + x
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


def _region_slice(data: bytes, region: tuple[int, int, int, int]) -> bytes:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    return b"".join(
        data[y * stride + x0 * 3:y * stride + x1 * 3] for y in range(y0, y1)
    )


def _region_diff(a: bytes, b: bytes, region: tuple[int, int, int, int]) -> int:
    left = _region_slice(a, region)
    right = _region_slice(b, region)
    return max(abs(x - y) for x, y in zip(left, right))


def _first_ink(data: bytes, x: int, y0: int, y1: int, threshold: int) -> int:
    """Baris pertama (dari atas) di kolom `x` dengan salah satu kanal > ambang."""
    for y in range(y0, y1):
        if max(_px(data, x, y)) > threshold:
            return y
    raise AssertionError(f"tinta tidak terdeteksi di kolom x={x}, y={y0}..{y1}")


def _green_count(data: bytes, region: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    count = 0
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = data[base:base + (x1 - x0) * 3]
        for x in range(x1 - x0):
            i = x * 3
            r, g, b = row[i], row[i + 1], row[i + 2]
            if g >= 120 and g > r + 60 and g > b + 60:
                count += 1
    return count


def _green_bbox_width(data: bytes, region: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    min_x = 10**9
    max_x = -1
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = data[base:base + (x1 - x0) * 3]
        for x in range(x1 - x0):
            i = x * 3
            r, g, b = row[i], row[i + 1], row[i + 2]
            if g >= 120 and g > r + 60 and g > b + 60:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
    return 0 if max_x < 0 else max_x - min_x + 1


def _white_count(data: bytes, region: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    count = 0
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = data[base:base + (x1 - x0) * 3]
        for x in range(x1 - x0):
            i = x * 3
            if row[i] > 200 and row[i + 1] > 200 and row[i + 2] > 200:
                count += 1
    return count


def _count_yellow(data: bytes, region: tuple[int, int, int, int]) -> int:
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


# ---------------------------------------------------------------------------
# Tes piksel utama
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class ChecklistPixelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")

        cls.clip_fx = _clip(overlays=[_checklist_overlay()])
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
        index = round((START + presets.CHECK_ENTRY + 2.0 / FPS) * FPS)
        frame = self._frame("fx", index)
        bbox = _scan_bbox(frame, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNotNone(bbox, msg="kartu tidak terlihat")
        assert bbox is not None
        self.assertLessEqual(
            max(abs(a - b) for a, b in zip(bbox, CARD_RECT)), 2,
            msg=f"bbox kartu {bbox} vs teoretis {CARD_RECT}",
        )
        got = _px(frame, *CARD_INTERIOR)
        for channel, (value, want) in enumerate(zip(got, CARD_RGB)):
            self.assertAlmostEqual(
                value, want, delta=6,
                msg=f"kanal {channel} interior kartu {value} vs {want} (piksel {got})",
            )

    # -- (c) masuk kaku ---------------------------------------------------

    def test_entry_is_rigid(self) -> None:
        start_frame = round(START * FPS)
        frames = [start_frame + k for k in (3, 4, 5, 6)]
        offsets = []
        for index in frames:
            frame = self._frame("fx", index)
            card_top = _first_ink(frame, 540, 150, 900, threshold=5)
            # Jendela relatif terhadap tepi atas kartu: cincin butir 1 berada
            # di card_top+114..card_top+158, judul berakhir ~card_top+90, dan
            # cincin butir 2 mulai ~card_top+178. Jendela 100..170 karena itu
            # hanya berisi cincin butir 1 tanpa judul/cincin lain. Kalau
            # elemen tidak kaku, jarak terukur berubah (atau cincin keluar
            # jendela -> gagal).
            ring = _scan_bbox(
                frame, (95, card_top + 100, 160, card_top + 170),
                threshold=25,
            )
            self.assertIsNotNone(ring, msg=f"cincin butir 1 tidak terlihat di frame {index}")
            assert ring is not None
            cx = (ring[0] + ring[2]) / 2.0
            cy = (ring[1] + ring[3]) / 2.0
            offsets.append((round(cx - 60.0, 2), round(cy - card_top, 2)))
        for axis in (0, 1):
            values = [offset[axis] for offset in offsets]
            self.assertLessEqual(
                max(values) - min(values), 1.0,
                msg=f"elemen kartu tidak kaku pada sumbu {axis}: {offsets}",
            )

    # -- (d) cincin -> hijau + centang + overshoot -----------------------

    def test_green_appears_exactly_at_done_frame(self) -> None:
        for item_index, frame in enumerate(DONE_FRAMES):
            center_y = 396 + presets.CARD_ROW_H * item_index
            region = (90, int(center_y - 36), 165, int(center_y + 36))
            before2 = _green_count(self._frame("fx", frame - 2), region)
            before1 = _green_count(self._frame("fx", frame - 1), region)
            self.assertEqual(
                before2, 0,
                msg=f"hijau butir {item_index + 1} sudah ada 2 frame sebelum "
                    f"done_at (frame {frame - 2})",
            )
            self.assertEqual(
                before1, 0,
                msg=f"hijau butir {item_index + 1} sudah ada 1 frame sebelum "
                    f"done_at (frame {frame - 1})",
            )

    def test_green_and_check_pixels_after_settle(self) -> None:
        frame = self._frame("fx", DONE_FRAMES[0] + 8)
        for point in ((108, 396), (144, 396), (126, 378), (126, 414)):
            with self.subTest(point=point):
                got = _px(frame, *point)
                for channel, (value, want) in enumerate(zip(got, GREEN_RGB)):
                    self.assertAlmostEqual(
                        value, want, delta=6,
                        msg=(
                            f"piksel {point} kanal {channel} {value} vs {want} "
                            f"(piksel {got}); cincin belum hijau penuh"
                        ),
                    )
        whites = _white_count(frame, (108, 380, 145, 412))
        self.assertGreater(whites, 5, msg=f"centang putih tidak terlihat ({whites} px)")

    def test_ring_center_before_done_is_not_green(self) -> None:
        frame = self._frame("fx", DONE_FRAMES[0] - 2)
        r, g, b = _px(frame, *RING1)
        self.assertLess(g, 120, msg=f"pusat cincin sudah hijau: {(r, g, b)}")
        # Cincin abu harus masih ada di titik tepi kiri.
        edge = _px(frame, RING1[0] - 18, RING1[1])
        self.assertGreater(min(edge), 40, msg=f"cincin abu hilang: {edge}")

    def test_pop_overshoots_before_settling(self) -> None:
        region = (90, 360, 165, 435)
        widths = []
        for offset in range(2, 9):
            frame = self._frame("fx", DONE_FRAMES[0] + offset)
            widths.append(_green_bbox_width(frame, region))
        settled = widths[-1]
        self.assertGreater(settled, 30, msg=f"lingkaran hijau tidak terlihat: {widths}")
        self.assertGreater(
            max(widths[:-1]), settled + 1,
            msg=f"tidak ada overshoot pop (diameter hijau): {widths}",
        )

    # -- (e) penghitung tepat pada frame ---------------------------------

    def test_counter_changes_exactly_on_done_frame(self) -> None:
        for frame in DONE_FRAMES:
            before2 = self._frame("fx", frame - 2)
            before1 = self._frame("fx", frame - 1)
            at = self._frame("fx", frame)
            after = self._frame("fx", frame + 1)
            self.assertLessEqual(
                _region_diff(before2, before1, COUNTER_REGION), 20,
                msg=f"penghitung sudah berubah sebelum frame {frame}",
            )
            self.assertGreater(
                _region_diff(before1, at, COUNTER_REGION), 40,
                msg=f"penghitung tidak berubah tepat pada frame {frame}",
            )
            self.assertLessEqual(
                _region_diff(at, after, COUNTER_REGION), 12,
                msg=f"penghitung berubah lagi sesudah frame {frame}",
            )
        # Frame lain di tengah state tidak berubah.
        quiet = round((DONE_FRAMES[0] + DONE_FRAMES[1]) / 2)
        self.assertLessEqual(
            _region_diff(self._frame("fx", quiet), self._frame("fx", quiet + 1),
                         COUNTER_REGION),
            12,
            msg="penghitung berubah di luar done_at",
        )

    # -- (f) sesudah keluar identik --------------------------------------

    def test_pixels_after_exit_are_identical(self) -> None:
        index = round((END + presets.CHECK_EXIT + 2.0 / FPS) * FPS)
        self.assertEqual(
            self._frame("fx", index), self._frame("plain", index),
            msg=f"frame {index} (t={index / FPS:.3f}s) berbeda dari tanpa preset",
        )

    def test_exit_fade_reduces_card_opacity_before_end(self) -> None:
        full = _px(self._frame("fx", round((START + presets.CHECK_ENTRY + 2.0 / FPS) * FPS)),
                   *CARD_INTERIOR)
        fading = _px(self._frame("fx", round((END - 0.1) * FPS)), *CARD_INTERIOR)
        self.assertGreater(full[0], 13, msg=f"kartu penuh terlalu gelap: {full}")
        self.assertLess(
            fading[0], full[0] * 0.75,
            msg=f"fade keluar tidak terlihat: penuh {full} vs {fading} di end-0,1 s",
        )

    # -- (g) durasi/frame tidak berubah ----------------------------------

    def test_frame_count_and_audio_duration_are_identical(self) -> None:
        want = round(CLIP_DUR * FPS)
        for probe in (self.probe_fx, self.probe_plain):
            self.assertEqual(int(probe["video"]["nb_frames"]), want)
        a = float(self.probe_fx["audio"]["duration"])
        b = float(self.probe_plain["audio"]["duration"])
        self.assertLessEqual(abs(a - b), 1.0 / 48.0, msg=f"preset {a:.4f}s vs tanpa {b:.4f}s")

    # -- (i) kontrol font -------------------------------------------------

    def test_bundled_font_differs_from_system_fallback(self) -> None:
        index = round((START + presets.CHECK_ENTRY + 2.0 / FPS) * FPS)
        bundled = self._frame("fx", index)
        fallback = self._frame("fallback", index)

        bbox_bundled = _scan_bbox(bundled, TITLE_REGION, threshold=80)
        bbox_fallback = _scan_bbox(fallback, TITLE_REGION, threshold=80)
        self.assertIsNotNone(bbox_bundled, msg="judul font bundel tidak terlihat")
        self.assertIsNotNone(bbox_fallback, msg="judul fallback tidak terlihat")
        assert bbox_bundled is not None and bbox_fallback is not None
        width_bundled = bbox_bundled[2] - bbox_bundled[0] + 1
        width_fallback = bbox_fallback[2] - bbox_fallback[0] + 1

        font = fontmetrics.Font.load(ARCHIVO_FILE)
        predicted = font.width(TITLE, presets.CHECK_TITLE_EM)
        self.assertAlmostEqual(
            width_bundled / predicted, 1.0, delta=0.08,
            msg=(
                f"lebar judul {width_bundled} px vs prediksi fontmetrics "
                f"{predicted:.1f} px; Fontsize/font bundel tidak sesuai"
            ),
        )

        diff = sum(1 for a, b in zip(bundled, fallback) if a != b)
        differs = abs(width_bundled - width_fallback) >= 3 or diff >= 2000
        if not differs:
            self.skipTest(
                "font sistem kebetulan identik dengan Archivo Black "
                f"(lebar {width_bundled} vs {width_fallback}); kontrol tidak "
                "bisa membedakan, bukan bukti lulus."
            )


# ---------------------------------------------------------------------------
# (h) Caption tetap di atas kartu
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class ChecklistCaptionLayerTest(unittest.TestCase):
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

        overlay = _checklist_overlay(
            rect={"x": 140, "y": 1250, "w": 800, "h": 300},
        )
        overlay["props"]["items"] = [
            {"text": "Beli kopi", "done_at": 0.8},
            {"text": "Rapat jam 9", "done_at": None},
        ]
        cls.clip_with = _clip(overlays=[overlay], captions=[dict(cls.CAPTION)])
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

    def test_caption_ink_stays_on_top_of_card(self) -> None:
        index = round(1.0 * FPS)  # kartu penuh, caption sudah settle
        region = (400, 1340, 680, 1460)
        without = _count_yellow(_frame_rgb(self.out_without, index), region)
        combined = _count_yellow(_frame_rgb(self.out_with, index), region)
        self.assertGreater(without, 100, msg="caption kuning tidak terlihat")
        self.assertGreaterEqual(
            combined, int(without * 0.9),
            msg=(
                f"caption tertutup kartu: piksel kuning {combined} vs {without}; "
                f"caption harus jadi filter terakhir"
            ),
        )


# ---------------------------------------------------------------------------
# C15: frame dengan pembulatan sentidetik KE ATAS (38, 41, 68 @30 fps)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class ChecklistRoundingPixelTest(unittest.TestCase):
    """Penghitung + lingkaran hijau harus berganti TEPAT pada frame itu.

    Frame 38/41/68 @30 fps adalah frame di mana `round(frame / fps, 2)`
    membulat ke atas. Mutan C15 memakai rumus itu untuk waktu mulai event,
    sehingga event baru tampil satu frame terlambat. Tes piksel ini memeriksa
    frame F-1, F, F+1: penghitung berubah di F, dan hijau (yang mulai dengan
    skala 0) sudah terlihat di F+1 — pada mutan F+1 masih kosong.
    """

    FRAMES = (38, 41, 68)

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")

        items = [
            {"text": f"Butir {i + 1}", "done_at": frame / FPS}
            for i, frame in enumerate(cls.FRAMES)
        ]
        overlay = _checklist_overlay(start=0.4, end=3.6)
        overlay["props"] = {"title": "ROUNDING", "items": items}
        cls.clip = _clip(overlays=[overlay])
        cls.out = cls.wd / "out" / "clip_rounding.mp4"
        # crf 10: tes ini membandingkan dua frame yang teksnya SAMA di region
        # penghitung; derau x264 crf 20 bisa melewati ambang 12.
        render.render_clip(EDL, cls.clip, cls.wd, cls.out, crf=10)
        cls._frames: dict[int, bytes] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _frame(self, index: int) -> bytes:
        if index not in self._frames:
            self._frames[index] = _frame_rgb(self.out, index)
        return self._frames[index]

    def test_counter_changes_exactly_on_round_up_frames(self) -> None:
        for frame in self.FRAMES:
            with self.subTest(frame=frame):
                self.assertLessEqual(
                    _region_diff(self._frame(frame - 2), self._frame(frame - 1),
                                 COUNTER_REGION),
                    12,
                    msg=f"penghitung sudah berubah sebelum frame {frame}",
                )
                self.assertGreater(
                    _region_diff(self._frame(frame - 1), self._frame(frame),
                                 COUNTER_REGION),
                    40,
                    msg=f"penghitung tidak berubah tepat pada frame {frame}",
                )
                self.assertLessEqual(
                    _region_diff(self._frame(frame), self._frame(frame + 1),
                                 COUNTER_REGION),
                    12,
                    msg=f"penghitung berubah lagi sesudah frame {frame}",
                )

    def test_green_circle_starts_on_round_up_frame_not_one_late(self) -> None:
        for item_index, frame in enumerate(self.FRAMES):
            center_y = 396 + presets.CARD_ROW_H * item_index
            region = (90, int(center_y - 36), 165, int(center_y + 36))
            with self.subTest(frame=frame):
                self.assertEqual(
                    _green_count(self._frame(frame - 1), region), 0,
                    msg=f"hijau sudah ada sebelum frame {frame}",
                )
                # Event mulai ~30 ms SEBELUM timestamp frame (aturan
                # sentidetik), jadi pada frame F pop sudah berada di node
                # pertama rantai \\t dan hijau WAJIB sudah terlihat di F.
                # Mutan C15 menulis start 1,27/1,37/2,27 sehingga frame F
                # masih kosong dan hijau baru tampil di F+1.
                self.assertGreater(
                    _green_count(self._frame(frame), region), 0,
                    msg=(
                        f"hijau butir {item_index + 1} tidak muncul di frame "
                        f"{frame}: event terlambat satu frame (mutan C15)"
                    ),
                )
                self.assertGreater(
                    _green_count(self._frame(frame + 1), region), 0,
                    msg=f"hijau butir {item_index + 1} hilang di frame {frame + 1}",
                )


if __name__ == "__main__":
    unittest.main()
