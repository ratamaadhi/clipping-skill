"""Aset font kedua: DM Serif Display Italic untuk preset `zoom_through_text`.

Sama seperti `tests/test_fonts_assets.py` untuk Archivo Black, berkas dipin
sha256 dan ukuran, diperiksa statis (tanpa `fvar`), lisensinya dibaca, dan
semua karakter wajib dibuktikan punya glyph nyata. Nama keluarga dibaca dari
tabel `name` lewat `fontmetrics`, bukan ditebak: nama itu yang ditulis ke
`Style Fontname` ASS.

Kenapa terpisah dari tes Archivo Black: berkas ini bukan font caption, dan
kegagalannya berarti preset zoom-through mati (dilewati dengan peringatan),
bukan caption salah huruf.
"""

from __future__ import annotations

import hashlib
import struct
import unittest
from pathlib import Path

from tests.helpers import ROOT

from scripts.lib import fontmetrics

FONT_DIR = ROOT / "assets" / "fonts"
FONT_FILE = FONT_DIR / "DMSerifDisplay-Italic.ttf"
OFL_FILE = FONT_DIR / "OFL-DMSerifDisplay.txt"

FONT_SHA256 = "df74c0ac387baeaeb0fe4f2324e1668e6a3ed8c09cd9796fe162c71753e19e45"
OFL_SHA256 = "a3e5cdd67d4571dd0a24fcc968de0efde7ae97ef752daf0906e4767619dd7231"
FONT_BYTES = 71208
OFL_BYTES = 4605

# Karakter yang dipakai teks preset: Latin dasar, angka, tanda baca, dan satu
# glyph beraksen (é) untuk membuktikan cmap Latin-1 tidak kosong.
REQUIRED_CHARS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    ".,!?-'\":;é"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sfnt_table_tags(path: Path) -> list[str]:
    data = path.read_bytes()
    if data[:4] == b"ttcf":
        raise AssertionError(f"berkas .ttc tidak didukung tes ini: {path}")
    (num_tables,) = struct.unpack_from(">H", data, 4)
    tags: list[str] = []
    for i in range(num_tables):
        rec = 12 + 16 * i
        tags.append(data[rec : rec + 4].decode("latin-1"))
    return tags


class DMSerifFontFileTest(unittest.TestCase):
    def test_font_file_exists_and_size_matches(self) -> None:
        self.assertTrue(FONT_FILE.is_file(), msg=f"hilang: {FONT_FILE}")
        self.assertEqual(FONT_FILE.stat().st_size, FONT_BYTES)

    def test_sha256_is_pinned(self) -> None:
        self.assertEqual(_sha256(FONT_FILE), FONT_SHA256)

    def test_is_static_font_without_fvar(self) -> None:
        tags = _sfnt_table_tags(FONT_FILE)
        self.assertNotIn("fvar", tags, msg=f"variable font, tabel: {tags}")
        self.assertNotIn("gvar", tags, msg=f"variable font, tabel: {tags}")
        for required in ("cmap", "head", "hhea", "hmtx", "maxp", "name"):
            self.assertIn(required, tags)

    def test_family_and_full_name_as_read_by_fontmetrics(self) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        self.assertEqual(font.family, "DM Serif Display")
        self.assertEqual(font.full_name, "DM Serif Display Italic")

    def test_all_required_glyphs_present(self) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        missing = [ch for ch in REQUIRED_CHARS if not font.has_glyph(ch)]
        self.assertEqual(missing, [], msg=f"glyph hilang: {missing!r}")

    def test_space_glyph_present(self) -> None:
        self.assertTrue(fontmetrics.Font.load(FONT_FILE).has_glyph(" "))

    def test_font_is_not_modified_by_loading(self) -> None:
        before = _sha256(FONT_FILE)
        fontmetrics.Font.load(FONT_FILE).width("5 JAM", 160.0)
        self.assertEqual(_sha256(FONT_FILE), before)


class DMSerifLicenseTest(unittest.TestCase):
    def test_license_file_exists_size_and_sha(self) -> None:
        self.assertTrue(OFL_FILE.is_file(), msg=f"hilang: {OFL_FILE}")
        self.assertEqual(OFL_FILE.stat().st_size, OFL_BYTES)
        self.assertEqual(_sha256(OFL_FILE), OFL_SHA256)

    def test_ofl_contains_sil_open_font_license_1_1(self) -> None:
        text = OFL_FILE.read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE", text)
        self.assertIn("Version 1.1", text)


if __name__ == "__main__":
    unittest.main()
