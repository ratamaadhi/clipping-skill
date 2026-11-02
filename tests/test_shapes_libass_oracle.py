"""Tes oracle libass untuk `scripts.shapes`: path, aturan isi, layer, wipe.

Kenapa perlu render sungguhan: tes murni hanya memeriksa string path. Hanya
rasterizer libass yang membuktikan (a) aturan isi yang dipakai, (b) koordinat
desimal pada path tidak dibulatkan ke integer, (c) `\\t(\\clip)` benar-benar
dianimasikan per frame. Ketiganya diukur di sini pada kanvas hitam
1080x1920 @30, pola render yang sama dengan
`tests/test_kinetic_libass_oracle.py`.

Pengukuran memakai Python murni (tanpa numpy/cv2): pindai byte rgb24 pada
daerah yang diketahui. Ambang "tinta" = salah satu kanal > 20, cukup rendah
untuk menghitung piksel anti-alias di tepi tetapi tetap memisahkan dari hitam.

Tes SKIP dengan pesan jujur bila tidak ada ffmpeg berlibass; lihat
`tests/ffmpeg_libass.py`.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import shapes

from tests.ffmpeg_libass import find_ffmpeg_with_libass

PLAY_W = 1080
PLAY_H = 1920
FPS = 30
FRAME = 30  # t = 1,0 s; semua event 0..3 s sudah stabil

INK_MIN = 20

_FFMPEG = find_ffmpeg_with_libass()

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` (Homebrew Apple Silicon: "
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg; Intel: "
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg) atau set env CLIP_FFMPEG ke path "
    "ffmpeg berlibass. Formula `ffmpeg` Homebrew biasa dibangun tanpa libass."
)


# ---------------------------------------------------------------------------
# Render + ukur (Python murni)
# ---------------------------------------------------------------------------

def _render_frame(ass_text: str, frame: int) -> bytes:
    """Render satu frame ASS di atas hitam 1080x1920; balikkan rgb24."""
    assert _FFMPEG is not None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ass_file = tmp_path / "shapes.ass"
        ass_file.write_text(ass_text, encoding="utf-8")
        out_file = tmp_path / "frame.raw"
        chain = (
            f"subtitles={ass_file.name},"
            f"trim=start_frame={frame}:end_frame={frame + 1},"
            f"setpts=PTS-STARTPTS"
        )
        cmd = [
            _FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c=black:s={PLAY_W}x{PLAY_H}:d=4:r={FPS}",
            "-vf", chain,
            "-frames:v", "1",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            str(out_file),
        ]
        proc = subprocess.run(
            cmd, cwd=tmp_path, capture_output=True, timeout=120, check=False
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"ffmpeg gagal ({proc.returncode}): {proc.stderr.decode()[:800]}"
            )
        data = out_file.read_bytes()
        expected = PLAY_W * PLAY_H * 3
        if len(data) != expected:
            raise AssertionError(f"ukuran frame {len(data)} != {expected} byte")
        return data


def _render_event(event: dict, frame: int = FRAME, ass_text: str | None = None) -> bytes:
    """Bangun dokumen ASS dari satu event (atau pakai `ass_text`) lalu render."""
    if ass_text is None:
        ass_text = shapes.ass_document([shapes.shape_event(**event)])
    return _render_frame(ass_text, frame)


def _scan(
    frame: bytes, region: tuple[int, int, int, int], sample_step: int = 1
) -> dict:
    """Pindai daerah (x0, y0, x1, y1) eksklusif; ukur bbox/luas/rata-rata warna.

    Hanya piksel dengan salah satu kanal > INK_MIN yang dihitung. Rata-rata
    warna dihitung dari piksel yang sama; untuk bidang datar besar nilainya
    mendekati warna isi (tepi anti-alias menariknya sedikit ke arah hitam).
    """
    x0, y0, x1, y1 = region
    stride = PLAY_W * 3
    min_x = min_y = 10**9
    max_x = max_y = -1
    count = 0
    sum_r = sum_g = sum_b = 0
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = frame[base : base + (x1 - x0) * 3]
        for x in range(0, x1 - x0, sample_step):
            i = x * 3
            r = row[i]
            g = row[i + 1]
            b = row[i + 2]
            if r <= INK_MIN and g <= INK_MIN and b <= INK_MIN:
                continue
            count += 1
            gx = x0 + x
            if gx < min_x:
                min_x = gx
            if gx > max_x:
                max_x = gx
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
            sum_r += r
            sum_g += g
            sum_b += b
    if count == 0:
        return {"bbox": None, "count": 0, "mean": None}
    return {
        "bbox": (min_x, min_y, max_x, max_y),
        "count": count,
        "mean": (sum_r / count, sum_g / count, sum_b / count),
    }


def _px(frame: bytes, x: int, y: int) -> tuple[int, int, int]:
    i = (y * PLAY_W + x) * 3
    return frame[i], frame[i + 1], frame[i + 2]


def _dominant(frame: bytes, region: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Warna RGB paling sering di daerah — dipakai untuk uji warna interior."""
    x0, y0, x1, y1 = region
    stride = PLAY_W * 3
    counts: dict[tuple[int, int, int], int] = {}
    for y in range(y0, y1):
        base = y * stride + x0 * 3
        row = frame[base : base + (x1 - x0) * 3]
        for x in range(x1 - x0):
            i = x * 3
            r, g, b = row[i], row[i + 1], row[i + 2]
            if r <= INK_MIN and g <= INK_MIN and b <= INK_MIN:
                continue
            key = (r, g, b)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return 0, 0, 0
    return max(counts, key=counts.get)


def _path_points(path: str) -> list[tuple[float, float]]:
    tokens = path.split()
    pts: list[tuple[float, float]] = []
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        i += 1
        n = 2 if cmd in ("m", "l") else 6
        for _ in range(n // 2):
            pts.append((float(tokens[i]), float(tokens[i + 1])))
            i += 2
    return pts


def _expected_pixel_bbox(path: str) -> tuple[int, int, int, int]:
    """Bbox piksel teoretis dari SEMUA koordinat path.

    Untuk kontur bezier, titik kontrol selalu berada di dalam bbox anchor
    (lingkaran/rounded rect), jadi bbox semua koordinat = bbox tinta.
    """
    xs = [p[0] for p in _path_points(path)]
    ys = [p[1] for p in _path_points(path)]
    return (
        math.floor(min(xs)),
        math.floor(min(ys)),
        math.ceil(max(xs)) - 1,
        math.ceil(max(ys)) - 1,
    )


def _expanded(region: tuple[int, int, int, int], pad: int = 12) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = region
    return (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(PLAY_W, x1 + 1 + pad),
        min(PLAY_H, y1 + 1 + pad),
    )


def _assert_bbox(
    case: unittest.TestCase,
    got: tuple[int, int, int, int] | None,
    expected: tuple[int, int, int, int],
    label: str,
    delta: float = 1.5,
) -> None:
    case.assertIsNotNone(got, msg=f"{label}: tidak ada piksel tinta")
    for index, (name, g, e) in enumerate(zip(("x0", "y0", "x1", "y1"), got, expected)):
        case.assertAlmostEqual(
            g, e, delta=delta,
            msg=f"{label}: bbox {name} terukur {g} vs teoretis {e} (bbox {got})",
        )


# ---------------------------------------------------------------------------
# Spesifikasi bentuk yang diuji
# ---------------------------------------------------------------------------

FILL = "#FF00FF"


def _shape_specs() -> dict[str, dict]:
    """Path dan angka teoretis; dibangun saat kelas tes berjalan, bukan impor."""
    return {
        "rect": {
            "path": shapes.rect(200, 300, 400, 250),
            "area": 400 * 250,
            "tol": 0.01,
        },
        "rounded_rect": {
            "path": shapes.rounded_rect(200, 700, 400, 250, 60),
            "area": 400 * 250 - (4 - math.pi) * 60**2,
            "tol": 0.02,
        },
        "circle": {
            "path": shapes.circle(500, 1200, 150),
            "area": math.pi * 150**2,
            "tol": 0.03,
        },
        "line_horizontal": {
            "path": shapes.line(100, 1450, 700, 1450, 40),
            "area": 600 * 40,
            "tol": 0.02,
        },
        "line_slanted": {
            "path": shapes.line(100, 1600, 500, 1800, 30),
            # Luas piksel tidak di-gate: keliling tipis membuat pita
            # anti-alias mendominasi galat relatif. Kebenaran luas garis
            # diuji murni lewat shoelace di tests/test_shapes.py.
            "area": None,
            "tol": None,
        },
        "polyline": {
            "path": shapes.polyline([(120, 1050), (420, 1050), (720, 1250)], 36),
            "area": None,
            "tol": None,
        },
        "check_mark": {
            "path": shapes.check_mark(800, 1600, 180, 30),
            "area": None,
            "tol": None,
        },
    }

# Warna yang diminta; interior harus mendekati ini (libass lewat YUV).
FILL_RGB = (255, 0, 255)


# ---------------------------------------------------------------------------
# (a) Geometri tiap bentuk
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class ShapeGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.specs = _shape_specs()
        cls.measured = {}
        for name, spec in cls.specs.items():
            expected = _expected_pixel_bbox(spec["path"])
            ass = shapes.ass_document(
                [shapes.shape_event(0.0, 3.0, spec["path"], fill=FILL)]
            )
            frame = _render_frame(ass, FRAME)
            region = _expanded(expected)
            cls.measured[name] = {
                "scan": _scan(frame, region),
                "dominant": _dominant(frame, region),
                "expected": expected,
                "frame": frame,
                "region": region,
            }

    def test_bbox_matches_theoretical_for_every_shape(self) -> None:
        for name in self.specs:
            with self.subTest(name=name):
                data = self.measured[name]
                _assert_bbox(
                    self, data["scan"]["bbox"], data["expected"], name
                )

    def test_pixel_area_matches_theoretical_where_exact(self) -> None:
        for name, spec in self.specs.items():
            if spec["area"] is None:
                continue
            with self.subTest(name=name):
                got = self.measured[name]["scan"]["count"]
                expected = spec["area"]
                rel = abs(got - expected) / expected
                self.assertLessEqual(
                    rel, spec["tol"],
                    msg=(
                        f"{name}: luas piksel {got} vs teoretis {expected:.1f} "
                        f"= {rel:.4%} > {spec['tol']:.1%}"
                    ),
                )

    def test_interior_colour_matches_request(self) -> None:
        for name in self.specs:
            with self.subTest(name=name):
                got = self.measured[name]["dominant"]
                for channel, (value, want) in enumerate(zip(got, FILL_RGB)):
                    self.assertAlmostEqual(
                        value, want, delta=3.0,
                        msg=f"{name}: kanal {channel} warna dominan {value} vs {want}",
                    )

    def test_rounded_rect_corner_pixels_stay_background(self) -> None:
        frame = self.measured["rounded_rect"]["frame"]
        for point in ((200, 700), (201, 701), (599, 949)):
            with self.subTest(point=point):
                self.assertEqual(_px(frame, *point), (0, 0, 0))

    def test_opacity_half_yields_half_intensity(self) -> None:
        path = shapes.rect(350, 300, 300, 300)
        ass = shapes.ass_document(
            [shapes.shape_event(0.0, 3.0, path, fill="#FF0000", opacity=0.5)]
        )
        frame = _render_frame(ass, FRAME)
        r, g, b = _px(frame, 500, 450)
        self.assertAlmostEqual(r, 127.5, delta=6.0, msg=f"piksel ({r},{g},{b})")
        self.assertLessEqual(g, 6)
        self.assertLessEqual(b, 6)

    def test_decimal_path_coordinates_are_subpixel(self) -> None:
        """x=100,5 harus menutupi setengah kolom 100; x=100 menutupi penuh.

        Kalau libass membulatkan/menolak koordinat desimal, kedua render akan
        sama dan selisih di bawah gagal.
        """
        integer = shapes.ass_document(
            [shapes.shape_event(0.0, 3.0, shapes.rect(100, 200, 100, 100), fill=FILL)]
        )
        half = shapes.ass_document(
            [shapes.shape_event(0.0, 3.0, shapes.rect(100.5, 200, 100, 100), fill=FILL)]
        )
        a = sum(_px(_render_frame(integer, FRAME), 100, 250))
        b = sum(_px(_render_frame(half, FRAME), 100, 250))
        self.assertGreater(
            a - b, 100,
            msg=f"kolom tepi integer {a} vs setengah {b}: desimal tidak subpiksel",
        )


# ---------------------------------------------------------------------------
# (b) Aturan isi + sambungan polyline
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class FillRuleTest(unittest.TestCase):
    def _render_path(self, path: str) -> bytes:
        return _render_event(
            {
                "start": 0.0,
                "end": 3.0,
                "path": path,
                "fill": FILL,
            }
        )

    def test_overlapping_contours_with_same_orientation_form_union(self) -> None:
        left = shapes.rect(100, 100, 400, 400)
        right = shapes.rect(300, 300, 400, 400)
        frame = self._render_path(left + " " + right)
        self.assertNotEqual(_px(frame, 400, 400), (0, 0, 0))
        self.assertNotEqual(_px(frame, 200, 200), (0, 0, 0))
        self.assertNotEqual(_px(frame, 600, 600), (0, 0, 0))

    def test_reversed_contour_creates_a_hole_negative_control(self) -> None:
        """Kontrol negatif: orientasi berlawanan -> irisan berlubang.

        Ini membuktikan tes di atas peka: dengan aturan nonzero, winding +1
        dan -1 saling meniadakan sehingga irisan harus hitam.
        """
        left = shapes.rect(100, 100, 400, 400)
        reversed_right = "m 300 300 l 300 700 l 700 700 l 700 300 l 300 300"
        frame = self._render_path(left + " " + reversed_right)
        self.assertEqual(
            _px(frame, 400, 400), (0, 0, 0),
            msg="irisan seharusnya berlubang pada kontur berlawanan arah",
        )
        self.assertNotEqual(_px(frame, 200, 200), (0, 0, 0))
        self.assertNotEqual(_px(frame, 600, 600), (0, 0, 0))

    def test_polyline_joint_is_filled(self) -> None:
        path = shapes.polyline([(300, 300), (600, 300), (600, 600)], 80)
        frame = self._render_path(path)
        self.assertNotEqual(
            _px(frame, 620, 280), (0, 0, 0),
            msg="piksel sudut luar sambungan kosong: lingkaran sambungan hilang",
        )

    def test_two_separate_lines_leave_the_joint_gap_control(self) -> None:
        """Kontrol: dua `line` tanpa lingkaran sambungan memang bercelah."""
        path = (
            shapes.line(300, 300, 600, 300, 80)
            + " "
            + shapes.line(600, 300, 600, 600, 80)
        )
        frame = self._render_path(path)
        self.assertEqual(
            _px(frame, 620, 280), (0, 0, 0),
            msg="kontrol negatif gagal: sudut luar seharusnya kosong",
        )


# ---------------------------------------------------------------------------
# (c) Layer
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class LayerOrderTest(unittest.TestCase):
    def test_higher_layer_is_drawn_on_top(self) -> None:
        events = [
            shapes.shape_event(
                0.0, 3.0, shapes.rect(100, 100, 400, 400), layer=0, fill="#FF0000"
            ),
            shapes.shape_event(
                0.0, 3.0, shapes.rect(200, 200, 300, 300), layer=1, fill="#00FF00"
            ),
        ]
        frame = _render_event({}, ass_text=shapes.ass_document(events))
        r, g, b = _px(frame, 250, 250)
        self.assertGreater(g, 200, msg=f"irisan harus hijau (layer 1), dapat {(r, g, b)}")
        self.assertLess(r, 60, msg=f"merah layer 0 menutupi layer 1: {(r, g, b)}")
        r0, g0, b0 = _px(frame, 150, 150)
        self.assertGreater(r0, 200, msg=f"area hanya layer 0 harus merah: {(r0, g0, b0)}")
        self.assertLess(g0, 60)


# ---------------------------------------------------------------------------
# (d) Wipe `\t(\clip)`
# ---------------------------------------------------------------------------

WIPE_RECT = (200, 300, 600, 250)  # x, y, w, h -> 200..800, 300..550
WIPE_BOUNDS = (200, 300, 800, 550)
WIPE_TIMES = (0.0, 0.15, 0.25, 0.35, 0.5, 0.6)
WIPE_FULL = 600

_WIPE_REGION = _expanded((200, 300, 799, 549), pad=8)


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class WipeTest(unittest.TestCase):
    def _widths(self, direction: str, accel: float = 1.0) -> list[int]:
        """Lebar (horizontal) atau tinggi (vertikal) area terisi per waktu."""
        path = shapes.rect(*WIPE_RECT)
        tag = shapes.wipe_tags(*WIPE_BOUNDS, 0.0, 0.5, direction=direction, accel=accel)
        ass = shapes.ass_document(
            [
                shapes.shape_event(
                    0.0, 3.0, path, fill=FILL, extra_tags=tag
                )
            ]
        )
        widths: list[int] = []
        for t in WIPE_TIMES:
            frame = _render_frame(ass, round(t * FPS))
            scan = _scan(frame, _WIPE_REGION)
            if scan["bbox"] is None:
                widths.append(0)
                continue
            x0, y0, x1, y1 = scan["bbox"]
            if direction in ("right", "left"):
                widths.append(x1 - x0 + 1)
            else:
                widths.append(y1 - y0 + 1)
        return widths

    def test_wipe_progress_per_direction(self) -> None:
        for direction in ("right", "left", "up", "down"):
            with self.subTest(direction=direction):
                widths = self._widths(direction)
                self.assertEqual(
                    widths[0], 0,
                    msg=f"{direction}: awal harus kosong, dapat {widths}",
                )
                self.assertTrue(
                    all(b >= a for a, b in zip(widths, widths[1:])),
                    msg=f"{direction}: lebar menurun: {widths}",
                )
                full = WIPE_FULL if direction in ("right", "left") else WIPE_RECT[3]
                for index in (1, 2, 3):
                    self.assertGreater(
                        widths[index], 0,
                        msg=f"{direction}: tidak ada kemajuan pada t={WIPE_TIMES[index]}: {widths}",
                    )
                    self.assertLess(
                        widths[index], full,
                        msg=f"{direction}: sudah penuh terlalu awal: {widths}",
                    )
                for index in (4, 5):
                    self.assertAlmostEqual(
                        widths[index], full, delta=2.0,
                        msg=f"{direction}: akhir t={WIPE_TIMES[index]} tidak penuh: {widths}",
                    )

    def test_accel_parameter_changes_progress(self) -> None:
        linear = self._widths("right", accel=1.0)
        eased = self._widths("right", accel=2.0)
        self.assertGreater(
            linear[1] - eased[1], 50,
            msg=(
                f"accel=2 harus lebih lambat di awal: linear {linear}, "
                f"accel {eased}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
