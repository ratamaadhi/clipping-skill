"""Caption kinetic per kata (tier-2): jendela tampil, layout, dan penulis ASS.

Kenapa modul terpisah dari `captions.py`: `captions.py` adalah penulis ASS
tier-1 yang sudah dikunci tes golden. Kinetic butuh satu event per kata,
`\\an5\\pos` per kata, dan rantai `\\t` hasil sampel spring — logika yang sama
sekali berbeda dan tidak boleh menyentuh jalur tier-1.

Tiga keputusan yang menentukan bentuk kode ini (docs/MOTION-TIER2-PLAN.md
Langkah 3 dan tabel temuan):

1. **Jendela tampil ≠ jendela caption** (temuan #10, `MAX_CAP_DUR=2.0` <
   `MAX_PHRASE_DUR=2.2`). `captions[].start/end` hanya dibaca; jendela kinetic
   dihitung `display_window` dan boleh lebih panjang dari caption, tetapi
   selalu dipotong sebelum frasa berikutnya tampil supaya dua frasa tidak
   pernah berbagi layar (risiko R6).
2. **Posisi dihitung dari frasa LENGKAP, sekali** (Langkah 3, "Layout kata").
   Kalau posisi dihitung dari kata yang sudah muncul, kata sebelumnya bergeser
   setiap kali kata baru masuk — getaran yang justru merusak gaya kinetic.
3. **Tidak ada font fallback senyap** (risiko R4). `font_path=None` memakai
   font bundel; kalau berkasnya tidak ada, `FileNotFoundError`. Jatuh diam-diam
   ke DejaVu akan membuat lebar teks di layout Python berbeda dari yang
   digambar libass, dan kata akan bertumpuk.
4. **Celah antar-kata diturunkan dari celah TINTA yang diinginkan**, bukan dari
   `gap_em` yang buta terhadap garis tepi dan bearing glyph (Langkah 3b-iii;
   nilai clearancenya dikoreksi di 3b-iv). Lihat `ink_gap_target` dan
   `layout_phrase`.

Semua waktu di sini = timeline OUTPUT (kontrak EDL, D-001).
"""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import captions as _tier1
from .lib import fontmetrics
from .lib import spring
from .lib import text as _text

__all__ = [
    "BUNDLED_FONT",
    "CLEARANCE_EM",
    "DEFAULT_LEAD",
    "GAP_EM",
    "MAX_MERGED_WORDS",
    "MIN_VISIBLE",
    "OUTLINE_PX",
    "SHADOW_PX",
    "MAX_SEGMENTS",
    "MIN_WINDOW",
    "SCALE_EMPHASIS",
    "SCALE_END",
    "SCALE_START",
    "TAIL_PAD",
    "build_ass",
    "display_window",
    "effective_captions",
    "ink_gap_target",
    "layout_phrase",
    "spring_chain",
    "word_bearings",
]

# --- konstanta tampilan (satu tempat, dipakai tes) -------------------------

# Font bundel. Path relatif ke akar repo, bukan ke modul, supaya mudah dibaca
# manusia; `_default_font_path()` menyelesaikannya.
BUNDLED_FONT = "assets/fonts/ArchivoBlack-Regular.ttf"

DEFAULT_LEAD = 0.04      # tampilkan kata 40 ms lebih awal (R5: ASR telat)
TAIL_PAD = 0.12          # ekor setelah kata terakhir supaya tidak memotong
NEXT_GUARD = 0.04        # jarak aman sebelum frasa berikutnya
MIN_WINDOW = 0.05        # jendela minimum bila terjepit

# Frasa yang jendela tampilnya lebih pendek dari ini digabung dengan tetangganya
# saat render (EDL tidak diubah, D-010). Asal: temuan produk F2 pada klip nyata
# `work/clip04_t2/edl_t2.json` - caption `Lu,` (kata 80 ms) hanya mendapat
# jendela 40 ms karena DEFAULT_LEAD + NEXT_GUARD memakan sisanya, sehingga satu
# frame beralfa ~39% adalah satu-satunya yang memuatnya dan kata itu tidak
# pernah terbaca. Fade-in dua frame + pop membuat jendela < 0,25 s praktis tak
# terlihat; 0,25 s = 7,5 frame pada 30 fps, cukup untuk fade-in, pop, dan
# setidaknya beberapa frame teks diam. Angka ini dipilih dari temuan F2, bukan
# dikalibrasi ulang di tugas ini.
MIN_VISIBLE = 0.25

# Batas kata untuk satu frasa hasil gabungan. Enam kata masih muat dua baris
# pada em 84 untuk kata-kata transkrip normal (lebar baris 972 px) dan menjaga
# agar penggabungan berantai berhenti; lebih dari itu frasa menjadi terlalu
# padat untuk dibaca dalam satu jendela.
MAX_MERGED_WORDS = 6

SCALE_START = 60.0       # skala awal pop kata (%)
SCALE_END = 100.0        # skala akhir normal (%)
SCALE_EMPHASIS = 112.0   # skala akhir kata emphasis (%)

# Maksimum segmen rantai \t per kata. 10 dipilih dari pengukuran: pada 30 fps
# galat relatif maksimum rantai terhadap spring analitik 0,66% (target 100) dan
# 0,75% (target 112), jauh di dalam toleransi 2% yang diminta rencana. Menambah
# segmen tidak menurunkan galat secara berarti karena batasnya adalah lebar
# frame (33 ms), bukan jumlah titik.
MAX_SEGMENTS = 10

# Batas galat chord yang dipakai saat menambah titik: 0,2% dari rentang skala
# (0,2 poin persen pada 60->100). Ini yang membuat rantai berhenti menambah
# segmen lebih awal daripada 10 pada fps rendah, sehingga tidak ada \t
# berdurasi 0 ms (yang tidak monoton dan bisa diabaikan libass).
_CHAIN_TOLERANCE = 0.2

# --- celah antar-kata (Langkah 3b-iii; clearance dikoreksi 3b-iv) -----------
#
# Celah yang dijanjikan `gap_em` bukan celah yang terlihat: garis tepi (Outline)
# 7 px tiap kata memakan 14 px, dan bearing sisi glyph memakan 0-13 px lagi.
# Terukur pada render nyata: `apa|enggak` tinggal 7 px, `apa|capeknya` 0 px,
# sedangkan celah antar-huruf di dalam kata 6-11 px -> kata terbaca menyatu.
#
# Karena itu celah diturunkan dari celah TINTA yang diinginkan:
#
#     celah_tinta_target = 2 x OUTLINE_PX + CLEARANCE_EM x size
#
# `2 x OUTLINE_PX` karena tiap kata adalah event ASS terpisah di Layer yang
# sama: garis tepi kata yang digambar belakangan menutupi 7 px di sekitarnya,
# jadi kedua kata harus menyisakan 7 px masing-masing. `CLEARANCE_EM x size`
# adalah sisa latar yang membuat dua kata terbaca sebagai dua kata.
#
# Kenapa 0,22 em: jarak tinta ALAMI Archivo Black pada transkrip nyata
# (`work/clip04`, em 84) = spasi 0,333 em (27,97 px) + rsb + lsb, median
# 35,3 px (p10 30,9; p90 38,7). 0,22 em = 18,48 px, sehingga target menjadi
# 2 x 7 + 18,48 = 32,48 px - sekitar 92% jarak alami. Itu menyisakan ruang
# untuk baris dua-kata dan puncak overshoot spring tanpa kembali sesak.
#
# Koreksi 3b-iv: 3b-iii memakai 0,10 em (target 22,4 px) dengan alasan
# "sama dengan celah `Pertama,|pasti` pada oracle lama". Alasan itu KELIRU:
# pasangan tersebut melibatkan kata beremphasis, yang tintanya memakan celah,
# jadi 22,4 px bukan celah alami antar-kata biasa. Akibatnya semua pasangan
# biasa dipersempit dari ~35 px ke ~23 px (~63% jarak alami) dan terlihat
# sesak di render nyata (`setiap hari di posisi`, `lu ngerasain`).
OUTLINE_PX = 7.0
SHADOW_PX = 3.0
CLEARANCE_EM = 0.22

# DEPRECATED: dipertahankan hanya demi kompatibilitas tanda tangan. Nilainya
# TIDAK lagi menentukan celah; lihat `CLEARANCE_EM`/`ink_gap_target`. Dulu
# celah antar kata = `GAP_EM x size` (23,52 px pada em 84).
GAP_EM = 0.28
LINE_HEIGHT_EM = 1.15

_MAX_LINES = 2

# Karakter yang tidak boleh lolos ke teks ASS: `{`/`}` membuka/menutup blok
# override dan `\` memulai perintah di dalamnya. Peta penggantinya SAMA dengan
# `captions._escape` tier-1 supaya gaya escaping kedua penulis konsisten.
_ESCAPE_MAP = {"{": "(", "}": ")", "\\": "/"}


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    """Netralkan `{`, `}` dan `\\` supaya teks tidak bisa menyuntikkan override.

    Koma aman: `Text` adalah field ke-10 (terakhir) pada format Dialogue, jadi
    tidak ada field yang bisa digeser olehnya.
    """
    out = str(text)
    for src, dst in _ESCAPE_MAP.items():
        out = out.replace(src, dst)
    return out


def _ass_time(t: float) -> str:
    """Format waktu ASS, kuantisasi sentidetik — sama persis dengan tier-1."""
    return _tier1._ass_time(t)


def _quantize(t: float) -> float:
    """Bulatkan ke sentidetik supaya teks dan End konsisten dengan stamp ASS."""
    return round(max(0.0, float(t)) + 1e-9, 2)


def _default_font_path() -> Path:
    return Path(__file__).resolve().parent.parent / BUNDLED_FONT


def _load_font(font_path: Any) -> fontmetrics.Font:
    """Muat font; berkas tidak ada -> FileNotFoundError dengan pesan jelas.

    `fontmetrics.Font.load` melempar `FontError` (turunan ValueError) untuk
    berkas rusak, tetapi untuk berkas yang tidak ada pesannya tidak menyebut
    cara memperbaikinya. Di sini kasus itu diterjemahkan ke FileNotFoundError
    supaya pemanggil bisa membedakan "font belum diunduh" dari "font rusak".
    """
    path = Path(font_path) if font_path is not None else _default_font_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"font kinetic tidak ditemukan: {path}. "
            f"Font bundel ada di {BUNDLED_FONT} (lihat assets/fonts/SOURCES.md); "
            f"jangan mengandalkan font sistem — libass akan diam-diam memakai "
            f"DejaVu dan layout kata menjadi salah (risiko R4)."
        )
    return fontmetrics.Font.load(path)


def _clean_word(word: str) -> str:
    """Normalisasi kata untuk pencocokan emphasis — sama dengan tier-1."""
    return _text.clean(str(word))


# ---------------------------------------------------------------------------
# Jendela tampil
# ---------------------------------------------------------------------------

def display_window(
    captions: list[dict[str, Any]], i: int, lead: float = DEFAULT_LEAD
) -> tuple[float, float]:
    """Jendela tampil frasa ke-`i` (detik, timeline output).

    mulai = max(0, words[0].start - lead)
    akhir = max(cap.end, words[-1].end + TAIL_PAD)
    akhir = min(akhir, mulai_frasa_berikutnya - NEXT_GUARD)
    akhir > mulai dijamin (bila terjepit: mulai + MIN_WINDOW)

    `captions[].start/end` tidak pernah diubah, hanya dibaca. Frasa tanpa
    `words` memakai `cap.start/end` apa adanya sebagai batas, karena tidak ada
    waktu kata untuk dijadikan acuan.
    """
    cap = captions[i]
    words = cap.get("words") or []
    if words:
        start = max(0.0, float(words[0]["start"]) - lead)
        end = max(float(cap["end"]), float(words[-1]["end"]) + TAIL_PAD)
    else:
        # Tanpa kata, tidak ada yang bisa ditampilkan; jendela tetap dihitung
        # dari caption supaya pemanggil tidak perlu cabang khusus.
        start = max(0.0, float(cap["start"]) - lead)
        end = float(cap["end"])

    if i + 1 < len(captions):
        nxt_words = captions[i + 1].get("words") or []
        if nxt_words:
            next_start = max(0.0, float(nxt_words[0]["start"]) - lead)
            end = min(end, next_start - NEXT_GUARD)
        else:
            next_start = max(0.0, float(captions[i + 1]["start"]) - lead)
            end = min(end, next_start - NEXT_GUARD)

    if end <= start:
        end = start + MIN_WINDOW
    # EDL menyimpan waktu dengan 3 desimal (lihat `edl._kinetic_words`), jadi
    # jendela dibulatkan ke presisi yang sama. Tanpa ini, `5.02 - 0.04` menjadi
    # 4.9799999999999995 dan stamp ASS berbeda dari yang dihitung di tes/laporan.
    return round(start, 3), round(end, 3)


# ---------------------------------------------------------------------------
# Bearing sisi glyph (analitik dari berkas font)
# ---------------------------------------------------------------------------

# Cache per (path font, mtime, ukuran) -> objek pembaca `glyf`. Dibangun sekali
# per proses; `fontmetrics` sudah punya cache serupa untuk metrik dasarnya.
_GLYF_CACHE: dict[tuple[str, int, int], "_GlyfReader"] = {}


class _GlyfReader:
    """`loca` + `glyf` minimal untuk bbox glyph: lsb dan rsb per glyph.

    Kenapa di sini, bukan di `fontmetrics`: `scripts/lib/*` tidak boleh disentuh
    pada tugas ini, dan yang dibutuhkan hanya dua angka per kata (lsb glyph
    pertama, rsb glyph terakhir) untuk menurunkan celah kotak dari celah tinta.
    Pembacaan memakai `struct` seperti `fontmetrics` (tanpa dependensi, D-004).
    """

    __slots__ = ("_data", "_tables", "_loca", "_glyf", "_upem", "_long_loca", "_advances")

    def __init__(self, path: Path, font: fontmetrics.Font) -> None:
        import struct

        data = path.read_bytes()
        n_tables = struct.unpack_from(">H", data, 4)[0]
        tables: dict[str, tuple[int, int]] = {}
        for i in range(n_tables):
            rec = 12 + 16 * i
            tag = data[rec : rec + 4].decode("latin-1")
            offset, length = struct.unpack_from(">II", data, rec + 8)
            tables[tag] = (offset, length)
        if "loca" not in tables or "glyf" not in tables:
            raise fontmetrics.FontError(
                f"font tanpa tabel loca/glyf, bearing tidak bisa dihitung: {path}"
            )
        self._data = data
        self._tables = tables
        self._upem = font.units_per_em
        head = tables["head"][0]
        self._long_loca = struct.unpack_from(">h", data, head + 50)[0] == 1
        self._loca = tables["loca"][0]
        self._glyf = tables["glyf"][0]
        # Advance per glyph sudah dibaca `fontmetrics`; pakai ulang supaya
        # hanya ada satu implementasi `hmtx`.
        self._advances = font._advances

    def _glyph_offset(self, gid: int) -> int:
        import struct

        if self._long_loca:
            return struct.unpack_from(">I", self._data, self._loca + 4 * gid)[0]
        return struct.unpack_from(">H", self._data, self._loca + 2 * gid)[0] * 2

    def x_extent(self, gid: int) -> tuple[int, int] | None:
        """(xMin, xMax) glyph dalam unit font, atau None untuk glyph kosong."""
        import struct

        start = self._glyph_offset(gid)
        end = self._glyph_offset(gid + 1)
        if end <= start:
            return None  # glyph kosong (mis. spasi): tidak ada tinta
        base = self._glyf + start
        _n_contours, x_min, _y_min, x_max, _y_max = struct.unpack_from(
            ">hhhhh", self._data, base
        )
        return x_min, x_max

    def bearings(self, font: fontmetrics.Font, word: str, size: float) -> tuple[float, float]:
        """(lsb glyph pertama, rsb glyph terakhir) kata pada `size`, dalam piksel.

        lsb = `xMin` glyph pertama (jarak tepi kiri kotak advance ke tinta).
        rsb = `advance - xMax` glyph terakhir (jarak tinta ke tepi kanan).
        Keduanya ANALITIK dari berkas font, bukan dikalibrasi dari render:
        kalibrasi akan mengunci nilai ke satu ukuran font dan satu versi libass.
        Glyph kosong (spasi) atau glyph tanpa `glyf` -> 0,0, karena tidak ada
        tinta yang bisa mendekat.
        """
        if not word:
            return 0.0, 0.0
        first = font.glyph_id(word[0])
        last = font.glyph_id(word[-1])
        scale = size / self._upem

        left = self.x_extent(first)
        lsb = 0.0 if left is None else left[0] * scale

        right = self.x_extent(last)
        if right is None:
            rsb = 0.0
        else:
            advance = self._advances[last] if last < len(self._advances) else 0
            rsb = (advance - right[1]) * scale
        return lsb, rsb


def _glyf_reader(font: fontmetrics.Font) -> _GlyfReader:
    path = Path(font.path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    reader = _GLYF_CACHE.get(key)
    if reader is None:
        reader = _GlyfReader(path, font)
        if len(_GLYF_CACHE) >= 16:
            _GLYF_CACHE.pop(next(iter(_GLYF_CACHE)))
        _GLYF_CACHE[key] = reader
    return reader


def word_bearings(font: fontmetrics.Font, word: str, size: float) -> tuple[float, float]:
    """(lsb, rsb) tinta `word` pada `size` piksel, dalam piksel.

    `lsb` = jarak dari tepi kiri kotak advance ke tinta paling kiri (glyph
    pertama). `rsb` = jarak dari tinta paling kanan (glyph terakhir) ke tepi
    kanan kotak advance. Dipakai `layout_phrase` untuk menurunkan celah KOTAK
    dari celah TINTA yang diinginkan, karena `gap_em x size` tidak tahu-menahu
    soal bearing.

    Nilainya analitik dari `hmtx` + bbox `glyf` (lihat `_GlyfReader`). Untuk
    kata kosong atau glyph kosong hasilnya (0, 0): tidak ada tinta.
    """
    return _glyf_reader(font).bearings(font, word, size)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def ink_gap_target(
    size: float,
    *,
    outline_px: float = OUTLINE_PX,
    clearance_em: float = CLEARANCE_EM,
) -> float:
    """Celah TINTA antar-kata yang diinginkan pada `size` (piksel).

    = `2 x outline_px + clearance_em x size`.

    Turunan. Tiap kata adalah satu event ASS di Layer yang sama, jadi libass
    menggambar garis tepi selebar `outline_px` di luar glyph tiap kata, dan
    garis tepi kata yang digambar belakangan menimpa apa pun di dalamnya.
    Dua kata yang berdekatan karena itu membutuhkan `2 x outline_px` ruang
    kosong hanya untuk garis tepinya, ditambah `clearance_em x size` sebagai
    sisa latar yang membuat keduanya terbaca sebagai dua kata.

    Pada em 84 dan Outline 7 hasilnya 32,48 px: sekitar 92% dari celah tinta
    alami Archivo Black (median 35,3 px pada transkrip nyata; spasi 0,333 em =
    27,97 px + rsb + lsb). Clearance 0,10 em dari 3b-iii (22,4 px) dikoreksi
    di 3b-iv karena alasan lamanya keliru: 22,4 px adalah celah pasangan
    `Pertama,|pasti` yang melibatkan kata beremphasis (tintanya memakan
    celah), bukan celah alami antar-kata biasa.
    """
    if not math.isfinite(size) or size < 0.0:
        raise ValueError(f"size harus >= 0 dan berhingga, dapat {size!r}")
    if not math.isfinite(outline_px) or outline_px < 0.0:
        raise ValueError(
            f"outline_px harus >= 0 dan berhingga, dapat {outline_px!r}"
        )
    if not math.isfinite(clearance_em) or clearance_em < 0.0:
        raise ValueError(
            f"clearance_em harus >= 0 dan berhingga, dapat {clearance_em!r}"
        )
    return 2.0 * outline_px + clearance_em * size


def _box_gaps(
    texts: list[str],
    scales: list[float],
    font: fontmetrics.Font,
    size: float,
    *,
    outline_px: float,
    clearance_em: float,
) -> list[float]:
    """Celah KOTAK antar kata berurutan, dari celah tinta target.

    `celah_kotak = max(0, celah_tinta_target - rsb_i x s_i - lsb_j x s_j)`.

    Turunan: tinta kata i berhenti `rsb_i x s_i` di dalam tepi kanan kotak
    BERSKALA-nya, dan tinta kata j mulai `lsb_j x s_j` di dalam tepi kiri
    kotaknya. Jadi `celah_tinta = celah_kotak + rsb_i x s_i + lsb_j x s_j`.
    Suku `(s-1)/2 x advance` tidak muncul terpisah karena kotak yang dipakai
    sudah kotak berskala (`x +- advance x s / 2`); itulah inti perbaikan
    "lebar kotak memperhitungkan skala akhir".

    Dijepit >= 0: bearing dua kata bisa lebih besar dari target (mis. `lu` 5,6
    px + `lu` 5,6 px pada clearance kecil), dan celah kotak negatif berarti
    kotak saling menembus - tata letak tidak boleh menghasilkan itu.
    """
    target = ink_gap_target(size, outline_px=outline_px, clearance_em=clearance_em)
    gaps: list[float] = []
    for i in range(len(texts) - 1):
        _, rsb = word_bearings(font, texts[i], size)
        lsb, _ = word_bearings(font, texts[i + 1], size)
        gaps.append(max(0.0, target - rsb * scales[i] - lsb * scales[i + 1]))
    return gaps


def _wrap_indices(
    widths: list[float], gaps: list[float], max_width: float, max_lines: int
) -> list[list[int]]:
    """Bungkus greedy per kata: [[indeks kata baris 0], [baris 1], ...].

    Beda dengan `fontmetrics.wrap` yang bekerja pada string: di sini yang
    dibungkus adalah indeks kata, karena lebar tiap kata sudah diukur sekali
    (pada skala akhirnya) dan tidak boleh diukur ulang dari teks gabungan.

    `gaps[i]` adalah celah kotak antara kata i dan i+1, jadi celah yang dipakai
    saat membungkus adalah celah pasangan yang benar-benar bersebelahan, bukan
    satu nilai seragam. Kata tidak pernah dipotong; kata yang lebih lebar dari
    `max_width` berdiri sendiri.
    """
    lines: list[list[int]] = []
    current: list[int] = []
    current_w = 0.0
    for i, w in enumerate(widths):
        extra = w if not current else gaps[i - 1] + w
        if current and current_w + extra > max_width:
            lines.append(current)
            current = [i]
            current_w = w
        else:
            current.append(i)
            current_w += extra
    if current:
        lines.append(current)

    if len(lines) > max_lines:
        # Baris terakhir menampung sisa kata apa adanya (melebar), tanpa ada
        # kata yang dibuang: caption tidak pernah dihilangkan.
        tail: list[int] = []
        for line in lines[max_lines - 1:]:
            tail.extend(line)
        lines = lines[: max_lines - 1] + [tail]
    return lines


def layout_phrase(
    words: list[dict[str, Any]],
    font: fontmetrics.Font,
    size: float,
    *,
    max_width: float = 972.0,
    gap_em: float = GAP_EM,
    max_lines: int = _MAX_LINES,
    center_x: float = 540.0,
    center_y: float = 1400.0,
    line_height_em: float = LINE_HEIGHT_EM,
    scales: list[float] | None = None,
    outline_px: float = OUTLINE_PX,
    clearance_em: float = CLEARANCE_EM,
) -> list[dict[str, Any]]:
    """Posisi PUSAT tiap kata untuk frasa LENGKAP (dipanggil sekali per frasa).

    Mengembalikan satu dict per kata: `{i, x, y, w, line, scale}`, `(x, y)` =
    pusat kata untuk `\\an5\\pos(x,y)`. Karena `words` adalah frasa utuh, kata
    yang sudah tampil tidak pernah bergeser saat kata berikutnya muncul.

    **Lebar kotak memperhitungkan skala akhir** (`scales`): kata beremphasis
    digambar libass pada 112%, jadi kotak yang benar-benar dipakai selebar
    `advance x 1,12`, bukan `advance`. Dulu `w` selalu `advance` 100%, sehingga
    tepi tinta kata emphasis bergeser keluar `(s-1)/2 x advance` (~16 px untuk
    "enggak") dan memakan celah antar-kata. Pemotongan baris (`max_width`) juga
    memakai lebar berskala, supaya baris tidak melewati batas setelah kata
    membesar.

    **Celah kotak diturunkan dari celah TINTA** (`ink_gap_target`), bukan dari
    `gap_em`: `celah_kotak = max(0, 2 x outline_px + clearance_em x size
    - rsb_i x s_i - lsb_j x s_j)`. Lihat `_box_gaps` untuk turunannya. Alasan:
    garis tepi 7 px tiap kata dan bearing glyph bukan bagian dari
    `gap_em x size`, dan keduanya itulah yang membuat dua kata terbaca menyatu
    di render nyata (celah tinta 7 px, sama dengan celah antar-huruf).

    Parameter `gap_em` **DEPRECATED**: dipertahankan hanya supaya pemanggil lama
    tidak pecah, dan nilainya TIDAK dipakai lagi. Celah kini ditentukan
    `clearance_em` + `outline_px` + bearing. Lihat catatan di `GAP_EM`.

    `scales=None` berarti semua kata pada skala 100% (`w` = advance), sehingga
    pemanggil yang tidak peduli emphasis tidak perlu berubah.
    """
    if max_lines < 1:
        raise ValueError(f"max_lines harus >= 1, dapat {max_lines!r}")
    if not words:
        return []

    if scales is None:
        scales = [1.0] * len(words)
    if len(scales) != len(words):
        raise ValueError(
            f"scales harus sepanjang words ({len(words)}), dapat {len(scales)}"
        )
    for i, s in enumerate(scales):
        if not math.isfinite(s) or s <= 0.0:
            raise ValueError(f"scales[{i}] harus > 0 dan berhingga, dapat {s!r}")

    texts = [_escape(w["w"]) for w in words]
    widths = [font.width(t, size) * s for t, s in zip(texts, scales)]
    gaps = _box_gaps(
        texts, scales, font, size,
        outline_px=outline_px, clearance_em=clearance_em,
    )
    lines = _wrap_indices(widths, gaps, max_width, max_lines)

    line_height = line_height_em * size
    n_lines = len(lines)
    out: dict[int, dict[str, Any]] = {}
    for line_idx, line in enumerate(lines):
        line_width = sum(widths[i] for i in line) + sum(
            gaps[i] for i in line[:-1]
        )
        # Blok dipusatkan vertikal di center_y: dengan n baris, baris ke-k
        # berada di center_y + (k - (n-1)/2) * line_height.
        y = center_y + (line_idx - (n_lines - 1) / 2.0) * line_height
        x = center_x - line_width / 2.0
        for i in line:
            out[i] = {
                "i": i,
                "x": x + widths[i] / 2.0,
                "y": y,
                "w": widths[i],
                "line": line_idx,
                "scale": scales[i],
            }
            x += widths[i]
            if i != line[-1]:
                x += gaps[i]

    return [out[i] for i in range(len(words))]


# ---------------------------------------------------------------------------
# Penggabungan frasa berjendela pendek (temuan produk F2)
# ---------------------------------------------------------------------------

# Lebar baris yang dipakai `layout_phrase` (0,9 x 1080). Disalin sebagai
# konstanta supaya pemeriksaan "muat 2 baris" memakai batas yang SAMA dengan
# tata letak; kalau default `layout_phrase` berubah, ubah keduanya.
_MAX_WIDTH = 972.0

# Ukuran em bawaan `build_ass`. `effective_captions` tidak menerima parameter
# font/ukuran sesuai kontrak publiknya; pemeriksaan muat 2 baris memakai nilai
# bawaan ini, yang juga dipakai produk.
_DEFAULT_SIZE = 84.0


def _merged_emphasis(first: dict[str, Any], second: dict[str, Any]) -> str:
    """Emphasis frasa gabungan: frasa kedua menang bila keduanya punya."""
    return str(second.get("emphasis") or first.get("emphasis") or "")


def _scales_for_emphasis(
    words: list[dict[str, Any]], emphasis: str
) -> list[float]:
    """Skala akhir tiap kata untuk frasa gabungan (satu emphasis per frasa).

    Aturannya sama dengan `build_ass`: kemunculan PERTAMA kata yang cocok
    mendapat `SCALE_EMPHASIS`, sisanya `SCALE_END`. Dipakai hanya untuk
    memeriksa apakah frasa muat dua baris; `build_ass` tetap menghitung
    skalanya sendiri dari frasa yang sudah digabung.
    """
    clean = _clean_word(emphasis) if emphasis else ""
    scales: list[float] = []
    accented = False
    for w in words:
        if clean and not accented and _clean_word(w["w"]) == clean:
            scales.append(SCALE_EMPHASIS / 100.0)
            accented = True
        else:
            scales.append(SCALE_END / 100.0)
    return scales


def _fits_two_lines(
    words: list[dict[str, Any]],
    emphasis: str,
    font: fontmetrics.Font,
    size: float,
) -> bool:
    """True bila `words` muat dua baris pada tata letak `build_ass`.

    `layout_phrase` tidak membuang kata: bila baris alami lebih dari
    `max_lines`, sisa kata digabung ke baris terakhir sehingga garis itu
    MELEBAR. Karena itu jumlah baris saja tidak cukup; lebar tiap baris hasil
    (dari `x - w/2` ke `x + w/2`) juga harus <= `_MAX_WIDTH`. Frasa yang butuh
    tiga baris akan menghasilkan baris terakhir yang melewati batas ini.
    """
    positions = layout_phrase(
        words, font, size, max_lines=_MAX_LINES,
        scales=_scales_for_emphasis(words, emphasis),
    )
    rows: dict[int, list[dict[str, Any]]] = {}
    for pos in positions:
        rows.setdefault(int(pos["line"]), []).append(pos)
    if len(rows) > _MAX_LINES:
        return False
    for row in rows.values():
        left = min(p["x"] - p["w"] / 2.0 for p in row)
        right = max(p["x"] + p["w"] / 2.0 for p in row)
        if right - left > _MAX_WIDTH + 1e-9:
            return False
    return True


def _pair_fits(
    first: dict[str, Any],
    second: dict[str, Any],
    max_words: int,
    font: fontmetrics.Font,
    size: float,
) -> bool:
    """True bila `first` dan `second` boleh digabung jadi satu frasa.

    Syarat: keduanya punya kata, jumlah kata gabungan <= `max_words`, dan
    gabungannya muat dua baris. Frasa tanpa `words` tidak bisa digabung karena
    waktu kata untuk kata-katanya tidak ada.
    """
    first_words = first.get("words") or []
    second_words = second.get("words") or []
    if not first_words or not second_words:
        return False
    if len(first_words) + len(second_words) > max_words:
        return False
    merged_words = list(first_words) + list(second_words)
    return _fits_two_lines(
        merged_words, _merged_emphasis(first, second), font, size
    )


def _merge_pair(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Gabungkan dua frasa jadi SATU frasa baru (tanpa menyentuh masukan).

    - `start` = awal frasa pertama; `end` = akhir frasa kedua.
    - `text` = kedua teks digabung dengan satu spasi.
    - `words` = kata pertama lalu kata kedua; waktu kata TIDAK diubah.
    - `emphasis` = milik frasa mana pun; frasa kedua menang bila keduanya punya.
    - Kunci lain (mis. `src_start`) diambil dari frasa PERTAMA.
    """
    first_words = list(first.get("words") or [])
    second_words = list(second.get("words") or [])
    out = deepcopy(first)

    if "start" in first:
        out["start"] = first["start"]
    elif first_words:
        out["start"] = first_words[0]["start"]
    if "end" in second:
        out["end"] = second["end"]
    elif second_words:
        out["end"] = second_words[-1]["end"]

    first_text = first.get("text")
    if first_text is None:
        first_text = " ".join(str(w["w"]) for w in first_words)
    second_text = second.get("text")
    if second_text is None:
        second_text = " ".join(str(w["w"]) for w in second_words)
    parts = [str(p) for p in (first_text, second_text) if str(p) != ""]
    out["text"] = " ".join(parts)

    out["words"] = deepcopy(first_words) + deepcopy(second_words)

    emphasis = _merged_emphasis(first, second)
    if emphasis:
        out["emphasis"] = emphasis
    else:
        out.pop("emphasis", None)
    return out


def effective_captions(
    captions: list[dict[str, Any]],
    *,
    min_visible: float = MIN_VISIBLE,
    max_words: int = MAX_MERGED_WORDS,
) -> list[dict[str, Any]]:
    """Daftar caption SETELAH frasa berjendela pendek digabung (murni).

    Masalah yang diperbaiki (temuan produk F2): `display_window` dapat
    menghasilkan jendela yang lebih pendek dari fade-in + pop, sehingga kata
    tidak pernah terbaca. Contoh nyata: `Lu,` (kata 80 ms) hanya tampil 40 ms
    karena `DEFAULT_LEAD` + `NEXT_GUARD`. Penggabungan terjadi saat RENDER;
    EDL tidak berubah (D-010) dan waktu kata tidak diubah.

    Aturan, deterministik dari kiri ke kanan:
      1. Kandidat = caption ber-`words` yang `end - start < min_visible`.
      2. Coba gabung ke frasa BERIKUTNYA bila ada, jumlah kata gabungan
         <= `max_words`, dan muat dua baris (`layout_phrase`, batas yang sama
         dengan `build_ass`).
      3. Bila tidak bisa, coba gabung ke frasa SEBELUMNYA dengan syarat sama.
      4. Bila keduanya tidak memenuhi, biarkan apa adanya (tidak pernah gagal).
    Setelah satu penggabungan, daftar dipindai ulang dari awal; tiap
    penggabungan memperpendek daftar, jadi rantai A+B+C berhenti dan tidak ada
    rekursi tak terbatas.

    Nilai balik selalu salinan dalam (deep copy): `captions` dan `words` milik
    pemanggil tidak pernah dimodifikasi, termasuk pada kasus tanpa
    penggabungan.
    """
    out = [deepcopy(cap) for cap in (captions or [])]
    font: fontmetrics.Font | None = None

    while True:
        merged = False
        for i, cap in enumerate(out):
            if not (cap.get("words") or []):
                # Tanpa waktu kata tidak ada yang bisa digabung dan tidak ada
                # yang bisa dihitung jendelanya dengan benar.
                continue
            start, end = display_window(out, i)
            if not (end - start < min_visible):
                continue

            if font is None:
                font = _load_font(None)

            if i + 1 < len(out) and _pair_fits(
                cap, out[i + 1], max_words, font, _DEFAULT_SIZE
            ):
                out[i : i + 2] = [_merge_pair(cap, out[i + 1])]
                merged = True
                break
            if i > 0 and _pair_fits(
                out[i - 1], cap, max_words, font, _DEFAULT_SIZE
            ):
                out[i - 1 : i + 1] = [_merge_pair(out[i - 1], cap)]
                merged = True
                break
        if not merged:
            return out


# ---------------------------------------------------------------------------
# Rantai spring
# ---------------------------------------------------------------------------

def _scale_at(t: float, target: float) -> float:
    return SCALE_START + (target - SCALE_START) * spring.spring(t)


def _chord_error(t0: float, t1: float, target: float) -> float:
    """Galat maksimum antara garis lurus t0->t1 dan kurva spring di antaranya."""
    v0 = _scale_at(t0, target)
    v1 = _scale_at(t1, target)
    worst = 0.0
    steps = 64
    for k in range(1, steps):
        f = k / steps
        tm = t0 + (t1 - t0) * f
        chord = v0 + (v1 - v0) * f
        worst = max(worst, abs(chord - _scale_at(tm, target)))
    return worst


def spring_chain(
    fps: float,
    target: float,
    *,
    start: float = SCALE_START,
    max_segments: int = MAX_SEGMENTS,
) -> list[tuple[int, float]]:
    """Titik rantai `\\t` untuk skala `start` -> `target`: [(ms, skala), ...].

    Strategi (angka terukur ada di laporan tugas):
      1. Mulai dari grid FRAME sampai settle (33 ms di 30 fps) — animasi harus
         mengikuti apa yang benar-benar terlihat per frame.
      2. Kalau titiknya lebih dari `max_segments`+1, buang titik yang galat
         chord-nya paling kecil (thinning) sampai muat.
      3. Kalau masih ada ruang, belah segmen dengan galat terbesar sampai
         `_CHAIN_TOLERANCE` terpenuhi atau batas segmen habis.

    Hasil: waktu bulat MILIDETIK yang naik ketat, nilai skala dibulatkan ke
    bilangan bulat persen (libass membacanya sebagai persen), dan titik terakhir
    tepat `target` supaya kata berhenti di skala akhir, bukan di 102%.
    """
    if not (fps > 0.0) or not math.isfinite(fps):
        raise ValueError(f"fps harus > 0 dan berhingga, dapat {fps!r}")
    if max_segments < 1:
        raise ValueError(f"max_segments harus >= 1, dapat {max_segments!r}")

    settle = spring.settle_time()
    frames = max(1, math.ceil(round(settle * fps, 9)))
    nodes = [i / fps for i in range(frames + 1)]
    if nodes[-1] > settle:
        nodes[-1] = settle
    # Jangan pernah menyisakan dua titik identik (dt = 0 -> \t(0,0) tak valid).
    nodes = sorted({round(t, 9) for t in nodes})

    while len(nodes) - 1 > max_segments:
        best = None
        for i in range(1, len(nodes) - 1):
            err = _chord_error(nodes[i - 1], nodes[i + 1], target)
            if best is None or err < best[0]:
                best = (err, i)
        if best is None:
            break
        nodes.pop(best[1])

    while len(nodes) - 1 < max_segments:
        errors = [
            (_chord_error(nodes[i], nodes[i + 1], target), i)
            for i in range(len(nodes) - 1)
        ]
        err, i = max(errors)
        if err <= _CHAIN_TOLERANCE:
            break
        mid = round((nodes[i] + nodes[i + 1]) / 2.0, 9)
        if mid <= nodes[i] or mid >= nodes[i + 1]:
            break
        nodes.insert(i + 1, mid)

    chain: list[tuple[int, float]] = []
    for t in nodes[:-1]:
        chain.append((round(t * 1000.0), float(round(_scale_at(t, target)))))
    chain.append((round(nodes[-1] * 1000.0), float(round(target))))

    # Waktu wajib naik ketat dalam milidetik. Bila fps sangat tinggi, dua titik
    # frame bisa jatuh di milidetik yang sama; buang yang duplikat, dan kalau
    # tersisa satu titik pakai titik akhir saja.
    dedup: list[tuple[int, float]] = []
    for ms, value in chain:
        if dedup and ms <= dedup[-1][0]:
            dedup[-1] = (dedup[-1][0], value)
            continue
        dedup.append((ms, value))
    if len(dedup) < 2:
        dedup = [(0, float(round(start))), (max(1, chain[-1][0]), float(round(target)))]
    return dedup


# ---------------------------------------------------------------------------
# ASS
# ---------------------------------------------------------------------------

def _scale_tags(chain: list[tuple[int, float]]) -> str:
    """Rantai `\\t(t0,t1,\\fscx..\\fscy..)` dari titik-titik rantai."""
    parts: list[str] = []
    for (t0, _), (t1, value) in zip(chain, chain[1:]):
        v = f"{value:g}"
        parts.append(f"\\t({t0},{t1},\\fscx{v}\\fscy{v})")
    return "".join(parts)


def _alpha_tag(fps: float) -> str:
    """Alpha 0 -> 1 dalam 2 frame, mulai di awal event.

    Durasi dibulatkan KE BAWAH: fade harus selesai paling lambat tepat di
    frame ke-2. Membulatkan ke atas (67 ms pada 30 fps) membuat alpha baru
    penuh sesudah frame ke-2, yang melanggar "alpha penuh pada frame ke-2".
    """
    ms = max(1, int(2 * 1000.0 / fps))
    return f"\\t(0,{ms},\\alpha&H00&)"


def _event_line(
    start: float,
    end: float,
    x: float,
    y: float,
    text: str,
    *,
    chain: list[tuple[int, float]],
    alpha: str,
    colour: str | None,
) -> str:
    """Satu baris Dialogue. `Text` adalah field ke-10, jadi koma aman."""
    colour_tag = f"\\c{colour}" if colour else ""
    override = (
        f"{{\\an5\\pos({x:.2f},{y:.2f})\\fscx{SCALE_START:g}\\fscy{SCALE_START:g}"
        f"\\alpha&HFF&{colour_tag}{alpha}{_scale_tags(chain)}}}"
    )
    return (
        f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Kinetic,,0,0,0,,"
        f"{override}{text}"
    )


def _template() -> str:
    path = Path(__file__).resolve().parent.parent / "templates" / "caption_kinetic.ass.tmpl"
    if not path.is_file():
        raise FileNotFoundError(f"template kinetic tidak ditemukan: {path}")
    return path.read_text(encoding="utf-8")


def _fill_template(
    template: str,
    font_family: str,
    size: float,
    *,
    outline_px: float = OUTLINE_PX,
    shadow_px: float = SHADOW_PX,
) -> str:
    """Isi placeholder template; `size` di sini SUDAH berupa `Fontsize` ASS.

    Pemanggil bertanggung jawab mengalikan em dengan `cell_height_ratio`;
    fungsi ini tidak tahu-menahu soal semantik ukuran. `outline_px`/`shadow_px`
    diisi ke kolom Outline/Shadow `Style` supaya tata letak (yang mengurangi
    `2 x outline_px` dari celah tinta) dan render memakai angka yang SAMA.
    """
    return (
        template.replace("{{FONT}}", font_family)
        .replace("{{FONTSIZE}}", f"{size:g}")
        .replace("{{OUTLINE}}", f"{outline_px:g}")
        .replace("{{SHADOW}}", f"{shadow_px:g}")
        .replace("{{PRIMARY}}", _tier1.PRIMARY)
        .replace("{{ACCENT}}", _tier1.ACCENT)
    )

def _style_font_size(font: fontmetrics.Font, size: float) -> float:
    """`Fontsize` ASS yang membuat libass menggambar `size` sebagai em.

    libass (`ass_face_set_size`, gaya VSFilter) menafsirkan `Fontsize` sebagai
    tinggi sel `usWinAscent + usWinDescent`, bukan em. Untuk Archivo Black
    rasionya 1,347, jadi menulis `Fontsize = 84` membuat glyph 26% lebih kecil
    dari kotak `layout_phrase` — cacat yang terukur pada render sungguhan
    (lebar kata 0,707-0,724 x prediksi; docs/MOTION-TIER2-PLAN.md "Status
    Langkah 3b-i"). Karena itu `Fontsize = em x cell_height_ratio`.

    Dibulatkan ke 2 desimal: presisi 0,01 px pada `Fontsize` jauh di bawah
    satu piksel hasil render, dan teks ASS jadi stabil/deterministik.
    """
    return round(size * font.cell_height_ratio, 2)


def build_ass(
    clip: dict[str, Any],
    *,
    fps: float = 30.0,
    lead: float = DEFAULT_LEAD,
    font_path: Any = None,
    size: float = 84.0,
    play_res: tuple[int, int] = (1080, 1920),
    center_y: float = 1400.0,
    uppercase: bool = False,
    outline_px: float = OUTLINE_PX,
    clearance_em: float = CLEARANCE_EM,
) -> str:
    """ASS lengkap satu klip: satu `Dialogue` per kata, Layer 1.

    `Start` = max(window_start, word.start - lead) (dikuantisasi ke sentidetik
    seperti `captions.py`), `End` = akhir jendela frasa. Frasa tanpa `words`
    dilewati. Keluar frasa = potongan keras (tanpa `\\fade`), konsisten dengan
    keputusan tier-1.

    Sebelum jendela dan layout dihitung, `effective_captions` menggabungkan
    frasa yang `display_window`-nya lebih pendek dari `MIN_VISIBLE` (temuan
    produk F2). Penggabungan hanya memengaruhi ASS; `captions[].start/end`
    di EDL tidak pernah diubah.

    `uppercase=False` (bawaan) mempertahankan case asli transkrip: gaya reel
    yang memotivasi tier-2 memakai sentence case, bukan kapital. Teks
    ditransformasi SEBELUM diukur, jadi layout selalu mengikuti teks yang
    benar-benar digambar.

    **Semantik `size`: em dalam piksel**, bukan `Fontsize` ASS. Nilai ini
    dipakai apa adanya oleh `layout_phrase` (lebar kata, celah tinta dari
    `ink_gap_target`, tinggi baris 1,15 em), jadi mengubahnya mengubah tata
    letak. Yang ditulis ke `Style` adalah `round(size * font.cell_height_ratio,
    2)` karena libass menafsirkan `Fontsize` sebagai tinggi sel
    `usWinAscent + usWinDescent`
    (1,347 em untuk Archivo Black), bukan em — lihat
    `fontmetrics.Font.cell_height_ratio` dan catatan R3 di
    docs/MOTION-TIER2-PLAN.md. Pemisahan ini disengaja: tata letak berpikir
    dalam em, libass berpikir dalam tinggi sel, dan hanya penulis ASS yang
    perlu tahu bedanya.

    **Celah antar-kata** (`clearance_em`, `outline_px`) diteruskan apa adanya ke
    `layout_phrase`, dan `outline_px` juga ditulis ke kolom Outline `Style`
    supaya template dan tata letak memakai SATU angka yang sama. Sebelum
    Langkah 3b-iii kedua tempat itu tidak terhubung: template menulis 7 px
    garis tepi yang tidak pernah diperhitungkan tata letak, sehingga celah
    tinta di dekat kata beremphasis tinggal 7-9 px (sama dengan celah
    antar-huruf) dan kata terbaca menyatu. `outline_px=0.0` mematikan garis
    tepi di kedua tempat sekaligus - itu yang dipakai tes kontrol negatif.
    """
    font = _load_font(font_path)
    # Frasa berjendela sangat pendek digabung ke tetangganya SAAT RENDER
    # (temuan produk F2). Klip tanpa frasa pendek menghasilkan daftar yang
    # nilainya identik, jadi ASS-nya byte-identik dengan sebelum perubahan.
    captions = effective_captions(clip.get("captions") or [])
    width, height = play_res

    chain_cache: dict[float, list[tuple[int, float]]] = {}
    alpha = _alpha_tag(fps)

    events: list[str] = []
    for i, cap in enumerate(captions):
        words = cap.get("words") or []
        if not words:
            continue  # tidak ada waktu kata: tidak ada yang bisa dianimasikan

        window_start, window_end = display_window(captions, i, lead)

        shown: list[str] = []
        for w in words:
            raw = str(w["w"])
            shown.append(raw.upper() if uppercase else raw)

        emphasis = cap.get("emphasis")
        emphasis_clean = _clean_word(emphasis) if emphasis else ""
        accented = False

        # Skala akhir tiap kata ditentukan SEBELUM layout, karena kotak kata
        # emphasis selebar `advance x 1,12` di layar. Menentukan skala sesudah
        # layout (perilaku lama) membuat celah antar-kata dihitung untuk kotak
        # 100% dan tinta kata emphasis memakan celah itu.
        targets: list[float] = []
        for w in words:
            if emphasis_clean and not accented and _clean_word(w["w"]) == emphasis_clean:
                # Maksimum SATU kata beraksen per frasa; kalau kata yang sama
                # muncul dua kali, hanya kemunculan pertama yang diangkat.
                targets.append(SCALE_EMPHASIS)
                accented = True
            else:
                targets.append(SCALE_END)
        scales = [t / 100.0 for t in targets]

        # Layout dihitung dari frasa LENGKAP, sekali, atas teks yang digambar.
        positions = layout_phrase(
            [{"w": t} for t in shown],
            font,
            size,
            center_y=center_y,
            scales=scales,
            outline_px=outline_px,
            clearance_em=clearance_em,
        )

        for w, text, pos, target in zip(words, shown, positions, targets):
            colour = _tier1.ACCENT if target == SCALE_EMPHASIS else None

            chain = chain_cache.get(target)
            if chain is None:
                chain = spring_chain(fps, target)
                chain_cache[target] = chain

            word_start = max(window_start, float(w["start"]) - lead)
            events.append(
                _event_line(
                    _quantize(word_start),
                    _quantize(window_end),
                    pos["x"],
                    pos["y"],
                    _escape(text),
                    chain=chain,
                    alpha=alpha,
                    colour=colour,
                )
            )

    template = _fill_template(
        _template(),
        font.family,
        _style_font_size(font, size),
        outline_px=outline_px,
    )
    template = template.replace("PlayResX: 1080", f"PlayResX: {width}")
    template = template.replace("PlayResY: 1920", f"PlayResY: {height}")
    return template.replace("{{EVENTS}}", "\n".join(events))
