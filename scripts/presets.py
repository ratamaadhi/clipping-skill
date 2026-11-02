"""Preset efek referensi (Langkah 5b): `overlays[]` EDL -> dokumen ASS sendiri.

Preset adalah item `{"type": ..., "start": s, "end": e, "props": {...}, "rect"?}`
pada `clips[].overlays[]`, dirender libass sebagai dokumen ASS terpisah (tanpa
Chromium, D-011). Modul ini murni: tidak menjalankan ffmpeg, tidak menulis
berkas, tidak mengubah `shapes.py`. Renderer menulis dokumen yang dikembalikan
ke `captions/<id>.fx.ass` dan menambah SATU filter `subtitles` sebelum caption
(lihat `scripts/render.py`).

Kontrak umum (docs/MOTION-TIER2-PLAN.md Langkah 5b):

* waktu `start`/`end` = timeline OUTPUT, dipotong ke `[0, durasi_klip]`;
* overlay yang seluruhnya di luar klip dilewati dengan satu peringatan, bukan
  exception; `end <= start` setelah pemotongan -> `PresetError`;
* tipe yang tidak dikenal modul ini diabaikan tanpa peringatan (tier-1 `vs`
  tetap ditangani `scripts/motion.py`);
* font tidak tersedia / keluarga salah -> preset dilewati dengan satu
  peringatan, TIDAK ada exception;
* deterministik: EDL sama -> string identik.

Dokumen ASS dibangun dengan `shapes.ass_document(...)` lalu baris `Style`
yang dibutuhkan disisipkan sebelum `[Events]`. `shapes.py` tidak diubah:
style bentuk (`Shape`) tetap ada dan tidak dipakai. Klip yang hanya punya
`zoom_through_text` tetap mendapat SATU `Style: Serif,...` (dokumen byte-
identik dengan Langkah 5b-1); `Style: Sans,...` hanya ditambahkan bila ada
overlay `checklist`.

`zoom_through_text` (efek referensi #09): skala 80% -> 320% selama `duration`
dengan `\\t(...,accel=2,...)`, alfa 1 -> 0 pada 40% terakhir. `accel=2`
dipilih karena sudah DIUKUR pada `shapes.wipe_tags` (Langkah 5a): `accel=2`
memperlambat awal persis seperti `x^2` (55 px pada frame ke-4 vs 213 px
linear). Skala karena itu naik monoton dan terasa "menghentak" di akhir —
gerak zoom-through yang dimaksud. Teks yang melewati tepi frame pada skala
besar memang perilaku yang diinginkan (kamera menembus teks).

`checklist` (efek referensi #07) — versi DATAR (tanpa blur/kaca/emoji):

* kartu `rounded_rect` radius 40, `#14161B` pada opasitas 0,86; judul kiri,
  penghitung `n of N` kanan; tiap butir = cincin abu `#5B616B` + teks;
* pada `done_at` cincin berganti menjadi cakram hijau `#22C55E` + centang
  putih (`shapes.check_mark`) dengan pop spring 0 -> 108% -> 100%
  (`lib/spring.py`; rantai `\\t` disampel per frame);
* font Archivo Black bundel untuk semua teks (`Fontsize = em x
  cell_height_ratio`, sama dengan caption);
* SEMUA waktu diturunkan dari frame `round(t * fps)` SEKALI di akhir
  (`docs/PIPELINE.md` §7). Event penghitung dimulai pada sentidetik PERTAMA
  sesudah timestamp frame sebelumnya, sehingga libass menampilkannya tepat
  pada frame `round(done_at * fps)` — dibuktikan piksel di
  `tests/test_presets_checklist_render.py`. Menulis `round(t, 2)` biasa bisa
  membulatkan ke bawah/atas dan menggeser satu frame;
* masuk 0,30 s: translasi memakai `\\move` yang SAMA untuk semua elemen
  (libass tidak bisa menganimasikan `\\pos` lewat `\\t`; `\\move` terbukti
  kaku di oracle) + alfa ease-out (`accel=0,5`) dari transparan ke penuh;
  keluar 0,20 s fade;
* `shapes.shape_event` TIDAK dipakai untuk elemen yang bergerak: fungsi itu
  selalu menulis `\\pos`, dan libass mengabaikan `\\move` bila `\\pos` ada
  (diukur di probe 5b-2). Baris Dialogue dirakit di sini dengan `\\move`
  (masuk) atau `\\pos` (sesudah masuk);
* cincin = dua kontur lingkaran berlawanan arah (aturan isi nonzero yang
  diukur di Langkah 5a). Satu lingkaran saja akan menjadi cakram penuh dan
  menutupi latar kartu di tengah;
* pop 0 -> 108% -> 100% memakai `\\fscx/\\fscy` pada path lingkaran yang
  dipusatkan di (0, 0) dan `\\an7\\pos(cx, cy)`: skala libass berpusat di
  posisi itu (diukur: diameter 44 -> 48 -> 44 px tanpa geser pusat);
* peredupan teks butir setelah dicentang TIDAK dipakai: spesifikasi
  menandainya opsional, dan menghilangkannya membuat satu event per butir
  tetap cukup untuk seluruh status.

`chart_grow` (efek referensi #10) — kartu grafik datar (tanpa gradien/blur):

* kartu memakai keluarga visual yang SAMA dengan `checklist` (`#14161B`,
  opasitas 0,86, radius 40); sumbu x tipis abu, 4 garis grid horizontal
  sangat redup, label Archivo Black kecil di bawah tiap simpul;
* garis data kuning `#FFD60A` tebal 10 px dari `shapes.polyline` (lingkaran
  sambungan di tiap simpul interior); titik ujung = cakram kuning jari-jari
  14 dengan cincin gelap tipis (`\\bord` pada path);
* kepala garis bergerak dengan ease-in-out KOSINUS
  `(1 - cos(pi t)) / 2`, disampel 16 segmen. Setiap segmen adalah satu
  `\\t(t0,t1,1,\\clip(...))` linear; titik ujung memakai `\\move` per segmen
  dengan waktu frame yang SAMA, sehingga x(t) garis dan x(t) titik identik
  (selisih hanya pembulatan koordinat `\\clip` libass, <= 1 px). Ini
  menghindari dua masalah yang diukur di 5b-2: `\\move` linear (tidak bisa
  ease) dan `\\pos` yang membatalkan `\\move`;
* tag baru muncul tepat pada frame `start + ENTRY + grow` (pop spring
  0 -> ~108% -> 100%, pola `checklist`) dan menempel di titik ujung;
* masuk 0,30 s dengan `\\move` identik 60 px + alfa ease-out; keluar fade
  0,20 s. Semua waktu diturunkan dari frame `round(t * fps)` dan ditulis ke
  ASS lewat helper yang sama dengan `checklist`;
* maksimum 16 event titik + 15 event lain = 31 Dialogue untuk 8 titik.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from . import captions as _tier1
from . import shapes
from .lib import fontmetrics
from .lib import spring

__all__ = [
    "BUNDLED_FONT",
    "CHECKLIST_FONT",
    "DEFAULT_COLOUR",
    "DEFAULT_DURATION",
    "DEFAULT_SIZE_EM",
    "PRESET_TYPES",
    "REGISTRY",
    "PresetError",
    "build_fx_ass",
]

# ---------------------------------------------------------------------------
# Konstanta (satu tempat, dipakai tes)
# ---------------------------------------------------------------------------

# Font kedua (bukan caption): DM Serif Display Italic, OFL 1.1.
BUNDLED_FONT = "assets/fonts/DMSerifDisplay-Italic.ttf"
EXPECTED_FAMILY = "DM Serif Display"

PLAY_RES = (1080, 1920)
STYLE_NAME = "Serif"
LAYER = 0

# `zoom_through_text`: 0,8 -> 3,2 (80% -> 320%).
SCALE_START = 80.0
SCALE_END = 320.0
SCALE_ACCEL = 2.0
FADE_FRACTION = 0.4

DEFAULT_COLOUR = "#FFFFFF"
DEFAULT_SIZE_EM = 160.0
MIN_SIZE_EM = 60.0
MAX_SIZE_EM = 400.0
DEFAULT_DURATION = 0.7
MIN_DURATION = 0.4
MAX_DURATION = 1.5

MIN_TEXT = 1
MAX_TEXT = 24

# Props yang dikenal `zoom_through_text`. Kunci lain ditolak: typo seperti
# `size` (bukan `size_em`) tidak boleh diam-diam memakai nilai bawaan.
_ZOOM_PROPS = ("text", "colour", "size_em", "duration")

# --- `checklist` (efek referensi #07) -------------------------------------
#
# Semua angka visual di SATU tempat. Asal: struktur efek #07 pada video
# referensi (kartu gelap, cincin per butir, centang, penghitung), versi DATAR
# tanpa blur/kaca. Nilai geometri dipilih agar 6 butir muat di zona kartu
# bawaan `layout` (x=60, w=960) dan tidak menabrak zona aman bawah.

CHECKLIST_FONT = "assets/fonts/ArchivoBlack-Regular.ttf"
EXPECTED_CHECKLIST_FAMILY = "Archivo Black"
CHECK_STYLE = "Sans"

CARD_X = 60.0
CARD_Y = 260.0
CARD_W = 960.0
CARD_RADIUS = 40.0
CARD_COLOUR = "#14161B"
CARD_OPACITY = 0.86
CARD_PAD_X = 44.0
CARD_PAD_Y = 32.0
CARD_HEADER_H = 72.0
CARD_ROW_H = 64.0

RING_RADIUS = 22.0
RING_THICKNESS = 6.0          # cincin: jari-jari dalam 16
RING_COLOUR = "#5B616B"
GREEN_COLOUR = "#22C55E"
CHECK_COLOUR = "#FFFFFF"
CHECK_SIZE = 22.0
CHECK_THICKNESS = 5.0
CHECK_ROW_GAP = 20.0

TITLE_COLOUR = "#F5F7FA"
ITEM_COLOUR = "#E5E7EB"
COUNTER_COLOUR = "#9CA3AF"

CHECK_TITLE_EM = 44.0
CHECK_ITEM_EM = 36.0
CHECK_COUNTER_EM = 32.0
CHECK_TITLE_GAP = 24.0

CHECK_ENTRY = 0.30
CHECK_ENTRY_OFFSET = 60.0
CHECK_EXIT = 0.20
CHECK_ENTRY_ACCEL = 0.5       # ease-out: cepat di awal, melambat di akhir

CHECK_MIN_ITEMS = 2
CHECK_MAX_ITEMS = 6
CHECK_MAX_TITLE = 28
CHECK_MAX_ITEM_TEXT = 28
CHECK_MAX_DIALOGUES = 40

CHECK_POP_MAX_SEGMENTS = 10   # sama dengan batas rantai `kinetic.spring_chain`

# Layer: kartu 0 < lingkaran (cincin/hijau) < centang < teks.
CARD_LAYER = 0
RING_LAYER = 1
CHECK_LAYER = 2
TEXT_LAYER = 3

_CHECK_PROPS = ("title", "items")
_CHECK_ITEM_KEYS = ("text", "done_at")
_CHECK_RECT_KEYS = ("x", "y", "w", "h")

# --- `chart_grow` (efek referensi #10) -------------------------------------
#
# Semua angka visual di SATU tempat. Asal: struktur efek #10 pada video
# referensi (kartu grafik dengan sumbu + label, polyline yang tumbuh, titik
# ujung + tag yang mengikuti), versi DATAR tanpa gradien/blur. Kartu memakai
# palet `checklist` supaya dua preset tier-2 tidak terlihat dari dua produk
# berbeda.

CHART_CARD_X = 60.0
CHART_CARD_Y = 260.0
CHART_CARD_W = 960.0
CHART_CARD_H = 520.0
CHART_CARD_RADIUS = CARD_RADIUS
CHART_CARD_OPACITY = CARD_OPACITY
CHART_PAD_X = 44.0
CHART_PAD_Y = 32.0

CHART_TITLE_H = 56.0
CHART_TITLE_EM = 36.0
CHART_LABEL_H = 52.0
CHART_LABEL_EM = 28.0
CHART_LABEL_GAP = 12.0        # jarak plot -> puncak teks label
CHART_LABEL_SIDE_GAP = 8.0    # margin label ke tepi kartu / label tetangga
CHART_PLOT_INSET_X = 24.0
CHART_PLOT_MIN_H = 120.0

CHART_GRID_LINES = 4
CHART_AXIS_THICKNESS = 2.0
CHART_GRID_THICKNESS = 2.0

CHART_LINE_THICKNESS = 10.0
CHART_DOT_RADIUS = 14.0
CHART_DOT_RING = 3.0

CHART_ENTRY = 0.30
CHART_ENTRY_OFFSET = 60.0
CHART_ENTRY_ACCEL = 0.5       # ease-out alfa, sama dengan checklist
CHART_EXIT = 0.20

CHART_GROW_DEFAULT = 1.2
CHART_GROW_MIN = 0.6
CHART_GROW_MAX = 2.5
# Jumlah segmen `\t`/`\move`. 16 sampel kosinus per 0,6 s = 37,5 ms/segmen
# (>= 1 frame @30 fps); galat titik-vs-garis antar-node < 1 px karena kedua
# fungsi linear identik di antara node.
CHART_GROW_SEGMENTS = 16

CHART_TAG_EM = 34.0
CHART_TAG_PAD_X = 24.0
CHART_TAG_H = 64.0
CHART_TAG_RADIUS = 18.0
CHART_TAG_GAP = 16.0
# Ruang di atas plot untuk gelembung tag: jari-jari titik + jarak + tinggi.
CHART_TAG_BAND = CHART_DOT_RADIUS + CHART_TAG_GAP + CHART_TAG_H

CHART_MIN_LABELS = 3
CHART_MAX_LABELS = 8
CHART_MAX_LABEL_CHARS = 10
CHART_MAX_TAG_CHARS = 16
CHART_MAX_TITLE = 28
CHART_MAX_DIALOGUES = 40

CHART_LINE_COLOUR = "#FFD60A"
CHART_AXIS_COLOUR = "#5B616B"
CHART_GRID_COLOUR = "#2A2E35"
CHART_LABEL_COLOUR = "#9CA3AF"
CHART_TITLE_COLOUR = "#F5F7FA"
CHART_DOT_RING_COLOUR = "#14161B"
CHART_TAG_BG_COLOUR = "#1B1F27"
CHART_TAG_TEXT_COLOUR = "#FFD60A"
CHART_TAG_BORDER_COLOUR = "#FFD60A"

# Layer: kartu/grid/sumbu 0 < garis 1 < titik 2 < teks 3 < tag 4/5.
CHART_CARD_LAYER = 0
CHART_GRID_LAYER = 0
CHART_AXIS_LAYER = 0
CHART_LINE_LAYER = 1
CHART_DOT_LAYER = 2
CHART_TEXT_LAYER = 3
CHART_TAG_BUBBLE_LAYER = 4
CHART_TAG_TEXT_LAYER = 5

_CHART_PROPS = ("labels", "values", "tag", "title", "grow")

# --- `ui_panel` (efek referensi #03 "ui world") ----------------------------
#
# Semua angka visual di SATU tempat. Asal: struktur efek #03 pada video
# referensi (kartu krem membulat menutup zona atas, header kartu dengan judul
# Archivo Black gelap, baris thumbnail pastel membulat yang muncul berurutan
# dengan jeda 80 ms, tag pil kuning dengan teks gelap, bilah input putih
# dengan teks abu-gelap), versi DATAR tanpa gradien/blur/emoji.

UI_CARD_X = 60.0
UI_CARD_Y = 260.0
UI_CARD_W = 960.0
UI_CARD_RADIUS = 48.0
UI_CARD_COLOUR = "#F6EEDC"
UI_CARD_OPACITY = 0.96
UI_CARD_MAX_H = 700.0

UI_PAD_X = 45.0
UI_PAD_Y = 32.0

UI_TITLE_H = 56.0
UI_TITLE_EM = 36.0
UI_TITLE_GAP = 20.0
UI_TITLE_COLOUR = "#1B1B1F"

UI_TAG_H = 40.0
UI_TAG_RADIUS = 20.0
UI_TAG_EM = 24.0
UI_TAG_PAD_X = 18.0
UI_TAG_BG_COLOUR = "#FFD60A"
UI_TAG_TEXT_COLOUR = "#1B1B1F"

UI_THUMB_W = 270.0
UI_THUMB_H = 170.0
UI_THUMB_RADIUS = 20.0
UI_THUMB_GAP_X = 30.0
UI_THUMB_GAP_Y = 20.0
UI_GAP_HEADER_THUMBS = 24.0

UI_INPUT_H = 60.0
UI_INPUT_RADIUS = 18.0
UI_INPUT_EM = 30.0
UI_INPUT_PAD_X = 24.0
UI_GAP_THUMBS_INPUT = 24.0
UI_INPUT_BG_COLOUR = "#FFFFFF"
UI_INPUT_TEXT_COLOUR = "#4B5563"

UI_ENTRY = 0.30
UI_ENTRY_OFFSET = 60.0
UI_ENTRY_ACCEL = 0.5
UI_EXIT = 0.20
UI_THUMB_STAGGER = 0.080

UI_DEFAULT_THUMBS = 3
UI_MIN_THUMBS = 1
UI_MAX_THUMBS = 6
UI_MIN_TITLE_CHARS = 1
UI_MAX_TITLE_CHARS = 28
UI_MIN_TAG_CHARS = 1
UI_MAX_TAG_CHARS = 16
UI_MAX_INPUT_CHARS = 28
UI_MAX_DIALOGUES = 40

# Palet pastel tetap (>= 6 warna)
UI_PALETTE: tuple[str, ...] = (
    "#FFB5A7",  # Pastel Peach / Coral
    "#B7E4C7",  # Pastel Mint
    "#CDB4DB",  # Pastel Lavender
    "#A2D2FF",  # Pastel Sky Blue
    "#FDE2B8",  # Pastel Butter / Lemon
    "#F1B5CB",  # Pastel Rose
)

# Layer: kartu 0 < thumbnail 1 < bilah input 1 < teks input 2 < judul 2 < gelembung tag 3 < teks tag 4
UI_CARD_LAYER = 0
UI_THUMB_LAYER = 1
UI_INPUT_BAR_LAYER = 1
UI_INPUT_TEXT_LAYER = 2
UI_TITLE_LAYER = 2
UI_TAG_BUBBLE_LAYER = 3
UI_TAG_TEXT_LAYER = 4

_UI_PROPS = ("title", "tag", "thumbs", "input")

# Peta escape SAMA dengan `captions._escape`/`kinetic._escape`. `{`/`}` membuka
# blok override ASS dan `\\` memulai perintah di dalamnya; koma aman karena
# `Text` adalah field ke-10 (terakhir).
_ESCAPE_MAP = {"{": "(", "}": ")", "\\": "/"}


class PresetError(ValueError):
    """Props/waktu overlay preset tidak valid. Pesan menyebut indeks + tipe."""


# ---------------------------------------------------------------------------
# Util validasi
# ---------------------------------------------------------------------------

def _error(index: int, type_name: str, message: str) -> None:
    raise PresetError(f"overlay[{index}] tipe {type_name!r}: {message}")


def _finite_number(
    value: Any,
    label: str,
    index: int,
    type_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Konversi ke float berhingga; bool ditolak (True bukan angka 1)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(index, type_name, f"{label} harus angka berhingga, dapat {value!r}")
    number = float(value)
    if not math.isfinite(number):
        _error(index, type_name, f"{label} harus berhingga, dapat {value!r}")
    if minimum is not None and number < minimum:
        _error(
            index, type_name,
            f"{label} harus >= {minimum:g}, dapat {value!r}",
        )
    if maximum is not None and number > maximum:
        _error(
            index, type_name,
            f"{label} harus <= {maximum:g}, dapat {value!r}",
        )
    return number


def _escape_text(text: str) -> str:
    out = str(text)
    for source, target in _ESCAPE_MAP.items():
        out = out.replace(source, target)
    return out


def _fmt_number(value: float) -> str:
    """Format koordinat/tag tanpa nol ekor: 540.0 -> '540', 540.5 -> '540.5'."""
    number = round(float(value), 2)
    if number == 0.0:
        number = 0.0
    return f"{number:g}"


def _default_font_path() -> Path:
    return Path(__file__).resolve().parent.parent / BUNDLED_FONT


def _default_checklist_font_path() -> Path:
    return Path(__file__).resolve().parent.parent / CHECKLIST_FONT


def _load_font(
    kind: str, font_path: Any
) -> tuple[fontmetrics.Font | None, str | None]:
    """Muat font preset `kind` ("serif" | "sans"); gagal -> satu peringatan.

    `font_path` (bila diisi) menimpa path bundel untuk SEMUA jenis: tes bisa
    memaksa font yang salah dan memastikan preset yang membutuhkannya
    dilewati, bukan diam-diam memakai font fallback.
    """
    if kind == "serif":
        path = Path(font_path) if font_path is not None else _default_font_path()
        expected = EXPECTED_FAMILY
        label = "zoom_through_text"
    else:
        path = (
            Path(font_path) if font_path is not None
            else _default_checklist_font_path()
        )
        expected = EXPECTED_CHECKLIST_FAMILY
        # Satu font untuk preset sans: peringatan menyebut semua preset
        # yang terpengaruh supaya pengguna tidak bingung.
        label = "checklist/chart_grow/ui_panel"
    try:
        font = fontmetrics.Font.load(path)
    except (fontmetrics.FontError, OSError) as exc:
        return None, f"preset {label} dilewati: font {path} tidak terbaca ({exc})"
    if font.family != expected:
        return None, (
            f"preset {label} dilewati: font {path} bukan keluarga "
            f"{expected!r} (terbaca {font.family!r})"
        )
    return font, None


# ---------------------------------------------------------------------------
# Validasi props + waktu per tipe
# ---------------------------------------------------------------------------

def _rect_center(
    value: Any, index: int, type_name: str
) -> tuple[float, float]:
    if not isinstance(value, dict):
        _error(index, type_name, f"rect harus objek {{x,y,w,h}}, dapat {value!r}")
    out: dict[str, float] = {}
    for name in ("x", "y", "w", "h"):
        if name not in value:
            _error(index, type_name, f"rect['{name}'] wajib ada, dapat {value!r}")
        out[name] = _finite_number(
            value[name], f"rect['{name}']", index, type_name
        )
    if out["w"] <= 0.0 or out["h"] <= 0.0:
        _error(index, type_name, f"rect['w'] dan rect['h'] harus > 0, dapat {value!r}")
    return out["x"] + out["w"] / 2.0, out["y"] + out["h"] / 2.0


def _zoom_props(
    props: Any, index: int, type_name: str
) -> dict[str, Any]:
    """Validasi ketat props `zoom_through_text`; pesan menyebut nama props."""
    if not isinstance(props, dict):
        _error(index, type_name, f"props harus objek, dapat {props!r}")

    unknown = sorted(set(props) - set(_ZOOM_PROPS))
    if unknown:
        _error(
            index, type_name,
            f"props tidak dikenal: {unknown[0]!r} "
            f"(dikenal: {', '.join(_ZOOM_PROPS)})",
        )

    if "text" not in props:
        _error(index, type_name, "props['text'] wajib ada")
    text = props["text"]
    if not isinstance(text, str):
        _error(index, type_name, f"props['text'] harus string, dapat {text!r}")
    length = len(text)
    if not MIN_TEXT <= length <= MAX_TEXT:
        _error(
            index, type_name,
            f"props['text'] harus {MIN_TEXT}..{MAX_TEXT} karakter, dapat {length}",
        )
    if "\n" in text or "\r" in text:
        _error(index, type_name, f"props['text'] tidak boleh memuat newline: {text!r}")

    colour_raw = props.get("colour", DEFAULT_COLOUR)
    if not isinstance(colour_raw, str):
        _error(
            index, type_name,
            f"props['colour'] harus '#RRGGBB', dapat {colour_raw!r}",
        )
    try:
        colour = shapes.colour(colour_raw)
    except ValueError:
        _error(
            index, type_name,
            f"props['colour'] harus '#RRGGBB', dapat {colour_raw!r}",
        )

    size_em = _finite_number(
        props.get("size_em", DEFAULT_SIZE_EM),
        "props['size_em']", index, type_name,
        minimum=MIN_SIZE_EM, maximum=MAX_SIZE_EM,
    )
    duration = _finite_number(
        props.get("duration", DEFAULT_DURATION),
        "props['duration']", index, type_name,
        minimum=MIN_DURATION, maximum=MAX_DURATION,
    )

    return {
        "text": _escape_text(text),
        "colour": colour,
        "size_em": size_em,
        "duration": duration,
    }


def _zoom_event(plan: dict[str, Any], font: fontmetrics.Font) -> str:
    """Satu baris `Dialogue` untuk `zoom_through_text`."""
    # libass menafsirkan Fontsize/\fs sebagai tinggi sel, bukan em: kalikan
    # dengan cell_height_ratio seperti `kinetic._style_font_size`.
    size_ass = round(plan["size_em"] * font.cell_height_ratio, 2)
    animation_ms = int(round(plan["duration"] * 1000.0))
    fade_start_ms = int(round(plan["duration"] * (1.0 - FADE_FRACTION) * 1000.0))
    x, y = plan["pos"]

    override = (
        f"{{\\an5\\pos({_fmt_number(x)},{_fmt_number(y)})"
        f"\\fs{size_ass:g}"
        f"\\fscx{SCALE_START:g}\\fscy{SCALE_START:g}"
        f"\\bord0\\shad0\\alpha&H00&\\c{plan['colour']}"
        f"\\t(0,{animation_ms},{SCALE_ACCEL:g},"
        f"\\fscx{SCALE_END:g}\\fscy{SCALE_END:g})"
        f"\\t({fade_start_ms},{animation_ms},\\alpha&HFF&)}}"
    )
    return (
        f"Dialogue: {LAYER},{_ass_time(plan['start'])},"
        f"{_ass_time(plan['event_end'])},{STYLE_NAME},,0,0,0,,"
        f"{override}{plan['text']}"
    )


def _ass_time(t: float) -> str:
    """Format waktu ASS yang sama dengan tier-1/kinetic (`captions._ass_time`)."""
    return _tier1._ass_time(t)


# ---------------------------------------------------------------------------
# `checklist`: validasi props, rect, waktu
# ---------------------------------------------------------------------------

def _checklist_props(
    props: Any, index: int, type_name: str
) -> tuple[str, list[dict[str, Any]]]:
    """Validasi ketat props `checklist`; pesan menyebut indeks/tipe/nama props."""
    if not isinstance(props, dict):
        _error(index, type_name, f"props harus objek, dapat {props!r}")

    unknown = sorted(set(props) - set(_CHECK_PROPS))
    if unknown:
        _error(
            index, type_name,
            f"props tidak dikenal: {unknown[0]!r} "
            f"(dikenal: {', '.join(_CHECK_PROPS)})",
        )

    if "title" not in props:
        _error(index, type_name, "props['title'] wajib ada")
    title = props["title"]
    if not isinstance(title, str):
        _error(index, type_name, f"props['title'] harus string, dapat {title!r}")
    if not 1 <= len(title) <= CHECK_MAX_TITLE:
        _error(
            index, type_name,
            f"props['title'] harus 1..{CHECK_MAX_TITLE} karakter, dapat {len(title)}",
        )
    if "\n" in title or "\r" in title:
        _error(index, type_name, f"props['title'] tidak boleh memuat newline: {title!r}")

    if "items" not in props:
        _error(index, type_name, "props['items'] wajib ada")
    raw_items = props["items"]
    if isinstance(raw_items, (str, bytes)) or not isinstance(raw_items, list):
        _error(index, type_name, f"props['items'] harus daftar, dapat {raw_items!r}")
    if not CHECK_MIN_ITEMS <= len(raw_items) <= CHECK_MAX_ITEMS:
        _error(
            index, type_name,
            f"props['items'] harus {CHECK_MIN_ITEMS}..{CHECK_MAX_ITEMS} butir, "
            f"dapat {len(raw_items)}",
        )

    items: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            _error(
                index, type_name,
                f"props['items'][{position}] harus objek, dapat {raw!r}",
            )
        extra = sorted(set(raw) - set(_CHECK_ITEM_KEYS))
        if extra:
            _error(
                index, type_name,
                f"props['items'][{position}] kunci tidak dikenal: {extra[0]!r} "
                f"(dikenal: {', '.join(_CHECK_ITEM_KEYS)})",
            )
        for key in _CHECK_ITEM_KEYS:
            if key not in raw:
                _error(
                    index, type_name,
                    f"props['items'][{position}]['{key}'] wajib ada",
                )

        text = raw["text"]
        if not isinstance(text, str):
            _error(
                index, type_name,
                f"props['items'][{position}]['text'] harus string, dapat {text!r}",
            )
        if not 1 <= len(text) <= CHECK_MAX_ITEM_TEXT:
            _error(
                index, type_name,
                f"props['items'][{position}]['text'] harus 1.."
                f"{CHECK_MAX_ITEM_TEXT} karakter, dapat {len(text)}",
            )
        if "\n" in text or "\r" in text:
            _error(
                index, type_name,
                f"props['items'][{position}]['text'] tidak boleh memuat newline: "
                f"{text!r}",
            )

        done_at = raw["done_at"]
        if done_at is not None:
            if isinstance(done_at, bool) or not isinstance(done_at, (int, float)):
                _error(
                    index, type_name,
                    f"props['items'][{position}]['done_at'] harus angka atau null, "
                    f"dapat {done_at!r}",
                )
            if not math.isfinite(float(done_at)):
                _error(
                    index, type_name,
                    f"props['items'][{position}]['done_at'] harus berhingga, "
                    f"dapat {done_at!r}",
                )
            done_at = float(done_at)

        items.append({"text": _escape_text(text), "done_at": done_at})

    return _escape_text(title), items


def _checklist_rect(
    item: dict[str, Any],
    index: int,
    type_name: str,
    item_count: int,
) -> dict[str, float]:
    """Rect kartu (atau bawaan dari isi); validasi kanvas + tinggi minimum."""
    required_h = (
        2.0 * CARD_PAD_Y
        + CARD_HEADER_H
        + item_count * CARD_ROW_H
    )
    if "rect" not in item:
        return {"x": CARD_X, "y": CARD_Y, "w": CARD_W, "h": required_h}

    rect = item["rect"]
    if not isinstance(rect, dict):
        _error(index, type_name, f"rect harus objek {{x,y,w,h}}, dapat {rect!r}")
    unknown = sorted(set(rect) - set(_CHECK_RECT_KEYS))
    if unknown:
        _error(
            index, type_name,
            f"rect kunci tidak dikenal: {unknown[0]!r} "
            f"(dikenal: {', '.join(_CHECK_RECT_KEYS)})",
        )
    out: dict[str, float] = {}
    for name in _CHECK_RECT_KEYS:
        if name not in rect:
            _error(index, type_name, f"rect['{name}'] wajib ada, dapat {rect!r}")
        out[name] = _finite_number(
            rect[name], f"rect['{name}']", index, type_name
        )
    if out["w"] <= 0.0 or out["h"] <= 0.0:
        _error(index, type_name, f"rect['w'] dan rect['h'] harus > 0, dapat {rect!r}")

    width, height = PLAY_RES
    if (
        out["x"] < 0.0
        or out["y"] < 0.0
        or out["x"] + out["w"] > width + 1e-9
        or out["y"] + out["h"] > height + 1e-9
    ):
        _error(
            index, type_name,
            f"rect {{x={out['x']:g}, y={out['y']:g}, w={out['w']:g}, "
            f"h={out['h']:g}}} keluar kanvas {width}x{height}",
        )
    if out["h"] + 1e-9 < required_h:
        _error(
            index, type_name,
            f"rect['h'] {out['h']:g} < tinggi yang dibutuhkan {required_h:g} "
            f"(2 x {CARD_PAD_Y:g} padding + {CARD_HEADER_H:g} header + "
            f"{item_count} baris x {CARD_ROW_H:g}); kartu tidak boleh disusutkan",
        )
    return out


# ---------------------------------------------------------------------------
# `chart_grow`: validasi props, rect, geometri murni
# ---------------------------------------------------------------------------

def _chart_props(
    props: Any, index: int, type_name: str
) -> dict[str, Any]:
    """Validasi ketat props `chart_grow`; pesan menyebut nama props."""
    if not isinstance(props, dict):
        _error(index, type_name, f"props harus objek, dapat {props!r}")

    unknown = sorted(set(props) - set(_CHART_PROPS))
    if unknown:
        _error(
            index, type_name,
            f"props tidak dikenal: {unknown[0]!r} "
            f"(dikenal: {', '.join(_CHART_PROPS)})",
        )

    if "labels" not in props:
        _error(index, type_name, "props['labels'] wajib ada")
    raw_labels = props["labels"]
    if isinstance(raw_labels, (str, bytes)) or not isinstance(raw_labels, list):
        _error(index, type_name, f"props['labels'] harus daftar, dapat {raw_labels!r}")
    if not CHART_MIN_LABELS <= len(raw_labels) <= CHART_MAX_LABELS:
        _error(
            index, type_name,
            f"props['labels'] harus {CHART_MIN_LABELS}..{CHART_MAX_LABELS} label, "
            f"dapat {len(raw_labels)}",
        )

    labels: list[str] = []
    for position, raw in enumerate(raw_labels):
        if not isinstance(raw, str):
            _error(
                index, type_name,
                f"props['labels'][{position}] harus string, dapat {raw!r}",
            )
        if not 1 <= len(raw) <= CHART_MAX_LABEL_CHARS:
            _error(
                index, type_name,
                f"props['labels'][{position}] harus 1.."
                f"{CHART_MAX_LABEL_CHARS} karakter, dapat {len(raw)}",
            )
        if "\n" in raw or "\r" in raw:
            _error(
                index, type_name,
                f"props['labels'][{position}] tidak boleh memuat newline: {raw!r}",
            )
        labels.append(_escape_text(raw))

    if "values" not in props:
        _error(index, type_name, "props['values'] wajib ada")
    raw_values = props["values"]
    if isinstance(raw_values, (str, bytes)) or not isinstance(raw_values, list):
        _error(index, type_name, f"props['values'] harus daftar, dapat {raw_values!r}")
    if len(raw_values) != len(labels):
        _error(
            index, type_name,
            f"props['values'] harus panjang sama dengan labels ({len(labels)}), "
            f"dapat {len(raw_values)}",
        )
    values: list[float] = []
    for position, raw in enumerate(raw_values):
        values.append(
            _finite_number(
                raw, f"props['values'][{position}]", index, type_name
            )
        )
    low, high = min(values), max(values)
    span = high - low
    if span == 0.0 or not math.isfinite(span):
        _error(
            index, type_name,
            f"props['values'] harus punya rentang bukan nol: skala y tak "
            f"terdefinisi bila semua nilai sama ({low:g})",
        )

    if "tag" not in props:
        _error(index, type_name, "props['tag'] wajib ada")
    tag = props["tag"]
    if not isinstance(tag, str):
        _error(index, type_name, f"props['tag'] harus string, dapat {tag!r}")
    if not 1 <= len(tag) <= CHART_MAX_TAG_CHARS:
        _error(
            index, type_name,
            f"props['tag'] harus 1..{CHART_MAX_TAG_CHARS} karakter, "
            f"dapat {len(tag)}",
        )
    if "\n" in tag or "\r" in tag:
        _error(index, type_name, f"props['tag'] tidak boleh memuat newline: {tag!r}")

    title = props.get("title")
    if title is not None:
        if not isinstance(title, str):
            _error(index, type_name, f"props['title'] harus string, dapat {title!r}")
        if len(title) > CHART_MAX_TITLE:
            _error(
                index, type_name,
                f"props['title'] harus <= {CHART_MAX_TITLE} karakter, "
                f"dapat {len(title)}",
            )
        if "\n" in title or "\r" in title:
            _error(
                index, type_name,
                f"props['title'] tidak boleh memuat newline: {title!r}",
            )
        title = _escape_text(title)

    grow = _finite_number(
        props.get("grow", CHART_GROW_DEFAULT),
        "props['grow']", index, type_name,
        minimum=CHART_GROW_MIN, maximum=CHART_GROW_MAX,
    )

    return {
        "labels": labels,
        "values": values,
        "tag": _escape_text(tag),
        "title": title,
        "grow": grow,
    }


def _chart_required_height(has_title: bool) -> float:
    """Tinggi minimum kartu: padding + judul + band tag + plot + label."""
    return (
        2.0 * CHART_PAD_Y
        + (CHART_TITLE_H if has_title else 0.0)
        + CHART_TAG_BAND
        + CHART_PLOT_MIN_H
        + CHART_LABEL_H
    )


def _chart_rect(
    item: dict[str, Any],
    index: int,
    type_name: str,
    has_title: bool,
) -> dict[str, float]:
    """Rect kartu (bawaan 60,260,960,520); validasi kanvas + tinggi minimum."""
    required_h = _chart_required_height(has_title)
    if "rect" not in item:
        return {
            "x": CHART_CARD_X, "y": CHART_CARD_Y,
            "w": CHART_CARD_W, "h": CHART_CARD_H,
        }

    rect = item["rect"]
    if not isinstance(rect, dict):
        _error(index, type_name, f"rect harus objek {{x,y,w,h}}, dapat {rect!r}")
    unknown = sorted(set(rect) - set(_CHECK_RECT_KEYS))
    if unknown:
        _error(
            index, type_name,
            f"rect kunci tidak dikenal: {unknown[0]!r} "
            f"(dikenal: {', '.join(_CHECK_RECT_KEYS)})",
        )
    out: dict[str, float] = {}
    for name in _CHECK_RECT_KEYS:
        if name not in rect:
            _error(index, type_name, f"rect['{name}'] wajib ada, dapat {rect!r}")
        out[name] = _finite_number(
            rect[name], f"rect['{name}']", index, type_name
        )
    if out["w"] <= 0.0 or out["h"] <= 0.0:
        _error(index, type_name, f"rect['w'] dan rect['h'] harus > 0, dapat {rect!r}")

    width, height = PLAY_RES
    if (
        out["x"] < 0.0
        or out["y"] < 0.0
        or out["x"] + out["w"] > width + 1e-9
        or out["y"] + out["h"] > height + 1e-9
    ):
        _error(
            index, type_name,
            f"rect {{x={out['x']:g}, y={out['y']:g}, w={out['w']:g}, "
            f"h={out['h']:g}}} keluar kanvas {width}x{height}",
        )
    if out["h"] + 1e-9 < required_h:
        _error(
            index, type_name,
            f"rect['h'] {out['h']:g} < tinggi yang dibutuhkan {required_h:g} "
            f"(2 x {CHART_PAD_Y:g} padding + "
            f"{CHART_TITLE_H if has_title else 0:g} judul + "
            f"{CHART_TAG_BAND:g} band tag + {CHART_PLOT_MIN_H:g} plot + "
            f"{CHART_LABEL_H:g} label); kartu tidak boleh disusutkan",
        )
    return out


def _chart_geometry(rect: dict[str, float], has_title: bool) -> dict[str, float]:
    """Geometri plot di dalam kartu; satu sumber untuk event dan tes."""
    title_h = CHART_TITLE_H if has_title else 0.0
    return {
        "plot_x0": rect["x"] + CHART_PAD_X + CHART_PLOT_INSET_X,
        "plot_x1": rect["x"] + rect["w"] - CHART_PAD_X - CHART_PLOT_INSET_X,
        "plot_top": rect["y"] + CHART_PAD_Y + title_h + CHART_TAG_BAND,
        "plot_bottom": rect["y"] + rect["h"] - CHART_PAD_Y - CHART_LABEL_H,
        "label_y": (
            rect["y"] + rect["h"] - CHART_PAD_Y - CHART_LABEL_H + CHART_LABEL_GAP
        ),
    }


def _chart_points(
    values: list[float], geometry: dict[str, float]
) -> list[tuple[float, float]]:
    """Simpul data: x rata, y linier min->dasar, max->puncak plot."""
    count = len(values)
    x0, x1 = geometry["plot_x0"], geometry["plot_x1"]
    low, high = min(values), max(values)
    span = high - low
    height = geometry["plot_bottom"] - geometry["plot_top"]
    points = []
    for position, value in enumerate(values):
        x = x0 + (x1 - x0) * position / (count - 1)
        y = geometry["plot_bottom"] - (value - low) / span * height
        points.append((x, y))
    return points


def _chart_progress(fraction: float) -> float:
    """Ease-in-out kosinus: lambat di awal & akhir, tercepat di tengah."""
    if fraction <= 0.0:
        return 0.0
    if fraction >= 1.0:
        return 1.0
    return (1.0 - math.cos(math.pi * fraction)) / 2.0


def _chart_head_point(
    points: list[tuple[float, float]], progress: float
) -> tuple[float, float]:
    """Posisi kepala garis pada `progress` 0..1 (linear di sepanjang ruas)."""
    progress = min(1.0, max(0.0, float(progress)))
    t = progress * (len(points) - 1)
    index = min(int(math.floor(t)), len(points) - 2)
    fraction = t - index
    x0, y0 = points[index]
    x1, y1 = points[index + 1]
    return x0 + (x1 - x0) * fraction, y0 + (y1 - y0) * fraction


def _chart_grow_nodes(grow_frames: int) -> list[tuple[int, float]]:
    """(offset frame, kemajuan) untuk tiap node `\\t`/`\\move`.

    Node waktu DIKUNCI ke grid frame (`round`), jadi x(t) garis dan titik
    identik pada setiap frame yang dirender. Jumlah segmen dibatasi 16 dan
    tidak melebihi jumlah frame supaya tidak ada node duplikat.
    """
    frames = max(1, int(grow_frames))
    segments = max(1, min(CHART_GROW_SEGMENTS, frames))
    nodes: list[tuple[int, float]] = []
    for k in range(segments + 1):
        frame = int(round(k * frames / segments))
        nodes.append((frame, _chart_progress(k / segments)))
    return nodes


def _chart_tag_size(tag: str, font: fontmetrics.Font) -> tuple[float, float]:
    """(lebar, tinggi) gelembung tag; lebar diukur, tinggi tetap."""
    return font.width(tag, CHART_TAG_EM) + 2.0 * CHART_TAG_PAD_X, CHART_TAG_H


def _chart_tag_center(
    rect: dict[str, float],
    point: tuple[float, float],
    bubble_w: float,
    bubble_h: float,
) -> tuple[float, float]:
    """Pusat gelembung: di atas titik, digeser mendatar agar tetap di kartu."""
    x, y = point
    center_y = y - CHART_DOT_RADIUS - CHART_TAG_GAP - bubble_h / 2.0
    low = rect["x"] + CHART_LABEL_SIDE_GAP + bubble_w / 2.0
    high = rect["x"] + rect["w"] - CHART_LABEL_SIDE_GAP - bubble_w / 2.0
    if low > high:
        center_x = rect["x"] + rect["w"] / 2.0
    else:
        center_x = min(max(x, low), high)
    return center_x, center_y


def _frame_index(t: float, fps: float) -> int:
    """Konversi waktu -> frame SEKALI, aturan proyek: `round(t * fps)`."""
    return int(round(float(t) * float(fps)))


def _frame_start_time(frame: int, fps: float) -> float:
    """Waktu ASS (detik, 2 desimal) agar event PERTAMA tampil di `frame`.

    ASS menulis waktu dalam sentidetik. Membulatkan timestamp frame ke 2
    desimal bisa MELEWATI timestamp itu sendiri (0,0667 -> 0,07), sehingga
    event baru tampil satu frame terlambat. Yang benar: sentidetik PERTAMA
    yang lebih besar dari timestamp frame sebelumnya, sehingga
    `t_prev < start <= t_frame`. Diukur di libass: start 0,04 tampil di frame
    2 @30 fps, start 0,03 tampil di frame 1.
    """
    if frame <= 0:
        return 0.0
    previous = (frame - 1) / fps
    centiseconds = math.floor(previous * 100.0 + 1e-9) + 1
    return round(centiseconds / 100.0, 2)


def _frame_end_time(frame: int, fps: float) -> float:
    """Waktu ASS akhir: event aktif sampai frame `frame - 1`, bukan `frame`."""
    return round(frame / fps + 1e-9, 2)


def _pop_chain(fps: float) -> list[tuple[int, float]]:
    """Rantai `\\t` skala pop 0 -> ~108% -> 100% (spring, disampel per frame).

    Pola sama dengan `kinetic.spring_chain`, tetapi `kinetic.spring_chain`
    menginterpolasi dari `SCALE_START` global (60%), bukan parameter `start`;
    pop checklist HARUS mulai dari 0%. Titik diambil pada grid frame sampai
    `spring.settle_time()`, lalu di-thin ke `CHECK_POP_MAX_SEGMENTS` dengan
    membuang titik yang galat chord-nya paling kecil (puncak overshoot
    dipertahankan karena galatnya besar).
    """
    settle = spring.settle_time()
    frames = max(1, math.ceil(round(settle * fps, 9)))
    nodes = [i / fps for i in range(frames + 1)]
    if nodes[-1] > settle:
        nodes[-1] = settle
    nodes = sorted({round(t, 9) for t in nodes})

    def chord_error(t0: float, t1: float) -> float:
        v0 = spring.spring(t0) * 100.0
        v1 = spring.spring(t1) * 100.0
        worst = 0.0
        for k in range(1, 32):
            fraction = k / 32.0
            tm = t0 + (t1 - t0) * fraction
            chord = v0 + (v1 - v0) * fraction
            worst = max(worst, abs(chord - spring.spring(tm) * 100.0))
        return worst

    while len(nodes) - 1 > CHECK_POP_MAX_SEGMENTS:
        best: tuple[float, int] | None = None
        for i in range(1, len(nodes) - 1):
            error = chord_error(nodes[i - 1], nodes[i + 1])
            if best is None or error < best[0]:
                best = (error, i)
        if best is None:
            break
        nodes.pop(best[1])

    chain: list[tuple[int, float]] = []
    for t in nodes[:-1]:
        milliseconds = int(round(t * 1000.0))
        if chain and milliseconds <= chain[-1][0]:
            continue
        chain.append((milliseconds, float(round(spring.spring(t) * 100.0))))
    last = max(int(round(nodes[-1] * 1000.0)), chain[-1][0] + 1)
    chain.append((last, 100.0))
    return chain


def _pop_tags(chain: list[tuple[int, float]]) -> str:
    parts = []
    for (t0, _), (t1, value) in zip(chain, chain[1:]):
        parts.append(f"\\t({t0},{t1},\\fscx{value:g}\\fscy{value:g})")
    return "".join(parts)


def _fmt_path(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded == 0.0:
        rounded = 0.0
    return f"{rounded:g}"


def _reversed_circle(cx: float, cy: float, radius: float) -> str:
    """Lingkaran dengan arah kontur TERBALIK (lubang pada aturan nonzero).

    `shapes.circle` selalu menghasilkan orientasi positif; cincin butuh kontur
    dalam yang berlawanan agar libass membuat lubang, bukan cakram penuh
    (fakta aturan isi nonzero yang diukur di Langkah 5a). `shapes.py` tidak
    boleh diubah, jadi kontur dibalik di sini dari geometri bezier yang sama.
    """
    kappa = radius * shapes.KAPPA
    segments = []
    for i in range(4):
        start_angle = i * (math.pi / 2.0)
        end_angle = start_angle + math.pi / 2.0
        p0 = (cx + radius * math.cos(start_angle), cy + radius * math.sin(start_angle))
        p1 = (cx + radius * math.cos(end_angle), cy + radius * math.sin(end_angle))
        c1 = (
            p0[0] - kappa * math.sin(start_angle),
            p0[1] + kappa * math.cos(start_angle),
        )
        c2 = (
            p1[0] + kappa * math.sin(end_angle),
            p1[1] - kappa * math.cos(end_angle),
        )
        segments.append((p0, c1, c2, p1))

    start = segments[-1][3]
    parts = [f"m {_fmt_path(start[0])} {_fmt_path(start[1])}"]
    for p0, c1, c2, _p1 in reversed(segments):
        parts.append(
            f"b {_fmt_path(c2[0])} {_fmt_path(c2[1])} "
            f"{_fmt_path(c1[0])} {_fmt_path(c1[1])} "
            f"{_fmt_path(p0[0])} {_fmt_path(p0[1])}"
        )
    return " ".join(parts)


def _ring_path(cx: float, cy: float, outer: float, thickness: float) -> str:
    inner = outer - thickness
    return f"{shapes.circle(cx, cy, outer)} {_reversed_circle(cx, cy, inner)}"


def _move_tag(
    x0: float, y0: float, x1: float, y1: float, t0: int, t1: int
) -> str:
    return (
        f"\\move({_fmt_number(x0)},{_fmt_number(y0)},"
        f"{_fmt_number(x1)},{_fmt_number(y1)},{t0},{t1})"
    )


def _shape_line(
    layer: int,
    start_t: float,
    end_t: float,
    name: str,
    path: str,
    fill: str,
    opacity: float,
    position_tag: str,
    extra_tags: str,
) -> str:
    """Satu event bentuk; `position_tag` = `\\move(...)` atau `\\pos(x,y)`.

    Sengaja tidak memakai `shapes.shape_event` untuk elemen yang bergerak:
    fungsi itu selalu menulis `\\pos`, dan libass mengabaikan `\\move` bila
    `\\pos` hadir (diukur di probe 5b-2: bbox tidak bergeser satu piksel pun).
    """
    text = (
        f"{{\\an7{position_tag}\\bord0\\shad0"
        f"\\1c{shapes.colour(fill)}\\1a{shapes.alpha(opacity)}"
        f"{extra_tags}\\p1}}{path}{{\\p0}}"
    )
    return (
        f"Dialogue: {layer},{_ass_time(start_t)},{_ass_time(end_t)},"
        f"{CHECK_STYLE},{name},0,0,0,,{text}"
    )


def _text_line(
    layer: int,
    start_t: float,
    end_t: float,
    name: str,
    alignment: int,
    position_tag: str,
    colour: str,
    size_em: float,
    font: fontmetrics.Font,
    base_alpha: str,
    extra_tags: str,
    text: str,
) -> str:
    size_ass = round(size_em * font.cell_height_ratio, 2)
    override = (
        f"{{\\an{alignment}{position_tag}\\bord0\\shad0"
        f"\\c{shapes.colour(colour)}\\fs{size_ass:g}"
        f"\\alpha{base_alpha}{extra_tags}}}"
    )
    return (
        f"Dialogue: {layer},{_ass_time(start_t)},{_ass_time(end_t)},"
        f"{CHECK_STYLE},{name},0,0,0,,{override}{text}"
    )


def _checklist_events(
    plan: dict[str, Any], font: fontmetrics.Font
) -> list[str]:
    """Semua baris Dialogue satu overlay `checklist`."""
    index = plan["index"]
    type_name = plan["type"]
    fps = float(plan["fps"])
    item_count = len(plan["items"])
    label_n = str(item_count)

    rect = plan["rect"]
    x, y = rect["x"], rect["y"]
    width, height = rect["w"], rect["h"]
    right = x + width
    header_cy = y + CARD_PAD_Y + CARD_HEADER_H / 2.0
    ring_cx = x + CARD_PAD_X + RING_RADIUS
    text_x = x + CARD_PAD_X + 2.0 * RING_RADIUS + CHECK_ROW_GAP
    row_cy = [
        y + CARD_PAD_Y + CARD_HEADER_H + CARD_ROW_H * (i + 0.5)
        for i in range(item_count)
    ]

    frame_start = plan["frame_start"]
    frame_end = plan["frame_end"]
    start_t = _frame_start_time(frame_start, fps)
    end_t = _frame_end_time(frame_end, fps)
    entry_ms = int(round(CHECK_ENTRY * 1000.0))
    exit_frames = int(round(CHECK_EXIT * fps))
    exit_frame = max(frame_start, frame_end - exit_frames)

    counter_texts = [f"{n} of {label_n}" for n in range(item_count + 1)]
    counter_width = max(
        font.width(text, CHECK_COUNTER_EM) for text in counter_texts
    )
    title_available = width - 2.0 * CARD_PAD_X - counter_width - CHECK_TITLE_GAP
    title_width = font.width(plan["title"], CHECK_TITLE_EM)
    if title_width > title_available + 1e-9:
        _error(
            index, type_name,
            f"props['title'] tidak muat: lebar terukur {title_width:g} px > "
            f"tersedia {title_available:g} px",
        )

    item_available = (
        width - 2.0 * CARD_PAD_X - 2.0 * RING_RADIUS - CHECK_ROW_GAP
    )
    for position, item in enumerate(plan["items"]):
        measured = font.width(item["text"], CHECK_ITEM_EM)
        if measured > item_available + 1e-9:
            _error(
                index, type_name,
                f"props['items'][{position}]['text'] tidak muat: lebar terukur "
                f"{measured:g} px > tersedia {item_available:g} px",
            )

    def exit_state(event_start_frame: int, event_start_t: float) -> tuple[str, str]:
        """(alfa awal, tag fade keluar) untuk event yang mulai di frame ini."""
        span = frame_end - exit_frame
        progress = 0.0
        if span > 0 and event_start_frame > exit_frame:
            progress = min(1.0, (event_start_frame - exit_frame) / span)
        end_rel = max(
            1, int(round((frame_end / fps - event_start_t) * 1000.0))
        )
        if progress > 0.0:
            base = f"&H{int(round(progress * 255.0)):02X}&"
            return base, f"\\t(0,{end_rel},\\alpha&HFF&)"
        start_rel = max(
            0, int(round((exit_frame / fps - event_start_t) * 1000.0))
        )
        start_rel = min(start_rel, max(0, end_rel - 1))
        return "&H00&", f"\\t({start_rel},{end_rel},\\alpha&HFF&)"

    events: list[str] = []

    # -- kartu -------------------------------------------------------------
    card_exit_base, card_exit_tag = exit_state(frame_start, start_t)
    events.append(
        _shape_line(
            CARD_LAYER, start_t, end_t, "card",
            shapes.rounded_rect(x, y, width, height, CARD_RADIUS),
            CARD_COLOUR, CARD_OPACITY,
            _move_tag(0, -CHECK_ENTRY_OFFSET, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{CHECK_ENTRY_ACCEL:g},"
            f"\\1a{shapes.alpha(CARD_OPACITY)}){card_exit_tag}",
        )
    )

    # -- cincin per butir --------------------------------------------------
    ring_path = [
        _ring_path(ring_cx, row_cy[i], RING_RADIUS, RING_THICKNESS)
        for i in range(item_count)
    ]
    _, ring_exit_tag = exit_state(frame_start, start_t)
    for i in range(item_count):
        events.append(
            _shape_line(
                RING_LAYER, start_t, end_t, "ring", ring_path[i],
                RING_COLOUR, 1.0,
                _move_tag(0, -CHECK_ENTRY_OFFSET, 0, 0, 0, entry_ms),
                f"\\1a&HFF&\\t(0,{entry_ms},{CHECK_ENTRY_ACCEL:g},\\1a&H00&)"
                f"{ring_exit_tag}",
            )
        )

    # -- teks butir --------------------------------------------------------
    _, text_exit_tag = exit_state(frame_start, start_t)
    for i, item in enumerate(plan["items"]):
        events.append(
            _text_line(
                TEXT_LAYER, start_t, end_t, "item", 4,
                _move_tag(text_x, row_cy[i] - CHECK_ENTRY_OFFSET,
                          text_x, row_cy[i], 0, entry_ms),
                ITEM_COLOUR, CHECK_ITEM_EM, font,
                "&HFF&",
                f"\\t(0,{entry_ms},{CHECK_ENTRY_ACCEL:g},\\alpha&H00&)"
                f"{text_exit_tag}",
                item["text"],
            )
        )

    # -- judul -------------------------------------------------------------
    events.append(
        _text_line(
            TEXT_LAYER, start_t, end_t, "title", 4,
            _move_tag(x + CARD_PAD_X, header_cy - CHECK_ENTRY_OFFSET,
                      x + CARD_PAD_X, header_cy, 0, entry_ms),
            TITLE_COLOUR, CHECK_TITLE_EM, font,
            "&HFF&",
            f"\\t(0,{entry_ms},{CHECK_ENTRY_ACCEL:g},\\alpha&H00&)"
            f"{text_exit_tag}",
            plan["title"],
        )
    )

    # -- penghitung n of N: satu event per keadaan ------------------------
    done_frames = [
        (_frame_index(item["done_at"], fps), i)
        for i, item in enumerate(plan["items"])
        if item["done_at"] is not None
    ]
    done_before_end = [(f, i) for f, i in done_frames if f < frame_end]
    states: list[tuple[int, int]] = [(frame_start, 0)]
    for frame in sorted({f for f, _ in done_before_end}):
        count = sum(1 for f, _ in done_before_end if f <= frame)
        states.append((frame, count))

    counter_events: list[str] = []
    for state_index, (state_frame, count) in enumerate(states):
        state_start_t = (
            _frame_start_time(state_frame, fps) if state_index else start_t
        )
        if state_index + 1 < len(states):
            state_end_t = _frame_start_time(states[state_index + 1][0], fps)
        else:
            state_end_t = end_t
        if state_start_t >= state_end_t:
            continue
        base_alpha, exit_tag = exit_state(state_frame, state_start_t)
        if state_index == 0:
            position_tag = _move_tag(
                right - CARD_PAD_X, header_cy - CHECK_ENTRY_OFFSET,
                right - CARD_PAD_X, header_cy, 0, entry_ms,
            )
            base_alpha = "&HFF&"
            extra = (
                f"\\t(0,{entry_ms},{CHECK_ENTRY_ACCEL:g},\\alpha&H00&)"
                f"{exit_tag}"
            )
        else:
            position_tag = (
                f"\\pos({_fmt_number(right - CARD_PAD_X)},"
                f"{_fmt_number(header_cy)})"
            )
            extra = exit_tag
        counter_events.append(
            _text_line(
                TEXT_LAYER, state_start_t, state_end_t, "counter", 6,
                position_tag, COUNTER_COLOUR, CHECK_COUNTER_EM, font,
                base_alpha, extra, f"{count} of {label_n}",
            )
        )
    events.extend(counter_events)

    # -- hijau + centang: mulai TEPAT pada frame done_at -------------------
    pop = _pop_chain(fps)
    pop_tags = _pop_tags(pop)
    check_path = shapes.check_mark(0.0, 0.0, CHECK_SIZE, CHECK_THICKNESS)
    for frame, item_index in done_before_end:
        event_start_t = _frame_start_time(frame, fps)
        if event_start_t >= end_t:
            continue
        base_alpha, exit_tag = exit_state(frame, event_start_t)
        position = (
            f"\\pos({_fmt_number(ring_cx)},{_fmt_number(row_cy[item_index])})"
        )
        events.append(
            _shape_line(
                RING_LAYER, event_start_t, end_t, "green",
                shapes.circle(0.0, 0.0, RING_RADIUS),
                GREEN_COLOUR, 1.0, position,
                f"\\1a{base_alpha}\\fscx0\\fscy0{pop_tags}{exit_tag}",
            )
        )
        events.append(
            _shape_line(
                CHECK_LAYER, event_start_t, end_t, "check", check_path,
                CHECK_COLOUR, 1.0, position,
                f"\\1a{base_alpha}\\fscx0\\fscy0{pop_tags}{exit_tag}",
            )
        )

    return events


def _chart_exit_state(
    frame_end: int,
    fps: float,
    exit_frame: int,
    event_start_frame: int,
    event_start_t: float,
) -> tuple[str, str]:
    """(alfa awal, tag fade keluar) untuk event yang mulai di frame ini.

    Logika SAMA dengan `_checklist_events.exit_state` (dipertahankan terpisah
    supaya keluaran checklist 5b-2 byte-identik); lihat docstring di sana.
    """
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


def _chart_clip_chain(
    x_left: float,
    y0: float,
    y1: float,
    head_xs: list[float],
    times_ms: list[int],
) -> str:
    """`\\clip` yang tepi kanannya mengikuti kepala garis (kiri tetap).

    Satu `\\t` LINEAR per segmen; node waktunya sama dengan `\\move` titik
    ujung, jadi x(t) garis dan titik identik pada grid frame. Semua koordinat
    klip dibulatkan libass ke integer (fakta Langkah 5a) — itu satu-satunya
    selisih yang tersisa (<= 1 px).
    """
    def box(right: float) -> str:
        return (
            f"\\clip({_fmt_number(x_left)},{_fmt_number(y0)},"
            f"{_fmt_number(right)},{_fmt_number(y1)})"
        )

    parts = [box(x_left)]
    for k in range(1, len(head_xs)):
        parts.append(f"\\t({times_ms[k - 1]},{times_ms[k]},1,{box(head_xs[k])})")
    return "".join(parts)


def _chart_events(plan: dict[str, Any], font: fontmetrics.Font) -> list[str]:
    """Semua baris Dialogue satu overlay `chart_grow`."""
    index = plan["index"]
    type_name = plan["type"]
    fps = float(plan["fps"])
    frame_start = plan["frame_start"]
    frame_end = plan["frame_end"]
    start_t = _frame_start_time(frame_start, fps)
    end_t = _frame_end_time(frame_end, fps)

    entry_frames = max(1, int(round(CHART_ENTRY * fps)))
    grow_frames = max(1, int(round(plan["grow"] * fps)))
    grow_start_frame = frame_start + entry_frames
    grow_end_frame = min(grow_start_frame + grow_frames, frame_end)
    exit_frames = int(round(CHART_EXIT * fps))
    exit_frame = max(frame_start, frame_end - exit_frames)

    def rel_ms(frame: int) -> int:
        return int(round((frame / fps - start_t) * 1000.0))

    entry_ms = rel_ms(grow_start_frame)

    def exit_state(event_frame: int, event_start: float) -> tuple[str, str]:
        return _chart_exit_state(
            frame_end, fps, exit_frame, event_frame, event_start
        )

    rect = plan["rect"]
    x, y = rect["x"], rect["y"]
    width, height = rect["w"], rect["h"]
    title = plan["title"]
    labels = plan["labels"]
    values = plan["values"]
    tag = plan["tag"]

    geom = _chart_geometry(rect, title is not None)
    points = _chart_points(values, geom)
    plot_w = geom["plot_x1"] - geom["plot_x0"]

    # -- teks muat (diukur, bukan ditebak) --------------------------------
    spacing = plot_w / (len(labels) - 1)
    label_available = min(
        spacing - CHART_LABEL_SIDE_GAP,
        2.0 * (geom["plot_x0"] - x - CHART_LABEL_SIDE_GAP),
    )
    for position, label in enumerate(labels):
        measured = font.width(label, CHART_LABEL_EM)
        if measured > label_available + 1e-9:
            _error(
                index, type_name,
                f"props['labels'][{position}] tidak muat: lebar terukur "
                f"{measured:g} px > tersedia {label_available:g} px",
            )

    bubble_w, bubble_h = _chart_tag_size(tag, font)
    tag_available = width - 2.0 * CHART_PAD_X
    if bubble_w > tag_available + 1e-9:
        _error(
            index, type_name,
            f"props['tag'] tidak muat: lebar gelembung terukur "
            f"{bubble_w:g} px > tersedia {tag_available:g} px",
        )

    events: list[str] = []

    # -- kartu ------------------------------------------------------------
    _, card_exit_tag = exit_state(frame_start, start_t)
    events.append(
        _shape_line(
            CHART_CARD_LAYER, start_t, end_t, "card",
            shapes.rounded_rect(x, y, width, height, CHART_CARD_RADIUS),
            CARD_COLOUR, CHART_CARD_OPACITY,
            _move_tag(0, -CHART_ENTRY_OFFSET, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{CHART_ENTRY_ACCEL:g},"
            f"\\1a{shapes.alpha(CHART_CARD_OPACITY)}){card_exit_tag}",
        )
    )

    # -- garis grid + sumbu x --------------------------------------------
    plot_h = geom["plot_bottom"] - geom["plot_top"]
    grid_paths = []
    for k in range(1, CHART_GRID_LINES + 1):
        gy = geom["plot_bottom"] - plot_h * k / (CHART_GRID_LINES + 1)
        grid_paths.append(
            shapes.rect(
                geom["plot_x0"], gy - CHART_GRID_THICKNESS / 2.0,
                plot_w, CHART_GRID_THICKNESS,
            )
        )
    _, grid_exit_tag = exit_state(frame_start, start_t)
    events.append(
        _shape_line(
            CHART_GRID_LAYER, start_t, end_t, "grid",
            " ".join(grid_paths), CHART_GRID_COLOUR, 1.0,
            _move_tag(0, -CHART_ENTRY_OFFSET, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{CHART_ENTRY_ACCEL:g},\\1a&H00&)"
            f"{grid_exit_tag}",
        )
    )
    events.append(
        _shape_line(
            CHART_AXIS_LAYER, start_t, end_t, "axis",
            shapes.rect(
                geom["plot_x0"] - 12.0,
                geom["plot_bottom"] - CHART_AXIS_THICKNESS / 2.0,
                plot_w + 24.0, CHART_AXIS_THICKNESS,
            ),
            CHART_AXIS_COLOUR, 1.0,
            _move_tag(0, -CHART_ENTRY_OFFSET, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{CHART_ENTRY_ACCEL:g},\\1a&H00&)"
            f"{grid_exit_tag}",
        )
    )

    # -- judul + label sumbu ---------------------------------------------
    _, text_exit_tag = exit_state(frame_start, start_t)
    if title is not None:
        events.append(
            _text_line(
                CHART_TEXT_LAYER, start_t, end_t, "title", 7,
                _move_tag(
                    x + CHART_PAD_X, y + CHART_PAD_Y - CHART_ENTRY_OFFSET,
                    x + CHART_PAD_X, y + CHART_PAD_Y, 0, entry_ms,
                ),
                CHART_TITLE_COLOUR, CHART_TITLE_EM, font, "&HFF&",
                f"\\t(0,{entry_ms},{CHART_ENTRY_ACCEL:g},\\alpha&H00&)"
                f"{text_exit_tag}",
                title,
            )
        )
    for position, label in enumerate(labels):
        px, _py = points[position]
        events.append(
            _text_line(
                CHART_TEXT_LAYER, start_t, end_t, "label", 8,
                _move_tag(
                    px, geom["label_y"] - CHART_ENTRY_OFFSET,
                    px, geom["label_y"], 0, entry_ms,
                ),
                CHART_LABEL_COLOUR, CHART_LABEL_EM, font, "&HFF&",
                f"\\t(0,{entry_ms},{CHART_ENTRY_ACCEL:g},\\alpha&H00&)"
                f"{text_exit_tag}",
                label,
            )
        )

    # -- garis data + rantai wipe ----------------------------------------
    nodes = _chart_grow_nodes(grow_frames)
    node_times = [rel_ms(grow_start_frame + frame) for frame, _p in nodes]
    heads = [_chart_head_point(points, progress) for _frame, progress in nodes]
    head_xs = [head[0] for head in heads]

    clip_y0 = geom["plot_top"] - CHART_DOT_RADIUS - CHART_LINE_THICKNESS
    clip_y1 = geom["plot_bottom"] + CHART_DOT_RADIUS + CHART_LINE_THICKNESS
    clip_chain = _chart_clip_chain(
        geom["plot_x0"], clip_y0, clip_y1, head_xs, node_times
    )
    _, line_exit_tag = exit_state(frame_start, start_t)
    events.append(
        _shape_line(
            CHART_LINE_LAYER, start_t, end_t, "line",
            shapes.polyline(points, CHART_LINE_THICKNESS),
            CHART_LINE_COLOUR, 1.0,
            _move_tag(0, -CHART_ENTRY_OFFSET, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{CHART_ENTRY_ACCEL:g},\\1a&H00&)"
            f"{clip_chain}{line_exit_tag}",
        )
    )

    # -- titik ujung: satu event per sub-ruas, waktu frame yang sama ------
    for k in range(1, len(nodes)):
        start_frame = grow_start_frame + nodes[k - 1][0]
        end_frame = grow_start_frame + nodes[k][0]
        event_start_t = _frame_start_time(start_frame, fps)
        event_end_t = (
            end_t if k == len(nodes) - 1
            else _frame_start_time(end_frame, fps)
        )
        if event_start_t >= event_end_t:
            continue
        offset0 = int(round((start_frame / fps - event_start_t) * 1000.0))
        offset1 = int(round((end_frame / fps - event_start_t) * 1000.0))
        base_alpha, dot_exit_tag = exit_state(start_frame, event_start_t)
        x0, y0 = heads[k - 1]
        x1, y1 = heads[k]
        events.append(
            _shape_line(
                CHART_DOT_LAYER, event_start_t, event_end_t, "dot",
                shapes.circle(0.0, 0.0, CHART_DOT_RADIUS),
                CHART_LINE_COLOUR, 1.0,
                _move_tag(x0, y0, x1, y1, offset0, offset1),
                f"\\bord{CHART_DOT_RING:g}"
                f"\\3c{shapes.colour(CHART_DOT_RING_COLOUR)}"
                f"\\1a{base_alpha}{dot_exit_tag}",
            )
        )

    # -- tag: pop sesudah garis selesai, menempel di titik ujung ----------
    tag_start_t = _frame_start_time(grow_end_frame, fps)
    if tag_start_t < end_t:
        tag_frame = grow_end_frame
        base_alpha, tag_exit_tag = exit_state(tag_frame, tag_start_t)
        center_x, center_y = _chart_tag_center(
            rect, points[-1], bubble_w, bubble_h
        )
        position = (
            f"\\pos({_fmt_number(center_x)},{_fmt_number(center_y)})"
        )
        pop_tags = _pop_tags(_pop_chain(fps))
        events.append(
            _shape_line(
                CHART_TAG_BUBBLE_LAYER, tag_start_t, end_t, "tagbubble",
                shapes.rounded_rect(
                    -bubble_w / 2.0, -bubble_h / 2.0,
                    bubble_w, bubble_h, CHART_TAG_RADIUS,
                ),
                CHART_TAG_BG_COLOUR, 1.0, position,
                f"\\bord2\\3c{shapes.colour(CHART_TAG_BORDER_COLOUR)}"
                f"\\1a{base_alpha}\\fscx0\\fscy0{pop_tags}{tag_exit_tag}",
            )
        )
        events.append(
            _text_line(
                CHART_TAG_TEXT_LAYER, tag_start_t, end_t, "tagtext", 5,
                position, CHART_TAG_TEXT_COLOUR, CHART_TAG_EM, font,
                base_alpha,
                f"\\fscx0\\fscy0{pop_tags}{tag_exit_tag}",
                tag,
            )
        )

    return events


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _build_zoom_through_text(
    index: int,
    item: dict[str, Any],
    clip_duration: float,
    *,
    fps: float,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validasi satu overlay; balikkan plan atau daftar peringatan."""
    type_name = str(item.get("type"))
    warnings: list[str] = []

    start = _finite_number(item.get("start"), "start", index, type_name)
    end = _finite_number(item.get("end"), "end", index, type_name)

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
        _error(
            index, type_name,
            f"end harus > start setelah dipotong ke [0, {clip_duration:g}]; "
            f"dapat {item.get('start')!r}..{item.get('end')!r}",
        )

    props = _zoom_props(item.get("props"), index, type_name)

    pos = (PLAY_RES[0] / 2.0, PLAY_RES[1] / 2.0)
    if "rect" in item:
        pos = _rect_center(item["rect"], index, type_name)

    event_end = min(end, start + props["duration"])
    if event_end <= start:  # pertahanan: durasi tervalidasi >= 0.4
        _error(index, type_name, f"jendela event kosong: {start!r}..{event_end!r}")

    return {
        "index": index,
        "type": type_name,
        "start": start,
        "end": end,
        "event_end": event_end,
        "pos": pos,
        "font_kind": "serif",
        **props,
    }, warnings


def _build_checklist(
    index: int,
    item: dict[str, Any],
    clip_duration: float,
    *,
    fps: float,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validasi satu overlay `checklist`; balikkan plan atau peringatan."""
    type_name = str(item.get("type"))
    warnings: list[str] = []

    start = _finite_number(item.get("start"), "start", index, type_name)
    end = _finite_number(item.get("end"), "end", index, type_name)

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
        _error(
            index, type_name,
            f"end harus > start setelah dipotong ke [0, {clip_duration:g}]; "
            f"dapat {item.get('start')!r}..{item.get('end')!r}",
        )

    title, items = _checklist_props(item.get("props"), index, type_name)
    rect = _checklist_rect(item, index, type_name, len(items))

    entry_limit = start + CHECK_ENTRY
    for position, entry in enumerate(items):
        done_at = entry["done_at"]
        if done_at is None:
            continue
        if done_at < entry_limit - 1e-9 or done_at > end + 1e-9:
            _error(
                index, type_name,
                f"props['items'][{position}]['done_at'] harus di dalam "
                f"[{entry_limit:g}, {end:g}], dapat {done_at!r}",
            )

    frame_start = _frame_index(start, fps)
    frame_end = _frame_index(end, fps)
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
        "title": title,
        "items": items,
        "font_kind": "sans",
    }, warnings


def _build_chart_grow(
    index: int,
    item: dict[str, Any],
    clip_duration: float,
    *,
    fps: float,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validasi satu overlay `chart_grow`; balikkan plan atau peringatan."""
    type_name = str(item.get("type"))
    warnings: list[str] = []

    start = _finite_number(item.get("start"), "start", index, type_name)
    end = _finite_number(item.get("end"), "end", index, type_name)

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
        _error(
            index, type_name,
            f"end harus > start setelah dipotong ke [0, {clip_duration:g}]; "
            f"dapat {item.get('start')!r}..{item.get('end')!r}",
        )

    props = _chart_props(item.get("props"), index, type_name)
    rect = _chart_rect(item, index, type_name, props["title"] is not None)

    grow_end = start + CHART_ENTRY + props["grow"]
    if grow_end > end + 1e-9:
        _error(
            index, type_name,
            f"props['grow'] {props['grow']:g} s + ENTRY {CHART_ENTRY:g} s "
            f"selesai pada {grow_end:g} s, melewati end {end:g} s; tag tidak "
            f"akan pernah tampil",
        )

    frame_start = _frame_index(start, fps)
    frame_end = _frame_index(end, fps)
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
        "font_kind": "sans",
        **props,
    }, warnings


# ---------------------------------------------------------------------------
# Implementasi `ui_panel` (efek referensi #03)
# ---------------------------------------------------------------------------

def _ui_required_height(thumbs: int) -> float:
    """Tinggi minimum kartu dihitung dari isi (1 atau 2 baris thumbnail)."""
    rows = 1 if thumbs <= 3 else 2
    thumbs_h = rows * UI_THUMB_H + (rows - 1) * UI_THUMB_GAP_Y
    return (
        UI_PAD_Y * 2
        + UI_TITLE_H
        + UI_GAP_HEADER_THUMBS
        + thumbs_h
        + UI_GAP_THUMBS_INPUT
        + UI_INPUT_H
    )


def _ui_props(props: Any, index: int, type_name: str) -> dict[str, Any]:
    """Validasi ketat props `ui_panel`; pesan menyebut nama props dan kunci sah."""
    if not isinstance(props, dict):
        _error(index, type_name, f"props harus objek, dapat {props!r}")

    unknown = sorted(set(props) - set(_UI_PROPS))
    if unknown:
        _error(
            index, type_name,
            f"props tidak dikenal: {unknown[0]!r} "
            f"(dikenal: {', '.join(_UI_PROPS)})",
        )

    if "title" not in props:
        _error(index, type_name, "props['title'] wajib ada")
    title = props["title"]
    if not isinstance(title, str):
        _error(index, type_name, f"props['title'] harus string, dapat {title!r}")
    if not UI_MIN_TITLE_CHARS <= len(title) <= UI_MAX_TITLE_CHARS:
        _error(
            index, type_name,
            f"props['title'] harus {UI_MIN_TITLE_CHARS}..{UI_MAX_TITLE_CHARS} karakter, dapat {len(title)}",
        )
    if "\n" in title or "\r" in title:
        _error(index, type_name, f"props['title'] tidak boleh memuat newline: {title!r}")

    if "tag" not in props:
        _error(index, type_name, "props['tag'] wajib ada")
    tag = props["tag"]
    if not isinstance(tag, str):
        _error(index, type_name, f"props['tag'] harus string, dapat {tag!r}")
    if not UI_MIN_TAG_CHARS <= len(tag) <= UI_MAX_TAG_CHARS:
        _error(
            index, type_name,
            f"props['tag'] harus {UI_MIN_TAG_CHARS}..{UI_MAX_TAG_CHARS} karakter, dapat {len(tag)}",
        )
    if "\n" in tag or "\r" in tag:
        _error(index, type_name, f"props['tag'] tidak boleh memuat newline: {tag!r}")

    thumbs_val = props.get("thumbs", UI_DEFAULT_THUMBS)
    if isinstance(thumbs_val, bool) or not isinstance(thumbs_val, int):
        _error(
            index, type_name,
            f"props['thumbs'] harus bilangan bulat 1..6, dapat {thumbs_val!r}",
        )
    if not UI_MIN_THUMBS <= thumbs_val <= UI_MAX_THUMBS:
        _error(
            index, type_name,
            f"props['thumbs'] harus bilangan bulat 1..6, dapat {thumbs_val!r}",
        )

    input_val = props.get("input", "")
    if not isinstance(input_val, str):
        _error(index, type_name, f"props['input'] harus string, dapat {input_val!r}")
    if len(input_val) > UI_MAX_INPUT_CHARS:
        _error(
            index, type_name,
            f"props['input'] harus <= {UI_MAX_INPUT_CHARS} karakter, dapat {len(input_val)}",
        )
    if "\n" in input_val or "\r" in input_val:
        _error(index, type_name, f"props['input'] tidak boleh memuat newline: {input_val!r}")

    return {
        "title": title,
        "tag": tag,
        "thumbs": thumbs_val,
        "input": input_val,
    }


def _ui_rect(
    item: dict[str, Any],
    index: int,
    type_name: str,
    thumbs: int,
) -> dict[str, float]:
    """Rect kartu (bawaan 60,260,960,h_terhitung); validasi kanvas + tinggi/lebar."""
    required_h = _ui_required_height(thumbs)
    cols = min(thumbs, 3)
    min_required_w = UI_PAD_X * 2 + cols * UI_THUMB_W + (cols - 1) * UI_THUMB_GAP_X

    if "rect" not in item:
        return {
            "x": UI_CARD_X,
            "y": UI_CARD_Y,
            "w": UI_CARD_W,
            "h": required_h,
        }

    rect = item["rect"]
    if not isinstance(rect, dict):
        _error(index, type_name, f"rect harus objek {{x,y,w,h}}, dapat {rect!r}")
    unknown = sorted(set(rect) - set(_CHECK_RECT_KEYS))
    if unknown:
        _error(
            index, type_name,
            f"rect kunci tidak dikenal: {unknown[0]!r} (dikenal: {', '.join(_CHECK_RECT_KEYS)})",
        )
    out: dict[str, float] = {}
    for name in ("x", "y", "w"):
        if name not in rect:
            _error(index, type_name, f"rect['{name}'] wajib ada, dapat {rect!r}")
        out[name] = _finite_number(rect[name], f"rect['{name}']", index, type_name)
    if "h" in rect:
        out["h"] = _finite_number(rect["h"], "rect['h']", index, type_name)
    else:
        out["h"] = required_h

    if out["w"] <= 0.0 or out["h"] <= 0.0:
        _error(index, type_name, f"rect['w'] dan rect['h'] harus > 0, dapat {rect!r}")

    width, height = PLAY_RES
    if (
        out["x"] < 0.0
        or out["y"] < 0.0
        or out["x"] + out["w"] > width + 1e-9
        or out["y"] + out["h"] > height + 1e-9
    ):
        _error(
            index, type_name,
            f"rect {{x={out['x']:g}, y={out['y']:g}, w={out['w']:g}, h={out['h']:g}}} keluar kanvas {width}x{height}",
        )

    if out["w"] + 1e-9 < min_required_w:
        _error(
            index, type_name,
            f"rect['w'] {out['w']:g} < lebar yang dibutuhkan {min_required_w:g} "
            f"untuk {cols} kolom thumbnail; thumbnail tidak muat",
        )

    if out["h"] + 1e-9 < required_h:
        _error(
            index, type_name,
            f"rect['h'] {out['h']:g} < tinggi yang dibutuhkan {required_h:g} "
            f"({thumbs} thumbnail); kartu tidak boleh disusutkan",
        )
    return out


def _ui_validate_text_fit(
    index: int,
    type_name: str,
    plan: dict[str, Any],
    rect: dict[str, float],
    font: fontmetrics.Font,
) -> None:
    """Validasi lebar teks terhadap ruang tersedia dengan font Archivo Black."""
    avail_header_w = rect["w"] - 2 * UI_PAD_X
    title_w = font.width(plan["title"], UI_TITLE_EM)
    tag_text_w = font.width(plan["tag"], UI_TAG_EM)
    tag_w = tag_text_w + 2 * UI_TAG_PAD_X
    needed_header_w = title_w + UI_TITLE_GAP + tag_w

    if tag_w > avail_header_w:
        _error(
            index, type_name,
            f"teks tag {plan['tag']!r} ({tag_w:.1f} px) tidak muat di header ({avail_header_w:.1f} px tersedia)",
        )
    if needed_header_w > avail_header_w:
        _error(
            index, type_name,
            f"teks judul ({title_w:.1f} px) dan tag ({tag_w:.1f} px) tidak muat di header ({avail_header_w:.1f} px tersedia)",
        )

    input_text = plan["input"]
    if input_text:
        avail_input_w = rect["w"] - 2 * UI_PAD_X - 2 * UI_INPUT_PAD_X
        input_w = font.width(input_text, UI_INPUT_EM)
        if input_w > avail_input_w:
            _error(
                index, type_name,
                f"teks input {input_text!r} ({input_w:.1f} px) tidak muat di bilah input ({avail_input_w:.1f} px tersedia)",
            )


def _build_ui_panel(
    index: int,
    item: dict[str, Any],
    clip_duration: float,
    *,
    fps: float = 30.0,
) -> tuple[dict[str, Any] | None, list[str]]:
    type_name = "ui_panel"
    warnings: list[str] = []

    start = _finite_number(item.get("start"), "start", index, type_name)
    end = _finite_number(item.get("end"), "end", index, type_name)
    if start >= clip_duration or end <= 0.0:
        warnings.append(
            f"overlay[{index}] tipe {type_name!r}: seluruhnya di luar klip "
            f"[0, {clip_duration:g}]; dilewati"
        )
        return None, warnings

    start = max(0.0, start)
    end = min(clip_duration, end)
    if end <= start:
        _error(
            index, type_name,
            f"end harus > start setelah dipotong ke [0, {clip_duration:g}]; "
            f"dapat {item.get('start')!r}..{item.get('end')!r}",
        )

    props = _ui_props(item.get("props"), index, type_name)
    rect = _ui_rect(item, index, type_name, props["thumbs"])

    frame_start = _frame_index(start, fps)
    frame_end = _frame_index(end, fps)
    if frame_end <= frame_start:
        warnings.append(
            f"overlay[{index}] tipe {type_name!r}: jendela kurang dari satu frame pada {fps:g} fps; dilewati"
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
        "font_kind": "sans",
        **props,
    }, warnings


def _ui_events(plan: dict[str, Any], font: fontmetrics.Font) -> list[str]:
    """Semua baris Dialogue satu overlay `ui_panel`."""
    index = plan["index"]
    type_name = plan["type"]
    rect = plan["rect"]
    fps = float(plan["fps"])
    frame_start = plan["frame_start"]
    frame_end = plan["frame_end"]

    _ui_validate_text_fit(index, type_name, plan, rect, font)

    start_t = _frame_start_time(frame_start, fps)
    end_t = _frame_end_time(frame_end, fps)

    entry_frames = max(1, int(round(UI_ENTRY * fps)))
    full_frame = frame_start + entry_frames
    exit_frames = int(round(UI_EXIT * fps))
    exit_frame = max(frame_start, frame_end - exit_frames)

    def rel_ms(frame: int) -> int:
        return int(round((frame / fps - start_t) * 1000.0))

    entry_ms = rel_ms(full_frame)

    def exit_state(event_frame: int, event_start: float) -> tuple[str, str]:
        return _chart_exit_state(
            frame_end, fps, exit_frame, event_frame, event_start
        )

    events: list[str] = []

    # -- 1. Badan Kartu (krem, bergerak kaku 60 px ke bawah) --
    _card_base_alpha, card_exit = exit_state(frame_start, start_t)
    card_alpha_hex = shapes.alpha(UI_CARD_OPACITY)
    card_path = shapes.rounded_rect(
        rect["x"], rect["y"], rect["w"], rect["h"], UI_CARD_RADIUS
    )
    events.append(
        _shape_line(
            UI_CARD_LAYER, start_t, end_t, "card", card_path,
            UI_CARD_COLOUR, UI_CARD_OPACITY,
            _move_tag(0, -UI_ENTRY_OFFSET, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{UI_ENTRY_ACCEL:g},\\1a{card_alpha_hex})"
            f"{card_exit}",
        )
    )

    # -- 2. Judul (bergerak kaku 60 px) --
    title_x = rect["x"] + UI_PAD_X
    header_y = rect["y"] + UI_PAD_Y
    title_cy = header_y + UI_TITLE_H / 2.0
    title_move = _move_tag(
        title_x, title_cy - UI_ENTRY_OFFSET,
        title_x, title_cy,
        0, entry_ms,
    )
    events.append(
        _text_line(
            UI_TITLE_LAYER, start_t, end_t, "title", 4,
            title_move, UI_TITLE_COLOUR, UI_TITLE_EM, font,
            "&H00&",
            f"\\alpha&HFF&\\t(0,{entry_ms},{UI_ENTRY_ACCEL:g},\\alpha&H00&)"
            f"{card_exit}",
            _escape_text(plan["title"]),
        )
    )

    # -- 3. Bilah Input (rounded rect putih, bergerak kaku 60 px) --
    rows = 1 if plan["thumbs"] <= 3 else 2
    thumbs_total_h = rows * UI_THUMB_H + (rows - 1) * UI_THUMB_GAP_Y
    input_y = header_y + UI_TITLE_H + UI_GAP_HEADER_THUMBS + thumbs_total_h + UI_GAP_THUMBS_INPUT
    input_x = rect["x"] + UI_PAD_X
    input_w = rect["w"] - 2 * UI_PAD_X
    input_path = shapes.rounded_rect(
        input_x, input_y, input_w, UI_INPUT_H, UI_INPUT_RADIUS
    )
    events.append(
        _shape_line(
            UI_INPUT_BAR_LAYER, start_t, end_t, "inputbar", input_path,
            UI_INPUT_BG_COLOUR, 1.0,
            _move_tag(0, -UI_ENTRY_OFFSET, 0, 0, 0, entry_ms),
            f"\\1a&HFF&\\t(0,{entry_ms},{UI_ENTRY_ACCEL:g},\\1a&H00&)"
            f"{card_exit}",
        )
    )

    # Teks input (bila input tidak kosong)
    if plan["input"]:
        input_text_x = input_x + UI_INPUT_PAD_X
        input_text_cy = input_y + UI_INPUT_H / 2.0
        input_text_move = _move_tag(
            input_text_x, input_text_cy - UI_ENTRY_OFFSET,
            input_text_x, input_text_cy,
            0, entry_ms,
        )
        events.append(
            _text_line(
                UI_INPUT_TEXT_LAYER, start_t, end_t, "inputtext", 4,
                input_text_move, UI_INPUT_TEXT_COLOUR, UI_INPUT_EM, font,
                "&H00&",
                f"\\alpha&HFF&\\t(0,{entry_ms},{UI_ENTRY_ACCEL:g},\\alpha&H00&)"
                f"{card_exit}",
                _escape_text(plan["input"]),
            )
        )

    # -- 4. Thumbnail (pop spring berurutan setelah kartu penuh) --
    pop_chain = _pop_chain(fps)
    pop_tags = _pop_tags(pop_chain)
    thumb_path = shapes.rounded_rect(
        -UI_THUMB_W / 2.0, -UI_THUMB_H / 2.0,
        UI_THUMB_W, UI_THUMB_H, UI_THUMB_RADIUS,
    )

    thumbs_start_y = header_y + UI_TITLE_H + UI_GAP_HEADER_THUMBS
    for k in range(plan["thumbs"]):
        t_thumb = plan["start"] + UI_ENTRY + k * UI_THUMB_STAGGER
        thumb_frame = int(round(t_thumb * fps))
        if thumb_frame >= frame_end:
            continue
        thumb_start_t = _frame_start_time(thumb_frame, fps)
        if thumb_start_t >= end_t:
            continue

        base_alpha, thumb_exit = exit_state(thumb_frame, thumb_start_t)

        col = k % 3
        row = k // 3
        cx = rect["x"] + UI_PAD_X + col * (UI_THUMB_W + UI_THUMB_GAP_X) + UI_THUMB_W / 2.0
        cy = thumbs_start_y + row * (UI_THUMB_H + UI_THUMB_GAP_Y) + UI_THUMB_H / 2.0
        pos_str = f"\\pos({_fmt_number(cx)},{_fmt_number(cy)})"
        colour = UI_PALETTE[k % len(UI_PALETTE)]

        events.append(
            _shape_line(
                UI_THUMB_LAYER, thumb_start_t, end_t, "thumb", thumb_path,
                colour, 1.0, pos_str,
                f"\\1a{base_alpha}\\fscx0\\fscy0{pop_tags}{thumb_exit}",
            )
        )

    # -- 5. Tag Pil Kuning (pop spring sesudah thumbnail terakhir) --
    tag_t = plan["start"] + UI_ENTRY + plan["thumbs"] * UI_THUMB_STAGGER
    tag_frame = int(round(tag_t * fps))
    if tag_frame < frame_end:
        tag_start_t = _frame_start_time(tag_frame, fps)
        if tag_start_t < end_t:
            base_alpha, tag_exit = exit_state(tag_frame, tag_start_t)

            tag_text_w = font.width(plan["tag"], UI_TAG_EM)
            tag_w = tag_text_w + 2 * UI_TAG_PAD_X
            tag_cx = rect["x"] + rect["w"] - UI_PAD_X - tag_w / 2.0
            tag_cy = title_cy
            pos_str = f"\\pos({_fmt_number(tag_cx)},{_fmt_number(tag_cy)})"

            tag_bubble_path = shapes.rounded_rect(
                -tag_w / 2.0, -UI_TAG_H / 2.0,
                tag_w, UI_TAG_H, UI_TAG_RADIUS,
            )
            events.append(
                _shape_line(
                    UI_TAG_BUBBLE_LAYER, tag_start_t, end_t, "tagbubble",
                    tag_bubble_path, UI_TAG_BG_COLOUR, 1.0, pos_str,
                    f"\\1a{base_alpha}\\fscx0\\fscy0{pop_tags}{tag_exit}",
                )
            )
            events.append(
                _text_line(
                    UI_TAG_TEXT_LAYER, tag_start_t, end_t, "tagtext", 5,
                    pos_str, UI_TAG_TEXT_COLOUR, UI_TAG_EM, font,
                    base_alpha,
                    f"\\fscx0\\fscy0{pop_tags}{tag_exit}",
                    _escape_text(plan["tag"]),
                )
            )

    return events


def _build_phone_frame(
    index: int,
    item: dict[str, Any],
    clip_duration: float,
    *,
    fps: float,
    font_path: Any = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    from . import presets_phone
    return presets_phone.build(
        index, item, clip_duration, fps=fps, font_path=font_path
    )


Builder = Callable[..., tuple[dict[str, Any] | None, list[str]]]

REGISTRY: dict[str, Builder] = {
    "zoom_through_text": _build_zoom_through_text,
    "checklist": _build_checklist,
    "chart_grow": _build_chart_grow,
    "ui_panel": _build_ui_panel,
    "phone_frame": _build_phone_frame,
}

PRESET_TYPES: tuple[str, ...] = tuple(REGISTRY)


# ---------------------------------------------------------------------------
# Dokumen ASS
# ---------------------------------------------------------------------------

def _style_line(font: fontmetrics.Font, size_em: float) -> str:
    """Satu baris Style `Serif` (Italic -1, Bold 0, tanpa outline/bayangan)."""
    size_ass = round(size_em * font.cell_height_ratio, 2)
    return (
        f"Style: {STYLE_NAME},{font.family},{size_ass:g},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,-1,0,0,100,100,0,0,1,0,0,5,0,0,0,1"
    )


def _checklist_style_line(font: fontmetrics.Font, size_em: float) -> str:
    """Satu baris Style `Sans`: Archivo Black, Bold/Italic 0, tanpa outline.

    `Bold: 0` karena berkasnya sudah Black; bold sintetik libass merusak
    ketajaman (alasan yang sama dengan `assets/fonts/SOURCES.md`).
    """
    size_ass = round(size_em * font.cell_height_ratio, 2)
    return (
        f"Style: {CHECK_STYLE},{font.family},{size_ass:g},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
    )


def _document(events: Iterable[str], style_lines: list[str]) -> str:
    """Dokumen `shapes.ass_document` + baris Style yang disisipkan eksplisit.

    `shapes.py` terlarang diubah, jadi style tambahan tidak bisa dititipkan ke
    `ass_document`. Penyisipan dilakukan pada penanda `[Events]` (satu kali),
    bukan dengan merakit ulang header, supaya format Dialogue dan direktif
    Script Info tetap milik `shapes.ass_document` (satu sumber kebenaran).

    Satu baris saja (kasus klip `zoom_through_text` lama) menghasilkan string
    yang PERSIS sama dengan implementasi 5b-1.
    """
    doc = shapes.ass_document(events, play_res=PLAY_RES)
    marker = "\n[Events]"
    if marker not in doc:
        raise PresetError("dokumen ASS shapes tidak memuat penanda [Events]")
    styles = "\n".join(style_lines)
    return doc.replace(marker, "\n" + styles + "\n" + marker, 1)


# ---------------------------------------------------------------------------
# API publik
# ---------------------------------------------------------------------------

def build_fx_ass(
    clip: dict[str, Any],
    *,
    fps: float = 30.0,
    font_path: Any = None,
) -> tuple[str | None, list[str]]:
    """Dokumen ASS preset untuk `clip`, atau `(None, peringatan)`.

    `None` bila klip tidak punya overlay bertipe preset (termasuk klip tier-1
    dan overlay `vs`). `font_path` hanya untuk tes/kontrol: default font bundel
    DM Serif Display Italic. Font hilang/salah keluarga -> `(None, [satu
    peringatan])`, tanpa exception.

    `fps` adalah bagian kontrak pemanggil (sama dengan penulis ASS lain) dan
    divalidasi; waktu tetap ditulis dalam detik/ms ASS — tidak ada snapping
    frame tambahan yang tidak diminta kontrak.
    """
    if (
        isinstance(fps, bool)
        or not isinstance(fps, (int, float))
        or not math.isfinite(float(fps))
        or float(fps) <= 0.0
    ):
        raise ValueError(f"fps harus angka > 0 dan berhingga, dapat {fps!r}")

    overlays = clip.get("overlays") or []
    if not isinstance(overlays, list):
        raise PresetError(f"overlays harus daftar, dapat {type(overlays).__name__}")

    selected = [
        (i, item)
        for i, item in enumerate(overlays)
        if isinstance(item, dict)
        and isinstance(item.get("type"), str)
        and item.get("type") in REGISTRY
    ]
    if not selected:
        return None, []

    segments = clip.get("segments") or []
    if not isinstance(segments, list) or not segments:
        raise PresetError(
            f"klip {clip.get('id', '?')!r}: preset butuh `segments` untuk "
            f"menghitung durasi klip"
        )
    try:
        clip_duration = sum(
            float(segment["src_end"]) - float(segment["src_start"])
            for segment in segments
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PresetError(
            f"klip {clip.get('id', '?')!r}: segments tidak bisa dihitung: {exc}"
        ) from None
    if not math.isfinite(clip_duration) or clip_duration <= 0.0:
        raise PresetError(
            f"klip {clip.get('id', '?')!r}: durasi klip harus > 0, "
            f"dapat {clip_duration!r}"
        )

    warnings: list[str] = []
    plans: list[dict[str, Any]] = []
    for index, item in selected:
        type_name = str(item.get("type"))
        plan, overlay_warnings = REGISTRY[type_name](
            index, item, clip_duration, fps=float(fps)
        )
        warnings.extend(overlay_warnings)
        if plan is not None:
            plans.append(plan)

    if not plans:
        return None, warnings

    # Satu font per jenis; font yang gagal menghapus SEMUA plan jenis itu dan
    # menambah SATU peringatan (pola 5b-1), bukan exception.
    fonts: dict[str, fontmetrics.Font] = {}
    for kind in ("serif", "sans"):
        if not any(plan["font_kind"] == kind for plan in plans):
            continue
        font, font_warning = _load_font(kind, font_path)
        if font is None:
            warnings.append(
                font_warning if font_warning else "preset dilewati: font tidak tersedia"
            )
            plans = [plan for plan in plans if plan["font_kind"] != kind]
        else:
            fonts[kind] = font
    if not plans:
        return None, warnings

    events: list[str] = []
    for plan in plans:
        font = fonts[plan["font_kind"]]
        if plan["type"] == "zoom_through_text":
            events.append(_zoom_event(plan, font))
        elif plan["type"] == "checklist":
            events.extend(_checklist_events(plan, font))
        elif plan["type"] == "chart_grow":
            events.extend(_chart_events(plan, font))
        elif plan["type"] == "ui_panel":
            events.extend(_ui_events(plan, font))
        elif plan["type"] == "phone_frame":
            from . import presets_phone
            events.extend(presets_phone.events(plan, float(fps), font))

    # Urutan Style deterministik dan hanya yang dipakai: klip zoom-only tetap
    # satu baris `Serif` seperti 5b-1; klip checklist-only tetap satu `Sans`
    # dengan event yang sama persis (hash 5b-2 berubah HANYA bila preset ini
    # benar-benar hadir).
    style_lines: list[str] = []
    zoom_plans = [plan for plan in plans if plan["type"] == "zoom_through_text"]
    if zoom_plans:
        style_lines.append(_style_line(fonts["serif"], zoom_plans[0]["size_em"]))
    if any(plan["font_kind"] == "sans" for plan in plans):
        style_lines.append(_checklist_style_line(fonts["sans"], CHECK_TITLE_EM))

    document = _document(events, style_lines)
    return document, warnings
