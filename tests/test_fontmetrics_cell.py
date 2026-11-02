"""Tes `Font.cell_height_ratio` — tinggi sel OS/2 yang dipakai libass.

Kenapa ada: libass (`ass_face_set_size`) menafsirkan `Fontsize` ASS sebagai
tinggi sel `usWinAscent + usWinDescent` dalam unit font, BUKAN sebagai em.
Archivo Black: win 1035 + 312 = 1347 pada upem 1000, jadi em efektif =
Fontsize / 1,347. Tanpa properti ini, `Style Fontsize` yang ditulis dari em
membuat glyph 26% lebih kecil dari kotak tata letaknya (risiko R3, terbukti
pada render libass sungguhan).

Berkas ini membangun font sfnt sintetis sendiri (stdlib `struct` saja) supaya
setiap cabang pembacaan punya kasus eksplisit: OS/2 normal, OS/2 tidak ada,
OS/2 terpotong, win 0/0, hhea 0/0, dan upem != 1000. Font nyata diuji di
`tests/test_fonts_assets.py`.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401

from scripts.lib import fontmetrics

BUNDLED_FONT = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"

# Nilai terukur pada font bundel (dibaca langsung dari tabelnya).
ARCHIVO_WIN_ASCENT = 1035
ARCHIVO_WIN_DESCENT = 312
ARCHIVO_UPEM = 1000
ARCHIVO_RATIO = 1347 / 1000  # 1,347

# ---------------------------------------------------------------------------
# Pembangun sfnt sintetis minimal
# ---------------------------------------------------------------------------

DEFAULT_UPEM = 1000
# glyph 0 = .notdef, 1 = 'W', 2 = 'i'
DEFAULT_ADVANCES = [500, 1000, 300]
DEFAULT_HHEA_ASCENDER = 800
DEFAULT_HHEA_DESCENDER = -200

def _pad4(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 4)

def _head(units_per_em: int) -> bytes:
    return struct.pack(
        ">IIIIHHqqhhhhHHhhh",
        0x00010000, 0x00010000, 0, 0x5F0F3CF5, 0, units_per_em,
        0, 0, 0, 0, 1000, 1000, 0, 8, 2, 0, 0,
    )

def _hhea(number_of_h_metrics: int, ascender: int, descender: int) -> bytes:
    return struct.pack(
        ">IhhhHhhhhhh8xhH",
        0x00010000, ascender, descender, 0, 1000, 0, 0, 1000,
        1, 0, 0, 0, number_of_h_metrics,
    )

def _maxp(num_glyphs: int) -> bytes:
    return struct.pack(">IH", 0x00010000, num_glyphs) + b"\x00" * 26

def _hmtx(advances: list[int]) -> bytes:
    return b"".join(struct.pack(">Hh", adv, 0) for adv in advances)

def _os2(win_ascent: int, win_descent: int, *, length: int = 78) -> bytes:
    """Tabel OS/2 dengan usWinAscent (offset 74) dan usWinDescent (offset 76).

    `length` bisa dipendekkan untuk menguji pemeriksaan batas: pembaca harus
    jatuh ke hhea, bukan membaca byte tabel sebelahnya atau melempar galat.
    """
    body = bytearray(length)
    struct.pack_into(">H", body, 0, 3)  # version
    if length >= 78:
        struct.pack_into(">HH", body, 74, win_ascent, win_descent)
    return bytes(body)

def _cmap_format4() -> bytes:
    """Dua segmen: 'W' -> gid 1, 'i' -> gid 2."""
    segments = [
        {"start": 0x57, "end": 0x57, "delta": (1 - 0x57) & 0xFFFF},
        {"start": 0x69, "end": 0x69, "delta": (2 - 0x69) & 0xFFFF},
        {"start": 0xFFFF, "end": 0xFFFF, "delta": 1},
    ]
    seg_count = len(segments)
    seg2 = seg_count * 2
    search_range = 2 * (2 ** (seg_count.bit_length() - 1))
    entry_selector = seg_count.bit_length() - 1
    range_shift = seg2 - search_range
    ends = b"".join(struct.pack(">H", s["end"]) for s in segments)
    starts = b"".join(struct.pack(">H", s["start"]) for s in segments)
    deltas = b"".join(struct.pack(">H", s["delta"] & 0xFFFF) for s in segments)
    ranges = b"\x00\x00" * seg_count
    body = (
        struct.pack(">HHHHHHH", 4, 0, 0, seg2, search_range, entry_selector, range_shift)
        + ends
        + b"\x00\x00"
        + starts
        + deltas
        + ranges
    )
    return body[:2] + struct.pack(">H", len(body)) + body[4:]

def _cmap() -> bytes:
    sub = _cmap_format4()
    return struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub

def _name() -> bytes:
    raw = "Synthetic Cell".encode("utf-16-be")
    record = struct.pack(">HHHHHH", 3, 1, 0x409, 1, len(raw), 0)
    return struct.pack(">HHH", 0, 1, 6 + 12) + record + raw

def _build_ttf(tables: dict[str, bytes]) -> bytes:
    tags = sorted(tables)
    n = len(tags)
    search_range = 16 * (2 ** (n.bit_length() - 1))
    entry_selector = n.bit_length() - 1
    range_shift = 16 * n - search_range
    header = struct.pack(">IHHHH", 0x00010000, n, search_range, entry_selector, range_shift)
    offset = 12 + 16 * n
    directory = b""
    body = b""
    for tag in tags:
        data = tables[tag]
        directory += struct.pack(">4sIII", tag.encode("latin-1"), 0, offset, len(data))
        padded = _pad4(data)
        body += padded
        offset += len(padded)
    return header + directory + body

def make_font(
    path: Path,
    *,
    units_per_em: int = DEFAULT_UPEM,
    os2: bytes | None = None,
    hhea_ascender: int = DEFAULT_HHEA_ASCENDER,
    hhea_descender: int = DEFAULT_HHEA_DESCENDER,
    advances: list[int] | None = None,
) -> Path:
    advances = list(DEFAULT_ADVANCES if advances is None else advances)
    num_glyphs = len(advances)
    tables: dict[str, bytes] = {
        "head": _head(units_per_em),
        "hhea": _hhea(num_glyphs, hhea_ascender, hhea_descender),
        "maxp": _maxp(num_glyphs),
        "hmtx": _hmtx(advances),
        "cmap": _cmap(),
        "name": _name(),
    }
    if os2 is not None:
        tables["OS/2"] = os2
    path.write_bytes(_build_ttf(tables))
    return path

class CellHeightCase(unittest.TestCase):
    """Base: satu direktori sementara per kelas."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

# ---------------------------------------------------------------------------
# Cabang utama
# ---------------------------------------------------------------------------

class WinMetricsTest(CellHeightCase):
    def test_win_ascent_plus_descent_over_upem(self) -> None:
        """OS/2 win 1035/312, upem 1000 -> 1,347 (nilai Archivo Black)."""
        path = make_font(
            self.tmp / "win1347.ttf", os2=_os2(ARCHIVO_WIN_ASCENT, ARCHIVO_WIN_DESCENT)
        )
        font = fontmetrics.Font.load(path)
        self.assertEqual(font.units_per_em, ARCHIVO_UPEM)
        self.assertEqual(font.cell_height_ratio, ARCHIVO_RATIO)

    def test_win_metrics_win_over_hhea(self) -> None:
        """hhea di font ini 800/-200 (=1,0); win 1035/312 harus menang."""
        path = make_font(self.tmp / "win_beats_hhea.ttf", os2=_os2(1035, 312))
        font = fontmetrics.Font.load(path)
        self.assertEqual(font.cell_height_ratio, ARCHIVO_RATIO)
        self.assertNotAlmostEqual(font.cell_height_ratio, 1.0, places=3)

    def test_upem_not_1000(self) -> None:
        """upem 2048: pembaginya 2048, bukan 1000 (mutan 'bagi 1000')."""
        path = make_font(
            self.tmp / "upem2048.ttf",
            units_per_em=2048,
            os2=_os2(2070, 624),
            advances=[1024, 2048, 512],
        )
        font = fontmetrics.Font.load(path)
        self.assertEqual(font.units_per_em, 2048)
        self.assertAlmostEqual(font.cell_height_ratio, 2694 / 2048, places=12)
        # Kalau pembaginya dipaku 1000, hasilnya 2,694: beda jauh.
        self.assertLess(font.cell_height_ratio, 1.5)

# ---------------------------------------------------------------------------
# Jatuh ke hhea
# ---------------------------------------------------------------------------

class HheaFallbackTest(CellHeightCase):
    def test_no_os2_table_uses_hhea(self) -> None:
        """Tanpa OS/2: (ascender - descender) / upem = (800 - -200) / 1000."""
        path = make_font(self.tmp / "no_os2.ttf", os2=None)
        font = fontmetrics.Font.load(path)
        self.assertAlmostEqual(font.cell_height_ratio, 1.0, places=12)

    def test_no_os2_uses_real_hhea_values_not_one(self) -> None:
        """hhea 900/-250 -> 1,15: membuktikan nilainya benar-benar dibaca."""
        path = make_font(
            self.tmp / "no_os2_hhea.ttf",
            os2=None,
            hhea_ascender=900,
            hhea_descender=-250,
        )
        font = fontmetrics.Font.load(path)
        self.assertAlmostEqual(font.cell_height_ratio, 1.15, places=12)

    def test_truncated_os2_falls_back_to_hhea(self) -> None:
        """OS/2 terlalu pendek -> hhea, bukan crash dan bukan byte tabel lain.

        Tabel OS/2 sengaja diletakkan di awal berkas (urut tag) sehingga
        membaca offset 74/76 tanpa pemeriksaan panjang akan mengambil byte
        tabel berikutnya — nilai sampah yang tidak sama dengan 1,15.
        """
        path = make_font(
            self.tmp / "short_os2.ttf",
            os2=_os2(1035, 312, length=60),
            hhea_ascender=900,
            hhea_descender=-250,
        )
        font = fontmetrics.Font.load(path)
        self.assertAlmostEqual(font.cell_height_ratio, 1.15, places=12)

    def test_zero_win_metrics_fall_back_to_hhea(self) -> None:
        """win 0/0 tidak informatif -> hhea (mutan 'pakai 0/0 apa adanya' -> 0,0)."""
        path = make_font(
            self.tmp / "zero_win.ttf",
            os2=_os2(0, 0),
            hhea_ascender=900,
            hhea_descender=-250,
        )
        font = fontmetrics.Font.load(path)
        self.assertAlmostEqual(font.cell_height_ratio, 1.15, places=12)

    def test_zero_everything_gives_one(self) -> None:
        """OS/2 0/0 DAN hhea 0/0 -> 1.0 (netral), bukan 0 dan bukan galat."""
        path = make_font(
            self.tmp / "zero_all.ttf",
            os2=_os2(0, 0),
            hhea_ascender=0,
            hhea_descender=0,
        )
        font = fontmetrics.Font.load(path)
        self.assertEqual(font.cell_height_ratio, 1.0)

    def test_negative_hhea_descent_adds_not_subtracts(self) -> None:
        """descender hhea negatif: asc - desc = asc + |desc| (mutan 'asc + desc' -> 0,65)."""
        path = make_font(
            self.tmp / "sign.ttf",
            os2=None,
            hhea_ascender=800,
            hhea_descender=-200,
        )
        font = fontmetrics.Font.load(path)
        self.assertAlmostEqual(font.cell_height_ratio, 1.0, places=12)
        self.assertGreater(font.cell_height_ratio, 0.9)

# ---------------------------------------------------------------------------
# Font bundel
# ---------------------------------------------------------------------------

class BundledFontTest(unittest.TestCase):
    def test_bundled_font_ratio_is_1347(self) -> None:
        """Archivo Black: win 1035 + 312 = 1347 pada upem 1000 -> 1,347 persis."""
        font = fontmetrics.Font.load(BUNDLED_FONT)
        self.assertEqual(font.units_per_em, ARCHIVO_UPEM)
        self.assertEqual(font.cell_height_ratio, ARCHIVO_RATIO)

    def test_bundled_font_ratio_is_not_hhea_ratio(self) -> None:
        """hhea Archivo (878/-210) = 1,088; nilai 1,088 berarti cabang salah."""
        font = fontmetrics.Font.load(BUNDLED_FONT)
        self.assertNotAlmostEqual(font.cell_height_ratio, 1.088, places=3)

    def test_ratio_is_stable_across_loads(self) -> None:
        a = fontmetrics.Font.load(BUNDLED_FONT).cell_height_ratio
        b = fontmetrics.Font.load(BUNDLED_FONT).cell_height_ratio
        self.assertEqual(a, b)

if __name__ == "__main__":
    unittest.main()
