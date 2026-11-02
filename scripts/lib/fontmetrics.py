"""Pembaca metrik TrueType minimal dengan `struct` — tanpa dependensi (D-004).

Kenapa ada: layout kata caption kinetic (Langkah 3) harus dihitung di Python
sebelum libass merender, jadi lebar teks perlu diketahui tanpa memanggil libass.

Yang dibaca: `head` (unitsPerEm), `hhea` (numberOfHMetrics, ascender,
descender), `hmtx`, `maxp` (numGlyphs), `cmap` (format 4 dan 12), `name`
(family/full name), dan `OS/2` (usWinAscent/usWinDescent, untuk
`Font.cell_height_ratio`).
Yang TIDAK dibaca: `kern`, `GPOS`, outline, hinting.

`Font.cell_height_ratio` ada karena libass tidak memakai em: lihat docstring
properti itu.

Batas kejujuran (risiko R3 di docs/MOTION-TIER2-PLAN.md): libass memakai
HarfBuzz, yang menerapkan kerning dan shaping. `Font.width` di sini hanya
menjumlahkan advance per glyph, jadi lebarnya bisa sedikit berbeda dari
render libass. Selisih itu diukur oleh tes oracle bbox di Langkah 3b, bukan
di sini.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

__all__ = ["Font", "FontError", "wrap"]

MAX_FILE_BYTES = 25 * 1024 * 1024
_CACHE_LIMIT = 64

# Tabel yang wajib ada agar pengukuran bisa dipercaya. `name` wajib karena
# risiko R4 (fallback font senyap) hanya bisa dideteksi bila nama keluarga
# dibaca dari berkas yang benar-benar dipakai. `OS/2` TIDAK wajib: font lama
# boleh tidak punya, dan `cell_height_ratio` punya cadangan hhea.
_REQUIRED_TABLES = ("cmap", "head", "hhea", "hmtx", "maxp", "name")

# Offset `usWinAscent` di tabel OS/2 (spec OpenType). `usWinDescent` tepat
# sesudahnya. Keduanya uint16 dan baru ada bila tabel >= 78 byte.
_OS2_WIN_ASCENT_OFFSET = 74
_OS2_WIN_DESCENT_OFFSET = 76
_OS2_WIN_FIELDS_END = _OS2_WIN_DESCENT_OFFSET + 2

_SFNT_TRUETYPE = b"\x00\x01\x00\x00"
_SFNT_CFF = b"OTTO"
_SFNT_COLLECTION = b"ttcf"


class FontError(ValueError):
    """Berkas bukan font sfnt yang bisa dibaca. Selalu turunan ValueError."""


# ---------------------------------------------------------------------------
# Pembacaan biner dengan batas eksplisit
# ---------------------------------------------------------------------------

class _Reader:
    """Pembaca big-endian dengan pemeriksaan batas; galat -> FontError."""

    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data

    def _check(self, offset: int, size: int) -> None:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise FontError(
                f"berkas terpotong: butuh {size} byte di offset {offset}, "
                f"ukuran berkas {len(self.data)}"
            )

    def u8(self, offset: int) -> int:
        self._check(offset, 1)
        return self.data[offset]

    def u16(self, offset: int) -> int:
        self._check(offset, 2)
        return struct.unpack_from(">H", self.data, offset)[0]

    def i16(self, offset: int) -> int:
        self._check(offset, 2)
        return struct.unpack_from(">h", self.data, offset)[0]

    def u32(self, offset: int) -> int:
        self._check(offset, 4)
        return struct.unpack_from(">I", self.data, offset)[0]

    def tag(self, offset: int) -> str:
        self._check(offset, 4)
        return self.data[offset : offset + 4].decode("latin-1")

    def raw(self, offset: int, size: int) -> bytes:
        self._check(offset, size)
        return self.data[offset : offset + size]


# ---------------------------------------------------------------------------
# cmap
# ---------------------------------------------------------------------------

def _parse_cmap_format4(reader: _Reader, base: int) -> dict[int, int]:
    """Format 4: segmen endCode/startCode/idDelta/idRangeOffset."""
    seg_count = reader.u16(base + 6) // 2
    if seg_count == 0:
        return {}
    end_pos = base + 14
    start_pos = base + 16 + 2 * seg_count
    delta_pos = base + 16 + 4 * seg_count
    range_pos = base + 16 + 6 * seg_count

    mapping: dict[int, int] = {}
    for seg in range(seg_count):
        end_code = reader.u16(end_pos + 2 * seg)
        start_code = reader.u16(start_pos + 2 * seg)
        delta = reader.i16(delta_pos + 2 * seg)
        range_offset = reader.u16(range_pos + 2 * seg)
        if start_code > end_code:
            continue
        for code in range(start_code, end_code + 1):
            if code == 0xFFFF:
                continue
            if range_offset == 0:
                gid = (code + delta) & 0xFFFF
            else:
                # idRangeOffset relatif terhadap LOKASI ENTRI INI, bukan ke
                # awal array atau awal tabel. Salah basis = glyph ngawur.
                addr = range_pos + 2 * seg + range_offset + 2 * (code - start_code)
                gid = reader.u16(addr)
                if gid != 0:
                    gid = (gid + delta) & 0xFFFF
            if gid:
                mapping[code] = gid
    return mapping


def _parse_cmap_format12(reader: _Reader, base: int) -> dict[int, int]:
    """Format 12: grup (startCharCode, endCharCode, startGlyphID) 32-bit."""
    n_groups = reader.u32(base + 12)
    mapping: dict[int, int] = {}
    pos = base + 16
    for _ in range(n_groups):
        start = reader.u32(pos)
        end = reader.u32(pos + 4)
        start_gid = reader.u32(pos + 8)
        pos += 12
        if start > end:
            continue
        # Batas kewarasan: tabel rusak tidak boleh membuat memori meledak.
        if end - start > 0x10FFFF:
            raise FontError(f"cmap format 12: grup terlalu besar ({start}..{end})")
        for code in range(start, end + 1):
            gid = start_gid + (code - start)
            if gid:
                mapping[code] = gid
    return mapping


def _cmap_candidates(reader: _Reader, table_offset: int) -> list[tuple[int, int, int]]:
    """(skor, offset subtable, format) untuk semua subtable yang didukung."""
    n_tables = reader.u16(table_offset + 2)
    out: list[tuple[int, int, int]] = []
    for i in range(n_tables):
        rec = table_offset + 4 + 8 * i
        platform = reader.u16(rec)
        encoding = reader.u16(rec + 2)
        sub_offset = table_offset + reader.u32(rec + 4)
        fmt = reader.u16(sub_offset)

        if fmt == 12 and (platform, encoding) in ((3, 10), (0, 4), (0, 6)):
            score = 40
        elif fmt == 12:
            score = 30
        elif fmt == 4 and (platform, encoding) == (3, 1):
            score = 20  # Unicode BMP Windows
        elif fmt == 4 and platform == 0:
            score = 15  # Unicode BMP
        elif fmt == 4:
            score = 10
        else:
            continue
        out.append((score, sub_offset, fmt))
    # Stabil: skor tertinggi menang, seri -> urutan berkas.
    out.sort(key=lambda item: -item[0])
    return out


def _parse_cmap(reader: _Reader, table_offset: int) -> dict[int, int]:
    candidates = _cmap_candidates(reader, table_offset)
    if not candidates:
        raise FontError("cmap tidak punya subtable format 4 atau 12 yang didukung")
    _, sub_offset, fmt = candidates[0]
    if fmt == 12:
        return _parse_cmap_format12(reader, sub_offset)
    return _parse_cmap_format4(reader, sub_offset)


# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------

def _decode_name(raw: bytes, platform: int) -> str:
    if platform in (0, 3):
        text = raw.decode("utf-16-be", errors="replace")
    else:
        try:
            text = raw.decode("mac_roman")
        except LookupError:  # pragma: no cover - mac_roman selalu ada di CPython
            text = raw.decode("ascii", errors="replace")
    return text.replace("\x00", "").strip()


def _parse_name_records(reader: _Reader, table_offset: int) -> dict[int, list[tuple[tuple[int, int, int], str]]]:
    count = reader.u16(table_offset + 2)
    storage = table_offset + reader.u16(table_offset + 4)
    records: dict[int, list[tuple[tuple[int, int, int], str]]] = {}
    for i in range(count):
        rec = table_offset + 6 + 12 * i
        platform = reader.u16(rec)
        encoding = reader.u16(rec + 2)
        language = reader.u16(rec + 4)
        name_id = reader.u16(rec + 6)
        length = reader.u16(rec + 8)
        offset = reader.u16(rec + 10)
        raw = reader.raw(storage + offset, length)
        records.setdefault(name_id, []).append(
            ((platform, encoding, language), _decode_name(raw, platform))
        )
    return records


def _pick_name(
    records: dict[int, list[tuple[tuple[int, int, int], str]]], name_id: int
) -> str:
    entries = records.get(name_id)
    if not entries:
        return ""

    def rank(entry: tuple[tuple[int, int, int], str]) -> tuple[int, int]:
        (platform, _encoding, language), _text = entry
        # Windows Inggris dulu, lalu Windows apa pun, lalu Unicode/Mac.
        if platform == 3 and language == 0x409:
            return (0, 0)
        if platform == 3:
            return (1, 0)
        if platform == 0:
            return (2, 0)
        return (3, 0)

    best = min(entries, key=rank)
    return best[1]


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

class Font:
    """Metrik satu berkas font. Buat lewat `Font.load`, jangan langsung."""

    __slots__ = (
        "path",
        "units_per_em",
        "family",
        "full_name",
        "number_of_h_metrics",
        "num_glyphs",
        "hhea_ascender",
        "hhea_descender",
        "win_ascent",
        "win_descent",
        "_advances",
        "_cmap",
    )

    def __init__(
        self,
        path: Path,
        units_per_em: int,
        family: str,
        full_name: str,
        advances: list[int],
        cmap: dict[int, int],
        number_of_h_metrics: int,
        num_glyphs: int,
        hhea_ascender: int = 0,
        hhea_descender: int = 0,
        win_ascent: int = 0,
        win_descent: int = 0,
    ) -> None:
        self.path = path
        self.units_per_em = units_per_em
        self.family = family
        self.full_name = full_name
        self.number_of_h_metrics = number_of_h_metrics
        self.num_glyphs = num_glyphs
        self.hhea_ascender = hhea_ascender
        self.hhea_descender = hhea_descender
        self.win_ascent = win_ascent
        self.win_descent = win_descent
        self._advances = advances
        self._cmap = cmap

    # -- pemuatan ---------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "Font":
        """Muat font dari `path` (cache per path + mtime + ukuran).

        Berkas > 25 MB, bukan sfnt, `.ttc`, atau tabel wajib yang hilang
        -> FontError (turunan ValueError).
        """
        p = Path(path)
        try:
            stat = p.stat()
        except OSError as exc:
            raise FontError(f"tidak bisa membaca font {p}: {exc}") from exc
        if not p.is_file():
            raise FontError(f"bukan berkas: {p}")
        if stat.st_size > MAX_FILE_BYTES:
            raise FontError(
                f"berkas font terlalu besar: {stat.st_size} byte > {MAX_FILE_BYTES}"
            )
        key = (str(p.resolve()), stat.st_mtime_ns, stat.st_size)
        cached = _CACHE.get(key)
        if cached is not None:
            return cached

        font = cls._parse(p)
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = font
        return font

    @classmethod
    def _parse(cls, path: Path) -> "Font":
        try:
            data = path.read_bytes()  # satu kali baca
        except OSError as exc:
            raise FontError(f"tidak bisa membaca font {path}: {exc}") from exc
        if not data:
            raise FontError(f"berkas font kosong: {path}")

        try:
            return cls._parse_bytes(path, data)
        except FontError:
            raise
        except (struct.error, IndexError, UnicodeDecodeError) as exc:
            raise FontError(f"font rusak ({path}): {exc}") from exc

    @classmethod
    def _parse_bytes(cls, path: Path, data: bytes) -> "Font":
        reader = _Reader(data)
        version = data[:4]
        if version == _SFNT_COLLECTION:
            raise FontError(
                f"berkas .ttc (koleksi) tidak didukung: {path}; pakai berkas .ttf tunggal"
            )
        if version not in (_SFNT_TRUETYPE, _SFNT_CFF):
            raise FontError(
                f"bukan TrueType/OpenType (sfnt version {version!r}): {path}"
            )

        n_tables = reader.u16(4)
        if not 0 < n_tables <= 4096:
            raise FontError(f"jumlah tabel tidak masuk akal ({n_tables}): {path}")
        tables: dict[str, tuple[int, int]] = {}
        for i in range(n_tables):
            rec = 12 + 16 * i
            tag = reader.tag(rec)
            offset = reader.u32(rec + 8)
            length = reader.u32(rec + 12)
            if offset + length > len(data):
                raise FontError(f"tabel {tag!r} keluar batas berkas: {path}")
            tables[tag] = (offset, length)

        missing = [tag for tag in _REQUIRED_TABLES if tag not in tables]
        if missing:
            raise FontError(f"tabel wajib hilang: {', '.join(missing)} ({path})")

        units_per_em = reader.u16(tables["head"][0] + 18)
        if not 16 <= units_per_em <= 16384:
            raise FontError(f"unitsPerEm tidak valid ({units_per_em}): {path}")

        num_glyphs = reader.u16(tables["maxp"][0] + 4)
        number_of_h_metrics = reader.u16(tables["hhea"][0] + 34)
        if num_glyphs == 0:
            raise FontError(f"numGlyphs 0: {path}")
        if not 0 < number_of_h_metrics <= num_glyphs:
            raise FontError(
                f"numberOfHMetrics tidak valid ({number_of_h_metrics} dari "
                f"{num_glyphs} glyph): {path}"
            )

        advances = _parse_hmtx(
            reader, tables["hmtx"][0], number_of_h_metrics, num_glyphs
        )
        cmap = _parse_cmap(reader, tables["cmap"][0])
        names = _parse_name_records(reader, tables["name"][0])
        family = _pick_name(names, 16) or _pick_name(names, 1)
        full_name = _pick_name(names, 4) or family

        hhea_ascender = reader.i16(tables["hhea"][0] + 4)
        hhea_descender = reader.i16(tables["hhea"][0] + 6)
        win_ascent, win_descent = _parse_os2_win_metrics(reader, tables.get("OS/2"))

        return cls(
            path=path,
            units_per_em=units_per_em,
            family=family,
            full_name=full_name,
            advances=advances,
            cmap=cmap,
            number_of_h_metrics=number_of_h_metrics,
            num_glyphs=num_glyphs,
            hhea_ascender=hhea_ascender,
            hhea_descender=hhea_descender,
            win_ascent=win_ascent,
            win_descent=win_descent,
        )

    # -- pengukuran -------------------------------------------------------

    @property
    def cell_height_ratio(self) -> float:
        """Faktor pengali `em` -> `Fontsize` ASS agar libass menggambar em.

        libass (`ass_face_set_size`, gaya VSFilter) menafsirkan `Fontsize`
        sebagai tinggi sel `usWinAscent + usWinDescent` dalam unit font, BUKAN
        sebagai em. Archivo Black: 1035 + 312 = 1347 pada upem 1000, jadi
        `Fontsize = 84` menghasilkan em efektif 84 / 1,347 = 62,3 px — glyph
        26% lebih kecil dari kotak yang dihitung `layout_phrase` (risiko R3).

        Karena itu penulis ASS mengalikan em dengan rasio ini. Urutan
        pemilihan, sesuai spec OpenType dan perilaku libass:

        1. `(usWinAscent + usWinDescent) / unitsPerEm` bila OS/2 ada dan
           jumlahnya bukan 0 (kasus normal; ini yang dipakai libass).
        2. `(hhea.ascender - hhea.descender) / unitsPerEm` bila OS/2 tidak
           ada, terlalu pendek, atau win-nya 0/0. `descender` di hhea
           bertanda NEGATIF, jadi dikurangkan.
        3. `1.0` bila keduanya tidak informatif — netral, bukan 0 dan bukan
           galat, supaya layout tetap berjalan pada font aneh.

        Rasio ini HANYA untuk `Fontsize`; `Font.width` tetap memakai em
        (advance / unitsPerEm), jadi tata letak tidak berubah.
        """
        upem = self.units_per_em
        win = self.win_ascent + self.win_descent
        if win > 0:
            return win / upem
        hhea = self.hhea_ascender - self.hhea_descender
        if hhea > 0:
            return hhea / upem
        return 1.0

    def glyph_id(self, ch: str) -> int:
        """Glyph id untuk satu karakter; 0 (`.notdef`) bila tidak dipetakan."""
        if not isinstance(ch, str) or len(ch) != 1:
            raise ValueError(f"glyph_id butuh tepat satu karakter, dapat {ch!r}")
        return self._cmap.get(ord(ch), 0)

    def has_glyph(self, ch: str) -> bool:
        """True bila `ch` dipetakan ke glyph nyata (bukan `.notdef`)."""
        return self.glyph_id(ch) != 0

    def advance(self, ch: str) -> int:
        """Advance satu karakter dalam unit font.

        Karakter tak terpetakan memakai advance glyph 0 (`.notdef`).
        Glyph di atas numberOfHMetrics memakai advance entri hmtx terakhir
        (aturan spec TrueType).
        """
        gid = self.glyph_id(ch)
        if gid >= len(self._advances):
            gid = 0
        return self._advances[gid]

    def width(self, text: str, size: float) -> float:
        """Lebar `text` pada ukuran `size` (satuan sama dengan `size`).

        = jumlah advance × size / unitsPerEm. TANPA kerning: HarfBuzz/libass
        bisa menghasilkan lebar sedikit berbeda (risiko R3).
        """
        if not math.isfinite(size) or size < 0.0:
            raise ValueError(f"size harus >= 0 dan berhingga, dapat {size!r}")
        total = 0
        for ch in text:
            total += self.advance(ch)
        return total * size / self.units_per_em


def _parse_os2_win_metrics(
    reader: _Reader, table: tuple[int, int] | None
) -> tuple[int, int]:
    """(usWinAscent, usWinDescent) dari OS/2, atau (0, 0) bila tak terbaca.

    Tabel `OS/2` tidak wajib ada dan versi/panjangnya berbeda-beda. Bila tabel
    tidak ada atau lebih pendek dari 78 byte (field win belum ada), kembalikan
    (0, 0) — `Font.cell_height_ratio` yang memutuskan jatuh ke hhea. Tabel
    rusak TIDAK boleh membuat pemuatan font gagal: kerusakan di sini hanya
    memengaruhi skala `Fontsize` ASS, bukan lebar teks.
    """
    if table is None:
        return 0, 0
    offset, length = table
    if length < _OS2_WIN_FIELDS_END:
        return 0, 0
    try:
        ascent = reader.u16(offset + _OS2_WIN_ASCENT_OFFSET)
        descent = reader.u16(offset + _OS2_WIN_DESCENT_OFFSET)
    except FontError:
        # Tabel mengklaim panjang cukup tetapi keluar batas berkas: perlakukan
        # seperti tabel tak terbaca, bukan galat fatal.
        return 0, 0
    return ascent, descent

def _parse_hmtx(
    reader: _Reader, table_offset: int, number_of_h_metrics: int, num_glyphs: int
) -> list[int]:
    """Advance per glyph; glyph setelah numberOfHMetrics mewarisi yang terakhir."""
    advances: list[int] = []
    for i in range(number_of_h_metrics):
        advances.append(reader.u16(table_offset + 4 * i))
    # Entri setelah numberOfHMetrics hanya berisi lsb (int16), tanpa advance:
    # advance-nya = advance entri terakhir (aturan spec TrueType).
    advances.extend([advances[-1]] * (num_glyphs - number_of_h_metrics))
    return advances


_CACHE: dict[tuple[str, int, int], Font] = {}


# ---------------------------------------------------------------------------
# Line breaking
# ---------------------------------------------------------------------------

def wrap(
    text: str,
    font: Font,
    size: float,
    max_width: float,
    max_lines: int = 2,
) -> list[str]:
    """Bungkus `text` per KATA secara greedy agar tiap baris <= `max_width`.

    - Kata tidak pernah dipotong. Kata yang lebih lebar dari `max_width`
      berdiri sendiri satu baris.
    - Bila hasilnya lebih dari `max_lines` baris, kembalikan `max_lines` baris:
      baris terakhir berisi sisa kata apa adanya (melebar), tanpa ada kata
      yang dibuang.
    - Teks kosong / hanya spasi -> list kosong.
    """
    if not math.isfinite(max_width) or max_width <= 0.0:
        raise ValueError(f"max_width harus > 0 dan berhingga, dapat {max_width!r}")
    if max_lines < 1:
        raise ValueError(f"max_lines harus >= 1, dapat {max_lines!r}")

    words = text.split()
    if not words:
        return []

    groups: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if not current:
            current = [word]
            continue
        trial = " ".join(current + [word])
        if font.width(trial, size) <= max_width:
            current.append(word)
        else:
            groups.append(current)
            current = [word]
    if current:
        groups.append(current)

    if len(groups) > max_lines:
        tail: list[str] = []
        for group in groups[max_lines - 1 :]:
            tail.extend(group)
        groups = groups[: max_lines - 1] + [tail]

    return [" ".join(group) for group in groups]
