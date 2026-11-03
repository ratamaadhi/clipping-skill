"""Tes integrasi preset `chart_grow`: piksel, geometri, waktu, lapisan.

Klip hitam sintetis 4 s @30 + audio, dirender lewat `render.render_clip` (jalur
produk). Semua tes di-skip dengan pesan jujur bila tidak ada ffmpeg berlibass
(`tests/ffmpeg_libass.py`).

Yang dibuktikan HANYA bisa dilihat di piksel:
  (a) sebelum `start` identik dengan render tanpa preset;
  (b) bbox kartu = rect teoretis ±2 px, interior = #14161B x 0,86 ±6;
  (c) lebar kuning garis naik monoton saat tumbuh, nol sebelum tumbuh, dan
      sama dengan lebar jalur penuh sesudah selesai;
  (d) pusat titik ujung <= 3 px dari kepala garis yang terlihat (>= 6 frame);
  (e) y garis penuh pada x simpul = y teoretis dari `values` ±2 px;
  (f) bbox tiap label sumbu di dalam ±6 px dari x simpulnya;
  (g) tag baru muncul setelah garis selesai (tidak ada piksel di frame
      grow_end-2), lalu pusat gelembung = posisi teoretis ±3 px dan teksnya
      terlihat;
  (h) sesudah end + EXIT + 2 frame identik dengan tanpa preset;
  (i) jumlah frame + durasi audio tidak berubah;
  (j) caption tetap di lapisan atas kartu;
  (k) kontrol font: fontsdir tanpa Archivo Black memberi lebar label berbeda.

Angka teoretis diturunkan dari konstanta `scripts.presets` (bukan dari string
ASS), jadi tag yang berubah tetapi piksel tetap tidak membuat tes palsu lulus.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import ROOT

from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts import presets
from scripts import render
from scripts import shapes
from scripts.lib import fontmetrics

FONT_DIR = (ROOT / "assets" / "fonts").resolve()
ARCHIVO_FILE = FONT_DIR / "ArchivoBlack-Regular.ttf"
TYPE = "chart_grow"

SRC_W, SRC_H = 1920, 1080
SRC_FPS = 30
FPS = 30
OUT_W, OUT_H = 1080, 1920
CLIP_DUR = 4.0

START = 0.4
END = 3.6
GROW = 1.2
LABELS = ("SEN", "SEL", "RAB", "KAM", "JUM")
VALUES = (10.0, 40.0, 25.0, 55.0, 80.0)
TAG = "+240%"
TITLE = "GROWTH"

ENTRY_FRAME = round(START * FPS) + round(presets.CHART_ENTRY * FPS)
GROW_FRAMES = round(GROW * FPS)
GROW_END_FRAME = ENTRY_FRAME + GROW_FRAMES
EXIT_FRAME = round(END * FPS) - round(presets.CHART_EXIT * FPS)

_FFMPEG = find_ffmpeg_with_libass()
_FFPROBE = str(Path(_FFMPEG).with_name("ffprobe")) if _FFMPEG else None
if _FFPROBE and not Path(_FFPROBE).exists():
    _FFPROBE = None

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` atau set env CLIP_FFMPEG ke path ffmpeg berlibas."
)


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


def _chart_overlay(
    *,
    rect: dict | None = None,
    labels: tuple[str, ...] = LABELS,
    values: tuple[float, ...] = VALUES,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": TYPE,
        "start": START,
        "end": END,
        "props": {
            "labels": list(labels),
            "values": list(values),
            "tag": TAG,
            "title": TITLE,
            "grow": GROW,
        },
    }
    if rect is not None:
        item["rect"] = rect
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


def _default_rect() -> dict[str, float]:
    return {
        "x": presets.CHART_CARD_X,
        "y": presets.CHART_CARD_Y,
        "w": presets.CHART_CARD_W,
        "h": presets.CHART_CARD_H,
    }


def _geometry() -> dict[str, float]:
    return presets._chart_geometry(_default_rect(), True)


def _points() -> list[tuple[float, float]]:
    return presets._chart_points(list(VALUES), _geometry())


# ---------------------------------------------------------------------------
# ffmpeg + pembacaan frame
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


def _is_yellow(r: int, g: int, b: int) -> bool:
    return r >= 225 and g >= 175 and b <= 80


def _scan_bbox(
    data: bytes, region: tuple[int, int, int, int], threshold: int = 20
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
            r, g, b = row[i], row[i + 1], row[i + 2]
            if _is_yellow(r, g, b):
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


def _yellow_width(data: bytes, region: tuple[int, int, int, int]) -> int:
    bbox = _yellow_bbox(data, region)
    return 0 if bbox is None else bbox[2] - bbox[0] + 1


def _yellow_count(data: bytes, region: tuple[int, int, int, int]) -> int:
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


def _yellow_run(data: bytes, x: int, y0: int, y1: int) -> tuple[int, int] | None:
    first = last = None
    for y in range(max(0, y0), min(OUT_H, y1)):
        r, g, b = _px(data, x, y)
        if _is_yellow(r, g, b):
            if first is None:
                first = y
            last = y
    if first is None:
        return None
    assert last is not None
    return first, last


def _region_diff(a: bytes, b: bytes, region: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = region
    stride = OUT_W * 3
    worst = 0
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        left = a[base:base + (x1 - x0) * 3]
        right = b[base:base + (x1 - x0) * 3]
        worst = max(worst, max(abs(p - q) for p, q in zip(left, right)))
    return worst


def _progress_at(offset: int) -> float:
    nodes = presets._chart_grow_nodes(GROW_FRAMES)
    for (f0, p0), (f1, p1) in zip(nodes, nodes[1:]):
        if f0 <= offset <= f1:
            if f1 == f0:
                return p1
            return p0 + (p1 - p0) * (offset - f0) / (f1 - f0)
    return 1.0


# ---------------------------------------------------------------------------
# Tes piksel utama
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class ChartPixelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")

        cls.clip_fx = _clip(overlays=[_chart_overlay()])
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
        cls.geom = _geometry()
        cls.points = _points()
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

    def _line_region(self) -> tuple[int, int, int, int]:
        return (
            0,
            int(self.geom["plot_top"] - 25),
            OUT_W,
            int(self.geom["plot_bottom"] + 40),
        )

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
        bbox = _scan_bbox(frame, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNotNone(bbox, msg="kartu tidak terlihat")
        assert bbox is not None
        want = (60, 260, 1019, 779)
        self.assertLessEqual(
            max(abs(a - b) for a, b in zip(bbox, want)), 2,
            msg=f"bbox kartu {bbox} vs teoretis {want}",
        )
        got = _px(frame, 1000, 504)
        # #14161B x 0,86 di atas hitam.
        for channel, (value, target) in enumerate(zip(got, (17, 19, 23))):
            self.assertAlmostEqual(
                value, target, delta=6,
                msg=f"kanal {channel} interior kartu {value} vs {target} (piksel {got})",
            )

    def test_card_position_diff_between_entry_start_and_full_matches_offset(self) -> None:
        frame_start = self._frame("fx", round(START * FPS))
        frame_full = self._frame("fx", ENTRY_FRAME)
        bbox_start = _scan_bbox(frame_start, (0, 0, OUT_W, OUT_H), threshold=5)
        bbox_full = _scan_bbox(frame_full, (0, 0, OUT_W, OUT_H), threshold=5)
        self.assertIsNotNone(bbox_start, msg="kartu tidak terlihat pada frame awal masuk")
        self.assertIsNotNone(bbox_full, msg="kartu tidak terlihat pada frame penuh")
        assert bbox_start is not None and bbox_full is not None
        diff = bbox_full[3] - bbox_start[3]
        self.assertAlmostEqual(
            diff, presets.CHART_ENTRY_OFFSET, delta=6.0,
            msg=f"selisih posisi kartu awal masuk vs penuh {diff} vs {presets.CHART_ENTRY_OFFSET}",
        )
        self.assertAlmostEqual(
            diff, 60.0, delta=6.0,
            msg=f"selisih posisi kartu {diff} vs 60 px teoretis",
        )

    def test_rendered_grid_lines_count_inside_plot(self) -> None:
        frame = self._frame("fx", round(2.7 * FPS))
        geom = self.geom
        grid_rows: list[int] = []
        for y in range(int(geom["plot_top"] + 5), int(geom["plot_bottom"] - 10)):
            dim_count = sum(
                1 for x in range(160, 300)
                if 30 <= _px(frame, x, y)[0] <= 60
                and abs(_px(frame, x, y)[0] - _px(frame, x, y)[2]) < 15
            )
            if dim_count > 100:
                grid_rows.append(y)
        clusters: list[list[int]] = []
        for y in grid_rows:
            if not clusters or y > clusters[-1][-1] + 3:
                clusters.append([y])
            else:
                clusters[-1].append(y)
        self.assertEqual(
            len(clusters), presets.CHART_GRID_LINES,
            msg=f"jumlah garis grid terukur {len(clusters)} vs {presets.CHART_GRID_LINES} (baris: {clusters})",
        )
        self.assertEqual(
            len(clusters), 4,
            msg=f"jumlah garis grid terukur {len(clusters)} vs 4 teoretis",
        )

    # -- (c) lebar garis tumbuh monoton ----------------------------------

    def test_yellow_line_is_absent_before_grow(self) -> None:
        frame = self._frame("fx", ENTRY_FRAME - 1)
        self.assertEqual(
            _yellow_width(frame, self._line_region()), 0,
            msg="garis/titik kuning sudah terlihat sebelum tumbuh",
        )

    def test_yellow_line_width_grows_monotonically_to_full_width(self) -> None:
        widths = [
            _yellow_width(self._frame("fx", round((START + presets.CHART_ENTRY
                                                   + k * GROW / 6.0) * FPS)),
                          self._line_region())
            for k in range(1, 7)
        ]
        self.assertTrue(all(width > 0 for width in widths), msg=f"lebar: {widths}")
        for left, right in zip(widths, widths[1:]):
            self.assertGreaterEqual(
                right, left - 2,
                msg=f"lebar kuning tidak naik monoton (toleransi 2 px): {widths}",
            )
        self.assertGreater(widths[-1], widths[0] + 200, msg=widths)

        # Lebar jalur penuh teoretis: klip kiri = simpul pertama (tepi stroke
        # kiri terpotong ~2 px oleh klip), klip kanan = titik ujung.
        left_ink = self.points[0][0]
        right_ink = self.points[-1][0] + presets.CHART_DOT_RADIUS
        expected = right_ink - left_ink
        self.assertAlmostEqual(
            widths[-1], expected, delta=6,
            msg=f"lebar jalur penuh {widths[-1]} vs teoretis {expected:.1f}",
        )

        settled = _yellow_width(self._frame("fx", round(2.7 * FPS)),
                                self._line_region())
        self.assertAlmostEqual(
            settled, widths[-1], delta=3,
            msg=f"lebar sesudah selesai {settled} vs saat selesai {widths[-1]}",
        )

    # -- (d) titik ujung mengikuti kepala garis --------------------------

    def test_dot_center_follows_the_visible_line_head(self) -> None:
        for offset in (3, 9, 15, 21, 27, 33):
            with self.subTest(offset=offset):
                frame = self._frame("fx", ENTRY_FRAME + offset)
                progress = _progress_at(offset)
                head_x, head_y = presets._chart_head_point(self.points, progress)
                y0 = int(self.geom["plot_top"] - 25)
                y1 = int(self.geom["plot_bottom"] + 40)
                columns = []
                for x in range(int(head_x - 22), int(head_x + 25)):
                    run = _yellow_run(frame, x, y0, y1)
                    if run is not None and run[1] - run[0] + 1 >= 18:
                        columns.append(x)
                self.assertGreaterEqual(
                    len(columns), 5,
                    msg=f"titik ujung tidak terlihat di sekitar x={head_x:.1f}",
                )
                center_x = (min(columns) + max(columns)) / 2.0
                run = _yellow_run(frame, int(round(center_x)), y0, y1)
                self.assertIsNotNone(run)
                assert run is not None
                center_y = (run[0] + run[1]) / 2.0
                self.assertLessEqual(
                    abs(center_x - head_x), 3.0,
                    msg=f"pusat titik x={center_x:.1f} vs kepala garis {head_x:.1f}",
                )
                self.assertLessEqual(
                    abs(center_y - head_y), 3.0,
                    msg=f"pusat titik y={center_y:.1f} vs y garis {head_y:.1f}",
                )

    # -- (e) y simpul data ------------------------------------------------

    def test_line_y_at_data_nodes_matches_values(self) -> None:
        frame = self._frame("fx", round(2.7 * FPS))
        y0 = int(self.geom["plot_top"] - 20)
        y1 = int(self.geom["plot_bottom"] + 20)
        for position, (x, y) in enumerate(self.points):
            # Simpul pertama: ujung butt stroke membuat irisan kolom tepat di
            # x=128 tidak simetris (bias ~3 px). Ukur 20 px di dalam ruas dan
            # bandingkan dengan y interpolasi teoretis — masih membuktikan
            # polyline melewati simpul. Simpul lain diukur tepat di x-nya
            # (lingkaran sambungan / titik ujung membuat run simetris).
            if position == 0:
                column = int(round(x)) + 20
                nx, ny = self.points[1]
                expected = y + (ny - y) * (column - x) / (nx - x)
            else:
                column = int(round(x))
                expected = y
            with self.subTest(x=x, y=y):
                run = _yellow_run(frame, column, y0, y1)
                self.assertIsNotNone(run, msg=f"garis tidak terlihat di x={x:.1f}")
                assert run is not None
                center = (run[0] + run[1]) / 2.0
                self.assertAlmostEqual(
                    center, expected, delta=2.0,
                    msg=f"y garis {center:.1f} vs teoretis {expected:.1f}",
                )

    # -- (f) label sumbu --------------------------------------------------

    def test_labels_are_centered_under_their_nodes(self) -> None:
        frame = self._frame("fx", round(2.7 * FPS))
        label_y = int(self.geom["label_y"])
        for label, (x, _y) in zip(LABELS, self.points):
            with self.subTest(label=label):
                region = (int(x) - 80, label_y - 6, int(x) + 80, label_y + 50)
                bbox = _scan_bbox(frame, region, threshold=80)
                self.assertIsNotNone(bbox, msg=f"label {label!r} tidak terlihat")
                assert bbox is not None
                center = (bbox[0] + bbox[2]) / 2.0
                self.assertLessEqual(
                    abs(center - x), 6.0,
                    msg=f"label {label!r} center {center:.1f} vs simpul {x:.1f}",
                )

    # -- (g) tag ----------------------------------------------------------

    def test_tag_appears_only_after_grow_and_sits_by_the_endpoint(self) -> None:
        font = fontmetrics.Font.load(ARCHIVO_FILE)
        bubble_w, bubble_h = presets._chart_tag_size(TAG, font)
        cx, cy = presets._chart_tag_center(
            _default_rect(), self.points[-1], bubble_w, bubble_h
        )
        region = (
            int(cx - bubble_w / 2.0 - 4), int(cy - bubble_h / 2.0 - 4),
            int(cx + bubble_w / 2.0 + 4), int(cy + bubble_h / 2.0 + 4),
        )
        before = _yellow_count(self._frame("fx", GROW_END_FRAME - 2), region)
        self.assertEqual(before, 0, msg=f"tag sudah terlihat sebelum garis selesai ({before} px)")

        frame = self._frame("fx", GROW_END_FRAME + 12)
        bbox = _yellow_bbox(frame, region)
        self.assertIsNotNone(bbox, msg="tag tidak terlihat sesudah grow + settle")
        assert bbox is not None
        got_x = (bbox[0] + bbox[2]) / 2.0
        got_y = (bbox[1] + bbox[3]) / 2.0
        self.assertLessEqual(
            abs(got_x - cx), 3.0, msg=f"pusat tag x={got_x:.1f} vs teoretis {cx:.1f}"
        )
        self.assertLessEqual(
            abs(got_y - cy), 3.0, msg=f"pusat tag y={got_y:.1f} vs teoretis {cy:.1f}"
        )

        interior = (
            int(cx - bubble_w / 2.0 + 10), int(cy - bubble_h / 2.0 + 10),
            int(cx + bubble_w / 2.0 - 10), int(cy + bubble_h / 2.0 - 10),
        )
        self.assertGreater(
            _yellow_count(frame, interior), 20,
            msg="teks tag tidak terlihat di dalam gelembung",
        )

    # -- (h) sesudah keluar identik --------------------------------------

    def test_pixels_after_exit_are_identical(self) -> None:
        index = round((END + presets.CHART_EXIT + 2.0 / FPS) * FPS)
        self.assertEqual(
            self._frame("fx", index), self._frame("plain", index),
            msg=f"frame {index} (t={index / FPS:.3f}s) berbeda dari tanpa preset",
        )

    # -- (i) durasi/frame tidak berubah ----------------------------------

    def test_frame_count_and_audio_duration_are_identical(self) -> None:
        want = round(CLIP_DUR * FPS)
        for probe in (self.probe_fx, self.probe_plain):
            self.assertEqual(int(probe["video"]["nb_frames"]), want)
        a = float(self.probe_fx["audio"]["duration"])
        b = float(self.probe_plain["audio"]["duration"])
        self.assertLessEqual(abs(a - b), 1.0 / 48.0,
                             msg=f"preset {a:.4f}s vs tanpa {b:.4f}s")

    # -- ASS yang ditulis renderer ---------------------------------------

    def test_rendered_ass_has_chart_dialogues(self) -> None:
        self.assertIn("Style: Sans,Archivo Black,", self.ass_fx)
        self.assertGreater(self.ass_fx.count("Dialogue:"), 20)
        self.assertIn(shapes.colour(presets.CHART_LINE_COLOUR), self.ass_fx)

    # -- (k) kontrol font -------------------------------------------------

    def test_bundled_font_differs_from_system_fallback(self) -> None:
        index = round(2.7 * FPS)
        bundled = self._frame("fx", index)
        fallback = self._frame("fallback", index)
        label_y = int(self.geom["label_y"])
        x = int(self.points[1][0])
        region = (x - 80, label_y - 6, x + 80, label_y + 50)
        bbox_bundled = _scan_bbox(bundled, region, threshold=80)
        bbox_fallback = _scan_bbox(fallback, region, threshold=80)
        self.assertIsNotNone(bbox_bundled, msg="label font bundel tidak terlihat")
        self.assertIsNotNone(bbox_fallback, msg="label fallback tidak terlihat")
        assert bbox_bundled is not None and bbox_fallback is not None
        width_bundled = bbox_bundled[2] - bbox_bundled[0] + 1
        width_fallback = bbox_fallback[2] - bbox_fallback[0] + 1

        font = fontmetrics.Font.load(ARCHIVO_FILE)
        predicted = font.width(LABELS[1], presets.CHART_LABEL_EM)
        self.assertAlmostEqual(
            width_bundled / predicted, 1.0, delta=0.20,
            msg=(
                f"lebar label {width_bundled} px vs prediksi fontmetrics "
                f"{predicted:.1f} px; Fontsize/font bundel tidak sesuai"
            ),
        )
        diff = sum(1 for a, b in zip(bundled, fallback) if a != b)
        differs = abs(width_bundled - width_fallback) >= 2 or diff >= 1000
        if not differs:
            self.skipTest(
                "font sistem kebetulan identik dengan Archivo Black "
                f"(lebar {width_bundled} vs {width_fallback}); kontrol tidak "
                "bisa membedakan, bukan bukti lulus."
            )


# ---------------------------------------------------------------------------
# (j) Caption tetap di lapisan atas kartu
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class ChartCaptionLayerTest(unittest.TestCase):
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

        # Kartu di bawah, nilai tengah = minimum sehingga garis di sekitar
        # caption (x 400..680) berada jauh di bawah region caption.
        overlay = _chart_overlay(
            rect={"x": 140, "y": 1250, "w": 800, "h": 520},
            values=(80.0, 40.0, 10.0, 55.0, 10.0),
        )
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
        index = round(1.0 * FPS)
        region = (400, 1340, 680, 1460)
        without = _yellow_count(_frame_rgb(self.out_without, index), region)
        combined = _yellow_count(_frame_rgb(self.out_with, index), region)
        self.assertGreater(without, 100, msg="caption kuning tidak terlihat")
        self.assertGreaterEqual(
            combined, int(without * 0.9),
            msg=(
                f"caption tertutup kartu: piksel kuning {combined} vs {without}; "
                f"caption harus jadi filter terakhir"
            ),
        )


if __name__ == "__main__":
    unittest.main()
