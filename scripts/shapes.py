"""Bentuk vektor ASS (`\\p1`), warna, event, dan wipe `\\clip` (tier-2).

Lapis bentuk untuk preset efek Langkah 5b. Modul ini hanya membangun string —
tidak merender, tidak membaca berkas, tidak menulis dokumen. Semua koordinat
berada di ruang PlayRes (bawaan 1080x1920) dan boleh berupa float; path
dibulatkan ke 2 desimal.

Empat keputusan yang dibuktikan tes oracle libass
(`tests/test_shapes_libass_oracle.py`), bukan ditebak:

1. **Aturan isi nonzero.** Dua `rect` yang tumpang tindih dan berorientasi
   SAMA terisi penuh sebagai gabungan (terukur 170.000 px pada dua persegi
   300x300 yang beririsan 100x100). Kontur kedua yang dibalik arah membuat
   irisan berlubang (160.000 px) — itu perilaku winding nonzero, bukan
   even-odd. Karena itu SEMUA kontur di modul ini dibuat dengan tanda luas
   shoelace yang sama (positif): tumpang tindih = gabungan, bukan lubang.
2. **Koordinat desimal diterima** oleh parser path libass dan dipakai secara
   subpiksel: `x=100` menutupi penuh kolom 100, `x=100.5` menutupi setengah
   (terukur 226 vs 127 pada kanal hijau).
3. **`\\t(\\clip)` dianimasikan** libass per frame: klip yang tumbuh dari
   lebar 0 ke 800 px menghasilkan lebar 211 px pada frame ke-4 (t=0,133 s),
   425 px pada frame ke-8, dan 800 px pada frame ke-15 — persis interpolasi
   linear `\\t(0,500,...)`. `accel=2` memperlambat awal (55 px pada frame 4),
   jadi parameter itu benar-benar dipakai.
4. **`\\clip` membulatkan koordinat ke integer.** Nilai 300,1/300,5/300,9
   menghasilkan tepi piksel yang sama, jadi `wipe_tags` menulis koordinat
   klip dengan 2 desimal (jujur terhadap argumen) tanpa mengharapkan
   ketelitian subpiksel dari klip.

Tanpa dependensi (D-004): hanya `math`/`re` dan penulis waktu tier-1.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Sequence

from . import captions as _tier1

__all__ = [
    "alpha",
    "ass_document",
    "check_mark",
    "circle",
    "colour",
    "line",
    "polyline",
    "rect",
    "rounded_rect",
    "shape_event",
    "wipe_tags",
]

# Konstanta bezier untuk seperempat lingkaran: 4/3 * tan(pi/8).
KAPPA = 0.5522847498

# Panjang sisi kotak centang yang dipakai sebelum diskalakan ke `size`.
# Titik-titik ini hanya bentuk; skala akhir dihitung supaya tinta (termasuk
# ketebalan) tepat muat di kotak `size` x `size`.
_CHECK_POINTS = ((-0.78, -0.12), (-0.18, 0.55), (0.78, -0.62))

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PATH_RE = re.compile(r"^[mlb0-9.\- ]+$")


# ---------------------------------------------------------------------------
# Validasi + format angka
# ---------------------------------------------------------------------------

def _finite(name: str, value: Any) -> float:
    """Konversi ke float dan tolak NaN/inf dengan pesan yang menyebut nama."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} harus angka berhingga, dapat {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} harus berhingga (bukan NaN/inf), dapat {value!r}")
    return number


def _positive(name: str, value: Any) -> float:
    number = _finite(name, value)
    if not number > 0.0:
        raise ValueError(f"{name} harus > 0, dapat {value!r}")
    return number


def _non_negative(name: str, value: Any) -> float:
    number = _finite(name, value)
    if number < 0.0:
        raise ValueError(f"{name} harus >= 0, dapat {value!r}")
    return number


def _pair(name: str, value: Any) -> tuple[float, float]:
    """Pasangan (x, y) berhingga; pesan menyebut `name`."""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} harus pasangan (x, y), dapat {value!r}")
    try:
        items = list(value)
    except TypeError:
        raise ValueError(f"{name} harus pasangan (x, y), dapat {value!r}") from None
    if len(items) != 2:
        raise ValueError(f"{name} harus berisi tepat 2 angka, dapat {value!r}")
    return _finite(f"{name}[0]", items[0]), _finite(f"{name}[1]", items[1])


def _fmt(value: float) -> str:
    """Format koordinat 2 desimal; `-0.00` dinormalkan menjadi `0.00`."""
    rounded = round(float(value), 2)
    if rounded == 0.0:
        rounded = 0.0
    return f"{rounded:.2f}"


def _text_field(name: str, value: Any) -> str:
    """String aman untuk field ASS: tanpa kurawal, newline, atau kontrol."""
    if not isinstance(value, str):
        raise ValueError(f"{name} harus string, dapat {value!r}")
    for char in value:
        code = ord(char)
        if char in "{}" or code < 0x20 or code == 0x7F:
            raise ValueError(
                f"{name} tidak boleh memuat kurawal/newline/karakter kontrol "
                f"({char!r}); dapat {value!r}"
            )
    return value


def _style_name(name: Any, label: str = "style") -> str:
    """Nama style tidak boleh menggeser field Dialogue lewat koma/baris baru."""
    text = _text_field(label, name)
    if "," in text:
        raise ValueError(f"{label} tidak boleh memuat koma; dapat {name!r}")
    if not text:
        raise ValueError(f"{label} tidak boleh kosong")
    return text


# ---------------------------------------------------------------------------
# Kontur + path
# ---------------------------------------------------------------------------

def _contour(points: Sequence[tuple[float, float]]) -> str:
    """Kontur poligon tertutup: `m` lalu `l` untuk tiap titik berikutnya."""
    parts = [f"m {_fmt(points[0][0])} {_fmt(points[0][1])}"]
    for x, y in points[1:]:
        parts.append(f"l {_fmt(x)} {_fmt(y)}")
    return " ".join(parts)


def _area_sign(points: Sequence[tuple[float, float]]) -> float:
    """Tanda luas shoelace; dipakai untuk menyeragamkan orientasi kontur."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        total += x0 * y1 - x1 * y0
    return total


def _bezier_contour(
    start: tuple[float, float],
    segments: Sequence[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]],
) -> str:
    """Kontur bezier: `m start` lalu `b c1 c2 end` per segmen."""
    parts = [f"m {_fmt(start[0])} {_fmt(start[1])}"]
    for c1, c2, end in segments:
        parts.append(
            f"b {_fmt(c1[0])} {_fmt(c1[1])} "
            f"{_fmt(c2[0])} {_fmt(c2[1])} {_fmt(end[0])} {_fmt(end[1])}"
        )
    return " ".join(parts)


def _points(name: str, points: Any) -> list[tuple[float, float]]:
    if isinstance(points, (str, bytes)):
        raise ValueError(f"{name} harus daftar titik (x, y), dapat {points!r}")
    try:
        raw = list(points)
    except TypeError:
        raise ValueError(f"{name} harus daftar titik (x, y), dapat {points!r}") from None
    out: list[tuple[float, float]] = []
    for index, point in enumerate(raw):
        if isinstance(point, (str, bytes)):
            raise ValueError(f"{name}[{index}] harus pasangan (x, y), dapat {point!r}")
        try:
            x, y = point
        except (TypeError, ValueError):
            raise ValueError(
                f"{name}[{index}] harus pasangan (x, y), dapat {point!r}"
            ) from None
        out.append((_finite(f"{name}[{index}][0]", x), _finite(f"{name}[{index}][1]", y)))
    return out


def rect(x: float, y: float, w: float, h: float) -> str:
    """Persegi `w` x `h` di (x, y), tertutup, orientasi positif."""
    x = _finite("x", x)
    y = _finite("y", y)
    w = _positive("w", w)
    h = _positive("h", h)
    return _contour(
        [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    )


def rounded_rect(x: float, y: float, w: float, h: float, r: float) -> str:
    """Persegi bersudut bulat; `r` dijepit ke `min(w, h)/2`.

    Sudut memakai bezier kubik dengan `KAPPA` (0,5522847498). `r=0` identik
    dengan `rect`.
    """
    x = _finite("x", x)
    y = _finite("y", y)
    w = _positive("w", w)
    h = _positive("h", h)
    r = _non_negative("r", r)
    r = min(r, min(w, h) / 2.0)
    if r == 0.0:
        return rect(x, y, w, h)

    k = r * KAPPA
    start = (x + r, y)
    segments = [
        ((x + w - r + k, y), (x + w, y + r - k), (x + w, y + r)),
        ((x + w, y + h - r + k), (x + w - r + k, y + h), (x + w - r, y + h)),
        ((x + r - k, y + h), (x, y + h - r + k), (x, y + h - r)),
        ((x, y + r - k), (x + r - k, y), (x + r, y)),
    ]
    # Titik `l` di antara sudut: tepi atas, kanan, bawah, kiri.
    return (
        f"m {_fmt(start[0])} {_fmt(start[1])} "
        f"l {_fmt(x + w - r)} {_fmt(y)} "
        f"b {_fmt(segments[0][0][0])} {_fmt(segments[0][0][1])} "
        f"{_fmt(segments[0][1][0])} {_fmt(segments[0][1][1])} "
        f"{_fmt(segments[0][2][0])} {_fmt(segments[0][2][1])} "
        f"l {_fmt(x + w)} {_fmt(y + h - r)} "
        f"b {_fmt(segments[1][0][0])} {_fmt(segments[1][0][1])} "
        f"{_fmt(segments[1][1][0])} {_fmt(segments[1][1][1])} "
        f"{_fmt(segments[1][2][0])} {_fmt(segments[1][2][1])} "
        f"l {_fmt(x + r)} {_fmt(y + h)} "
        f"b {_fmt(segments[2][0][0])} {_fmt(segments[2][0][1])} "
        f"{_fmt(segments[2][1][0])} {_fmt(segments[2][1][1])} "
        f"{_fmt(segments[2][2][0])} {_fmt(segments[2][2][1])} "
        f"l {_fmt(x)} {_fmt(y + r)} "
        f"b {_fmt(segments[3][0][0])} {_fmt(segments[3][0][1])} "
        f"{_fmt(segments[3][1][0])} {_fmt(segments[3][1][1])} "
        f"{_fmt(segments[3][2][0])} {_fmt(segments[3][2][1])}"
    )


def circle(cx: float, cy: float, r: float) -> str:
    """Lingkaran dari 4 bezier; orientasi positif (searah `rect`)."""
    cx = _finite("cx", cx)
    cy = _finite("cy", cy)
    r = _positive("r", r)
    k = r * KAPPA
    start = (cx + r, cy)
    segments = []
    for i in range(4):
        a = i * (math.pi / 2.0)
        b = a + math.pi / 2.0
        p0 = (cx + r * math.cos(a), cy + r * math.sin(a))
        p1 = (cx + r * math.cos(b), cy + r * math.sin(b))
        c1 = (p0[0] - k * math.sin(a), p0[1] + k * math.cos(a))
        c2 = (p1[0] + k * math.sin(b), p1[1] - k * math.cos(b))
        segments.append((c1, c2, p1))
    return _bezier_contour(start, segments)


def line(x1: float, y1: float, x2: float, y2: float, thickness: float) -> str:
    """Persegi panjang miring berujung butt dari (x1, y1) ke (x2, y2)."""
    x1 = _finite("x1", x1)
    y1 = _finite("y1", y1)
    x2 = _finite("x2", x2)
    y2 = _finite("y2", y2)
    thickness = _positive("thickness", thickness)
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0.0:
        raise ValueError(
            f"line: (x1,y1) dan (x2,y2) harus berbeda, dapat "
            f"({x1!r},{y1!r}) dan ({x2!r},{y2!r})"
        )
    nx = -dy / length * thickness / 2.0
    ny = dx / length * thickness / 2.0
    corners = [
        (x1 + nx, y1 + ny),
        (x2 + nx, y2 + ny),
        (x2 - nx, y2 - ny),
        (x1 - nx, y1 - ny),
    ]
    # Arah normal membalik tanda luas saat arah ruas berubah; balik urutan
    # supaya semua kontur di satu path punya orientasi yang sama.
    if _area_sign(corners + [corners[0]]) < 0.0:
        corners.reverse()
    return _contour(corners + [corners[0]])


def polyline(points: Iterable[tuple[float, float]], thickness: float) -> str:
    """Ruas `line` per segmen + lingkaran sambungan di tiap titik interior.

    Ujung tetap butt (sesuai `line`); lingkaran berjari-jari `thickness/2` di
    titik sambungan menutup takik luar sehingga polyline tidak bercelah.
    """
    pts = _points("points", points)
    if len(pts) < 2:
        raise ValueError(f"polyline: points harus berisi >= 2 titik, dapat {len(pts)}")
    thickness = _positive("thickness", thickness)
    for i in range(len(pts) - 1):
        if pts[i] == pts[i + 1]:
            raise ValueError(
                f"polyline: points[{i}] dan points[{i + 1}] berimpit; "
                f"setiap ruas harus punya panjang > 0"
            )
    contours = [
        line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], thickness)
        for i in range(len(pts) - 1)
    ]
    for cx, cy in pts[1:-1]:
        contours.append(circle(cx, cy, thickness / 2.0))
    return " ".join(contours)


def check_mark(cx: float, cy: float, size: float, thickness: float) -> str:
    """Centang tiga titik yang tintanya muat di kotak `size` x `size`."""
    cx = _finite("cx", cx)
    cy = _finite("cy", cy)
    size = _positive("size", size)
    thickness = _positive("thickness", thickness)
    if thickness >= size:
        raise ValueError(
            f"thickness harus < size supaya centang muat di kotak, "
            f"dapat thickness={thickness!r}, size={size!r}"
        )
    half = size / 2.0 - thickness / 2.0
    raw = _CHECK_POINTS
    extent = max(max(abs(x), abs(y)) for x, y in raw)
    scale = half / extent
    pts = [(cx + x * scale, cy + y * scale) for x, y in raw]
    return polyline(pts, thickness)


# ---------------------------------------------------------------------------
# Warna
# ---------------------------------------------------------------------------

def colour(hex_rgb: str) -> str:
    """`#RRGGBB` -> fragmen ASS `&HBBGGRR&` (ASS menyimpan BGR)."""
    if not isinstance(hex_rgb, str) or not _HEX_RE.match(hex_rgb):
        raise ValueError(f"colour: hex_rgb harus '#RRGGBB', dapat {hex_rgb!r}")
    rr = int(hex_rgb[1:3], 16)
    gg = int(hex_rgb[3:5], 16)
    bb = int(hex_rgb[5:7], 16)
    return f"&H{bb:02X}{gg:02X}{rr:02X}&"


def alpha(opacity: float) -> str:
    """Opasitas 0..1 -> fragmen alfa ASS `&HAA&` (0 = pekat, 255 = hilang)."""
    if isinstance(opacity, bool) or not isinstance(opacity, (int, float)):
        raise ValueError(f"opacity harus angka 0..1, dapat {opacity!r}")
    value = _finite("opacity", opacity)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"opacity harus di dalam [0, 1], dapat {opacity!r}")
    byte = int(round((1.0 - value) * 255.0))
    byte = min(255, max(0, byte))
    return f"&H{byte:02X}&"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

def _path_text(path: Any) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"path harus string path ASS yang tidak kosong, dapat {path!r}")
    if not _PATH_RE.match(path):
        raise ValueError(
            f"path hanya boleh memuat perintah m/l/b, angka, titik, minus, spasi; "
            f"dapat {path!r}"
        )
    return path.strip()


def shape_event(
    start: float,
    end: float,
    path: str,
    *,
    layer: int = 0,
    fill: str = "#FFFFFF",
    opacity: float = 1.0,
    pos: tuple[float, float] = (0.0, 0.0),
    extra_tags: str = "",
    style: str = "Shape",
) -> str:
    """Satu baris `Dialogue:` berisi gambar vektor `\\p1`.

    `pos` adalah titik jangkar `\\an7` (kiri-atas). Path ditulis relatif
    terhadap `pos`; biarkan `(0, 0)` bila koordinat path sudah absolut di
    ruang PlayRes. `extra_tags` hanya tag ASS (mis. hasil `wipe_tags`).
    """
    start = _finite("start", start)
    end = _finite("end", end)
    if end <= start:
        raise ValueError(f"end harus > start, dapat start={start!r}, end={end!r}")
    if isinstance(layer, bool) or not isinstance(layer, int) or layer < 0:
        raise ValueError(f"layer harus bilangan bulat >= 0, dapat {layer!r}")
    style = _style_name(style)
    pos_x, pos_y = _pair("pos", pos)
    extra = _text_field("extra_tags", extra_tags)
    path = _path_text(path)

    text = (
        f"{{\\an7\\pos({_fmt(pos_x)},{_fmt(pos_y)})\\bord0\\shad0"
        f"\\1c{colour(fill)}\\1a{alpha(opacity)}{extra}\\p1}}"
        f"{path}{{\\p0}}"
    )
    return (
        f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},,"
        f"0,0,0,,{text}"
    )


def _ass_time(t: float) -> str:
    """Waktu ASS persis penulis kinetic/tier-1 (`captions._ass_time`).

    Aturan: `f"{detik:05.2f}"` pada `t % 60`; 1,235 -> `0:00:01.24`,
    1,2349 -> `0:00:01.23`, dan 59,999 -> `0:00:60.00` (penulis tidak
    memindahkan kelebihan ke menit). Menyalin aturan ini, bukan membuat
    pembulatan sendiri, menjaga kedua penulis ASS tetap sinkron.
    """
    return _tier1._ass_time(t)


# ---------------------------------------------------------------------------
# Wipe
# ---------------------------------------------------------------------------

_DIRECTIONS = ("left", "right", "up", "down")


def _ms(t: float) -> int:
    """Detik -> milidetik bulat (dipakai `\\t`)."""
    return int(round(t * 1000.0))


def wipe_tags(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    t_start: float,
    t_end: float,
    *,
    direction: str = "right",
    accel: float = 1.0,
) -> str:
    """Tag `\\clip` yang membuka area dari satu tepi selama [t_start, t_end].

    `direction` = arah gerak tepi bukaan: `right` dari tepi kiri ke kanan,
    `left` dari kanan ke kiri, `down` dari atas ke bawah, `up` dari bawah ke
    atas. Waktu relatif terhadap awal event (detik) dan ditulis ke `\\t`
    sebagai milidetik bulat. `accel` diteruskan ke `\\t` (eksponen easing).
    Koordinat klip berada di ruang PlayRes absolut; pakai `pos=(0, 0)` di
    `shape_event` bila path juga absolut.
    """
    x0 = _finite("x0", x0)
    y0 = _finite("y0", y0)
    x1 = _finite("x1", x1)
    y1 = _finite("y1", y1)
    if not x1 > x0:
        raise ValueError(f"x1 harus > x0, dapat x0={x0!r}, x1={x1!r}")
    if not y1 > y0:
        raise ValueError(f"y1 harus > y0, dapat y0={y0!r}, y1={y1!r}")
    t_start = _finite("t_start", t_start)
    t_end = _finite("t_end", t_end)
    if t_start < 0.0:
        raise ValueError(f"t_start harus >= 0, dapat {t_start!r}")
    if not t_end > t_start:
        raise ValueError(f"t_end harus > t_start, dapat {t_start!r}..{t_end!r}")
    accel = _positive("accel", accel)
    if direction not in _DIRECTIONS:
        raise ValueError(
            f"direction harus salah satu {_DIRECTIONS}, dapat {direction!r}"
        )
    ms0 = _ms(t_start)
    ms1 = _ms(t_end)
    if ms1 <= ms0:
        raise ValueError(
            f"t_end harus > t_start setelah pembulatan milidetik, "
            f"dapat {ms0}..{ms1} ms"
        )

    if direction == "right":
        initial = (x0, y0, x0, y1)
    elif direction == "left":
        initial = (x1, y0, x1, y1)
    elif direction == "down":
        initial = (x0, y0, x1, y0)
    else:  # up
        initial = (x0, y1, x1, y1)
    final = (x0, y0, x1, y1)

    clip = lambda box: "\\clip(" + ",".join(_fmt(v) for v in box) + ")"
    return (
        f"{clip(initial)}\\t({ms0},{ms1},{accel:g},{clip(final)})"
    )


# ---------------------------------------------------------------------------
# Dokumen ASS
# ---------------------------------------------------------------------------

_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding"
)

_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text"
)


def ass_document(
    events: Iterable[str],
    *,
    play_res: tuple[int, int] = (1080, 1920),
    style_name: str = "Shape",
) -> str:
    """Dokumen ASS mandiri (header + satu style + events); tidak menulis berkas.

    Style `Shape` sengaja tanpa outline/shadow (`BorderStyle 1`, `Outline 0`,
    `Shadow 0`) karena bentuk sudah digambar sebagai path, bukan teks. Font
    `Arial` hanya pengisi: tidak ada glyph yang dipakai.
    """
    if isinstance(events, (str, bytes)):
        raise ValueError(
            f"events harus daftar baris Dialogue, bukan string tunggal: {events!r}"
        )
    try:
        lines = list(events)
    except TypeError:
        raise ValueError(f"events harus daftar baris Dialogue, dapat {events!r}") from None
    for index, line in enumerate(lines):
        if not isinstance(line, str) or "\n" in line or "\r" in line:
            raise ValueError(
                f"events[{index}] harus satu baris string tanpa newline, dapat {line!r}"
            )
    style_name = _style_name(style_name, "style_name")

    try:
        width, height = play_res
    except (TypeError, ValueError):
        raise ValueError(f"play_res harus pasangan (lebar, tinggi), dapat {play_res!r}") from None
    if isinstance(play_res, (str, bytes)):
        raise ValueError(f"play_res harus pasangan angka, dapat {play_res!r}")
    width = int(width) if isinstance(width, int) and not isinstance(width, bool) else 0
    height = int(height) if isinstance(height, int) and not isinstance(height, bool) else 0
    if width <= 0 or height <= 0:
        raise ValueError(f"play_res harus dua bilangan bulat > 0, dapat {play_res!r}")

    header = (
        "[Script Info]\n"
        "; Dokumen bentuk vektor ASS (scripts/shapes.py).\n"
        "; Path sudah dalam koordinat PlayRes; event memakai \\an7\\pos.\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        f"{_STYLE_FORMAT}\n"
        f"Style: {style_name},Arial,20,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n"
        "\n"
        "[Events]\n"
        f"{_EVENT_FORMAT}\n"
    )
    return header + "".join(f"{line}\n" for line in lines)
