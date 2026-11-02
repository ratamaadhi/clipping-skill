"""Tes aset font bundel: lisensi, statis, ukuran, glyph, dan kesesuaian template.

Kenapa ada: risiko R4 di `docs/MOTION-TIER2-PLAN.md` adalah **font fallback
senyap** ke DejaVu. Fallback itu tidak memunculkan error apa pun — caption tetap
tampil, hanya dengan huruf yang salah dan lebar yang salah, sehingga layout kata
menjadi bertumpuk. Tes ini menutup jalur itu dengan tiga cara:
  * berkasnya statis (tanpa tabel `fvar`) dan sha256-nya dipin,
  * `Fontname` di ASS berasal dari `fontmetrics`, bukan nama tebakan,
  * semua karakter yang wajib punya glyph nyata (bukan `.notdef`).
"""

from __future__ import annotations

import hashlib
import re
import struct
import unittest
from pathlib import Path

from tests.helpers import ROOT

from scripts import kinetic
from scripts.lib import fontmetrics

FONT_DIR = ROOT / "assets" / "fonts"
FONT_FILE = FONT_DIR / "ArchivoBlack-Regular.ttf"
OFL_FILE = FONT_DIR / "OFL.txt"
SOURCES_FILE = FONT_DIR / "SOURCES.md"

# Dipin di SOURCES.md. Kalau salah satu berubah, SOURCES.md harus diperbarui
# dan tes ini mengingatkan — bukan sebaliknya.
FONT_SHA256 = "dd9a89a019b4849f66ab75455fe7bdf931311042cbb0f0f97acc061539703180"
OFL_SHA256 = "3173acd82f8c6159b5b1037b539fcbd4edff68e65c2ea8b9412b5a5ca97b08ff"
MAX_BYTES = 1024 * 1024

# Tanda baca Indonesia + angka yang wajib ada glyph-nya.
REQUIRED_CHARS = (
    '"\'’…–-,.!?:;()&'
    + "0123456789"
    + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    + "abcdefghijklmnopqrstuvwxyz"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sfnt_table_tags(path: Path) -> list[str]:
    """Baca direktori tabel sfnt dengan `struct` — tanpa fontTools."""
    data = path.read_bytes()
    if data[:4] == b"ttcf":
        raise AssertionError(f"berkas .ttc tidak didukung tes ini: {path}")
    (num_tables,) = struct.unpack_from(">H", data, 4)
    tags: list[str] = []
    for i in range(num_tables):
        rec = 12 + 16 * i
        tags.append(data[rec : rec + 4].decode("latin-1"))
    return tags


def _style_field(ass: str, index: int) -> str:
    line = [ln for ln in ass.splitlines() if ln.startswith("Style: Kinetic,")][0]
    return line[len("Style: "):].split(",")[index]


class FontFileTest(unittest.TestCase):
    def test_font_file_exists(self) -> None:
        self.assertTrue(FONT_FILE.is_file(), msg=f"hilang: {FONT_FILE}")

    def test_sha256_matches_sources_md(self) -> None:
        digest = _sha256(FONT_FILE)
        self.assertEqual(digest, FONT_SHA256)
        self.assertIn(digest, SOURCES_FILE.read_text(encoding="utf-8"),
                      msg="sha256 font tidak tercatat di SOURCES.md")

    def test_size_under_one_megabyte(self) -> None:
        size = FONT_FILE.stat().st_size
        self.assertLessEqual(size, MAX_BYTES, msg=f"{size} byte > {MAX_BYTES}")
        sources = SOURCES_FILE.read_text(encoding="utf-8")
        # SOURCES.md menulis angka gaya Indonesia ("90.988"), tes menerima
        # kedua bentuk supaya dokumentasi tidak dipaksa berbahasa Inggris.
        self.assertTrue(
            str(size) in sources or f"{size:,}".replace(",", ".") in sources,
            msg=f"ukuran {size} byte tidak tercatat di SOURCES.md",
        )

    def test_is_static_font_without_fvar(self) -> None:
        """Variable font punya tabel `fvar`; libass memilih bobot lewat nama."""
        tags = _sfnt_table_tags(FONT_FILE)
        self.assertNotIn("fvar", tags, msg=f"variable font, tabel: {tags}")
        self.assertNotIn("gvar", tags, msg=f"variable font, tabel: {tags}")
        # Tabel wajib fontmetrics juga harus ada, kalau tidak Font.load gagal.
        for required in ("cmap", "head", "hhea", "hmtx", "maxp", "name", "glyf"):
            self.assertIn(required, tags)

    def test_family_and_full_name_are_readable(self) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        self.assertEqual(font.family, "Archivo Black")
        self.assertEqual(font.full_name, "Archivo Black Regular")
        sources = SOURCES_FILE.read_text(encoding="utf-8")
        self.assertIn(font.family, sources)
        self.assertIn(font.full_name, sources)

    def test_all_required_glyphs_present(self) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        missing = [ch for ch in REQUIRED_CHARS if not font.has_glyph(ch)]
        self.assertEqual(missing, [], msg=f"glyph hilang: {missing!r}")

    def test_space_glyph_present(self) -> None:
        self.assertTrue(fontmetrics.Font.load(FONT_FILE).has_glyph(" "))

    def test_font_is_not_modified_by_loading(self) -> None:
        before = _sha256(FONT_FILE)
        fontmetrics.Font.load(FONT_FILE).width("Pertama,", 84.0)
        self.assertEqual(_sha256(FONT_FILE), before)


class LicenseTest(unittest.TestCase):
    def test_ofl_text_present_and_sha_pinned(self) -> None:
        self.assertTrue(OFL_FILE.is_file())
        self.assertEqual(_sha256(OFL_FILE), OFL_SHA256)
        self.assertIn(OFL_SHA256, SOURCES_FILE.read_text(encoding="utf-8"))

    def test_ofl_contains_sil_open_font_license_1_1(self) -> None:
        text = OFL_FILE.read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE", text)
        self.assertIn("Version 1.1", text)

    def test_sources_md_records_urls_commit_date(self) -> None:
        text = SOURCES_FILE.read_text(encoding="utf-8")
        self.assertIn("94a7d81318e438525a5285e07ab72c050fdfeb44", text,
                      msg="commit google/fonts tidak dicatat")
        self.assertIn("raw.githubusercontent.com/google/fonts", text)
        self.assertIn("ofl/archivoblack", text)
        self.assertRegex(text, r"20\d\d-\d\d-\d\d", msg="tanggal unduh tidak dicatat")


def _script_info(ass: str) -> dict[str, str]:
    """Parse `[Script Info]` menjadi dict kunci->nilai (komentar `;` dibuang).

    Sengaja tidak memakai `assertIn("WrapStyle: 2", teks)`: komentar di template
    menyebut `WrapStyle: 2` juga, sehingga substring lolos walau direktifnya
    sudah diubah. Nilai harus dibaca dari baris direktif yang sebenarnya.
    """
    out: dict[str, str] = {}
    in_info = False
    for line in ass.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_info = stripped == "[Script Info]"
            continue
        if not in_info or not stripped or stripped.startswith(";"):
            continue
        key, _, value = stripped.partition(":")
        out[key.strip()] = value.strip()
    return out


class TemplateMatchesFontTest(unittest.TestCase):
    """Template tidak boleh memuat nama font hard-coded yang beda dari font bundel."""

    def test_template_exists(self) -> None:
        self.assertTrue((ROOT / "templates" / "caption_kinetic.ass.tmpl").is_file())

    def test_template_uses_placeholder_not_hardcoded_font(self) -> None:
        tpl = (ROOT / "templates" / "caption_kinetic.ass.tmpl").read_text(encoding="utf-8")
        style = [ln for ln in tpl.splitlines() if ln.startswith("Style: Kinetic,")][0]
        self.assertIn("{{FONT}}", style, msg="Fontname harus diisi build_ass")
        for wrong in ("DejaVu", "Montserrat", "Poppins", "Arial", "Helvetica"):
            self.assertNotIn(wrong, tpl, msg=f"nama font asing di template: {wrong}")

    def test_template_header_directives(self) -> None:
        tpl = (ROOT / "templates" / "caption_kinetic.ass.tmpl").read_text(encoding="utf-8")
        info = _script_info(tpl)
        self.assertEqual(info["PlayResX"], "1080")
        self.assertEqual(info["PlayResY"], "1920")
        self.assertEqual(info["ScaledBorderAndShadow"], "yes")
        self.assertEqual(info["WrapStyle"], "2")
        self.assertIn("[V4+ Styles]", tpl)
        self.assertIn("[Events]", tpl)

    def test_generated_ass_header_directives(self) -> None:
        """Nilai direktif di ASS hasil build, bukan hanya di template mentah."""
        ass = kinetic.build_ass({"captions": []}, font_path=FONT_FILE)
        info = _script_info(ass)
        self.assertEqual(info["WrapStyle"], "2")
        self.assertEqual(info["ScaledBorderAndShadow"], "yes")
        self.assertEqual(info["PlayResX"], "1080")
        self.assertEqual(info["PlayResY"], "1920")

    def test_generated_style_fontname_equals_font_family(self) -> None:
        family = fontmetrics.Font.load(FONT_FILE).family
        ass = kinetic.build_ass(
            {"captions": [{"start": 0.0, "end": 1.0, "text": "ya",
                           "words": [{"w": "ya", "start": 0.02, "end": 0.9}]}]},
            font_path=FONT_FILE,
        )
        self.assertEqual(_style_field(ass, 1), family)

    def test_generated_style_bold_is_zero_for_static_black(self) -> None:
        """Berkas sudah Black (usWeightClass 400, desain tebal): jangan bold sintetik."""
        ass = kinetic.build_ass(
            {"captions": [{"start": 0.0, "end": 1.0, "text": "ya",
                           "words": [{"w": "ya", "start": 0.02, "end": 0.9}]}]},
            font_path=FONT_FILE,
        )
        self.assertEqual(_style_field(ass, 7), "0")

    def test_generated_style_alignment_and_colours(self) -> None:
        from scripts import captions as cap_mod
        ass = kinetic.build_ass({"captions": []}, font_path=FONT_FILE)
        self.assertEqual(_style_field(ass, 3), cap_mod.PRIMARY)
        self.assertEqual(_style_field(ass, 18), "5")
        # Outline hitam tebal + bayangan lembut.
        outline = _style_field(ass, 16)
        shadow = _style_field(ass, 17)
        self.assertGreaterEqual(float(outline), 3.0, msg=f"Outline={outline}")
        self.assertGreater(float(shadow), 0.0, msg=f"Shadow={shadow}")


if __name__ == "__main__":
    unittest.main()
