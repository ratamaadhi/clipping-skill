"""Layout sadar wajah (Langkah 4a) — geometri murni, stdlib saja.

Masalah yang diselesaikan: caption dan overlay tidak boleh menutupi wajah
pembicara. Deteksi wajah (OpenCV) dan penulisan EDL dikerjakan modul lain;
modul ini hanya menghitung POSISI dari data yang sudah ada:

  face_track + jadwal punch + kotak elemen  ->  caption + slot overlay

Semua koordinat adalah piksel keluaran 1080x1920 SEBELUM punch. Wajah
diperbesar `FACE_INFLATE` lalu diskalakan terhadap pusat zoom (540, 960)
dengan skala punch MAKSIMUM pada shot itu (aturan rencana Langkah 4); audit
memakai skala punch yang berlaku PER FRAME, bukan maksimum.

**Zona aman platform masih [P].** `SAFE = {"top": 250, "bottom": 480,
"right": 120}` berasal dari panduan umum Reels/TikTok, BUKAN dari
spesifikasi resmi yang diverifikasi. Angka ini adalah konstanta satu tempat
dan harus diukur/diverifikasi sebelum dipakai sebagai janji produk.

Konstanta `SLOTS` juga nilai awal rencana: `top_safe=(60, 260, 960, 300)` dan
`mid_low=(60, 1000, 960, 240)` (x, y, w, h). Keduanya dapat dikoreksi dengan
alasan terukur tanpa mengubah pemanggil.

Modul ini sengaja TIDAK membaca/menulis EDL, TIDAK memanggil ffmpeg/OpenCV,
dan TIDAK menghitung lebar teks dari font. Kotak caption datang dari pemanggil
(`block_w`, `block_h`); integrasi font/EDL dikerjakan Langkah 4b.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

__all__ = [
    "CANVAS",
    "CAPTION_CANDIDATES_Y",
    "CAPTION_SHRINK",
    "FACE_INFLATE",
    "LayoutError",
    "Rect",
    "SAFE",
    "SLOTS",
    "SLOT_ORDER",
    "audit",
    "caption_rect",
    "compute_layout",
    "forbidden_zones",
    "max_punch_scale",
    "place_caption",
    "place_overlay",
    "punch_scale_at",
    "shots",
]

CANVAS = (1080, 1920)

# [P] Panduan umum Reels/TikTok (atas 250 px, bawah 480 px, kanan 120 px),
# BELUM diverifikasi ke spesifikasi resmi. Lihat docstring modul.
SAFE = {"top": 250, "bottom": 480, "right": 120}

# Wajah diperbesar total 8% (4% tiap sisi) sebelum skala punch diterapkan.
FACE_INFLATE = 0.08

# Kandidat pusat-y caption, berurutan: bawah-aman lebih dulu, lalu atas.
CAPTION_CANDIDATES_Y = (1400.0, 330.0)

# Bila kedua kandidat memotong wajah: coba kandidat pertama pada 85%.
CAPTION_SHRINK = 0.85

# Slot overlay awal (x, y, w, h) dalam piksel keluaran. Nilai rencana,
# diaudit di Langkah 4/5; lihat docstring modul.
SLOTS = {
    "top_safe": (60, 260, 960, 300),
    "mid_low": (60, 1000, 960, 240),
}

# Urutan slot per jenis overlay. `pullback` tidak memakai slot: jendela video
# hasil pull-back ditentukan `props`/`rect` pemanggil (Langkah 5b), dan
# `zoom_through_text` sengaja menutup seluruh frame sebagai efek teks.
SLOT_ORDER = {
    "ui_panel": ("top_safe", "mid_low"),
    "phone_frame": ("top_safe", "mid_low"),
    "chart_grow": ("top_safe", "mid_low"),
    "checklist": ("top_safe", "mid_low"),
    "pullback": (),
    "zoom_through_text": (),
}

# Jenis yang tidak dikenal memakai urutan yang sama dengan kartu UI; ini
# eksplisit supaya 4b tidak perlu menebak.
_DEFAULT_SLOT_ORDER = ("top_safe", "mid_low")


class LayoutError(ValueError):
    """Kesalahan validasi geometri layout (nama kelas dipakai tes/pemanggil)."""


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LayoutError(f"{name} harus angka berhingga, dapat {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise LayoutError(f"{name} harus angka berhingga, dapat {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _num(value, name)
    if out <= 0.0:
        raise LayoutError(f"{name} harus > 0, dapat {value!r}")
    return out


def _require_rect(value: Any, name: str) -> "Rect":
    if not isinstance(value, Rect):
        raise LayoutError(f"{name} harus Rect, dapat {type(value).__name__}")
    return value


def _rects(value: Any, name: str) -> list["Rect"]:
    if value is None:
        return []
    if isinstance(value, Rect):
        return [value]
    if not isinstance(value, (list, tuple)):
        raise LayoutError(f"{name} harus Rect, daftar Rect, atau None")
    out: list[Rect] = []
    for i, item in enumerate(value):
        out.append(_require_rect(item, f"{name}[{i}]"))
    return out


@dataclass(frozen=True, slots=True)
class Rect:
    """Kotak sumbu-sejajar di ruang keluaran 1080x1920 (piksel).

    `w` dan `h` wajib > 0 dan semua nilai berhingga; pelanggaran melempar
    `LayoutError` (turunan `ValueError`) dengan pesan yang menyebut nilainya.
    Kotak yang hanya bersentuhan di tepi TIDAK dianggap beririsan: piksel
    bersama tidak ada.
    """

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        x = _num(self.x, "Rect.x")
        y = _num(self.y, "Rect.y")
        w = _num(self.w, "Rect.w")
        h = _num(self.h, "Rect.h")
        if w <= 0.0 or h <= 0.0:
            raise LayoutError(
                f"Rect.w dan Rect.h harus > 0, dapat w={self.w!r} h={self.h!r}"
            )
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "w", w)
        object.__setattr__(self, "h", h)

    def intersection_area(self, other: "Rect") -> float:
        other = _require_rect(other, "other")
        iw = min(self.x + self.w, other.x + other.w) - max(self.x, other.x)
        ih = min(self.y + self.h, other.y + other.h) - max(self.y, other.y)
        if iw <= 0.0 or ih <= 0.0:
            return 0.0
        return iw * ih

    def intersects(self, other: "Rect") -> bool:
        return self.intersection_area(other) > 0.0

    def contains(self, other: "Rect") -> bool:
        other = _require_rect(other, "other")
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.x + other.w <= self.x + self.w
            and other.y + other.h <= self.y + self.h
        )

    def inflated(self, frac: float) -> "Rect":
        """Perbesar total `frac` (0,08 = +8% lebar dan tinggi, 4% tiap sisi)."""
        frac = _num(frac, "frac")
        if 1.0 + frac <= 0.0:
            raise LayoutError(f"frac harus > -1, dapat {frac!r}")
        w = self.w * (1.0 + frac)
        h = self.h * (1.0 + frac)
        return Rect(self.x - (w - self.w) / 2.0, self.y - (h - self.h) / 2.0, w, h)

    def scaled_about(self, cx: float, cy: float, s: float) -> "Rect":
        cx = _num(cx, "cx")
        cy = _num(cy, "cy")
        s = _positive(s, "s")
        return Rect(
            cx + (self.x - cx) * s,
            cy + (self.y - cy) * s,
            self.w * s,
            self.h * s,
        )

    def union_bbox(self, other: "Rect") -> "Rect":
        other = _require_rect(other, "other")
        x0 = min(self.x, other.x)
        y0 = min(self.y, other.y)
        x1 = max(self.x + self.w, other.x + other.w)
        y1 = max(self.y + self.h, other.y + other.h)
        return Rect(x0, y0, x1 - x0, y1 - y0)


def _clip_to_canvas(rect: Rect) -> Rect | None:
    x0 = max(rect.x, 0.0)
    y0 = max(rect.y, 0.0)
    x1 = min(rect.x + rect.w, float(CANVAS[0]))
    y1 = min(rect.y + rect.h, float(CANVAS[1]))
    if x1 <= x0 or y1 <= y0:
        return None
    return Rect(x0, y0, x1 - x0, y1 - y0)


# ---------------------------------------------------------------------------
# Shot
# ---------------------------------------------------------------------------


def shots(face_track: Any, duration: float) -> list[tuple[float, float, list[Rect]]]:
    """Ubah `face_track` menjadi `[(t0, t1, [Rect, ...]), ...]`.

    Entri `face_track` berbentuk `{"t": detik, "faces": [{"x","y","w","h"}]}`
    dan harus urut naik ketat di dalam `[0, duration]`. Shot ke-i berlaku dari
    `t_i` sampai `t_{i+1}`, shot terakhir sampai `duration`. Entri tanpa wajah
    menghasilkan shot tanpa zona (bukan error): frame tanpa wajah tetap boleh
    punya caption di posisi bawaan.

    Wajah dengan `w == 0` atau `h == 0` dilewati (deteksi degenerat, tidak
    punya luas); nilai negatif ditolak karena itu bukan kotak.
    """
    duration = _positive(duration, "duration")
    if face_track is None:
        return []
    if not isinstance(face_track, (list, tuple)):
        raise LayoutError("face_track harus daftar entri")

    entries: list[tuple[float, list[Rect]]] = []
    prev: float | None = None
    for i, entry in enumerate(face_track):
        if not isinstance(entry, dict) or "t" not in entry or "faces" not in entry:
            raise LayoutError(
                f"face_track[{i}] harus {{'t': float, 'faces': [...]}}"
            )
        t = _num(entry["t"], f"face_track[{i}].t")
        if t < 0.0 or t > duration:
            raise LayoutError(
                f"face_track[{i}].t={t!r} di luar [0, {duration!r}]"
            )
        if prev is not None and t <= prev:
            raise LayoutError(
                f"face_track harus monoton naik ketat; "
                f"t[{i}]={t!r} <= t[{i - 1}]={prev!r}"
            )
        raw_faces = entry["faces"]
        if not isinstance(raw_faces, (list, tuple)):
            raise LayoutError(f"face_track[{i}].faces harus daftar")
        faces: list[Rect] = []
        for j, face in enumerate(raw_faces):
            if not isinstance(face, dict):
                raise LayoutError(f"face_track[{i}].faces[{j}] harus objek")
            missing = [k for k in ("x", "y", "w", "h") if k not in face]
            if missing:
                raise LayoutError(
                    f"face_track[{i}].faces[{j}] tidak memuat {missing}"
                )
            x = _num(face["x"], f"face_track[{i}].faces[{j}].x")
            y = _num(face["y"], f"face_track[{i}].faces[{j}].y")
            w = _num(face["w"], f"face_track[{i}].faces[{j}].w")
            h = _num(face["h"], f"face_track[{i}].faces[{j}].h")
            if w < 0.0 or h < 0.0:
                raise LayoutError(
                    f"face_track[{i}].faces[{j}] punya w/h negatif: {w!r}, {h!r}"
                )
            if w == 0.0 or h == 0.0:
                continue
            faces.append(Rect(x, y, w, h))
        entries.append((t, faces))
        prev = t

    out: list[tuple[float, float, list[Rect]]] = []
    for i, (t, faces) in enumerate(entries):
        end = entries[i + 1][0] if i + 1 < len(entries) else duration
        out.append((t, end, faces))
    return out


# ---------------------------------------------------------------------------
# Punch
# ---------------------------------------------------------------------------


def _punch_entries(punch: Any) -> list[tuple[float, float]]:
    if not punch:
        return []
    if not isinstance(punch, (list, tuple)):
        raise LayoutError("punch harus daftar {'t','scale'}")
    entries: list[tuple[float, float]] = []
    for i, item in enumerate(punch):
        if not isinstance(item, dict) or "t" not in item or "scale" not in item:
            raise LayoutError(f"punch[{i}] harus {{'t': float, 'scale': float}}")
        t = _num(item["t"], f"punch[{i}].t")
        if t < 0.0:
            raise LayoutError(f"punch[{i}].t harus >= 0, dapat {t!r}")
        scale = _positive(item["scale"], f"punch[{i}].scale")
        entries.append((t, scale))
    entries.sort(key=lambda item: item[0])
    return entries


def punch_scale_at(punch: Any, t: float, *, fps: float | None = None) -> float:
    """Skala punch yang berlaku pada waktu `t`.

    **Semantik yang disimpulkan dari `motion.zoompan_filter`** (dibaca, bukan
    ditebak): ekspresinya

        if(lt(in,f_1), s_0, if(lt(in,f_2), s_1, ... s_last))

    dengan `f_i = max(0, round(t_i * fps))`. Jadi:

    * tidak ada ramp nilai/interpolasi sama sekali — skala konstan di antara
      dua batas dan berubah sebagai LANGKAH KERAS;
    * "ramp" satu-satunya adalah kuantisasi ke frame: perubahan terjadi pada
      frame `round(t_i * fps)`, bukan tepat di detik `t_i`;
    * bila `in >= f_i`, event ke-i sudah berlaku (perbandingan `lt` ketat).

    Tanpa `fps`, fungsi ini memakai versi kontinu dari langkah yang sama
    (`t_i <= t`). Dengan `fps`, ia meniru ekspresi frame demi frame; itulah
    yang dipakai `audit` supaya `t=4,37` pada 30 fps diperlakukan sebagai frame
    131 walau `131/30 < 4,37` di floating point.

    `punch` kosong/None berarti tanpa punch: skala 1,0.
    """
    t = _num(t, "t")
    entries = _punch_entries(punch)
    if not entries:
        return 1.0

    if fps is not None:
        fps = _positive(fps, "fps")
        frame = int(round(t * fps))
        thresholds = [max(0, int(round(tt * fps))) for tt, _ in entries]
        for i in range(1, len(entries)):
            if frame < thresholds[i]:
                return entries[i - 1][1]
        return entries[-1][1]

    for i in range(1, len(entries)):
        if t < entries[i][0]:
            return entries[i - 1][1]
    return entries[-1][1]


def _punch_scale_at_frame(punch: Any, frame: int, fps: float) -> float:
    """Skala punch untuk INDEKS frame input (tanpa pembulatan ulang)."""
    entries = _punch_entries(punch)
    if not entries:
        return 1.0
    thresholds = [max(0, int(round(tt * fps))) for tt, _ in entries]
    for i in range(1, len(entries)):
        if frame < thresholds[i]:
            return entries[i - 1][1]
    return entries[-1][1]


def max_punch_scale(punch: Any, t0: float, t1: float) -> float:
    """Skala punch maksimum pada jendela `[t0, t1]` (inklusif).

    Dipakai untuk zona wajah per shot: caption harus aman terhadap punch
    terbesar yang mungkin terjadi di shot itu. Audit TIDAK memakai fungsi ini;
    audit memakai skala per frame.
    """
    t0 = _num(t0, "t0")
    t1 = _num(t1, "t1")
    if t1 < t0:
        raise LayoutError(f"t1={t1!r} harus >= t0={t0!r}")
    entries = _punch_entries(punch)
    if not entries:
        return 1.0
    best = punch_scale_at(punch, t0)
    for t, scale in entries:
        if t0 < t <= t1:
            best = max(best, scale)
    return best


# ---------------------------------------------------------------------------
# Zona terlarang dan kotak caption
# ---------------------------------------------------------------------------


def forbidden_zones(
    shot_faces: Iterable[Rect],
    max_scale: float,
    *,
    inflate: float = FACE_INFLATE,
) -> list[Rect]:
    """Zona wajah: inflasi `inflate`, skala punch, lalu potong ke kanvas.

    Urutannya penting: inflasi dulu (ruang sebelum punch), baru
    `scaled_about(540, 960, max_scale)` karena zoompan memperbesar di sekitar
    pusat frame, lalu clipping ke `CANVAS`. Zona yang seluruhnya keluar kanvas
    dibuang.
    """
    max_scale = _positive(max_scale, "max_scale")
    frac = _num(inflate, "inflate")
    out: list[Rect] = []
    for i, face in enumerate(shot_faces):
        face = _require_rect(face, f"shot_faces[{i}]")
        clipped = _clip_to_canvas(
            face.inflated(frac).scaled_about(
                CANVAS[0] / 2.0, CANVAS[1] / 2.0, max_scale
            )
        )
        if clipped is not None:
            out.append(clipped)
    return out


def caption_rect(
    block_w: float,
    block_h: float,
    y_center: float,
    *,
    scale: float = 1.0,
    cx: float = 540.0,
) -> Rect:
    """Kotak blok caption dari ukuran yang diberikan pemanggil.

    Langkah 4a tidak menghitung lebar/tinggi dari font: `block_w`/`block_h`
    datang dari pemanggil (mis. hasil `kinetic.layout_phrase` + outline).
    `(cx, y_center)` adalah pusat blok; `scale` memperkecil/memperbesar blok
    di sekitar pusatnya (dipakai `CAPTION_SHRINK`).
    """
    block_w = _positive(block_w, "block_w")
    block_h = _positive(block_h, "block_h")
    y_center = _num(y_center, "y_center")
    scale = _positive(scale, "scale")
    cx = _num(cx, "cx")
    w = block_w * scale
    h = block_h * scale
    return Rect(cx - w / 2.0, y_center - h / 2.0, w, h)


def _anchor_in_safe(y_center: float, rect: Rect) -> bool:
    """Apakah kandidat dianggap "di dalam zona aman" untuk caption.

    Prioritas di `place_caption` adalah: tidak memotong wajah > di zona aman >
    kandidat lebih awal. Untuk sumbu-y yang dipakai adalah ANCHOR (`y_center`,
    yaitu pusat blok), bukan tepi atas/bawah kotak: rencana menetapkan
    `y=1400` sebagai "bawah-aman", padahal blok dua baris (193,2 px) yang
    dipusatkan di 1400 berakhir di 1496,6 — 56,6 px melewati garis
    `1920 - SAFE["bottom"] = 1440`. Kalau tepi kotak yang dipakai, kandidat
    bawaan pertama selalu "tidak aman" dan prioritas zona aman berubah jadi
    menggeser caption ke atas, kebalikan dari aturan kandidat berurutan.
    Karena itu vertikal memakai anchor; horizontal memakai tepi kotak
    (`SAFE["right"]`), karena lebar blok memang punya tepi nyata.

    Catatan: SAFE masih [P] (lihat docstring modul). Bila SAFE.bottom
    dikoreksi >= 520 px, aturan ini perlu ditinjau ulang di 4b.
    """
    if not (SAFE["top"] <= y_center <= CANVAS[1] - SAFE["bottom"]):
        return False
    if rect.x < 0.0:
        return False
    return rect.x + rect.w <= CANVAS[0] - SAFE["right"]


def place_caption(
    zones: Iterable[Rect],
    block_w: float,
    block_h: float,
    *,
    candidates: Sequence[float] = CAPTION_CANDIDATES_Y,
    shrink: float = CAPTION_SHRINK,
) -> dict[str, Any]:
    """Pilih `{y, scale, reason}` caption yang tidak memotong zona wajah.

    Urutan keputusan:

    1. Kandidat dicoba berurutan (`CAPTION_CANDIDATES_Y` = 1400 lalu 330).
       Kandidat yang tidak memotong satu pun zona menang.
    2. Di antara kandidat bebas, yang berada di zona aman dipilih lebih dulu
       (prioritas: tidak memotong wajah > zona aman > kandidat lebih awal).
    3. Bila SEMUA kandidat memotong, kandidat pertama dicoba pada skala
       `CAPTION_SHRINK` (0,85). Bila bebas, itu yang dipakai.
    4. Bila masih memotong, kandidat dengan irisan total terkecil dipilih pada
       skala 1,0 (seri -> kandidat lebih awal). Caption TIDAK PERNAH dibuang.
       Percobaan shrink yang gagal tidak ikut dibandingkan pada langkah ini.

    `reason` selalu menjelaskan jalur yang dipakai:
    `"clear:y=..."`, `"clear_safe:y=..."`, `"shrink:y=..."`, atau
    `"min_overlap:y=..."`.
    """
    zones = _rects(zones, "zones")
    block_w = _positive(block_w, "block_w")
    block_h = _positive(block_h, "block_h")
    shrink = _positive(shrink, "shrink")
    if not candidates:
        raise LayoutError("candidates tidak boleh kosong")
    ys = [_num(y, f"candidates[{i}]") for i, y in enumerate(candidates)]

    rects = [caption_rect(block_w, block_h, y) for y in ys]
    clear = [
        i for i, rect in enumerate(rects)
        if not any(rect.intersects(zone) for zone in zones)
    ]
    if clear:
        safe = [i for i in clear if _anchor_in_safe(ys[i], rects[i])]
        idx = safe[0] if safe else clear[0]
        prefix = "clear_safe" if safe else "clear"
        return {"y": ys[idx], "scale": 1.0, "reason": f"{prefix}:y={ys[idx]:g}"}

    shrunk = caption_rect(block_w, block_h, ys[0], scale=shrink)
    if not any(shrunk.intersects(zone) for zone in zones):
        return {"y": ys[0], "scale": shrink, "reason": f"shrink:y={ys[0]:g}"}

    areas = [sum(rect.intersection_area(zone) for zone in zones) for rect in rects]
    least = min(areas)
    # Dua kandidat dengan geometri sama bisa berbeda 1e-14 karena floating
    # point (mis. luas blok 135240,00000000003 vs 135240,0). Seri berarti
    # kandidat lebih awal, jadi bandingkan dengan toleransi relatif kecil.
    eps = 1e-9 * max(1.0, abs(least))
    idx = next(i for i, area in enumerate(areas) if area <= least + eps)
    return {
        "y": ys[idx],
        "scale": 1.0,
        "reason": f"min_overlap:y={ys[idx]:g}",
    }


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


def _slot_rect(value: Any, name: str) -> Rect:
    if isinstance(value, Rect):
        return value
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise LayoutError(f"slot {name!r} harus (x, y, w, h)")
    return Rect(value[0], value[1], value[2], value[3])


def _fit_in_slot(size: tuple[float, float], slot: Rect) -> Rect:
    w, h = size
    scale = min(1.0, slot.w / w, slot.h / h)
    fw = w * scale
    fh = h * scale
    return Rect(
        slot.x + (slot.w - fw) / 2.0,
        slot.y + (slot.h - fh) / 2.0,
        fw,
        fh,
    )


def _place_overlay(
    kind: str,
    size: tuple[float, float],
    zones: list[Rect],
    caption_rects: list[Rect],
    taken: list[Rect],
    *,
    slots: dict[str, Any],
    order: Sequence[str] | None,
) -> tuple[Rect | None, str | None]:
    names = tuple(order) if order is not None else SLOT_ORDER.get(
        kind, _DEFAULT_SLOT_ORDER
    )
    built: dict[str, Rect] = {}
    for name in names:
        if name not in slots:
            raise LayoutError(f"slot {name!r} tidak dikenal (ada: {sorted(slots)})")
        built[name] = _slot_rect(slots[name], name)

    for name in names:
        fitted = _fit_in_slot(size, built[name])
        if any(fitted.intersects(zone) for zone in zones):
            continue
        if any(fitted.intersects(rect) for rect in caption_rects):
            continue
        if any(fitted.intersects(rect) for rect in taken):
            continue
        return fitted, name
    return None, None


def place_overlay(
    kind: str,
    size: tuple[float, float],
    zones: Iterable[Rect],
    caption_rect_: Any,
    taken: Iterable[Rect],
    *,
    slots: dict[str, Any] = SLOTS,
    order: Sequence[str] | None = None,
) -> Rect | None:
    """Slot bebas pertama untuk overlay, atau `None` bila tidak ada.

    Urutan slot per jenis (`SLOT_ORDER`): `ui_panel`, `phone_frame`,
    `chart_grow`, dan `checklist` mencoba `top_safe` lalu `mid_low`. `pullback`
    dan `zoom_through_text` tidak memakai slot (pull-back punya jendela video
    sendiri; zoom-through menutup frame), jadi hasilnya selalu `None`. Jenis
    tak dikenal memakai urutan kartu UI yang sama.

    `size=(w, h)` adalah ukuran yang diminta. Overlay TIDAK pernah diperbesar
    melebihi permintaan; bila tidak muat di slot, ia diperkecil dengan rasio
    tetap (`min(1, slot.w/w, slot.h/h)`) dan dipusatkan di slot. Hasil tidak
    boleh memotong zona wajah, kotak caption, atau rect lain di `taken`.

    `caption_rect_` boleh satu `Rect`, daftar `Rect`, atau `None`. Daftar
    dipakai `compute_layout` untuk overlay yang hidup lintas shot: caption
    bisa berpindah posisi antar shot, dan memakai bounding-box gabungan akan
    memblokir slot yang sebenarnya aman.
    """
    if not isinstance(kind, str) or not kind:
        raise LayoutError("kind harus string tidak kosong")
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        raise LayoutError("size harus (w, h)")
    w = _positive(size[0], "size[0]")
    h = _positive(size[1], "size[1]")
    zones = _rects(zones, "zones")
    caption_rects = _rects(caption_rect_, "caption_rect_")
    taken = _rects(taken, "taken")
    fitted, _ = _place_overlay(
        kind, (w, h), zones, caption_rects, taken,
        slots=slots, order=order,
    )
    return fitted


# ---------------------------------------------------------------------------
# compute_layout
# ---------------------------------------------------------------------------


def _blocks(caption_blocks: Any) -> list[dict[str, float]]:
    if caption_blocks is None:
        return []
    if not isinstance(caption_blocks, (list, tuple)):
        raise LayoutError("caption_blocks harus daftar")
    out: list[dict[str, float]] = []
    prev_end: float | None = None
    for i, block in enumerate(caption_blocks):
        if not isinstance(block, dict):
            raise LayoutError(f"caption_blocks[{i}] harus objek")
        missing = [k for k in ("start", "end", "w", "h") if k not in block]
        if missing:
            raise LayoutError(f"caption_blocks[{i}] tidak memuat {missing}")
        start = _num(block["start"], f"caption_blocks[{i}].start")
        end = _num(block["end"], f"caption_blocks[{i}].end")
        w = _positive(block["w"], f"caption_blocks[{i}].w")
        h = _positive(block["h"], f"caption_blocks[{i}].h")
        if start < 0.0:
            raise LayoutError(f"caption_blocks[{i}].start harus >= 0")
        if end <= start:
            raise LayoutError(
                f"caption_blocks[{i}].end={end!r} harus > start={start!r}"
            )
        if prev_end is not None and start < prev_end - 1e-9:
            raise LayoutError(
                f"caption_blocks harus urut dan tidak tumpang tindih: "
                f"blok {i} mulai {start!r} < akhir blok sebelumnya {prev_end!r}"
            )
        out.append({"start": start, "end": end, "w": w, "h": h})
        prev_end = end
    return out


def _layout_shots(face_track: Any, duration: float) -> list[tuple[float, float, list[Rect]]]:
    result = shots(face_track, duration)
    if result and result[0][0] > 0.0:
        # face_track yang tidak mulai di 0 (mis. sampel pertama jatuh di frame
        # pertama yang punya wajah) tidak boleh membuat caption tanpa entri.
        result.insert(0, (0.0, result[0][0], []))
    return result


def _active_caption(entries: list[dict[str, Any]], phrase_start: float) -> dict[str, Any] | None:
    chosen: dict[str, Any] | None = None
    for entry in entries:
        if float(entry["t"]) <= phrase_start + 1e-12:
            chosen = entry
        else:
            break
    if chosen is None and entries:
        chosen = entries[0]
    return chosen


def _overlay_window(overlay: dict[str, Any], duration: float) -> tuple[float, float]:
    start = _num(overlay.get("start", 0.0), "overlay.start")
    end = _num(overlay.get("end", duration), "overlay.end")
    a = max(0.0, start)
    b = min(duration, end)
    return a, b


def _overlay_size(
    overlay: dict[str, Any], order: Sequence[str], slots: dict[str, Any]
) -> tuple[float, float]:
    if "size" in overlay:
        size = overlay["size"]
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise LayoutError("overlay.size harus (w, h)")
        return (_positive(size[0], "overlay.size[0]"),
                _positive(size[1], "overlay.size[1]"))
    first = _slot_rect(slots[order[0]], order[0])
    return (first.w, first.h)


def compute_layout(
    face_track: Any,
    punch: Any,
    duration: float,
    *,
    caption_blocks: Any,
    overlays: Any,
) -> dict[str, Any]:
    """Layout deterministik satu klip: caption per shot + slot overlay.

    Keluaran::

        {"version": 1,
         "caption": [{"t", "an", "y", "scale", "reason"}, ...],
         "overlays": [{"index", "rect": {x,y,w,h} | None, "reason"}, ...]}

    **Caption satu entri per shot.** `t` = awal shot. Aturan konsumsi (dipakai
    `audit` dan nanti `kinetic` di 4b): untuk sebuah frasa, keputusan yang
    berlaku adalah entri terakhir dengan `entry["t"] <= frasa.start`. Dengan
    aturan itu, batas shot yang jatuh DI TENGAH frasa tidak pernah mengubah
    caption di tengah frasa: entri shot baru punya `t` setelah awal frasa itu,
    jadi baru berlaku pada frasa BERIKUTNYA. Keputusan shot yang tidak memiliki
    frasa baru (mis. frasa panjang menyeberang shot) membawa posisi sebelumnya
    dengan `reason="no_caption"`.

    Bila satu shot memiliki beberapa frasa, ukuran yang dipakai adalah blok
    TERBESAR (max w, max h) supaya keputusan aman untuk semuanya. Tanpa
    `face_track` (None/kosong): satu entri bawaan `y=1400`, `scale=1,0`,
    `reason="no_face_track"`; tanpa `caption_blocks`: `caption` kosong.

    Overlay: satu keluaran per item `overlays`, berurutan. `size` opsional
    (bawaan: ukuran slot pertama). Jendela `start`/`end` opsional (bawaan:
    seluruh klip). Zona wajah untuk overlay = gabungan shot yang beririsan
    dengan jendelanya, masing-masing memakai skala punch maksimum pada
    irisan itu; kotak caption yang harus dihindari = semua frasa yang
    beririsan dengan jendela, memakai keputusan caption yang berlaku untuk
    frasa itu. Slot yang sudah dipakai overlay sebelumnya masuk `taken`.
    Alasan `rect=None`: `"no_slot_by_kind"`, `"empty_window"`, atau
    `"no_free_slot"`.

    Catatan skema: `schema/edl.schema.json` versi sekarang hanya
    mendeklarasikan `layout.version` + `layout.caption[]` (t/an/y/x/size) dan
    belum mengenal `scale`/`reason` maupun `layout.overlays`. Keluaran 4a
    sengaja aditif; penyelarasan skema adalah pekerjaan integrasi 4b.
    """
    duration = _positive(duration, "duration")
    blocks = _blocks(caption_blocks)
    shot_list = _layout_shots(face_track, duration)
    has_faces = bool(shot_list)

    caption: list[dict[str, Any]] = []
    if blocks:
        if not has_faces:
            caption = [{
                "t": 0.0,
                "an": 2,
                "y": float(CAPTION_CANDIDATES_Y[0]),
                "scale": 1.0,
                "reason": "no_face_track",
            }]
        else:
            carried = {
                "y": float(CAPTION_CANDIDATES_Y[0]),
                "scale": 1.0,
            }
            for t0, t1, faces in shot_list:
                owned = [
                    block for block in blocks
                    if t0 <= block["start"] < t1
                ]
                if owned:
                    block_w = max(block["w"] for block in owned)
                    block_h = max(block["h"] for block in owned)
                    zones = forbidden_zones(
                        faces, max_punch_scale(punch, t0, t1)
                    )
                    decision = place_caption(zones, block_w, block_h)
                    carried = {"y": decision["y"], "scale": decision["scale"]}
                    reason = decision["reason"]
                else:
                    reason = "no_caption"
                caption.append({
                    "t": float(t0),
                    "an": 2,
                    "y": float(carried["y"]),
                    "scale": float(carried["scale"]),
                    "reason": reason,
                })

    overlay_out: list[dict[str, Any]] = []
    taken: list[Rect] = []
    raw_overlays = overlays or []
    if not isinstance(raw_overlays, (list, tuple)):
        raise LayoutError("overlays harus daftar")
    for i, overlay in enumerate(raw_overlays):
        if not isinstance(overlay, dict):
            raise LayoutError(f"overlays[{i}] harus objek")
        kind = overlay.get("type")
        if not isinstance(kind, str) or not kind:
            raise LayoutError(f"overlays[{i}].type harus string tidak kosong")

        order = SLOT_ORDER.get(kind, _DEFAULT_SLOT_ORDER)
        if not order:
            overlay_out.append({"index": i, "rect": None, "reason": "no_slot_by_kind"})
            continue

        a, b = _overlay_window(overlay, duration)
        if b <= a:
            overlay_out.append({"index": i, "rect": None, "reason": "empty_window"})
            continue

        size = _overlay_size(overlay, order, SLOTS)

        zones: list[Rect] = []
        for s0, s1, faces in shot_list:
            if s0 < b and s1 > a:
                lo = max(s0, a)
                hi = min(s1, b)
                zones.extend(
                    forbidden_zones(faces, max_punch_scale(punch, lo, hi))
                )

        caption_rects: list[Rect] = []
        for block in blocks:
            if block["start"] < b and block["end"] > a:
                entry = _active_caption(caption, block["start"])
                if entry is None:
                    continue
                caption_rects.append(
                    caption_rect(
                        block["w"], block["h"], float(entry["y"]),
                        scale=float(entry["scale"]),
                    )
                )

        fitted, slot_name = _place_overlay(
            kind, size, zones, caption_rects, taken,
            slots=SLOTS, order=order,
        )
        if fitted is None:
            overlay_out.append({"index": i, "rect": None, "reason": "no_free_slot"})
            continue
        taken.append(fitted)
        overlay_out.append({
            "index": i,
            "rect": {"x": fitted.x, "y": fitted.y, "w": fitted.w, "h": fitted.h},
            "reason": f"slot={slot_name}",
        })

    return {"version": 1, "caption": caption, "overlays": overlay_out}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _layout_caption_entries(layout: dict[str, Any]) -> list[dict[str, float]]:
    if not isinstance(layout, dict) or "caption" not in layout:
        raise LayoutError("layout harus objek dengan kunci 'caption'")
    entries = layout["caption"]
    if not isinstance(entries, (list, tuple)):
        raise LayoutError("layout.caption harus daftar")
    out: list[dict[str, float]] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or "t" not in entry or "y" not in entry:
            raise LayoutError(f"layout.caption[{i}] harus memuat 't' dan 'y'")
        t = _num(entry["t"], f"layout.caption[{i}].t")
        y = _num(entry["y"], f"layout.caption[{i}].y")
        scale = _positive(
            entry.get("scale", 1.0), f"layout.caption[{i}].scale"
        )
        out.append({"t": t, "y": y, "scale": scale})
    out.sort(key=lambda item: item["t"])
    return out


def _layout_overlay_rects(layout: dict[str, Any]) -> dict[int, Rect]:
    if "overlays" not in layout:
        return {}
    raw = layout["overlays"]
    if not isinstance(raw, (list, tuple)):
        raise LayoutError("layout.overlays harus daftar")
    out: dict[int, Rect] = {}
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "index" not in item or "rect" not in item:
            raise LayoutError(
                f"layout.overlays[{i}] harus memuat 'index' dan 'rect'"
            )
        if not isinstance(item["index"], int) or isinstance(item["index"], bool):
            raise LayoutError(f"layout.overlays[{i}].index harus integer")
        rect = item["rect"]
        if rect is None:
            continue
        if not isinstance(rect, dict):
            raise LayoutError(f"layout.overlays[{i}].rect harus objek atau None")
        missing = [k for k in ("x", "y", "w", "h") if k not in rect]
        if missing:
            raise LayoutError(f"layout.overlays[{i}].rect tidak memuat {missing}")
        out[item["index"]] = Rect(rect["x"], rect["y"], rect["w"], rect["h"])
    return out


def audit(
    layout: dict[str, Any],
    face_track: Any,
    punch: Any,
    duration: float,
    caption_blocks: Any,
    overlays: Any,
    fps: float,
) -> dict[str, Any]:
    """Hitung tabrakan per FRAME pada layout yang diberikan.

    Tiga metrik, semuanya "frame unik" (satu frame dihitung sekali per jenis
    tabrakan):

    * `caption_face_frames` — frame dengan caption aktif yang memotong zona
      wajah. Zona memakai skala punch yang berlaku PADA FRAME ITU (bukan
      maksimum shot).
    * `overlay_face_frames` — frame dengan minimal satu overlay aktif yang
      memotong zona wajah.
    * `caption_overlay_frames` — frame dengan caption aktif dan overlay aktif
      yang saling memotong.

    Caption aktif = frasa yang memuat waktu frame (`start <= t < end`), dengan
    keputusan "entri terakhir yang `t <= frasa.start`" (aturan yang sama dengan
    `compute_layout`). Overlay aktif = jendela input `[start, end]` inklusif,
    sama seperti `enable='between(t,...)'` ffmpeg. `face_track` kosong berarti
    tidak ada zona wajah.

    `worst` berisi maksimal 10 tabrakan dengan luas terbesar:
    `{"kind", "frame", "t", "area"}` (+ `"index"` untuk tabrakan overlay),
    diurutkan luas menurun lalu frame naik.
    """
    duration = _positive(duration, "duration")
    fps = _positive(fps, "fps")
    blocks = _blocks(caption_blocks)
    captions = _layout_caption_entries(layout)
    placed = _layout_overlay_rects(layout)
    shot_list = shots(face_track, duration)

    phrase_rects: list[tuple[float, float, Rect]] = []
    for block in blocks:
        entry = _active_caption(captions, block["start"])
        if entry is None:
            continue
        phrase_rects.append((
            block["start"],
            block["end"],
            caption_rect(
                block["w"], block["h"], entry["y"], scale=entry["scale"]
            ),
        ))

    raw_overlays = overlays or []
    if not isinstance(raw_overlays, (list, tuple)):
        raise LayoutError("overlays harus daftar")
    overlay_windows: list[tuple[int, Rect, float, float]] = []
    for index, rect in placed.items():
        if index < 0 or index >= len(raw_overlays):
            raise LayoutError(
                f"layout.overlays index {index} tidak punya input overlays[{index}]"
            )
        overlay = raw_overlays[index]
        if not isinstance(overlay, dict):
            raise LayoutError(f"overlays[{index}] harus objek")
        a, b = _overlay_window(overlay, duration)
        if b > a:
            overlay_windows.append((index, rect, a, b))

    caption_face_frames = 0
    overlay_face_frames = 0
    caption_overlay_frames = 0
    worst: list[dict[str, Any]] = []

    n_frames = int(round(duration * fps))
    shot_i = 0
    phrase_i = 0
    for frame in range(n_frames):
        t = frame / fps

        while shot_i < len(shot_list) and shot_list[shot_i][1] <= t:
            shot_i += 1
        faces: list[Rect] = []
        if shot_i < len(shot_list):
            t0, t1, shot_faces = shot_list[shot_i]
            if t0 <= t < t1:
                faces = shot_faces
        zones = forbidden_zones(
            faces, _punch_scale_at_frame(punch, frame, fps)
        ) if faces else []

        while phrase_i < len(phrase_rects) and phrase_rects[phrase_i][1] <= t:
            phrase_i += 1
        caption: Rect | None = None
        if phrase_i < len(phrase_rects):
            start, end, rect = phrase_rects[phrase_i]
            if start <= t < end:
                caption = rect

        visible: list[tuple[int, Rect]] = [
            (index, rect) for index, rect, a, b in overlay_windows
            if a - 1e-12 <= t <= b + 1e-12
        ]

        if caption is not None:
            area = 0.0
            for zone in zones:
                area = max(area, caption.intersection_area(zone))
            if area > 0.0:
                caption_face_frames += 1
                worst.append({
                    "kind": "caption_face", "frame": frame,
                    "t": round(t, 6), "area": area,
                })

            best_index = None
            area = 0.0
            for index, rect in visible:
                hit = caption.intersection_area(rect)
                if hit > area:
                    area = hit
                    best_index = index
            if area > 0.0:
                caption_overlay_frames += 1
                worst.append({
                    "kind": "caption_overlay", "frame": frame,
                    "t": round(t, 6), "area": area, "index": best_index,
                })

        if visible and zones:
            best_index = None
            area = 0.0
            for index, rect in visible:
                for zone in zones:
                    hit = rect.intersection_area(zone)
                    if hit > area:
                        area = hit
                        best_index = index
            if area > 0.0:
                overlay_face_frames += 1
                worst.append({
                    "kind": "overlay_face", "frame": frame,
                    "t": round(t, 6), "area": area, "index": best_index,
                })

    worst.sort(key=lambda item: (-item["area"], item["frame"], item["kind"]))
    return {
        "caption_face_frames": caption_face_frames,
        "overlay_face_frames": overlay_face_frames,
        "caption_overlay_frames": caption_overlay_frames,
        "worst": worst[:10],
    }
