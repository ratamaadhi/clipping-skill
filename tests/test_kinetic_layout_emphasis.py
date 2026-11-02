"""Tes murni tata letak sadar-emphasis (Langkah 3b-iii), tanpa ffmpeg.

Kenapa terpisah dari `tests/test_kinetic.py`: berkas itu mengunci perilaku
Langkah 3b-i (celah seragam `gap_em x size`, lebar kotak = advance 100%).
Langkah 3b-iii mengubah DUA hal yang saling terkait dan butuh tes yang
menyebut rumusnya secara eksplisit:

1. **Lebar kotak memperhitungkan skala akhir kata.** Kata beremphasis digambar
   pada 112%, jadi kotak yang benar-benar dipakai libass selebar
   `advance x 1,12`. Dulu `layout_phrase` memakai `advance` 100%, sehingga tepi
   tinta kata emphasis bergeser keluar `(s-1)/2 x advance` (~16 px untuk
   "enggak") dan memakan celah 23,5 px. Terukur di render nyata: celah tinta
   `apa|enggak` tinggal 7 px, `apa|capeknya` 0 px (kotak advance-nya
   bertumpuk), sedangkan celah antar-huruf di dalam kata 6-11 px.

2. **Celah kotak diturunkan dari celah TINTA yang diinginkan**, bukan dari
   `gap_em` yang buta terhadap Outline dan bearing glyph:

       celah_tinta_target = 2 x outline_px + clearance_em x size
       celah_kotak[i]     = max(0, target - rsb(kata i) x s_i - lsb(kata i+1) x s_{i+1})

   Turunan: tinta kata i berhenti `rsb_i x s_i` di dalam tepi kanan kotaknya,
   dan tinta kata i+1 mulai `lsb_{i+1} x s_{i+1}` di dalam tepi kiri kotaknya.
   Jadi `celah_tinta = celah_kotak + rsb_i x s_i + lsb_{i+1} x s_{i+1}`.
   Suku `(s-1)/2 x advance` TIDAK muncul terpisah karena kotak yang dipakai
   sudah kotak BERSKALA: `x +- advance x s / 2`. Itulah inti perbaikan (1).

Kenapa `2 x outline_px`: tiap kata adalah event ASS terpisah di Layer yang
sama, dan libass menggambar garis tepi 7 px di luar glyph. Garis tepi kata yang
digambar belakangan menimpa apa pun yang ada di dalam 7 px itu, jadi jarak
tinta yang terlihat harus menyisakan `2 x 7 px` untuk kedua garis tepi.
`clearance_em x size` (0,22 em = 18,48 px) adalah sisa latar yang membuat dua
kata terbaca terpisah; total 32,48 px pada em 84.

Clearance 0,10 em (target 22,4 px) yang dikunci di 3b-iii adalah KESALAHAN
KOORDINATOR: alasan "sama dengan celah `Pertama,|pasti` pada oracle lama"
keliru karena pasangan itu melibatkan kata beremphasis yang tintanya memakan
celah. Jarak alami Archivo Black terukur pada transkrip nyata (spasi 0,333 em =
27,97 px; celah tinta median 35,3 px, p10 30,9, p90 38,7), jadi 22,4 px hanya
~63% jarak alami dan terlihat sesak. 0,22 em = 32,48 px ~92% jarak alami.

Bearing dihitung ANALITIK dari berkas font (`hmtx` lsb + bbox `glyf`), bukan
dikalibrasi dari render: lihat `kinetic.word_bearings`. Kalibrasi dari render
akan mengunci tes ke satu ukuran font dan satu versi libass.
"""

from __future__ import annotations

import unittest

from tests.helpers import ROOT

from scripts import kinetic
from scripts.lib import fontmetrics

FONT_PATH = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"
SIZE = 84.0
MAX_WIDTH = 972.0
CENTER_X = 540.0
CENTER_Y = 1400.0
LINE_H = 1.15 * SIZE

# Nilai ANALITIK dari Archivo Black pada em 84 (hmtx lsb + bbox glyf, dibagi
# unitsPerEm 1000 lalu dikali 84). Dibulatkan 2 desimal; tes memakai places=2.
BEARING_LSB = {
    "apa": 2.52, "enggak": 3.02, "capeknya": 3.02, "lu": 5.63, "ke": 5.04,
    "di": 3.02, "Pertama,": 6.22, "pasti": 5.12, "hari": 5.04,
    "menyebalkannya": 5.04, "dia": 3.02, "dimusuhin": 3.02,
}
BEARING_RSB = {
    "apa": 0.42, "enggak": 0.17, "capeknya": 0.42, "lu": 5.12, "ke": 3.02,
    "di": 5.63, "Pertama,": 5.04, "pasti": 5.63, "hari": 5.63,
    "menyebalkannya": 0.42, "dia": 0.42, "dimusuhin": 4.96,
}

_FONT: fontmetrics.Font | None = None


def _font() -> fontmetrics.Font:
    global _FONT
    if _FONT is None:
        _FONT = fontmetrics.Font.load(FONT_PATH)
    return _FONT


def _words(*items: str) -> list[dict]:
    return [{"w": w, "start": 0.02 + i * 0.3, "end": 0.27 + i * 0.3}
            for i, w in enumerate(items)]


def _layout(*items, scales=None, **kwargs):
    return kinetic.layout_phrase(_words(*items), _font(), SIZE, scales=scales, **kwargs)


def _target(**kwargs) -> float:
    return kinetic.ink_gap_target(SIZE, **kwargs)


# ---------------------------------------------------------------------------
# Rumus celah
# ---------------------------------------------------------------------------

class GapFormulaTest(unittest.TestCase):
    def test_target_ink_gap_is_two_outlines_plus_clearance(self) -> None:
        """Target celah tinta = 2 x outline + clearance x size = 32,48 px."""
        self.assertEqual(kinetic.OUTLINE_PX, 7.0)
        # 0,22 em adalah koreksi 3b-iv; angka ini HANYA dikunci di sini.
        # Tes lain memakai `kinetic.CLEARANCE_EM`/`ink_gap_target`, bukan
        # literal 0,22, supaya hanya ada satu sumber.
        self.assertEqual(kinetic.CLEARANCE_EM, 0.22)
        expected = 2.0 * kinetic.OUTLINE_PX + kinetic.CLEARANCE_EM * SIZE
        self.assertAlmostEqual(expected, 32.48, places=6)
        self.assertAlmostEqual(_target(), expected, places=6)
        # Nilai lain harus mengikuti rumus yang sama, bukan konstanta tersembunyi.
        self.assertAlmostEqual(
            _target(outline_px=0.0, clearance_em=kinetic.CLEARANCE_EM),
            kinetic.CLEARANCE_EM * SIZE, places=6,
        )
        self.assertAlmostEqual(
            _target(outline_px=7.0, clearance_em=0.20), 30.8, places=6
        )

    def test_bearings_are_analytic_from_the_font_file(self) -> None:
        """lsb/rsb = nilai glyf/hmtx x size / unitsPerEm, bukan hasil kalibrasi."""
        for word, want in BEARING_LSB.items():
            lsb, _ = kinetic.word_bearings(_font(), word, SIZE)
            self.assertAlmostEqual(lsb, want, places=2, msg=f"lsb {word!r}")
        for word, want in BEARING_RSB.items():
            _, rsb = kinetic.word_bearings(_font(), word, SIZE)
            self.assertAlmostEqual(rsb, want, places=2, msg=f"rsb {word!r}")

    def test_bearings_scale_linearly_with_size(self) -> None:
        lsb84, rsb84 = kinetic.word_bearings(_font(), "lu", 84.0)
        lsb42, rsb42 = kinetic.word_bearings(_font(), "lu", 42.0)
        self.assertAlmostEqual(lsb42, lsb84 / 2.0, places=6)
        self.assertAlmostEqual(rsb42, rsb84 / 2.0, places=6)

    def test_box_gap_subtracts_both_bearings_and_scales_them(self) -> None:
        """celah_kotak = max(0, target - rsb_i x s_i - lsb_j x s_j)."""
        res = _layout("apa", "enggak", scales=[1.0, 1.12])
        rsb_a = kinetic.word_bearings(_font(), "apa", SIZE)[1] * 1.0
        lsb_b = kinetic.word_bearings(_font(), "enggak", SIZE)[0] * 1.12
        gap = (res[1]["x"] - res[1]["w"] / 2.0) - (res[0]["x"] + res[0]["w"] / 2.0)
        self.assertAlmostEqual(gap, _target() - rsb_a - lsb_b, places=6)
        # 32,48 - 0,42 - 3,024 x 1,12 = 28,67312.
        self.assertAlmostEqual(gap, 28.6731, places=3)

    def test_box_gap_is_clamped_at_zero(self) -> None:
        """Kata dengan bearing besar tidak boleh menghasilkan celah kotak negatif."""
        res = _layout("lu", "lu", scales=[1.0, 1.0], clearance_em=0.0,
                      outline_px=0.0)
        gap = (res[1]["x"] - res[1]["w"] / 2.0) - (res[0]["x"] + res[0]["w"] / 2.0)
        self.assertGreaterEqual(gap, 0.0)
        self.assertAlmostEqual(gap, 0.0, places=6)

    def test_gap_em_is_deprecated_and_does_not_change_layout(self) -> None:
        """`gap_em` dipertahankan demi kompatibilitas tetapi TIDAK dipakai.

        Dulu `gap_em` menentukan celah; sekarang celah datang dari
        `clearance_em` + outline + bearing. Dua nilai `gap_em` yang berbeda
        harus menghasilkan tata letak yang IDENTIK, dan docstring harus
        menyebutnya deprecated.
        """
        base = _layout("apa", "enggak", scales=[1.0, 1.12])
        wide = _layout("apa", "enggak", scales=[1.0, 1.12], gap_em=1.5)
        self.assertEqual([r["x"] for r in base], [r["x"] for r in wide])
        doc = kinetic.layout_phrase.__doc__ or ""
        self.assertIn("gap_em", doc)
        self.assertIn("deprecated", doc.lower())


# ---------------------------------------------------------------------------
# Lebar berskala
# ---------------------------------------------------------------------------

class ScaledWidthTest(unittest.TestCase):
    def test_emphasis_word_box_is_advance_times_scale(self) -> None:
        """Kotak kata emphasis = advance x 1,12; kata biasa tetap advance."""
        res = _layout("apa", "enggak", scales=[1.0, 1.12])
        adv_apa = _font().width("apa", SIZE)
        adv_enggak = _font().width("enggak", SIZE)
        self.assertAlmostEqual(res[0]["w"], adv_apa, places=6)
        self.assertAlmostEqual(res[1]["w"], adv_enggak * 1.12, places=6)
        self.assertAlmostEqual(res[1]["w"], 376.5082, places=3)
        self.assertEqual(res[1]["scale"], 1.12)
        self.assertEqual(res[0]["scale"], 1.0)

    def test_default_scales_are_one(self) -> None:
        plain = _layout("apa", "enggak")
        same = _layout("apa", "enggak", scales=[1.0, 1.0])
        self.assertEqual([r["w"] for r in plain], [r["w"] for r in same])
        self.assertEqual([r["x"] for r in plain], [r["x"] for r in same])

    def test_emphasis_word_and_neighbour_centres_shift_by_scaled_width(self) -> None:
        """Pusat kata emphasis DAN tetangganya bergeser sesuai lebar berskala.

        Frase dua kata: blok dipusatkan di center_x, jadi saat kata kanan
        membesar `delta_w = adv x 0,12`, pusat kata kiri bergeser
        `-delta_w/2` dan pusat kata kanan bergeser `+delta_w/2` DIKURANGI
        perubahan celah kotak (bearing kata kanan ikut diskalakan).
        """
        plain = _layout("apa", "enggak")
        emph = _layout("apa", "enggak", scales=[1.0, 1.12])
        adv_b = _font().width("enggak", SIZE)
        delta_w = adv_b * 0.12

        rsb_a = kinetic.word_bearings(_font(), "apa", SIZE)[1]
        lsb_b = kinetic.word_bearings(_font(), "enggak", SIZE)[0]
        gap_plain = _target() - rsb_a - lsb_b
        gap_emph = _target() - rsb_a - lsb_b * 1.12
        # Lebar blok bertambah delta_w dan celah kotak menyusut (lsb diskalakan).
        block_delta = delta_w + (gap_emph - gap_plain)
        self.assertAlmostEqual(emph[0]["x"] - plain[0]["x"], -block_delta / 2.0, places=6)
        # Pusat kata kanan: x1 = C - blok/2 + w0 + gap + w1/2, jadi
        # delta_x1 = -block_delta/2 + (gap_emph - gap_plain) + delta_w/2.
        self.assertAlmostEqual(
            emph[1]["x"] - plain[1]["x"],
            -block_delta / 2.0 + (gap_emph - gap_plain) + delta_w / 2.0,
            places=6,
        )
        # Angka nyata: dx0 = -19,99 px, dx1 = -0,18 px. Tanpa lebar berskala
        # (mutan (a)) dx0 = -0,18 dan dx1 = +0,18, jadi asersi ini membedakan.
        self.assertAlmostEqual(emph[0]["x"] - plain[0]["x"], -19.9886, places=3)
        self.assertAlmostEqual(emph[1]["x"] - plain[1]["x"], -0.1814, places=3)
        self.assertGreater(block_delta, 0.0)

    def test_no_emphasis_layout_uses_new_formula_with_exact_values(self) -> None:
        """Frasa tanpa emphasis: nilai eksak dari rumus baru (bukan gap_em).

        `gap_em x size` = 23,52 px akan memberi x kata pertama 360,156. Rumus
        baru (3b-iv) memberi celah kotak 29,036 px = 32,48 - 0,42 (rsb "apa")
        - 3,024 (lsb "enggak"), sehingga bloknya 533,288 px dan pusat kata
        bergeser ke 357,398 / 638,560.
        """
        res = _layout("apa", "enggak")
        gap = (res[1]["x"] - res[1]["w"] / 2.0) - (res[0]["x"] + res[0]["w"] / 2.0)
        self.assertAlmostEqual(gap, 29.036, places=3)
        block = res[0]["w"] + gap + res[1]["w"]
        self.assertAlmostEqual(res[0]["x"], CENTER_X - block / 2.0 + res[0]["w"] / 2.0,
                               places=6)
        self.assertAlmostEqual(res[0]["x"], 357.398, places=3)
        self.assertAlmostEqual(res[1]["x"], 638.560, places=3)


# ---------------------------------------------------------------------------
# Pemotongan baris memakai lebar berskala
# ---------------------------------------------------------------------------

class WrapUsesScaledWidthTest(unittest.TestCase):
    def test_phrase_fits_unscaled_but_wraps_when_word_is_emphasised(self) -> None:
        """Kasus batas: muat satu baris pada 100%, jadi dua baris pada 112%.

        "apa" + "capeknya": 168,084 + 29,036 + 443,52 = 640,64 px (muat pada
        max_width 660). Dengan "capeknya" beremphasis: 168,084 + 28,673 +
        496,742 = 693,50 px (tidak muat) -> dua baris.
        """
        plain = _layout("apa", "capeknya", max_width=660.0)
        emph = _layout("apa", "capeknya", scales=[1.0, 1.12], max_width=660.0)
        self.assertEqual([r["line"] for r in plain], [0, 0])
        self.assertEqual([r["line"] for r in emph], [0, 1])

    def test_scaled_line_never_exceeds_max_width(self) -> None:
        """Tidak ada baris yang lebar kotaknya melewati max_width setelah skala.

        Dua kata: setiap `max_width` yang masuk akal harus dihormati. Tiga kata
        diperiksa terpisah di bawah karena aturan "kata tidak pernah dibuang"
        boleh melebarkan baris TERAKHIR ketika dua baris tidak cukup.
        """
        for max_width in (972.0, 660.0, 500.0, 400.0):
            res = _layout("apa", "enggak", scales=[1.0, 1.12], max_width=max_width)
            for line in sorted({r["line"] for r in res}):
                ws = [r for r in res if r["line"] == line]
                width = (max(r["x"] + r["w"] / 2.0 for r in ws)
                         - min(r["x"] - r["w"] / 2.0 for r in ws))
                self.assertLessEqual(width, max_width + 1e-6,
                                     msg=f"max_width {max_width}: baris {line} "
                                         f"lebar {width:.2f}")

    def test_only_the_last_line_may_overflow_and_only_when_lines_run_out(self) -> None:
        """Baris yang melebar hanya boleh baris TERAKHIR, dan hanya bila 2 baris habis.

        Aturan lama "kata tidak pernah dibuang" berarti baris terakhir menampung
        sisa kata apa adanya. Tes ini memastikan pengecualian itu TIDAK dipakai
        untuk menyembunyikan pembungkusan yang salah: baris sebelum terakhir
        wajib muat, dan baris terakhir hanya boleh melebar bila jumlah kata
        memang tidak bisa dibagi ke dalam `max_lines` baris.
        """
        res = _layout("apa", "enggak", "dia", scales=[1.0, 1.12, 1.0], max_width=500.0)
        rows = sorted({r["line"] for r in res})
        self.assertEqual(rows, [0, 1])

        def width_of(line: int) -> float:
            ws = [r for r in res if r["line"] == line]
            return (max(r["x"] + r["w"] / 2.0 for r in ws)
                    - min(r["x"] - r["w"] / 2.0 for r in ws))

        # Baris 0 (satu kata) muat; baris 1 (dua kata) melebar karena 500 px
        # tidak cukup untuk dua baris berisi tiga kata ini.
        self.assertLessEqual(width_of(0), 500.0 + 1e-6)
        self.assertGreater(width_of(1), 500.0)
        # Bukti bahwa baris 1 memang tidak mungkin muat: dengan max_lines=3
        # (yaitu tanpa penggabungan baris terakhir) ketiga kata menempati TIGA
        # baris, jadi dua baris memang tidak cukup.
        three = _layout("apa", "enggak", "dia", scales=[1.0, 1.12, 1.0],
                        max_width=500.0, max_lines=3)
        self.assertEqual(sorted({r["line"] for r in three}), [0, 1, 2])
        for line in (0, 1, 2):
            ws = [r for r in three if r["line"] == line]
            width = (max(r["x"] + r["w"] / 2.0 for r in ws)
                     - min(r["x"] - r["w"] / 2.0 for r in ws))
            self.assertLessEqual(width, 500.0 + 1e-6, msg=f"baris {line}: {width:.2f}")

    def test_wrap_uses_scaled_width_not_unscaled(self) -> None:
        """Mutan "pemotongan memakai lebar tanpa skala" harus mengubah hasil.

        Dengan max_width 660, pemotongan yang memakai lebar 100% akan tetap
        satu baris walau kata emphasis 112% -> baris melewati batas.
        """
        emph = _layout("apa", "capeknya", scales=[1.0, 1.12], max_width=660.0)
        self.assertEqual(len({r["line"] for r in emph}), 2)
        gap_emph = (
            _target()
            - kinetic.word_bearings(_font(), "apa", SIZE)[1]
            - kinetic.word_bearings(_font(), "capeknya", SIZE)[0] * 1.12
        )
        unscaled_total = (_font().width("apa", SIZE) + gap_emph
                          + _font().width("capeknya", SIZE))
        scaled_total = (_font().width("apa", SIZE) + gap_emph
                        + _font().width("capeknya", SIZE) * 1.12)
        self.assertAlmostEqual(gap_emph, 28.6731, places=3)
        self.assertLessEqual(unscaled_total, 660.0)
        self.assertGreater(scaled_total, 660.0)


# ---------------------------------------------------------------------------
# Posisi dari frasa LENGKAP
# ---------------------------------------------------------------------------

class FullPhrasePositionTest(unittest.TestCase):
    def test_first_word_does_not_move_when_later_words_are_added(self) -> None:
        """Prinsip lama dipertahankan: posisi dihitung dari frasa lengkap sekali.

        Kata pertama boleh bergeser karena frasa lengkapnya berbeda, tetapi
        posisi yang dipakai `build_ass` untuk frasa lengkap TIDAK berubah saat
        kata berikutnya muncul di layar (tidak ada perhitungan per prefix).
        """
        full = _layout("apa", "enggak", "dimusuhin", "dia", scales=[1.0, 1.12, 1.0, 1.0])
        again = _layout("apa", "enggak", "dimusuhin", "dia", scales=[1.0, 1.12, 1.0, 1.0])
        self.assertEqual([r["x"] for r in full], [r["x"] for r in again])
        # Prefix menghasilkan tata letak BERBEDA (bukti bahwa frasa lengkap
        # yang dipakai, bukan prefix yang tumbuh).
        prefix = _layout("apa", scales=[1.0])
        self.assertNotAlmostEqual(prefix[0]["x"], full[0]["x"], delta=1.0)
        # Dan posisi kata pertama di baris 0 bergantung pada kata kedua yang
        # beremphasis di baris yang sama.
        without = _layout("apa", "enggak", "dimusuhin", "dia",
                          scales=[1.0, 1.0, 1.0, 1.0])
        self.assertNotAlmostEqual(full[0]["x"], without[0]["x"], delta=1.0)

    def test_words_in_one_line_keep_left_to_right_order(self) -> None:
        res = _layout("apa", "enggak", "dia", scales=[1.0, 1.12, 1.0])
        self.assertEqual([r["i"] for r in res], [0, 1, 2])
        xs = [r["x"] for r in res]
        self.assertEqual(xs, sorted(xs))

    def test_block_is_centered_on_center_x(self) -> None:
        res = _layout("apa", "enggak", scales=[1.0, 1.12])
        left = min(r["x"] - r["w"] / 2.0 for r in res)
        right = max(r["x"] + r["w"] / 2.0 for r in res)
        self.assertAlmostEqual((left + right) / 2.0, CENTER_X, places=6)

    def test_two_lines_are_centered_and_separated_by_line_height(self) -> None:
        res = _layout("apa", "enggak", "dimusuhin", "dia",
                      scales=[1.0, 1.12, 1.0, 1.0])
        rows = sorted({r["line"] for r in res})
        self.assertEqual(rows, [0, 1])
        y0 = {r["y"] for r in res if r["line"] == 0}.pop()
        y1 = {r["y"] for r in res if r["line"] == 1}.pop()
        self.assertAlmostEqual(y1 - y0, LINE_H, places=6)
        self.assertAlmostEqual((y0 + y1) / 2.0, CENTER_Y, places=6)


# ---------------------------------------------------------------------------
# Kanvas dan lebar maksimum
# ---------------------------------------------------------------------------

class CanvasTest(unittest.TestCase):
    def test_all_words_stay_inside_the_1080_canvas(self) -> None:
        cases = [
            (("apa", "enggak"), [1.0, 1.12]),
            (("apa", "capeknya"), [1.0, 1.12]),
            (("dimusuhin", "dia"), [1.0, 1.12]),
            (("capeknya", "lu"), [1.12, 1.0]),
            (("menyebalkannya", "datang", "ke", "kantor"), [1.12, 1.0, 1.0, 1.0]),
            (("apa", "enggak", "dimusuhin", "dia"), [1.0, 1.12, 1.0, 1.0]),
        ]
        for items, scales in cases:
            res = _layout(*items, scales=scales)
            left = min(r["x"] - r["w"] / 2.0 for r in res)
            right = max(r["x"] + r["w"] / 2.0 for r in res)
            self.assertGreaterEqual(left, 0.0, msg=f"{items}: kiri {left:.2f}")
            self.assertLessEqual(right, 1080.0, msg=f"{items}: kanan {right:.2f}")

    def test_lines_respect_max_width_after_scaling(self) -> None:
        for items, scales in [
            (("apa", "enggak"), [1.0, 1.12]),
            (("apa", "capeknya"), [1.0, 1.12]),
            (("dimusuhin", "dia"), [1.0, 1.12]),
            (("capeknya", "lu"), [1.12, 1.0]),
        ]:
            res = _layout(*items, scales=scales)
            for line in sorted({r["line"] for r in res}):
                ws = [r for r in res if r["line"] == line]
                width = (max(r["x"] + r["w"] / 2.0 for r in ws)
                         - min(r["x"] - r["w"] / 2.0 for r in ws))
                self.assertLessEqual(width, MAX_WIDTH + 1e-6,
                                     msg=f"{items}: baris {line} lebar {width:.2f}")


# ---------------------------------------------------------------------------
# Validasi argumen
# ---------------------------------------------------------------------------

class ScalesValidationTest(unittest.TestCase):
    def test_scales_length_must_match_words(self) -> None:
        with self.assertRaises(ValueError):
            _layout("apa", "enggak", scales=[1.0])

    def test_scales_must_be_positive_and_finite(self) -> None:
        for bad in (0.0, -1.0, float("inf"), float("nan")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                _layout("apa", "enggak", scales=[1.0, bad])

    def test_clearance_must_be_finite_and_non_negative(self) -> None:
        for bad in (-0.01, float("inf"), float("nan")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                _layout("apa", "enggak", clearance_em=bad)

    def test_outline_must_be_finite_and_non_negative(self) -> None:
        for bad in (-0.01, float("inf"), float("nan")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                _layout("apa", "enggak", outline_px=bad)


# ---------------------------------------------------------------------------
# Integrasi: build_ass memakai skala emphasis
# ---------------------------------------------------------------------------

class BuildAssUsesScaledLayoutTest(unittest.TestCase):
    def _clip(self, emphasis: str | None = None) -> dict:
        words = _words("apa", "enggak", "dimusuhin", "dia")
        cap = {"start": 0.0, "end": 3.0, "text": "apa enggak dimusuhin dia",
               "words": words}
        if emphasis:
            cap["emphasis"] = emphasis
        return {"caption_style": "kinetic", "captions": [cap]}

    def test_dialogue_positions_match_scaled_layout(self) -> None:
        """`\\pos` tiap kata = layout_phrase dengan skala emphasis yang sama."""
        import re

        ass = kinetic.build_ass(self._clip("enggak"), font_path=FONT_PATH)
        expected = _layout("apa", "enggak", "dimusuhin", "dia",
                           scales=[1.0, 1.12, 1.0, 1.0])
        lines = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
        self.assertEqual(len(lines), 4)
        for line, exp in zip(lines, expected):
            m = re.search(r"\\pos\(([-\d.]+),([-\d.]+)\)", line)
            self.assertIsNotNone(m, msg=line)
            assert m is not None
            self.assertAlmostEqual(float(m.group(1)), exp["x"], delta=0.01)
            self.assertAlmostEqual(float(m.group(2)), exp["y"], delta=0.01)

    def test_no_emphasis_matches_scaled_layout_with_unit_scales(self) -> None:
        import re

        ass = kinetic.build_ass(self._clip(), font_path=FONT_PATH)
        expected = _layout("apa", "enggak", "dimusuhin", "dia")
        lines = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
        for line, exp in zip(lines, expected):
            m = re.search(r"\\pos\(([-\d.]+),([-\d.]+)\)", line)
            assert m is not None
            self.assertAlmostEqual(float(m.group(1)), exp["x"], delta=0.01)

    def test_style_outline_comes_from_the_single_constant(self) -> None:
        """Kolom Outline pada `Style: Kinetic` = `kinetic.OUTLINE_PX` (7)."""
        ass = kinetic.build_ass(self._clip(), font_path=FONT_PATH)
        style = [ln for ln in ass.splitlines() if ln.startswith("Style: Kinetic,")][0]
        fields = style[len("Style: "):].split(",")
        # Urutan kolom `Format: ... BorderStyle, Outline, Shadow, Alignment ...`
        # -> Outline = 16, Shadow = 17, Alignment = 18.
        self.assertEqual(fields[16], f"{kinetic.OUTLINE_PX:g}")
        self.assertEqual(fields[17], f"{kinetic.SHADOW_PX:g}")

    def test_outline_kwarg_changes_style_and_layout(self) -> None:
        """`outline_px=0` menulis Outline 0 DAN memperkecil celah kotak."""
        normal = kinetic.build_ass(self._clip(), font_path=FONT_PATH)
        zero = kinetic.build_ass(self._clip(), font_path=FONT_PATH, outline_px=0.0)
        style_n = [ln for ln in normal.splitlines() if ln.startswith("Style: Kinetic,")][0]
        style_z = [ln for ln in zero.splitlines() if ln.startswith("Style: Kinetic,")][0]
        self.assertEqual(style_n[len("Style: "):].split(",")[16], "7")
        self.assertEqual(style_z[len("Style: "):].split(",")[16], "0")

        exp_n = _layout("apa", "enggak", "dimusuhin", "dia")
        exp_z = _layout("apa", "enggak", "dimusuhin", "dia", outline_px=0.0)
        self.assertNotAlmostEqual(exp_n[0]["x"], exp_z[0]["x"], delta=1.0)

    def test_clearance_kwarg_reaches_layout_phrase(self) -> None:
        wide = kinetic.build_ass(self._clip(), font_path=FONT_PATH, clearance_em=0.5)
        exp = _layout("apa", "enggak", "dimusuhin", "dia", clearance_em=0.5)
        import re

        line = [ln for ln in wide.splitlines() if ln.startswith("Dialogue:")][0]
        m = re.search(r"\\pos\(([-\d.]+),", line)
        assert m is not None
        self.assertAlmostEqual(float(m.group(1)), exp[0]["x"], delta=0.01)


if __name__ == "__main__":
    unittest.main()
