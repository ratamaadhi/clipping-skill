"""Efek pull-back reveal (efek referensi #11) — modul terisolasi (Langkah 5b-6).

Pada jendela waktu overlay, video mengecil dari 1080x1920 ke jendela 9:16 yang
lebih kecil di atas latar krem (#F6EEDC) berhias UI datar, sementara sebuah
angka besar menghitung naik (count-up) di area krem di atas jendela; setelah
ditahan, video membesar kembali ke ukuran penuh.

Versi DATAR: tanpa bayangan lembut, tanpa blur latar, tanpa tilt 3D.
Sudut membulat jendela video (radius = 36) diterapkan pada keadaan stabil
(sesudah shrink selesai sampai sebelum grow dimulai) lewat pelengkap sudut
berwarna krem di dokumen ASS. Selama transisi shrink dan grow, sudut berbentuk
persegi (keterbatasan jujur: scale ffmpeg tidak memiliki mask dinamis per frame).

Modul ini adalah fungsi murni: tidak menjalankan subprocess ffmpeg, tidak
menulis berkas ke disk, dan tidak mengubah modul preset lain.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from . import captions as _tier1
from . import shapes
from .lib import fontmetrics

__all__ = [
    "ALLOWED_PROPS",
    "CORNER_RADIUS",
    "CREAM_ASS_COLOR",
    "CREAM_HEX",
    "DARK_ASS_COLOR",
    "DARK_HEX",
    "DEFAULT_COUNT",
    "DEFAULT_FONT_PATH",
    "DEFAULT_GROW",
    "DEFAULT_SHRINK",
    "DEFAULT_UI_FADE",
    "DEFAULT_WINDOW",
    "EXPECTED_FONT_FAMILY",
    "MAX_COUNT",
    "MAX_GROW",
    "MAX_OVERLAYS_PER_CLIP",
    "MAX_SHRINK",
    "MIN_COUNT",
    "MIN_GROW",
    "MIN_SHRINK",
    "NUMBER_AREA_BOTTOM",
    "PullbackError",
    "ass",
    "build",
    "filter_graph",
]

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

CREAM_HEX = "#F6EEDC"
# Format warna ASS: &HAABBGGRR& -> untuk #F6EEDC (R=F6, G=EE, B=DC)
CREAM_ASS_COLOR = "&H00DCEEF6&"

DARK_HEX = "#1B1B1F"
# Format warna ASS: #1B1B1F (R=1B, G=1B, B=1F)
DARK_ASS_COLOR = "&H001F1B1B&"

MUTED_DARK_ASS_COLOR = "&H004A463F&"
LINE_ASS_COLOR = "&H00C4BCAC&"

# Area angka di atas jendela berakhir di y = 600.
# Jendela video harus berada sepenuhnya di bawah batas ini.
NUMBER_AREA_BOTTOM = 600.0

# Jendela bawaan: w=648 (skala 0,6 dari 1080), x=216 (tengah), y=640.
# h = 648 * 16 / 9 = 1152. y + h = 1792 <= 1920 (margin bawah 128 px).
DEFAULT_WINDOW = {
    "x": 216.0,
    "y": 640.0,
    "w": 648.0,
    "h": 1152.0,
}

DEFAULT_SHRINK = 0.6
MIN_SHRINK = 0.3
MAX_SHRINK = 1.2

DEFAULT_GROW = 0.5
MIN_GROW = 0.3
MAX_GROW = 1.2

DEFAULT_COUNT = 1.2
MIN_COUNT = 0.4
MAX_COUNT = 3.0

CORNER_RADIUS = 36.0
DEFAULT_UI_FADE = 0.12
MAX_OVERLAYS_PER_CLIP = 3

DEFAULT_FONT_PATH = "assets/fonts/ArchivoBlack-Regular.ttf"
EXPECTED_FONT_FAMILY = "Archivo Black"

ALLOWED_PROPS = (
    "count",
    "decimals",
    "from",
    "grow",
    "label",
    "shrink",
    "suffix",
    "title",
    "to",
    "window",
)

ALLOWED_OVERLAY_KEYS = (
    "end",
    "left",
    "props",
    "rect",
    "renderer",
    "right",
    "slot",
    "start",
    "type",
)

PLAY_RES = (1080, 1920)


class PullbackError(ValueError):
    """Galat validasi konfigurasi pullback."""


# ---------------------------------------------------------------------------
# Validasi props & helper waktu
# ---------------------------------------------------------------------------


def _error(index: int, message: str) -> None:
    raise PullbackError(f"overlay[{index}] tipe 'pullback': {message}")


def _finite_number(val: Any, name: str, index: int) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _error(index, f"props['{name}'] harus angka berhingga, dapat {val!r}")
    num = float(val)
    if not math.isfinite(num):
        _error(index, f"props['{name}'] harus angka berhingga, dapat {val!r}")
    return num


def _frame_index(t: float, fps: float) -> int:
    return int(round(float(t) * float(fps)))


def _frame_start_time(frame: int, fps: float) -> float:
    if frame <= 0:
        return 0.0
    previous = (frame - 1) / fps
    centiseconds = math.floor(previous * 100.0 + 1e-9) + 1
    return round(centiseconds / 100.0, 2)


def _ass_time(t: float) -> str:
    return _tier1._ass_time(t)


def _smoothstep(p: float) -> float:
    """Kurva ease-in-out polinomial: p*p*(3 - 2p)."""
    p_clamped = max(0.0, min(1.0, float(p)))
    return p_clamped * p_clamped * (3.0 - 2.0 * p_clamped)


def _ease_out(p: float) -> float:
    """Kurva ease-out kuadratik: p*(2 - p)."""
    p_clamped = max(0.0, min(1.0, float(p)))
    return p_clamped * (2.0 - p_clamped)


def _format_number(val: float, decimals: int) -> str:
    if decimals == 0:
        return str(int(round(val)))
    if decimals == 1:
        return f"{val:.1f}"
    return f"{val:.2f}"


# ---------------------------------------------------------------------------
# build()
# ---------------------------------------------------------------------------


def build(
    clip: dict[str, Any],
    *,
    fps: float,
    width: int = 1080,
    height: int = 1920,
    font_path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validasi overlay pullback dan bangun rencana kerja (plan).

    Mengembalikan (plan | None, warnings). plan=None bila klip tidak memiliki
    overlay pullback atau seluruhnya di luar durasi klip.
    """
    if not isinstance(clip, dict):
        raise PullbackError(f"clip harus dict, dapat {clip!r}")

    segments = clip.get("segments") or []
    clip_duration = sum(
        float(seg["src_end"]) - float(seg["src_start"]) for seg in segments
    )

    all_overlays = clip.get("overlays") or []
    pullback_items: list[tuple[int, dict[str, Any]]] = []

    for idx, ov in enumerate(all_overlays):
        if not isinstance(ov, dict):
            continue
        if ov.get("type") == "pullback":
            pullback_items.append((idx, ov))

    if not pullback_items:
        return None, []

    warnings: list[str] = []
    validated_overlays: list[dict[str, Any]] = []

    for ov_idx, ov in pullback_items:
        # Periksa kunci overlay tak dikenal
        unknown_ov_keys = sorted(set(ov) - set(ALLOWED_OVERLAY_KEYS))
        if unknown_ov_keys:
            _error(
                ov_idx,
                f"kunci overlay tidak dikenal: {unknown_ov_keys}. Kunci sah: {sorted(ALLOWED_OVERLAY_KEYS)}",
            )

        raw_start = ov.get("start")
        raw_end = ov.get("end")
        if raw_start is None or raw_end is None:
            _error(ov_idx, "start dan end wajib ada")

        start = _finite_number(raw_start, "start", ov_idx)
        end = _finite_number(raw_end, "end", ov_idx)
        if end <= start:
            _error(ov_idx, f"end ({end}) harus > start ({start})")

        # Cek apakah overlay berada di luar durasi klip
        if clip_duration > 0 and (start >= clip_duration or end <= 0.0):
            warnings.append(
                f"overlay[{ov_idx}] di luar durasi klip ({clip_duration:.2f}s), dilewati"
            )
            continue

        clamped_start = max(0.0, start)
        clamped_end = min(clip_duration, end) if clip_duration > 0 else end
        if clamped_end <= clamped_start:
            warnings.append(
                f"overlay[{ov_idx}] di luar durasi klip ({clip_duration:.2f}s), dilewati"
            )
            continue

        props = ov.get("props")
        if not isinstance(props, dict):
            _error(ov_idx, f"props harus objek, dapat {props!r}")

        unknown_props = sorted(set(props) - set(ALLOWED_PROPS))
        if unknown_props:
            _error(
                ov_idx,
                f"props memuat kunci tidak dikenal: {unknown_props}. Kunci sah: {sorted(ALLOWED_PROPS)}",
            )

        # from dan to
        if "from" not in props:
            _error(ov_idx, "props['from'] wajib ada")
        if "to" not in props:
            _error(ov_idx, "props['to'] wajib ada")

        from_val = _finite_number(props["from"], "from", ov_idx)
        to_val = _finite_number(props["to"], "to", ov_idx)
        if math.isclose(from_val, to_val, abs_tol=1e-9):
            _error(ov_idx, f"props['to'] ({to_val}) tidak boleh sama dengan 'from' ({from_val})")

        # decimals
        raw_decimals = props.get("decimals", 0)
        if isinstance(raw_decimals, bool) or not isinstance(raw_decimals, int):
            _error(ov_idx, f"props['decimals'] harus integer 0-2, dapat {raw_decimals!r}")
        if not (0 <= raw_decimals <= 2):
            _error(ov_idx, f"props['decimals'] harus integer 0-2, dapat {raw_decimals!r}")
        decimals = raw_decimals

        # suffix
        raw_suffix = props.get("suffix", "")
        if not isinstance(raw_suffix, str) or len(raw_suffix) > 4 or "\n" in raw_suffix or "\r" in raw_suffix:
            _error(ov_idx, f"props['suffix'] harus string 0-4 karakter tanpa newline, dapat {raw_suffix!r}")
        suffix = raw_suffix

        # label & title
        raw_label = props.get("label", "")
        if not isinstance(raw_label, str) or len(raw_label) > 28 or "\n" in raw_label or "\r" in raw_label:
            _error(ov_idx, f"props['label'] harus string 0-28 karakter tanpa newline, dapat {raw_label!r}")
        label = raw_label

        raw_title = props.get("title", "")
        if not isinstance(raw_title, str) or len(raw_title) > 28 or "\n" in raw_title or "\r" in raw_title:
            _error(ov_idx, f"props['title'] harus string 0-28 karakter tanpa newline, dapat {raw_title!r}")
        title = raw_title

        # shrink, grow, count
        shrink = _finite_number(props.get("shrink", DEFAULT_SHRINK), "shrink", ov_idx)
        if not (MIN_SHRINK <= shrink <= MAX_SHRINK):
            _error(ov_idx, f"props['shrink'] harus antara {MIN_SHRINK} dan {MAX_SHRINK}, dapat {shrink}")

        grow = _finite_number(props.get("grow", DEFAULT_GROW), "grow", ov_idx)
        if not (MIN_GROW <= grow <= MAX_GROW):
            _error(ov_idx, f"props['grow'] harus antara {MIN_GROW} dan {MAX_GROW}, dapat {grow}")

        count = _finite_number(props.get("count", DEFAULT_COUNT), "count", ov_idx)
        if not (MIN_COUNT <= count <= MAX_COUNT):
            _error(ov_idx, f"props['count'] harus antara {MIN_COUNT} dan {MAX_COUNT}, dapat {count}")

        duration = clamped_end - clamped_start
        min_required_duration = shrink + count + grow
        if duration < min_required_duration - 1e-6:
            _error(
                ov_idx,
                f"total durasi fase (shrink={shrink}s + count={count}s + grow={grow}s = {min_required_duration:.2f}s) "
                f"tidak muat di jendela overlay ({duration:.2f}s)",
            )

        # window
        raw_window = props.get("window")
        if raw_window is None:
            window = dict(DEFAULT_WINDOW)
        elif not isinstance(raw_window, dict):
            _error(ov_idx, f"props['window'] harus objek {{x,y,w}}, dapat {raw_window!r}")
        else:
            for k in ("x", "y", "w"):
                if k not in raw_window:
                    _error(ov_idx, f"props['window']['{k}'] wajib ada")
            wx = _finite_number(raw_window["x"], "window.x", ov_idx)
            wy = _finite_number(raw_window["y"], "window.y", ov_idx)
            ww = _finite_number(raw_window["w"], "window.w", ov_idx)
            if ww <= 0.0:
                _error(ov_idx, f"props['window']['w'] harus > 0, dapat {ww}")
            wh_calc = ww * 16.0 / 9.0

            if "h" in raw_window:
                wh_given = _finite_number(raw_window["h"], "window.h", ov_idx)
                if abs(wh_given - wh_calc) > 0.5:
                    _error(
                        ov_idx,
                        f"props['window'] ukuran jendela tidak 9:16 (w={ww}, h={wh_given}; seharusnya h={wh_calc:.1f})",
                    )
            window = {"x": wx, "y": wy, "w": ww, "h": wh_calc}

        # Periksa window berada dalam kanvas
        if window["x"] < 0 or window["y"] < 0 or (window["x"] + window["w"] > width) or (window["y"] + window["h"] > height):
            _error(
                ov_idx,
                f"props['window'] di luar batas kanvas {width}x{height}: "
                f"x={window['x']}, y={window['y']}, w={window['w']}, h={window['h']}",
            )

        # Periksa window berada di bawah area angka
        if window["y"] < NUMBER_AREA_BOTTOM:
            _error(
                ov_idx,
                f"props['window']['y'] ({window['y']}) tumpang tindih dengan area angka (harus >= {NUMBER_AREA_BOTTOM})",
            )

        validated_overlays.append({
            "index": ov_idx,
            "start": clamped_start,
            "end": clamped_end,
            "duration": duration,
            "props": {
                "from": from_val,
                "to": to_val,
                "decimals": decimals,
                "suffix": suffix,
                "label": label,
                "title": title,
                "shrink": shrink,
                "grow": grow,
                "count": count,
                "window": window,
            },
        })

    if not validated_overlays:
        return None, warnings

    if len(validated_overlays) > MAX_OVERLAYS_PER_CLIP:
        raise PullbackError(
            f"klip '{clip.get('id', '?')}' memiliki {len(validated_overlays)} overlay pullback; "
            f"maksimum {MAX_OVERLAYS_PER_CLIP} per klip diizinkan"
        )

    # Urutkan berdasarkan waktu mulai
    validated_overlays.sort(key=lambda item: item["start"])

    # Periksa tumpang tindih waktu antar-overlay
    for i in range(len(validated_overlays) - 1):
        curr = validated_overlays[i]
        next_ov = validated_overlays[i + 1]
        if next_ov["start"] < curr["end"] - 1e-6:
            raise PullbackError(
                f"overlay[{next_ov['index']}] tumpang tindih waktu dengan overlay[{curr['index']}]: "
                f"[{next_ov['start']:.2f}s..{next_ov['end']:.2f}s] vs [{curr['start']:.2f}s..{curr['end']:.2f}s]"
            )

    # Resolusi path font
    effective_font_path = Path(font_path) if font_path else Path(DEFAULT_FONT_PATH)
    has_font = False
    if effective_font_path.exists():
        try:
            f = fontmetrics.Font.load(effective_font_path)
            if f.family == EXPECTED_FONT_FAMILY:
                has_font = True
        except Exception:
            has_font = False

    plan = {
        "clip_id": clip.get("id", "?"),
        "clip_duration": clip_duration,
        "width": width,
        "height": height,
        "overlays": validated_overlays,
        "has_font": has_font,
        "font_path": str(effective_font_path.resolve()),
    }
    return plan, warnings


# ---------------------------------------------------------------------------
# filter_graph()
# ---------------------------------------------------------------------------


def filter_graph(
    plan: dict[str, Any],
    *,
    in_label: str,
    out_label: str,
    fps: float,
) -> list[str]:
    """Bangun potongan filter_complex untuk komposit video pullback.

    Menggunakan pemotongan trim + concat per segmen agar hanya frame di dalam
    jendela overlay yang melalui scale & overlay dinamis (hemat komputasi dan
    memenuhi batas anggaran biaya +12%).
    """
    if not plan or not plan.get("overlays"):
        return [f"[{in_label}]null[{out_label}]"]

    width = plan.get("width", 1080)
    height = plan.get("height", 1920)
    clip_duration = plan.get("clip_duration", 0.0)
    overlays = plan["overlays"]

    # Bangun segmen waktu timeline
    # Setiap segmen bertipe "passthrough" atau "pullback"
    timeline_segments: list[dict[str, Any]] = []
    current_time = 0.0

    for ov in overlays:
        start = ov["start"]
        end = ov["end"]

        if start > current_time + 1e-4:
            timeline_segments.append({
                "type": "passthrough",
                "start": current_time,
                "end": start,
            })

        timeline_segments.append({
            "type": "pullback",
            "start": start,
            "end": end,
            "overlay": ov,
        })
        current_time = end

    # Segmen passthrough terakhir bila masih ada durasi tersisa
    if clip_duration > current_time + 1e-4:
        timeline_segments.append({
            "type": "passthrough",
            "start": current_time,
            "end": clip_duration,
            "is_tail": True,
        })

    num_segments = len(timeline_segments)
    filters: list[str] = []

    # Kasus khusus 1 segmen (pullback mencakup seluruh klip)
    if num_segments == 1 and timeline_segments[0]["type"] == "pullback":
        ov = timeline_segments[0]["overlay"]
        filters.extend(_build_pullback_segment(ov, in_label, out_label, fps, width, height))
        return filters

    # Multi segmen: split in_label
    split_labels = [f"pb_in_{i}" for i in range(num_segments)]
    filters.append(f"[{in_label}]split={num_segments}" + "".join(f"[{lbl}]" for lbl in split_labels))

    concat_inputs: list[str] = []

    for i, seg in enumerate(timeline_segments):
        in_lbl = split_labels[i]
        out_lbl = f"pb_seg_{i}"
        concat_inputs.append(f"[{out_lbl}]")

        if seg["type"] == "passthrough":
            if seg.get("is_tail"):
                filters.append(f"[{in_lbl}]trim=start={seg['start']:.3f},setpts=PTS-STARTPTS[{out_lbl}]")
            else:
                filters.append(
                    f"[{in_lbl}]trim=start={seg['start']:.3f}:end={seg['end']:.3f},setpts=PTS-STARTPTS[{out_lbl}]"
                )
        else:
            ov = seg["overlay"]
            raw_mid_lbl = f"pb_raw_{i}"
            filters.append(
                f"[{in_lbl}]trim=start={ov['start']:.3f}:end={ov['end']:.3f},setpts=PTS-STARTPTS[{raw_mid_lbl}]"
            )
            filters.extend(
                _build_pullback_segment(ov, raw_mid_lbl, out_lbl, fps, width, height, tag_suffix=f"_{i}")
            )

    # Gabungkan semua segmen dengan concat
    filters.append(
        "".join(concat_inputs) + f"concat=n={num_segments}:v=1:a=0,format=yuv420p[{out_label}]"
    )
    return filters


def _build_pullback_segment(
    ov: dict[str, Any],
    in_lbl: str,
    out_lbl: str,
    fps: float,
    width: int,
    height: int,
    tag_suffix: str = "",
) -> list[str]:
    """Bangun filter chain komposit pullback untuk satu jendela overlay."""
    dur = ov["duration"]
    props = ov["props"]
    win = props["window"]
    shrink = props["shrink"]
    grow = props["grow"]

    wx = win["x"]
    wy = win["y"]
    ww = win["w"]
    wh = win["h"]

    bg_lbl = f"pb_bg{tag_suffix}"
    sc_lbl = f"pb_sc{tag_suffix}"

    # Latar belakang warna krem
    bg_filter = f"color=c={CREAM_HEX}:s={width}x{height}:d={dur:.3f}:r={fps:g},format=yuv420p[{bg_lbl}]"

    # Waktu relatif dalam segmen t in [0, dur]:
    # Fase shrink: t in [0, shrink]
    # Fase hold: t in [shrink, dur - grow]
    # Fase grow: t in [dur - grow, dur]
    # Easing smoothstep: p*p*(3 - 2*p)
    hold_start = shrink
    grow_start = dur - grow

    p_s = f"clip(t/{shrink:.4f},0,1)"
    e_s = f"({p_s}*{p_s}*(3-2*{p_s}))"

    p_g = f"clip((t-{grow_start:.4f})/{grow:.4f},0,1)"
    e_g = f"({p_g}*{p_g}*(3-2*{p_g}))"

    # Lebar dan tinggi dengan pembulatan integer genap (syarat yuv420p)
    w_expr = (
        f"2*round((if(lt(t,{hold_start:.4f}),"
        f"{width}-({width}-{ww:.1f})*{e_s},"
        f"if(lt(t,{grow_start:.4f}),{ww:.1f},{ww:.1f}+({width}-{ww:.1f})*{e_g})))/2)"
    )
    h_expr = (
        f"2*round((if(lt(t,{hold_start:.4f}),"
        f"{height}-({height}-{wh:.1f})*{e_s},"
        f"if(lt(t,{grow_start:.4f}),{wh:.1f},{wh:.1f}+({height}-{wh:.1f})*{e_g})))/2)"
    )

    scale_filter = (
        f"[{in_lbl}]scale=w='{w_expr}':h='{h_expr}':eval=frame[{sc_lbl}]"
    )

    x_expr = (
        f"round(if(lt(t,{hold_start:.4f}),"
        f"{wx:.1f}*{e_s},"
        f"if(lt(t,{grow_start:.4f}),{wx:.1f},{wx:.1f}*(1-{e_g}))))"
    )
    y_expr = (
        f"round(if(lt(t,{hold_start:.4f}),"
        f"{wy:.1f}*{e_s},"
        f"if(lt(t,{grow_start:.4f}),{wy:.1f},{wy:.1f}*(1-{e_g}))))"
    )

    overlay_filter = (
        f"[{bg_lbl}][{sc_lbl}]overlay=x='{x_expr}':y='{y_expr}':eval=frame[{out_lbl}]"
    )

    return [bg_filter, scale_filter, overlay_filter]


# ---------------------------------------------------------------------------
# ass()
# ---------------------------------------------------------------------------


def ass(
    plan: dict[str, Any],
    *,
    fps: float,
) -> tuple[str | None, list[str]]:
    """Bangun dokumen ASS mandiri untuk elemen UI datar dan count-up angka.

    Bila font Archivo Black tidak tersedia, mengembalikan (None, [peringatan])
    dan efek video tetap berjalan tanpa teks.
    """
    if not plan or not plan.get("overlays"):
        return None, []

    font_path_str = plan.get("font_path", DEFAULT_FONT_PATH)
    font_path = Path(font_path_str)

    if not font_path.exists():
        return None, [f"Font '{font_path.name}' tidak ditemukan; efek teks pullback dilewati"]

    try:
        font = fontmetrics.Font.load(font_path)
    except Exception as exc:
        return None, [f"Font '{font_path.name}' gagal dibaca ({exc}); efek teks pullback dilewati"]

    if font.family != EXPECTED_FONT_FAMILY:
        return None, [
            f"Keluarga font '{font.family}' tidak cocok dengan '{EXPECTED_FONT_FAMILY}'; "
            "efek teks pullback dilewati"
        ]

    events: list[str] = []

    for ov in plan["overlays"]:
        ov_events = _build_overlay_events(ov, fps=fps)
        events.extend(ov_events)

    if not events:
        return None, []

    # Format styles
    # Style: Shape (bawaan shapes.ass_document)
    # Style: Sans (Archivo Black)
    style_lines = [
        f"Style: Sans,{font.family},40,{DARK_ASS_COLOR},&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1"
    ]

    base_doc = shapes.ass_document(events, play_res=PLAY_RES)
    marker = "\n[Events]"
    if marker not in base_doc:
        raise PullbackError("dokumen ASS shapes tidak memuat penanda [Events]")

    styles = "\n".join(style_lines)
    final_doc = base_doc.replace(marker, "\n" + styles + "\n" + marker, 1)
    return final_doc, []


def _build_overlay_events(ov: dict[str, Any], *, fps: float) -> list[str]:
    """Bangun seluruh event ASS untuk satu overlay pullback.

    SEMUA elemen UI (judul, angka, label, hiasan header, dan sudut membulat)
    hanya tampil dalam fase stabil (sesudah shrink selesai sampai sebelum grow
    dimulai), dengan fade-in 120 ms sesudah shrink selesai dan fade-out 120 ms
    yang selesai tepat saat grow dimulai (atau lebih awal bila fase stabil < 0,3 s).
    Selama shrink dan grow tidak ada piksel teks UI di dalam frame video.
    """
    events: list[str] = []
    start = ov["start"]
    end = ov["end"]
    props = ov["props"]

    from_val = props["from"]
    to_val = props["to"]
    decimals = props["decimals"]
    suffix = props["suffix"]
    title = props["title"]
    label = props["label"]
    shrink = props["shrink"]
    grow = props["grow"]
    count = props["count"]
    win = props["window"]

    # Waktu batas fase
    t_shrink_end = start + shrink
    t_count_end = start + shrink + count
    t_grow_start = end - grow

    f_shrink_end = _frame_index(t_shrink_end, fps)
    f_count_end = _frame_index(t_count_end, fps)
    f_grow_start = _frame_index(t_grow_start, fps)

    if f_grow_start <= f_shrink_end:
        return []

    # Waktu mulai dan selesai fase stabil untuk dokumen ASS
    t_stable_s = _frame_start_time(f_shrink_end, fps)
    t_stable_e = _frame_start_time(f_grow_start, fps)

    # Durasi fase stabil dan durasi fade
    stable_duration = max(0.0, t_grow_start - t_shrink_end)
    if stable_duration < 0.3:
        fade_ms = max(0, int(round(stable_duration * 0.4 * 1000.0)))
    else:
        fade_ms = int(round(DEFAULT_UI_FADE * 1000.0))

    fade_tag = f"\\fad({fade_ms},{fade_ms})" if fade_ms > 0 else ""

    # 1. Hiasan UI header: garis tipis + tiga titik (tampil hanya pada fase stabil)
    line_path = "m 216 120 l 864 120 l 864 122 l 216 122"
    events.append(
        f"Dialogue: 0,{_ass_time(t_stable_s)},{_ass_time(t_stable_e)},Shape,,0,0,0,,"
        f"{{{fade_tag}\\an7\\pos(0,0)\\bord0\\shad0\\1c{LINE_ASS_COLOR}\\1a&H40&\\p1}}{line_path}{{\\p0}}"
    )

    # Tiga titik dekoratif di kiri garis (x=236, 256, 276; y=105, r=4)
    dot1 = shapes.circle(236, 105, 4)
    dot2 = shapes.circle(256, 105, 4)
    dot3 = shapes.circle(276, 105, 4)
    dots_path = f"{dot1} {dot2} {dot3}"
    events.append(
        f"Dialogue: 0,{_ass_time(t_stable_s)},{_ass_time(t_stable_e)},Shape,,0,0,0,,"
        f"{{{fade_tag}\\an7\\pos(0,0)\\bord0\\shad0\\1c{LINE_ASS_COLOR}\\1a&H30&\\p1}}{dots_path}{{\\p0}}"
    )

    # 2. Title (bila ada): teks kecil gelap di atas angka (y=210)
    if title:
        events.append(
            f"Dialogue: 1,{_ass_time(t_stable_s)},{_ass_time(t_stable_e)},Sans,,0,0,0,,"
            f"{{{fade_tag}\\an5\\pos(540,210)\\bord0\\shad0\\c{MUTED_DARK_ASS_COLOR}\\fs32}}{title}"
        )

    # 3. Label (bila ada): teks kecil di bawah angka (y=500)
    if label:
        events.append(
            f"Dialogue: 1,{_ass_time(t_stable_s)},{_ass_time(t_stable_e)},Sans,,0,0,0,,"
            f"{{{fade_tag}\\an5\\pos(540,500)\\bord0\\shad0\\c{MUTED_DARK_ASS_COLOR}\\fs36}}{label}"
        )

    # 4. Angka count-up bertingkat
    num_steps = min(28, max(16, int(round(count * 18.0))))
    frames_in_count = max(1, f_count_end - f_shrink_end)
    total_stable_ms = (f_grow_start - f_shrink_end) / fps * 1000.0

    for i in range(num_steps):
        p_step = i / float(num_steps)
        val_step = from_val + (to_val - from_val) * _ease_out(p_step)
        formatted_val = _format_number(val_step, decimals)

        step_f_start = f_shrink_end + int(round(i * frames_in_count / float(num_steps)))
        step_f_end = f_shrink_end + int(round((i + 1) * frames_in_count / float(num_steps)))
        if step_f_end <= step_f_start:
            step_f_end = step_f_start + 1

        t_s = _frame_start_time(step_f_start, fps)
        t_e = _frame_start_time(step_f_end, fps)

        # Fade-in pada langkah count-up yang jatuh di dalam jendela fade_ms awal
        step_t_start_ms = (step_f_start - f_shrink_end) / fps * 1000.0
        step_t_end_ms = (step_f_end - f_shrink_end) / fps * 1000.0
        step_fade = ""
        if fade_ms > 0 and step_t_start_ms < fade_ms:
            a_start = int(round(max(0.0, min(1.0, 1.0 - step_t_start_ms / fade_ms)) * 255.0))
            a_end = int(round(max(0.0, min(1.0, 1.0 - step_t_end_ms / fade_ms)) * 255.0))
            step_dur_ms = max(1, int(round((step_f_end - step_f_start) / fps * 1000.0)))
            step_fade = f"\\alpha&H{a_start:02X}&\\t(0,{step_dur_ms},\\alpha&H{a_end:02X}&)"
        elif f_grow_start <= f_count_end and fade_ms > 0 and step_t_end_ms > total_stable_ms - fade_ms:
            # Bila tidak ada fase hold, langkah terakhir count-up melakukan fade-out
            fade_out_start_ms = total_stable_ms - fade_ms
            a_out_start = int(round(max(0.0, min(1.0, (step_t_start_ms - fade_out_start_ms) / fade_ms)) * 255.0))
            a_out_end = int(round(max(0.0, min(1.0, (step_t_end_ms - fade_out_start_ms) / fade_ms)) * 255.0))
            step_dur_ms = max(1, int(round((step_f_end - step_f_start) / fps * 1000.0)))
            step_fade = f"\\alpha&H{a_out_start:02X}&\\t(0,{step_dur_ms},\\alpha&H{a_out_end:02X}&)"

        suffix_tag = f"{{\\fs110}}{suffix}" if suffix else ""
        num_text = f"{{{step_fade}\\an5\\pos(540,360)\\bord0\\shad0\\c{DARK_ASS_COLOR}\\fs220}}{formatted_val}{suffix_tag}"
        events.append(
            f"Dialogue: 2,{_ass_time(t_s)},{_ass_time(t_e)},Sans,,0,0,0,,{num_text}"
        )

    # Fase hold: nilai TEPAT to_val dari akhir count sampai mulai grow (dengan fade-out 120 ms)
    if f_grow_start > f_count_end:
        t_hold_s = _frame_start_time(f_count_end, fps)
        t_hold_e = _frame_start_time(f_grow_start, fps)
        final_val_str = _format_number(to_val, decimals)
        suffix_tag = f"{{\\fs110}}{suffix}" if suffix else ""
        hold_fade = f"\\fad(0,{fade_ms})" if fade_ms > 0 else ""
        hold_text = f"{{{hold_fade}\\an5\\pos(540,360)\\bord0\\shad0\\c{DARK_ASS_COLOR}\\fs220}}{final_val_str}{suffix_tag}"
        events.append(
            f"Dialogue: 2,{_ass_time(t_hold_s)},{_ass_time(t_hold_e)},Sans,,0,0,0,,{hold_text}"
        )

    # 5. Pelengkap sudut membulat jendela video pada keadaan stabil (dengan fade-in dan fade-out)
    corners_path = _rounded_corner_caps(
        win["x"], win["y"], win["w"], win["h"], CORNER_RADIUS
    )
    events.append(
        f"Dialogue: 3,{_ass_time(t_stable_s)},{_ass_time(t_stable_e)},Shape,,0,0,0,,"
        f"{{{fade_tag}\\an7\\pos(0,0)\\bord0\\shad0\\1c{CREAM_ASS_COLOR}\\1a&H00&\\p1}}{corners_path}{{\\p0}}"
    )

    return events


def _rounded_corner_caps(x: float, y: float, w: float, h: float, r: float) -> str:
    """Bangun path ASS untuk 4 pelengkap sudut krem di luar sudut membulat."""
    # Bezier kappa untuk seperempat lingkaran
    d = r * shapes.KAPPA

    # Top-Left corner cap
    tl = (
        f"m {x:.2f} {y:.2f} "
        f"l {x + r:.2f} {y:.2f} "
        f"b {x + r - d:.2f} {y:.2f} {x:.2f} {y + r - d:.2f} {x:.2f} {y + r:.2f} "
        f"l {x:.2f} {y:.2f}"
    )

    # Top-Right corner cap
    tr = (
        f"m {x + w:.2f} {y:.2f} "
        f"l {x + w:.2f} {y + r:.2f} "
        f"b {x + w:.2f} {y + r - d:.2f} {x + w - r + d:.2f} {y:.2f} {x + w - r:.2f} {y:.2f} "
        f"l {x + w:.2f} {y:.2f}"
    )

    # Bottom-Right corner cap
    br = (
        f"m {x + w:.2f} {y + h:.2f} "
        f"l {x + w - r:.2f} {y + h:.2f} "
        f"b {x + w - r + d:.2f} {y + h:.2f} {x + w:.2f} {y + h - r + d:.2f} {x + w:.2f} {y + h - r:.2f} "
        f"l {x + w:.2f} {y + h:.2f}"
    )

    # Bottom-Left corner cap
    bl = (
        f"m {x:.2f} {y + h:.2f} "
        f"l {x:.2f} {y + h - r:.2f} "
        f"b {x:.2f} {y + h - r + d:.2f} {x + r - d:.2f} {y + h:.2f} {x + r:.2f} {y + h:.2f} "
        f"l {x:.2f} {y + h:.2f}"
    )

    return f"{tl} {tr} {br} {bl}"
