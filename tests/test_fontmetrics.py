"""Tes `scripts.lib.fontmetrics` — pembaca metrik TTF tanpa dependensi.

Hermetik: font sintetis minimal dibangun dengan `struct` di helper tes, jadi
tes tidak bergantung pada font yang terpasang di mesin. Satu tes tambahan
memakai font sistem nyata bila ada (skip bila tidak).

Kenapa tes ini dirancang begini: kesalahan paling mudah pada pembaca TTF
adalah (a) mengabaikan numberOfHMetrics, (b) salah basis idRangeOffset di
cmap format 4, (c) salah memetakan grup cmap format 12. Masing-masing
punya kasus eksplisit di bawah, sehingga mutan yang melakukan kesalahan itu
gagal di sini.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401

from scripts.lib import fontmetrics

# ---------------------------------------------------------------------------
# Pembangun TTF sintetis
# ---------------------------------------------------------------------------

UNITS_PER_EM = 1000
# glyph 0 = .notdef, 1 = 'W', 2 = 'i', 3 = ' ', 4 = 'A', 5 = emoji (font fmt 12)
DEFAULT_ADVANCES = [500, 1000, 300, 250, 700]


def _pad4(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 4)


def _head(units_per_em: int = UNITS_PER_EM) -> bytes:
    return struct.pack(
        ">IIIIHHqqhhhhHHhhh",
        0x00010000,  # version
        0x00010000,  # fontRevision
        0,  # checkSumAdjustment
        0x5F0F3CF5,  # magicNumber
        0,  # flags
        units_per_em,  # unitsPerEm (offset 18)
        0,  # created
        0,  # modified
        0, 0, 1000, 1000,  # bbox
        0,  # macStyle
        8,  # lowestRecPPEM
        2,  # fontDirectionHint
        0,  # indexToLocFormat
        0,  # glyphDataFormat
    )


def _hhea(number_of_h_metrics: int) -> bytes:
    return struct.pack(
        ">IhhhHhhhhhh8xhH",
        0x00010000,  # version
        800,  # ascender
        -200,  # descender
        0,  # lineGap
        1000,  # advanceWidthMax
        0,  # minLeftSideBearing
        0,  # minRightSideBearing
        1000,  # xMaxExtent
        1,  # caretSlopeRise
        0,  # caretSlopeRun
        0,  # caretOffset
        0,  # metricDataFormat (offset 32)
        number_of_h_metrics,  # numberOfHMetrics (offset 34)
    )


def _maxp(num_glyphs: int) -> bytes:
    # Versi 1.0: 4 byte version + 14 uint16; hanya numGlyphs (offset 4) yang dibaca.
    return struct.pack(">IH", 0x00010000, num_glyphs) + b"\x00" * 26


def _hmtx(advances: list[int], number_of_h_metrics: int) -> bytes:
    out = b""
    for gid in range(number_of_h_metrics):
        out += struct.pack(">Hh", advances[gid], 0)
    # Glyph setelah numberOfHMetrics hanya punya lsb (int16).
    for _gid in range(number_of_h_metrics, len(advances)):
        out += struct.pack(">h", 0)
    return out


def _cmap_format4(segments: list[dict], glyph_ids: list[int]) -> bytes:
    """Bangun subtable cmap format 4.

    Tiap segmen: {"start", "end", "delta"} atau {"start", "end", "gid"}.
    Segmen ber-"gid" memakai idRangeOffset + glyphIdArray (bukan idDelta).
    """
    seg_count = len(segments)
    seg2 = seg_count * 2
    search_range = 2 * (2 ** (seg_count.bit_length() - 1))
    entry_selector = seg_count.bit_length() - 1
    range_shift = seg2 - search_range

    ends = b"".join(struct.pack(">H", s["end"]) for s in segments)
    starts = b"".join(struct.pack(">H", s["start"]) for s in segments)
    # idDelta dibaca sebagai int16, tapi nilainya modulo 65536; kirim sebagai
    # unsigned 16-bit supaya (code + delta) & 0xFFFF tetap benar.
    deltas = b"".join(struct.pack(">H", s.get("delta", 0) & 0xFFFF) for s in segments)

    # Alamat array glyphIdArray, relatif terhadap awal tabel.
    glyph_array = b"".join(struct.pack(">H", g) for g in glyph_ids)
    # Layout: header(14) + endCode(2n) + reservedPad(2) + startCode(2n)
    #         + idDelta(2n) + idRangeOffset(2n) + glyphIdArray
    glyph_array_start = 16 + 8 * seg_count

    range_offsets = b""
    for i, seg in enumerate(segments):
        if "gid" not in seg:
            range_offsets += struct.pack(">H", 0)
            continue
        entry_pos = 16 + 6 * seg_count + 2 * i
        gid_pos = glyph_array_start + 2 * seg["_glyph_index"]
        range_offsets += struct.pack(">H", gid_pos - entry_pos)

    body = (
        struct.pack(">HHHHHHH", 4, 0, 0, seg2, search_range, entry_selector, range_shift)
        + ends
        + b"\x00\x00"
        + starts
        + deltas
        + range_offsets
        + glyph_array
    )
    length = len(body)
    return body[:2] + struct.pack(">H", length) + body[4:]


def _cmap_format12(groups: list[tuple[int, int, int]]) -> bytes:
    header = struct.pack(">HHIII", 12, 0, 16 + 12 * len(groups), 0, len(groups))
    body = b"".join(struct.pack(">III", start, end, gid) for start, end, gid in groups)
    return header + body


def _cmap(subtables: list[tuple[int, int, bytes]]) -> bytes:
    """`subtables` = [(platformID, encodingID, bytes)] -> tabel cmap lengkap."""
    header_len = 4 + 8 * len(subtables)
    records = b""
    data = b""
    for platform, encoding, sub in subtables:
        records += struct.pack(">HHI", platform, encoding, header_len + len(data))
        data += sub
    return struct.pack(">HH", 0, len(subtables)) + records + data


def _name(records: list[tuple[int, int, int, int, bytes]]) -> bytes:
    """`records` = [(platformID, encodingID, languageID, nameID, bytes)]."""
    storage = b""
    rec_bytes = b""
    for platform, encoding, language, name_id, raw in records:
        rec_bytes += struct.pack(
            ">HHHHHH", platform, encoding, language, name_id, len(raw), len(storage)
        )
        storage += raw
    return struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + rec_bytes + storage


def _name_utf16(text: str) -> bytes:
    return text.encode("utf-16-be")


def _name_mac(text: str) -> bytes:
    return text.encode("mac_roman")


def _build_ttf(tables: dict[str, bytes], sfnt_version: bytes = b"\x00\x01\x00\x00") -> bytes:
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
    return sfnt_version + header[4:] + directory + body


def _segments_with_glyph_array(
    segment_overrides: dict[int, dict] | None = None,
) -> tuple[list[dict], list[int]]:
    """Segmen standar; 'W' dan 'i' lewat idRangeOffset (bukan idDelta)."""
    segs: list[dict] = [
        {"start": 0x20, "end": 0x20, "delta": (3 - 0x20) & 0xFFFF},
        {"start": 0x41, "end": 0x41, "delta": (4 - 0x41) & 0xFFFF},
        {"start": 0x57, "end": 0x57, "gid": 1},
        {"start": 0x69, "end": 0x69, "gid": 2},
        {"start": 0xFFFF, "end": 0xFFFF, "delta": 1},
    ]
    for code, override in (segment_overrides or {}).items():
        for seg in segs:
            if seg["start"] == code == seg["end"]:
                seg.update(override)
    segs.sort(key=lambda s: s["start"])
    glyph_ids = [seg["gid"] for seg in segs if "gid" in seg]
    for index, seg in enumerate(segs):
        if "gid" in seg:
            seg["_glyph_index"] = glyph_ids.index(seg["gid"])
    return segs, glyph_ids


def make_font(
    path: Path,
    *,
    units_per_em: int = UNITS_PER_EM,
    advances: list[int] | None = None,
    number_of_h_metrics: int | None = None,
    cmap_format: int = 4,
    segment_overrides: dict[int, dict] | None = None,
    family_id16: str | None = "Test Sans Display",
    family_id1: str = "Test Sans",
    full_name: str = "Test Sans Display Regular",
    mac_only: bool = False,
    include_cmap: bool = True,
) -> Path:
    advances = list(DEFAULT_ADVANCES if advances is None else advances)
    num_glyphs = len(advances)
    n_hmetrics = num_glyphs if number_of_h_metrics is None else number_of_h_metrics

    if cmap_format == 4:
        segs, glyph_ids = _segments_with_glyph_array(segment_overrides)
        sub = _cmap_format4(segs, glyph_ids)
        cmap_table = _cmap([(3, 1, sub)])
    elif cmap_format == 12:
        groups = [(0x20, 0x20, 3), (0x41, 0x41, 4), (0x57, 0x57, 1), (0x69, 0x69, 2)]
        if num_glyphs > 5:
            groups.append((0x1F600, 0x1F600, 5))
        cmap_table = _cmap([(3, 10, _cmap_format12(groups))])
    else:  # pragma: no cover
        raise AssertionError(cmap_format)

    if mac_only:
        name_records = [
            (1, 0, 0, 1, _name_mac(family_id1)),
            (1, 0, 0, 4, _name_mac(full_name)),
        ]
    else:
        name_records = [
            (3, 1, 0x409, 1, _name_utf16(family_id1)),
            (3, 1, 0x409, 4, _name_utf16(full_name)),
        ]
        if family_id16 is not None:
            name_records.append((3, 1, 0x409, 16, _name_utf16(family_id16)))

    tables: dict[str, bytes] = {
        "head": _head(units_per_em),
        "hhea": _hhea(n_hmetrics),
        "maxp": _maxp(num_glyphs),
        "hmtx": _hmtx(advances, n_hmetrics),
        "name": _name(name_records),
    }
    if include_cmap:
        tables["cmap"] = cmap_table
    path.write_bytes(_build_ttf(tables))
    return path


class FontCase(unittest.TestCase):
    """Base: satu direktori sementara per kelas tes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.ttf = make_font(cls.tmp / "synthetic.ttf")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()


# ---------------------------------------------------------------------------
# Metrik dasar
# ---------------------------------------------------------------------------

class AdvanceTest(FontCase):
    def test_units_per_em(self) -> None:
        self.assertEqual(fontmetrics.Font.load(self.ttf).units_per_em, 1000)

    def test_advance_per_glyph(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.advance("W"), 1000)
        self.assertEqual(font.advance("i"), 300)
        self.assertEqual(font.advance(" "), 250)
        self.assertEqual(font.advance("A"), 700)

    def test_unmapped_char_uses_notdef_advance(self) -> None:
        """'Z' tidak ada di cmap -> glyph 0 -> advance .notdef = 500."""
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.advance("Z"), 500)
        self.assertFalse(font.has_glyph("Z"))

    def test_non_bmp_missing_in_format4(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertFalse(font.has_glyph("\U0001F600"))
        self.assertEqual(font.advance("\U0001F600"), 500)

    def test_has_glyph(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        for ch in "Wi A":
            self.assertTrue(font.has_glyph(ch), msg=repr(ch))

    def test_width_linear_in_text(self) -> None:
        """width('WW', 10) == 2*width('W', 10) == 20.0."""
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.width("WW", 10), 20.0)
        self.assertEqual(font.width("WW", 10), 2 * font.width("W", 10))

    def test_width_mixed_string(self) -> None:
        """(1000 + 300 + 250 + 700) / 1000 * 10 = 22.5."""
        font = fontmetrics.Font.load(self.ttf)
        self.assertAlmostEqual(font.width("Wi A", 10), 22.5, places=12)

    def test_width_empty_is_zero(self) -> None:
        self.assertEqual(fontmetrics.Font.load(self.ttf).width("", 32), 0.0)

    def test_width_scales_with_size(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertAlmostEqual(font.width("Wi", 20), 2 * font.width("Wi", 10), places=12)

    def test_width_divides_by_units_per_em_not_1000(self) -> None:
        """unitsPerEm=2048 harus dibagi 2048, bukan 1000 (mutan "bagi 1000").

        Font sintetis kedua dengan upem 2048 dan advance W=2048: width('W', 32)
        harus 32.0. Kalau pembaginya dipaku 1000 hasilnya 65,536.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = make_font(Path(tmp) / "upem2048.ttf", units_per_em=2048, advances=[1024, 2048, 512, 512, 1434])
            font = fontmetrics.Font.load(path)
            self.assertEqual(font.units_per_em, 2048)
            self.assertAlmostEqual(font.width("W", 32), 32.0, places=12)
            self.assertAlmostEqual(font.width("i", 32), 512 * 32 / 2048, places=12)

    def test_bad_arguments_rejected(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        with self.assertRaises(ValueError):
            font.width("W", -1)
        with self.assertRaises(ValueError):
            font.advance("WW")


class HmtxTest(unittest.TestCase):
    """numberOfHMetrics < numGlyphs: advance glyph di atasnya = advance terakhir."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ttf = make_font(
            Path(cls._tmp.name) / "short_hmtx.ttf",
            advances=[500, 1000, 300, 250, 700],
            number_of_h_metrics=3,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_metric_counters_read(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.number_of_h_metrics, 3)
        self.assertEqual(font.num_glyphs, 5)

    def test_measured_glyphs_keep_own_advance(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.advance("W"), 1000)
        self.assertEqual(font.advance("i"), 300)

    def test_glyphs_beyond_metrics_inherit_last_advance(self) -> None:
        """glyph 3 (' ') dan 4 ('A') tidak punya advance sendiri -> 300 (milik glyph 2).

        Kalau numberOfHMetrics diabaikan dan tiap glyph dibaca 4 byte, hasilnya
        akan 0 atau galat; kalau semua glyph dipaksa memakai advance terakhir
        dari daftar, 'W' jadi 300 dan tes ini gagal.
        """
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.advance(" "), 300)
        self.assertEqual(font.advance("A"), 300)
        self.assertAlmostEqual(font.width("Wi A", 10), (1000 + 300 + 300 + 300) / 1000 * 10, places=12)


class OutOfRangeGlyphTest(unittest.TestCase):
    """cmap menunjuk gid >= numGlyphs (font rusak/tidak konsisten).

    Pembaca harus jatuh ke advance .notdef, bukan IndexError. Font nyata
    kadang punya entri cmap yatim seperti ini.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ttf = make_font(
            Path(cls._tmp.name) / "oob.ttf",
            advances=[500, 1000, 300, 250, 700],
            segment_overrides={0x57: {"gid": 99, "delta": 0}},
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_out_of_range_gid_uses_notdef_advance(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.glyph_id("W"), 99)
        self.assertEqual(font.advance("W"), 500)


class CmapPreferenceTest(unittest.TestCase):
    """Font dengan DUA subtable: format 4 (BMP) dan format 12 (full).

    Subtable format 12 harus menang (cakupan penuh). Kalau pemilihan
    subtable salah, 'W' terbaca lewat tabel format 4 yang sengaja berbeda.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)

        # format 4: 'W' -> gid 1 (advance 1000); format 12: 'W' -> gid 3 (250).
        segs, glyph_ids = _segments_with_glyph_array()
        sub4 = _cmap_format4(segs, glyph_ids)
        groups = [(0x20, 0x20, 3), (0x41, 0x41, 4), (0x57, 0x57, 3), (0x69, 0x69, 2)]
        sub12 = _cmap_format12(groups)
        cmap_table = _cmap([(3, 1, sub4), (3, 10, sub12)])

        num_glyphs = 5
        tables = {
            "head": _head(),
            "hhea": _hhea(num_glyphs),
            "maxp": _maxp(num_glyphs),
            "hmtx": _hmtx(DEFAULT_ADVANCES, num_glyphs),
            "name": _name([(3, 1, 0x409, 1, _name_utf16("Dual Cmap"))]),
            "cmap": cmap_table,
        }
        cls.ttf = tmp / "dual_cmap.ttf"
        cls.ttf.write_bytes(_build_ttf(tables))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_format12_subtable_preferred(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.glyph_id("W"), 3, "subtable format 12 harus menang")
        self.assertEqual(font.advance("W"), 250)

    def test_bmp_glyphs_agree_across_subtables(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.advance("i"), 300)
        self.assertEqual(font.advance("A"), 700)


class CmapRangeOffsetDeltaTest(unittest.TestCase):
    """Segmen dengan idRangeOffset != 0 DAN idDelta != 0 sekaligus.

    Spec TrueType: bila idRangeOffset != 0, glyph = glyphIdArray[...] lalu
    ditambah idDelta (mod 65536). Mutan yang lupa menambahkan idDelta hanya
    tertangkap bila idDelta-nya tidak nol — karena itu tes ini ada.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        # 'W' (0x57) -> gid 1 lewat glyphIdArray, idDelta = +2 -> gid 3.
        # Advance gid 3 = 250, sedangkan gid 1 = 1000: beda 4x, tidak mungkin
        # tertukar karena pembulatan.
        cls.ttf = make_font(
            tmp / "delta_range.ttf",
            advances=[500, 1000, 300, 250, 700],
            segment_overrides={0x57: {"gid": 1, "delta": 2}},
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_delta_applied_after_glyph_array_lookup(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.glyph_id("W"), 3)
        self.assertEqual(font.advance("W"), 250)

    def test_unrelated_glyphs_unchanged(self) -> None:
        font = fontmetrics.Font.load(self.ttf)
        self.assertEqual(font.advance("i"), 300)
        self.assertEqual(font.advance("A"), 700)


class CmapFormat12Test(unittest.TestCase):
    """Format 12 (full Unicode) harus memberi hasil sama dengan format 4 BMP."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ttf4 = make_font(Path(cls._tmp.name) / "f4.ttf")
        cls.ttf12 = make_font(
            Path(cls._tmp.name) / "f12.ttf",
            advances=[500, 1000, 300, 250, 700, 600],
            cmap_format=12,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_same_advances_as_format4(self) -> None:
        f4 = fontmetrics.Font.load(self.ttf4)
        f12 = fontmetrics.Font.load(self.ttf12)
        for ch in "Wi A":
            self.assertEqual(f12.advance(ch), f4.advance(ch), msg=repr(ch))
            self.assertEqual(f12.has_glyph(ch), f4.has_glyph(ch), msg=repr(ch))

    def test_non_bmp_glyph_present(self) -> None:
        """Grup 32-bit: U+1F600 -> gid 5, advance 600."""
        f12 = fontmetrics.Font.load(self.ttf12)
        self.assertTrue(f12.has_glyph("\U0001F600"))
        self.assertEqual(f12.advance("\U0001F600"), 600)

    def test_unmapped_still_notdef(self) -> None:
        f12 = fontmetrics.Font.load(self.ttf12)
        self.assertEqual(f12.advance("Z"), 500)


class NameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.pref16 = make_font(tmp / "name16.ttf")
        cls.no16 = make_font(tmp / "name1.ttf", family_id16=None)
        cls.mac = make_font(tmp / "mac.ttf", mac_only=True, family_id1="Café Mac")
        # Non-ASCII di platform 3 (UTF-16BE). Kalau di-decode latin-1/ASCII,
        # "Ñandú" rusak; kalau UTF-16BE benar, hasilnya persis.
        # Karakter di luar Latin-1: byte tinggi UTF-16BE != 0x00, jadi
        # decode latin-1 + buang NUL TIDAK bisa menyamarkan kesalahan.
        cls.unicode_name = make_font(
            tmp / "unicode_name.ttf",
            family_id16="日本語 Grotesk",
            full_name="日本語 Grotesk Bold",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_family_prefers_name_id_16(self) -> None:
        font = fontmetrics.Font.load(self.pref16)
        self.assertEqual(font.family, "Test Sans Display")
        self.assertEqual(font.full_name, "Test Sans Display Regular")

    def test_family_falls_back_to_name_id_1(self) -> None:
        font = fontmetrics.Font.load(self.no16)
        self.assertEqual(font.family, "Test Sans")

    def test_platform3_utf16be_decoded(self) -> None:
        """Platform 3 = UTF-16BE; nama non-Latin-1 membongkar decode yang salah.

        '日本語' = U+65E5 U+672C U+8A9E -> byte 65 E5 67 2C 8A 9E. Decode
        latin-1 menghasilkan 'eåg, ...' yang tidak bisa diperbaiki dengan
        membuang NUL, jadi mutan decode latin-1 tertangkap.
        """
        font = fontmetrics.Font.load(self.unicode_name)
        self.assertEqual(font.family, "日本語 Grotesk")
        self.assertEqual(font.full_name, "日本語 Grotesk Bold")

    def test_macroman_platform1_decoded(self) -> None:
        """Platform 1 memakai MacRoman; 'é' = 0x8E, bukan UTF-8/UTF-16."""
        font = fontmetrics.Font.load(self.mac)
        self.assertEqual(font.family, "Café Mac")


class DeterminismTest(FontCase):
    def test_two_loads_identical(self) -> None:
        a = fontmetrics.Font.load(self.ttf)
        b = fontmetrics.Font.load(self.ttf)
        self.assertIs(a, b, "cache per path+mtime harus mengembalikan objek sama")
        self.assertEqual(a.width("Wi A", 32), b.width("Wi A", 32))
        self.assertEqual(a.advance("W"), b.advance("W"))

    def test_cache_invalidated_when_file_changes(self) -> None:
        """Cache berkunci path+mtime+ukuran: berkas yang ditulis ulang harus dibaca lagi.

        Kalau kunci cache hanya path, font lama akan dipakai selamanya —
        berbahaya karena Langkah 3 mengganti berkas font di assets/fonts.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = make_font(Path(tmp) / "swap.ttf", advances=[500, 1000, 300, 250, 700])
            first = fontmetrics.Font.load(path)
            self.assertEqual(first.advance("W"), 1000)

            make_font(path, advances=[500, 800, 300, 250, 700])
            # Pastikan mtime benar-benar berbeda (beberapa FS resolusi 1 s).
            stat = path.stat()
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

            second = fontmetrics.Font.load(path)
            self.assertEqual(second.advance("W"), 800, "cache tidak invalid saat berkas berubah")
            self.assertIsNot(first, second)

    def test_same_bytes_other_path_same_metrics(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            other = tmp / "copy.ttf"
            other.write_bytes(self.ttf.read_bytes())
            a = fontmetrics.Font.load(self.ttf)
            b = fontmetrics.Font.load(other)
            self.assertEqual(a.width("Wi A", 32), b.width("Wi A", 32))
        finally:
            for p in tmp.iterdir():
                p.unlink()
            tmp.rmdir()


# ---------------------------------------------------------------------------
# wrap()
# ---------------------------------------------------------------------------

class WrapTest(FontCase):
    def setUp(self) -> None:
        self.font = fontmetrics.Font.load(self.ttf)
        # size 10 -> 1 unit font = 0,01 px; W=10, i=3, spasi=2,5, A=7
        self.size = 10.0

    def test_single_line_when_fits(self) -> None:
        self.assertEqual(fontmetrics.wrap("Wi A", self.font, self.size, 30.0), ["Wi A"])

    def test_breaks_at_word_boundary(self) -> None:
        """'Wi A Wi' = 38 px; max 25 -> 'Wi A' (22,5) lalu 'Wi' (13)."""
        self.assertEqual(
            fontmetrics.wrap("Wi A Wi", self.font, self.size, 25.0), ["Wi A", "Wi"]
        )

    def test_never_breaks_inside_word(self) -> None:
        lines = fontmetrics.wrap("Wi A Wi A", self.font, self.size, 25.0)
        for line in lines:
            for word in line.split():
                self.assertIn(word, "Wi A Wi A".split())

    def test_overwide_word_stands_alone(self) -> None:
        """'WWW' = 30 px > 25: berdiri sendiri, tidak dipotong."""
        lines = fontmetrics.wrap("A WWW A", self.font, self.size, 25.0)
        self.assertEqual(lines, ["A", "WWW A"])
        self.assertIn("WWW", lines[1])

    def test_no_word_lost(self) -> None:
        sentence = "Wi A Wi A Wi A"
        for max_width in (10.0, 20.0, 25.0, 40.0, 1000.0):
            for max_lines in (1, 2, 3):
                lines = fontmetrics.wrap(
                    sentence, self.font, self.size, max_width, max_lines=max_lines
                )
                self.assertEqual(
                    " ".join(lines).split(),
                    sentence.split(),
                    msg=f"max_width={max_width} max_lines={max_lines}: {lines}",
                )

    def test_max_lines_respected(self) -> None:
        """5+ baris alami diringkas jadi max_lines, sisa kata di baris terakhir."""
        lines = fontmetrics.wrap("Wi A Wi A Wi A", self.font, self.size, 20.0, max_lines=2)
        self.assertEqual(len(lines), 2)
        self.assertGreater(len(lines[-1].split()), 1, "kata sisa harus di baris terakhir")

    def test_max_lines_one_keeps_everything(self) -> None:
        lines = fontmetrics.wrap("Wi A Wi", self.font, self.size, 5.0, max_lines=1)
        self.assertEqual(lines, ["Wi A Wi"])

    def test_empty_text(self) -> None:
        self.assertEqual(fontmetrics.wrap("   ", self.font, self.size, 100.0), [])

    def test_whitespace_normalized(self) -> None:
        self.assertEqual(
            fontmetrics.wrap("  Wi   A  ", self.font, self.size, 30.0), ["Wi A"]
        )

    def test_bad_arguments(self) -> None:
        with self.assertRaises(ValueError):
            fontmetrics.wrap("Wi", self.font, self.size, 0.0)
        with self.assertRaises(ValueError):
            fontmetrics.wrap("Wi", self.font, self.size, 100.0, max_lines=0)


# ---------------------------------------------------------------------------
# Penanganan kesalahan
# ---------------------------------------------------------------------------

class ErrorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_random_file(self) -> None:
        p = self.tmp / "random.bin"
        p.write_bytes(b"ini bukan font sama sekali" * 10)
        with self.assertRaises(ValueError):
            fontmetrics.Font.load(p)

    def test_empty_file(self) -> None:
        """Berkas 0 byte harus ditolak sebagai berkas kosong, bukan lolos jadi font.

        Pesan dicek supaya mutan yang mengganti isi berkas kosong dengan header
        palsu (lalu gagal di tempat lain) tidak lolos hanya karena sama-sama
        melempar ValueError.
        """
        p = self.tmp / "empty.ttf"
        p.write_bytes(b"")
        with self.assertRaises(ValueError) as ctx:
            fontmetrics.Font.load(p)
        self.assertIn("kosong", str(ctx.exception))

    def test_missing_cmap(self) -> None:
        p = make_font(self.tmp / "nocmap.ttf", include_cmap=False)
        with self.assertRaises(ValueError) as ctx:
            fontmetrics.Font.load(p)
        self.assertIn("cmap", str(ctx.exception))

    def test_ttc_collection_rejected(self) -> None:
        p = self.tmp / "coll.ttc"
        p.write_bytes(b"ttcf" + b"\x00" * 64)
        with self.assertRaises(ValueError) as ctx:
            fontmetrics.Font.load(p)
        self.assertIn("ttc", str(ctx.exception).lower())

    def test_truncated_file(self) -> None:
        """Berkas terpotong tidak boleh memunculkan struct.error mentah."""
        p = make_font(self.tmp / "full.ttf")
        data = p.read_bytes()
        p2 = self.tmp / "trunc.ttf"
        p2.write_bytes(data[: len(data) // 3])
        with self.assertRaises(ValueError):
            fontmetrics.Font.load(p2)

    def test_oversized_file_rejected(self) -> None:
        p = self.tmp / "big.ttf"
        with open(p, "wb") as fh:
            fh.truncate(fontmetrics.MAX_FILE_BYTES + 1)
        with self.assertRaises(ValueError) as ctx:
            fontmetrics.Font.load(p)
        self.assertIn("besar", str(ctx.exception))

    def test_missing_file(self) -> None:
        with self.assertRaises(ValueError):
            fontmetrics.Font.load(self.tmp / "tidak-ada.ttf")

    def test_bad_sfnt_version(self) -> None:
        p = self.tmp / "bad.ttf"
        p.write_bytes(b"\xde\xad\xbe\xef" + b"\x00" * 100)
        with self.assertRaises(ValueError) as ctx:
            fontmetrics.Font.load(p)
        self.assertIn("TrueType", str(ctx.exception))


# ---------------------------------------------------------------------------
# Font nyata (opsional)
# ---------------------------------------------------------------------------

REAL_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


def _first_real_font() -> str | None:
    for candidate in REAL_FONT_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


class RealFontTest(unittest.TestCase):
    @unittest.skipUnless(
        _first_real_font() is not None,
        "tidak ada font sistem dari daftar kandidat: " + ", ".join(REAL_FONT_CANDIDATES),
    )
    def test_real_font_metrics(self) -> None:
        path = _first_real_font()
        assert path is not None
        font = fontmetrics.Font.load(path)
        self.assertGreater(font.units_per_em, 0)
        self.assertTrue(font.family.strip(), f"family kosong untuk {path}")
        self.assertEqual(font.width("WW", 32), 2 * font.width("W", 32))
        self.assertTrue(font.has_glyph("W"))
        self.assertGreater(font.advance("W"), 0)
        self.assertAlmostEqual(
            font.width("WW", 100), font.width("W", 100) * 2, places=9
        )

    @unittest.skipUnless(
        _first_real_font() is not None, "tidak ada font sistem dari daftar kandidat"
    )
    def test_real_font_wrap_is_stable(self) -> None:
        path = _first_real_font()
        assert path is not None
        font = fontmetrics.Font.load(path)
        text = "Kata yang cukup panjang untuk dibungkus dua baris"
        a = fontmetrics.wrap(text, font, 48, 400)
        b = fontmetrics.wrap(text, font, 48, 400)
        self.assertEqual(a, b)
        self.assertEqual(" ".join(a).split(), text.split())


if __name__ == "__main__":
    unittest.main()
