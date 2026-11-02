"""Preset efek referensi #06 ("phone mockup") sebagai modul terisolasi.

Preset `phone_frame` menampilkan perangkat ponsel DATAR (tanpa tilt 3D, tanpa
kaca/blur) di sisi kanan-atas (atau kiri) layar yang menampilkan judul kecil
dan 2–4 baris teks yang muncul berurutan dengan bullet beraksen.

Keterbatasan jujur:
* libass tidak dapat menskalakan grup teks+bentuk secara kaku dari pusat bersama,
  sehingga pop skala pada badan perangkat tidak dipakai; gerak masuk sepenuhnya
  memakai translasi kaku `\\move`.
* Translasi `\\move` di libass bersifat LINEAR (tidak mendukung kurva easing);
  alfa ease-out (`accel=0.5`) diterapkan pada transparansi selama 0.35 s masuk.

Modul ini berdiri sendiri agar tidak berbenturan dengan worker lain yang menyunting
`scripts/presets.py` secara paralel.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from . import presets
from . import shapes
from .lib import fontmetrics

__all__ = [
    "ACCENT_LAYER",
    "BODY_LAYER",
    "INTEGRATION",
    "NOTCH_LAYER",
    "PHONE_BASE_H",
    "PHONE_BODY_COLOUR",
    "PHONE_BODY_RADIUS",
    "PHONE_BULLET_GAP",
    "PHONE_BULLET_RADIUS",
    "PHONE_DEFAULT_ACCENT",
    "PHONE_DEFAULT_W",
    "PHONE_DEFAULT_X_LEFT",
    "PHONE_DEFAULT_X_RIGHT",
    "PHONE_DEFAULT_Y",
    "PHONE_ENTRY",
    "PHONE_ENTRY_ACCEL",
    "PHONE_ENTRY_OFFSET",
    "PHONE_EXIT",
    "PHONE_GAP_UNDERLINE_LINES",
    "PHONE_LINE_COLOUR",
    "PHONE_LINE_EM",
    "PHONE_LINE_FADE_IN",
    "PHONE_LINE_OFFSET_Y",
    "PHONE_LINE_ROW_H",
    "PHONE_LINE_STAGGER",
    "PHONE_MAX_DIALOGUES",
    "PHONE_MAX_LINES",
    "PHONE_MAX_LINE_CHARS",
    "PHONE_MAX_TITLE_CHARS",
    "PHONE_MIN_LINES",
    "PHONE_MIN_LINE_CHARS",
    "PHONE_MIN_TITLE_CHARS",
    "PHONE_NOTCH_COLOUR",
    "PHONE_NOTCH_H",
    "PHONE_NOTCH_RADIUS",
    "PHONE_NOTCH_TOP_MARGIN",
    "PHONE_NOTCH_W",
    "PHONE_PAD_X",
    "PHONE_SCREEN_COLOUR",
    "PHONE_SCREEN_INSET",
    "PHONE_SCREEN_PAD_BOTTOM",
    "PHONE_SCREEN_RADIUS",
    "PHONE_TITLE_COLOUR",
    "PHONE_TITLE_EM",
    "PHONE_TITLE_H",
    "PHONE_TITLE_PAD_TOP",
    "PHONE_UNDERLINE_GAP",
    "PHONE_UNDERLINE_H",
    "PHONE_UNDERLINE_RADIUS",
    "PHONE_UNDERLINE_W",
    "PLAY_RES",
    "SCREEN_LAYER",
    "TEXT_LAYER",
    "TYPE",
    "build",
    "document",
    "events",
    "style_lines",
]

# ---------------------------------------------------------------------------
# Konstanta tata letak & visual (bergaya chart_grow, satu tempat, komentar asal)
# ---------------------------------------------------------------------------

TYPE = "phone_frame"
PLAY_RES = (1080, 1920)

# Koordinat bawaan: slot kanan-atas kanvas 1080x1920 (x=640, w=380 -> margin kanan 60 px).
# Bila side="left", posisi dicerminkan ke margin kiri 60 px (x=60, w=380).
PHONE_DEFAULT_X_RIGHT = 640.0
PHONE_DEFAULT_X_LEFT = 60.0
PHONE_DEFAULT_Y = 250.0
PHONE_DEFAULT_W = 380.0

# Badan ponsel: rounded_rect hitam pekat, radius sudut 56 px.
PHONE_BODY_COLOUR = "#0B0C10"
PHONE_BODY_RADIUS = 56.0

# Layar gelap: inset 14 px dari badan, radius sudut 44 px.
PHONE_SCREEN_INSET = 14.0
PHONE_SCREEN_COLOUR = "#15171C"
PHONE_SCREEN_RADIUS = 44.0

# Notch pil: di tengah atas layar ponsel (80x18 px, radius 9 px, inset 14 px dari atas layar).
PHONE_NOTCH_W = 80.0
PHONE_NOTCH_H = 18.0
PHONE_NOTCH_RADIUS = 9.0
PHONE_NOTCH_TOP_MARGIN = 14.0
PHONE_NOTCH_COLOUR = "#0B0C10"

# Warna aksen bawaan: kuning terang #FFD60A untuk bullet dan garis bawah judul.
PHONE_DEFAULT_ACCENT = "#FFD60A"

# Judul: Archivo Black putih kecil (em 22) di bagian atas layar.
PHONE_TITLE_COLOUR = "#FFFFFF"
PHONE_TITLE_EM = 22.0
PHONE_TITLE_PAD_TOP = 60.0
PHONE_TITLE_H = 32.0

# Garis bawah pendek aksen di bawah judul.
PHONE_UNDERLINE_GAP = 10.0
PHONE_UNDERLINE_W = 44.0
PHONE_UNDERLINE_H = 4.0
PHONE_UNDERLINE_RADIUS = 2.0
PHONE_GAP_UNDERLINE_LINES = 38.0

# Baris teks: bullet lingkaran aksen + teks abu terang #E5E7EB (em 18).
PHONE_LINE_COLOUR = "#E5E7EB"
PHONE_LINE_EM = 18.0
PHONE_LINE_ROW_H = 100.0
PHONE_BULLET_RADIUS = 5.0
PHONE_BULLET_GAP = 14.0
PHONE_PAD_X = 28.0

# Ruang bawah layar (chin/home indicator) dan komponen dasar tinggi badan ponsel.
# BASE_H (360) + n * LINE_ROW_H (100) -> 560 px (2 baris), 660 px (3 baris), 760 px (4 baris).
# Pada 4 baris, w=380 dan h=760 memberikan rasio ponsel tepat 1:2.
PHONE_SCREEN_PAD_BOTTOM = 188.0
PHONE_BASE_H = 360.0

# Gerak: masuk 0.35 s meluncur kaku dari sisi 140 px dengan alfa ease-out (accel=0.5).
PHONE_ENTRY = 0.35
PHONE_ENTRY_OFFSET = 140.0
PHONE_ENTRY_ACCEL = 0.5
PHONE_EXIT = 0.20

# Animasi baris: jeda 180 ms antar-baris, fade-in alfa 120 ms + geser ke atas 12 px kaku.
PHONE_LINE_FADE_IN = 0.120
PHONE_LINE_OFFSET_Y = 12.0
PHONE_LINE_STAGGER = 0.180

# Batas validasi props
PHONE_MIN_LINES = 2
PHONE_MAX_LINES = 4
PHONE_MIN_TITLE_CHARS = 1
PHONE_MAX_TITLE_CHARS = 22
PHONE_MIN_LINE_CHARS = 1
PHONE_MAX_LINE_CHARS = 22
PHONE_MAX_DIALOGUES = 40

# Urutan layer: badan (0) < layar (1) < notch (2) < aksen (3) < teks (4)
BODY_LAYER = 0
SCREEN_LAYER = 1
NOTCH_LAYER = 2
ACCENT_LAYER = 3
TEXT_LAYER = 4

_PHONE_PROPS = ("title", "lines", "accent", "side")
_PHONE_RECT_KEYS = ("x", "y", "w", "h")

# Daftar hook integrasi mekanis ke scripts/presets.py
INTEGRATION: dict[str, str] = {
    "PRESET_TYPES": "Tambahkan 'phone_frame' ke tuple PRESET_TYPES di scripts/presets.py",
    "REGISTRY": "Daftarkan 'phone_frame': presets_phone.build ke REGISTRY di scripts/presets.py",
    "build_fx_ass": "Tambah cabang elif plan['type'] == 'phone_frame': events.extend(presets_phone.events(plan, float(fps), font)) di build_fx_ass",
    "_document": "Gunakan _document(events, style_lines) dari presets.py tanpa duplikasi style 'Sans'",
    "_load_font": "Preset memakai font_kind == 'sans' (Archivo Black), dimuat lewat _load_font('sans', font_path)",
}


# ---------------------------------------------------------------------------
# Validasi props & geometri rect
# ---------------------------------------------------------------------------

def _validate_props(
    props: Any, index: int, type_name: str
) -> dict[str, Any]:
    """Validasi ketat props `phone_frame`; pesan menyebut indeks/tipe/nama props."""
    if props is None:
        presets._error(index, type_name, "props wajib ada")
    if not isinstance(props, dict):
        presets._error(index, type_name, f"props harus objek, dapat {props!r}")

    unknown = sorted(set(props) - set(_PHONE_PROPS))
    if unknown:
        presets._error(
            index,
            type_name,
            f"props tidak dikenal: {unknown[0]!r} (dikenal: {', '.join(_PHONE_PROPS)})",
        )

    if "title" not in props:
        presets._error(index, type_name, "props['title'] wajib ada")
    title = props["title"]
    if not isinstance(title, str):
        presets._error(index, type_name, f"props['title'] harus string, dapat {title!r}")
    if not PHONE_MIN_TITLE_CHARS <= len(title) <= PHONE_MAX_TITLE_CHARS:
        presets._error(
            index,
            type_name,
            f"props['title'] harus {PHONE_MIN_TITLE_CHARS}..{PHONE_MAX_TITLE_CHARS} karakter, dapat {len(title)}",
        )
    if "\n" in title or "\r" in title:
        presets._error(
            index,
            type_name,
            f"props['title'] tidak boleh memuat newline: {title!r}",
        )

    if "lines" not in props:
        presets._error(index, type_name, "props['lines'] wajib ada")
    raw_lines = props["lines"]
    if isinstance(raw_lines, (str, bytes)) or not isinstance(raw_lines, list):
        presets._error(index, type_name, f"props['lines'] harus daftar, dapat {raw_lines!r}")
    if not PHONE_MIN_LINES <= len(raw_lines) <= PHONE_MAX_LINES:
        presets._error(
            index,
            type_name,
            f"props['lines'] harus {PHONE_MIN_LINES}..{PHONE_MAX_LINES} baris, dapat {len(raw_lines)}",
        )

    lines: list[str] = []
    for pos, line in enumerate(raw_lines):
        if not isinstance(line, str):
            presets._error(
                index,
                type_name,
                f"props['lines'][{pos}] harus string, dapat {line!r}",
            )
        if not PHONE_MIN_LINE_CHARS <= len(line) <= PHONE_MAX_LINE_CHARS:
            presets._error(
                index,
                type_name,
                f"props['lines'][{pos}] harus {PHONE_MIN_LINE_CHARS}..{PHONE_MAX_LINE_CHARS} karakter, dapat {len(line)}",
            )
        if "\n" in line or "\r" in line:
            presets._error(
                index,
                type_name,
                f"props['lines'][{pos}] tidak boleh memuat newline: {line!r}",
            )
        lines.append(presets._escape_text(line))

    accent_raw = props.get("accent", PHONE_DEFAULT_ACCENT)
    if not isinstance(accent_raw, str):
        presets._error(
            index,
            type_name,
            f"props['accent'] harus '#RRGGBB', dapat {accent_raw!r}",
        )
    try:
        shapes.colour(accent_raw)
    except ValueError:
        presets._error(
            index,
            type_name,
            f"props['accent'] harus '#RRGGBB', dapat {accent_raw!r}",
        )
    accent = accent_raw

    side_raw = props.get("side", "right")
    if not isinstance(side_raw, str) or side_raw not in ("right", "left"):
        presets._error(
            index,
            type_name,
            f"props['side'] harus 'right' atau 'left', dapat {side_raw!r}",
        )
    side = side_raw

    return {
        "title": presets._escape_text(title),
        "lines": lines,
        "accent": accent,
        "side": side,
    }


def _validate_rect(
    item: dict[str, Any],
    index: int,
    type_name: str,
    line_count: int,
    side: str,
) -> dict[str, float]:
    """Rect badan ponsel (atau bawaan dari jumlah baris); validasi kanvas dan tinggi."""
    required_h = PHONE_BASE_H + line_count * PHONE_LINE_ROW_H
    if "rect" not in item:
        default_x = PHONE_DEFAULT_X_LEFT if side == "left" else PHONE_DEFAULT_X_RIGHT
        return {
            "x": default_x,
            "y": PHONE_DEFAULT_Y,
            "w": PHONE_DEFAULT_W,
            "h": required_h,
        }

    rect = item["rect"]
    if not isinstance(rect, dict):
        presets._error(index, type_name, f"rect harus objek {{x,y,w,h}}, dapat {rect!r}")
    unknown = sorted(set(rect) - set(_PHONE_RECT_KEYS))
    if unknown:
        presets._error(
            index,
            type_name,
            f"rect kunci tidak dikenal: {unknown[0]!r} (dikenal: {', '.join(_PHONE_RECT_KEYS)})",
        )
    out: dict[str, float] = {}
    for name in _PHONE_RECT_KEYS:
        if name not in rect:
            presets._error(index, type_name, f"rect['{name}'] wajib ada, dapat {rect!r}")
        out[name] = presets._finite_number(
            rect[name], f"rect['{name}']", index, type_name
        )
    if out["w"] <= 0.0 or out["h"] <= 0.0:
        presets._error(index, type_name, f"rect['w'] dan rect['h'] harus > 0, dapat {rect!r}")

    width, height = PLAY_RES
    if (
        out["x"] < 0.0
        or out["y"] < 0.0
        or out["x"] + out["w"] > width + 1e-9
        or out["y"] + out["h"] > height + 1e-9
    ):
        presets._error(
            index,
            type_name,
            f"rect {{x={out['x']:g}, y={out['y']:g}, w={out['w']:g}, "
            f"h={out['h']:g}}} keluar kanvas {width}x{height}",
        )
    if out["h"] + 1e-9 < required_h:
        presets._error(
            index,
            type_name,
            f"rect['h'] {out['h']:g} < tinggi yang dibutuhkan {required_h:g} "
            f"({PHONE_BASE_H:g} base + {line_count} baris x {PHONE_LINE_ROW_H:g}); "
            f"badan perangkat tidak boleh disusutkan",
        )
    return out


# ---------------------------------------------------------------------------
# Builder (kontrak yang sama dengan presets.py)
# ---------------------------------------------------------------------------

def build(
    index: int,
    item: dict[str, Any],
    clip_duration: float,
    *,
    fps: float,
    font_path: Any = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validasi satu overlay `phone_frame`; kembalikan plan atau peringatan.

    Font Archivo Black bundel diverifikasi; kegagalan memuat font mengembalikan
    peringatan dan plan=None, bukan exception. Teks diukur dengan fontmetrics
    dan ditolak bila tidak muat lebar layar ponsel.
    """
    type_name = str(item.get("type", TYPE))
    warnings: list[str] = []

    start = presets._finite_number(item.get("start"), "start", index, type_name)
    end = presets._finite_number(item.get("end"), "end", index, type_name)

    if end <= 0.0 or start >= clip_duration:
        warnings.append(
            f"overlay[{index}] tipe {type_name!r}: jendela "
            f"[{start:g}, {end:g}] sepenuhnya di luar durasi klip "
            f"{clip_duration:g} s; dilewati"
        )
        return None, warnings

    start = max(0.0, start)
    end = min(clip_duration, end)
    if end <= start:
        presets._error(
            index,
            type_name,
            f"end harus > start setelah dipotong ke [0, {clip_duration:g}]; "
            f"dapat {item.get('start')!r}..{item.get('end')!r}",
        )

    props = _validate_props(item.get("props"), index, type_name)
    rect = _validate_rect(item, index, type_name, len(props["lines"]), props["side"])

    # Muat font untuk mengukur teks; bila font gagal dimuat, preset dilewati dengan peringatan
    font, font_warning = presets._load_font("sans", font_path)
    if font is None:
        warnings.append(
            font_warning
            if font_warning
            else f"preset {type_name} dilewati: font tidak tersedia"
        )
        return None, warnings

    # Pengukuran fontmetrics: pastikan judul dan semua baris muat lebar layar
    screen_w = rect["w"] - 2.0 * PHONE_SCREEN_INSET
    title_available = screen_w - 2.0 * PHONE_PAD_X
    title_width = font.width(props["title"], PHONE_TITLE_EM)
    if title_width > title_available + 1e-9:
        presets._error(
            index,
            type_name,
            f"props['title'] tidak muat: lebar terukur {title_width:g} px > "
            f"tersedia {title_available:g} px",
        )

    line_available = (
        screen_w - 2.0 * PHONE_PAD_X - (2.0 * PHONE_BULLET_RADIUS + PHONE_BULLET_GAP)
    )
    for pos, line in enumerate(props["lines"]):
        line_w = font.width(line, PHONE_LINE_EM)
        if line_w > line_available + 1e-9:
            presets._error(
                index,
                type_name,
                f"props['lines'][{pos}] tidak muat: lebar terukur {line_w:g} px > "
                f"tersedia {line_available:g} px",
            )

    frame_start = presets._frame_index(start, fps)
    frame_end = presets._frame_index(end, fps)
    if frame_end <= frame_start:
        warnings.append(
            f"overlay[{index}] tipe {type_name!r}: jendela kurang dari satu "
            f"frame pada {fps:g} fps; dilewati"
        )
        return None, warnings

    return {
        "index": index,
        "type": type_name,
        "start": start,
        "end": end,
        "fps": float(fps),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "rect": rect,
        "title": props["title"],
        "lines": props["lines"],
        "accent": props["accent"],
        "side": props["side"],
        "font_kind": "sans",
    }, warnings


# ---------------------------------------------------------------------------
# Pembangkit baris Dialogue
# ---------------------------------------------------------------------------

def style_lines(font: fontmetrics.Font) -> list[str]:
    """Baris Style ASS untuk preset phone_frame (Style: Sans, Archivo Black).

    Pada integrasi penuh ke `presets.py`, Style `Sans` sudah dibuat oleh
    `_checklist_style_line`, sehingga tidak perlu digandakan.
    """
    return [presets._checklist_style_line(font, PHONE_TITLE_EM)]


def document(events: Iterable[str], font: fontmetrics.Font) -> str:
    """Bangun dokumen ASS mandiri untuk pengujian render langsung."""
    return presets._document(events, style_lines(font))


def events(
    plan: dict[str, Any], fps: float, font: fontmetrics.Font
) -> list[str]:
    """Hasilkan semua baris Dialogue untuk satu overlay `phone_frame`."""
    frame_start = plan["frame_start"]
    frame_end = plan["frame_end"]
    start_t = presets._frame_start_time(frame_start, fps)
    end_t = presets._frame_end_time(frame_end, fps)

    rect = plan["rect"]
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    side = plan["side"]

    # Offset luncur kaku: masuk dari kanan (+140) atau kiri (-140)
    dx = -PHONE_ENTRY_OFFSET if side == "left" else PHONE_ENTRY_OFFSET
    entry_ms = int(round(PHONE_ENTRY * 1000.0))

    exit_frames = int(round(PHONE_EXIT * fps))
    exit_frame = max(frame_start, frame_end - exit_frames)

    def exit_state(event_start_frame: int, event_start_t: float) -> tuple[str, str]:
        span = frame_end - exit_frame
        progress = 0.0
        if span > 0 and event_start_frame > exit_frame:
            progress = min(1.0, (event_start_frame - exit_frame) / span)
        end_rel = max(1, int(round((frame_end / fps - event_start_t) * 1000.0)))
        if progress > 0.0:
            base = f"&H{int(round(progress * 255.0)):02X}&"
            return base, f"\\t(0,{end_rel},\\alpha&HFF&)"
        start_rel = max(0, int(round((exit_frame / fps - event_start_t) * 1000.0)))
        start_rel = min(start_rel, max(0, end_rel - 1))
        return "&H00&", f"\\t({start_rel},{end_rel},\\alpha&HFF&)"

    res: list[str] = []

    # -- 1. Badan ponsel (layer 0) -------------------------------------------
    _, shell_exit_tag = exit_state(frame_start, start_t)
    shell_exit_shape = shell_exit_tag.replace("\\alpha", "\\1a")
    body_path = shapes.rounded_rect(x, y, w, h, PHONE_BODY_RADIUS)
    res.append(
        presets._shape_line(
            BODY_LAYER,
            start_t,
            end_t,
            "body",
            body_path,
            PHONE_BODY_COLOUR,
            1.0,
            presets._move_tag(dx, 0, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{PHONE_ENTRY_ACCEL:g},\\1a&H00&){shell_exit_shape}",
        )
    )

    # -- 2. Layar ponsel (layer 1) -------------------------------------------
    screen_x = x + PHONE_SCREEN_INSET
    screen_y = y + PHONE_SCREEN_INSET
    screen_w = w - 2.0 * PHONE_SCREEN_INSET
    screen_h = h - 2.0 * PHONE_SCREEN_INSET
    screen_path = shapes.rounded_rect(
        screen_x, screen_y, screen_w, screen_h, PHONE_SCREEN_RADIUS
    )
    res.append(
        presets._shape_line(
            SCREEN_LAYER,
            start_t,
            end_t,
            "screen",
            screen_path,
            PHONE_SCREEN_COLOUR,
            1.0,
            presets._move_tag(dx, 0, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{PHONE_ENTRY_ACCEL:g},\\1a&H00&){shell_exit_shape}",
        )
    )

    # -- 3. Notch pil (layer 2) ----------------------------------------------
    notch_cx = screen_x + screen_w / 2.0
    notch_x = notch_cx - PHONE_NOTCH_W / 2.0
    notch_y = screen_y + PHONE_NOTCH_TOP_MARGIN
    notch_path = shapes.rounded_rect(
        notch_x, notch_y, PHONE_NOTCH_W, PHONE_NOTCH_H, PHONE_NOTCH_RADIUS
    )
    res.append(
        presets._shape_line(
            NOTCH_LAYER,
            start_t,
            end_t,
            "notch",
            notch_path,
            PHONE_NOTCH_COLOUR,
            1.0,
            presets._move_tag(dx, 0, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{PHONE_ENTRY_ACCEL:g},\\1a&H00&){shell_exit_shape}",
        )
    )

    # -- 4. Garis bawah aksen judul (layer 3) --------------------------------
    content_x = screen_x + PHONE_PAD_X
    title_y = screen_y + PHONE_TITLE_PAD_TOP
    underline_x = content_x
    underline_y = title_y + PHONE_TITLE_H + PHONE_UNDERLINE_GAP
    underline_path = shapes.rounded_rect(
        underline_x,
        underline_y,
        PHONE_UNDERLINE_W,
        PHONE_UNDERLINE_H,
        PHONE_UNDERLINE_RADIUS,
    )
    res.append(
        presets._shape_line(
            ACCENT_LAYER,
            start_t,
            end_t,
            "underline",
            underline_path,
            plan["accent"],
            1.0,
            presets._move_tag(dx, 0, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{PHONE_ENTRY_ACCEL:g},\\1a&H00&){shell_exit_shape}",
        )
    )

    # -- 5. Judul (layer 4) --------------------------------------------------
    res.append(
        presets._text_line(
            TEXT_LAYER,
            start_t,
            end_t,
            "title",
            7,
            presets._move_tag(content_x + dx, title_y, content_x, title_y, 0, entry_ms),
            PHONE_TITLE_COLOUR,
            PHONE_TITLE_EM,
            font,
            "&HFF&",
            f"\\t(0,{entry_ms},{PHONE_ENTRY_ACCEL:g},\\alpha&H00&){shell_exit_tag}",
            plan["title"],
        )
    )

    # -- 6. Baris-baris (bullet layer 3, teks layer 4) -----------------------
    entry_frame = frame_start + round(PHONE_ENTRY * fps)
    line_fade_ms = int(round(PHONE_LINE_FADE_IN * 1000.0))
    line_dy = PHONE_LINE_OFFSET_Y

    header_bottom = (
        screen_y
        + PHONE_TITLE_PAD_TOP
        + PHONE_TITLE_H
        + PHONE_UNDERLINE_GAP
        + PHONE_UNDERLINE_H
    )
    first_line_top = header_bottom + PHONE_GAP_UNDERLINE_LINES
    bullet_cx = content_x + PHONE_BULLET_RADIUS
    text_x = content_x + 2.0 * PHONE_BULLET_RADIUS + PHONE_BULLET_GAP

    for k, line_text in enumerate(plan["lines"]):
        line_frame = entry_frame + round(k * PHONE_LINE_STAGGER * fps)
        line_start_t = presets._frame_start_time(line_frame, fps)

        row_cy = first_line_top + k * PHONE_LINE_ROW_H + PHONE_LINE_ROW_H / 2.0

        _, line_exit_tag = exit_state(line_frame, line_start_t)
        line_exit_shape = line_exit_tag.replace("\\alpha", "\\1a")

        # Bullet aksen (lingkaran): fade-in 120 ms + geser ke atas 12 px (move dari y+12 ke y)
        bullet_path = shapes.circle(bullet_cx, row_cy, PHONE_BULLET_RADIUS)
        res.append(
            presets._shape_line(
                ACCENT_LAYER,
                line_start_t,
                end_t,
                f"line_bullet_{k}",
                bullet_path,
                plan["accent"],
                1.0,
                presets._move_tag(0, line_dy, 0, 0, 0, line_fade_ms),
                f"\\1a&HFF&\\t(0,{line_fade_ms},\\1a&H00&){line_exit_shape}",
            )
        )

        # Teks baris (alignment 4 = middle-left): fade-in 120 ms + geser ke atas 12 px
        res.append(
            presets._text_line(
                TEXT_LAYER,
                line_start_t,
                end_t,
                f"line_text_{k}",
                4,
                presets._move_tag(
                    text_x, row_cy + line_dy, text_x, row_cy, 0, line_fade_ms
                ),
                PHONE_LINE_COLOUR,
                PHONE_LINE_EM,
                font,
                "&HFF&",
                f"\\t(0,{line_fade_ms},\\alpha&H00&){line_exit_tag}",
                line_text,
            )
        )

    return res
