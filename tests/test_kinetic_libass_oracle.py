"""Tes oracle libass: apakah `Style Fontsize` dari `kinetic.build_ass` benar?

Kenapa ada: seluruh tes `kinetic` lain mengukur dengan `fontmetrics` Python,
jadi mereka konsisten dengan dirinya sendiri walau semantik `Fontsize` salah.
Hanya render libass sungguhan yang membuktikan glyph yang digambar berukuran
sama dengan kotak yang dihitung `layout_phrase`.

Cacat yang ditutup (R3, docs/MOTION-TIER2-PLAN.md "Status Langkah 3b-i"):
libass `ass_face_set_size` menafsirkan `Fontsize` sebagai tinggi sel
`usWinAscent + usWinDescent`, bukan em. Archivo Black 1,347 em, sehingga
dengan `Fontsize = 84` (em) kata terukur hanya 0,707-0,724 x prediksi.
Perbaikannya `Fontsize = em x cell_height_ratio` (Langkah 3b-ii-a).

Skenario di bawah SENGAJA identik dengan pengukuran koordinator: frasa empat
kata, satu kata emphasis, fps 30, frame ke-72 (t = 2,40 s) — semua kata sudah
settle dan frasa belum keluar (window_end = 2,46 s). Angka acuan yang
dilaporkan koordinator pada kode SEBELUM perbaikan: 299/181/304/263 px
(rasio 0,720/0,707/0,724/0,722).

Tes ini SKIP bila tidak ada ffmpeg berlibass; lihat `tests/ffmpeg_libass.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts import kinetic
from scripts.lib import fontmetrics

FONT_DIR = ROOT / "assets" / "fonts"
FONT_FILE = FONT_DIR / "ArchivoBlack-Regular.ttf"

PLAY_W = 1080
PLAY_H = 1920
FPS = 30
FRAME = 72  # t = 2,40 s

SIZE = 84.0
GAP_EM = kinetic.GAP_EM  # 0,28

# Pita baris: baris 0 di center_y - line_height/2 (1351,7), baris 1 di 1448,3.
# Kapasitas glyph ~155 px, jadi 1250-1400 dan 1400-1560 memisahkan kedua baris
# tanpa memotong tinta (terukur: tinta hanya di y 1318-1495).
BAND_ROW0 = (1250, 1400)
BAND_ROW1 = (1400, 1560)

# Pemisah klaster. Terukur pada render BENAR: celah tinta dalam satu kata
# maksimum 8-10 px, celah antar-kata ~32 px (target 3b-iv = 32,48 px). 16 px
# memberi margin ~6 px di sisi dalam dan ~16 px di sisi luar. Ambang 40 px
# (spesifikasi awal) hanya cocok untuk render CACAT yang celahnya 105-132 px.
WORD_GAP_PX = 16

# Asersi lebar: tinta lebih sempit dari advance karena sisi glyph (lsb/rsb).
RATIO_MIN = 0.94
RATIO_MAX = 1.02
SPREAD_MAX = 0.04

# Pusat kata terhadap `\pos`.
CENTER_TOL_PX = 3.0

# Jarak antar-tinta Pertama, -> pasti.
INK_GAP_TOL_PX = 6.0

# Kontrol fallback: render dengan fontsdir kosong harus BERBEDA dari render
# font bundel, kalau tidak tes tidak bisa membedakan font yang dipakai (R4).
CONTROL_SPREAD_MIN = 0.04
CONTROL_MEAN_DELTA_MIN = 0.03

# Klip TETAP — sama persis dengan pengukuran koordinator.
CLIP = {
    "captions": [
        {
            "start": 1.02,
            "end": 2.34,
            "text": "Pertama, pasti nenekmu bangga.",
            "emphasis": "pasti",
            "words": [
                {"w": "Pertama,", "start": 1.02, "end": 1.34},
                {"w": "pasti", "start": 1.38, "end": 1.58},
                {"w": "nenekmu", "start": 1.62, "end": 1.94},
                {"w": "bangga.", "start": 2.02, "end": 2.34},
            ],
        }
    ]
}

WORDS = [w["w"] for w in CLIP["captions"][0]["words"]]
# Skala akhir per kata: "pasti" emphasis -> 112%, lainnya 100%.
SCALES = [1.0, kinetic.SCALE_EMPHASIS / 100.0, 1.0, 1.0]

# Baris hasil layout untuk frasa ini: kata 0,1 di baris 0; kata 2,3 di baris 1.
ROW_OF_WORD = [0, 0, 1, 1]

_FFMPEG = find_ffmpeg_with_libass()

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` (Homebrew Apple Silicon: "
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg; Intel: "
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg) atau set env CLIP_FFMPEG ke path "
    "ffmpeg berlibass. Formula `ffmpeg` Homebrew biasa dibangun tanpa libass."
)

# ---------------------------------------------------------------------------
# Render + ukur
# ---------------------------------------------------------------------------

def _render_frame(ass_text: str, fontsdir: str | None) -> bytes:
    """Render ASS ke frame ke-`FRAME` di atas hitam 1080x1920; balikkan rgb24.

    `fontsdir=None` berarti opsi `fontsdir` tidak dikirim sama sekali (libass
    memakai font sistem) — dipakai untuk kontrol fallback.
    """
    assert _FFMPEG is not None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ass_file = tmp_path / "clip.ass"
        ass_file.write_text(ass_text, encoding="utf-8")
        out_file = tmp_path / "frame.raw"

        sub = f"subtitles={ass_file.name}"
        if fontsdir is not None:
            sub += f":fontsdir={fontsdir}"
        # `trim` memilih frame ke-72 tanpa `select` (ekspresi `select` butuh
        # escaping koma yang berbeda antar-shell/versi ffmpeg).
        chain = (
            f"{sub},trim=start_frame={FRAME}:end_frame={FRAME + 1},"
            f"setpts=PTS-STARTPTS"
        )
        cmd = [
            _FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c=black:s={PLAY_W}x{PLAY_H}:d=3:r={FPS}",
            "-vf", chain,
            "-frames:v", "1",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            str(out_file),
        ]
        proc = subprocess.run(
            cmd, cwd=tmp_path, capture_output=True, timeout=120, check=False
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"ffmpeg gagal ({proc.returncode}): {proc.stderr.decode()[:800]}"
            )
        data = out_file.read_bytes()

    expected = PLAY_W * PLAY_H * 3
    if len(data) != expected:
        raise AssertionError(f"ukuran frame {len(data)} != {expected} byte")
    return data

def _ink_columns(frame: bytes, y0: int, y1: int) -> list[int]:
    """Kolom yang memuat piksel "isi" di pita baris [y0, y1).

    "Isi" = putih (R,G,B > 200) atau kuning aksen (R,G > 200, B < 90). Ambang
    ini memisahkan tinta dari latar hitam dan dari tepi anti-alias gelap,
    sehingga lebar yang diukur adalah inti glyph, bukan halo-nya.
    """
    cols: set[int] = set()
    stride = PLAY_W * 3
    for y in range(y0, y1):
        base = y * stride
        row = frame[base : base + stride]
        for x in range(PLAY_W):
            i = x * 3
            r = row[i]
            g = row[i + 1]
            b = row[i + 2]
            if r > 200 and g > 200 and (b > 200 or b < 90):
                cols.add(x)
    return sorted(cols)

def _runs(cols: list[int]) -> list[tuple[int, int]]:
    """Kelompokkan kolom berurutan menjadi rentang [awal, akhir] (inklusif)."""
    out: list[tuple[int, int]] = []
    if not cols:
        return out
    start = prev = cols[0]
    for x in cols[1:]:
        if x - prev > 1:
            out.append((start, prev))
            start = x
        prev = x
    out.append((start, prev))
    return out

def _gaps(cols: list[int]) -> list[int]:
    """Lebar celah (px) antar rentang kolom berurutan."""
    runs = _runs(cols)
    return [b - a - 1 for (_, a), (b, _) in zip(runs, runs[1:])]

def _cluster_words(cols: list[int], gap: int = WORD_GAP_PX) -> list[tuple[int, int]]:
    """Gabungkan rentang kolom yang berdekatan menjadi klaster KATA.

    Jarak antar-klaster > `gap`; jarak di dalam klaster <= `gap`.
    """
    runs = _runs(cols)
    if not runs:
        return []
    clusters = [list(runs[0])]
    for start, end in runs[1:]:
        if start - clusters[-1][1] - 1 > gap:
            clusters.append([start, end])
        else:
            clusters[-1][1] = end
    return [(a, b) for a, b in clusters]

def _layout() -> list[dict]:
    font = fontmetrics.Font.load(FONT_FILE)
    return kinetic.layout_phrase(
        [{"w": w} for w in WORDS], font, SIZE, scales=SCALES
    )

def _predictions() -> list[float]:
    font = fontmetrics.Font.load(FONT_FILE)
    return [font.width(w, SIZE) * s for w, s in zip(WORDS, SCALES)]

# ---------------------------------------------------------------------------
# Tes
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class LibassOracleTest(unittest.TestCase):
    """Render libass sungguhan; ukur tinta tiap kata dan bandingkan ke prediksi."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ass = kinetic.build_ass(CLIP, fps=FPS)
        cls.layout = _layout()
        cls.pred = _predictions()
        cls.frame = _render_frame(cls.ass, str(FONT_DIR))
        cls.style = [
            ln for ln in cls.ass.splitlines() if ln.startswith("Style: Kinetic,")
        ][0]

        # Klaster kata per baris. Jumlahnya HARUS sama dengan jumlah kata di
        # baris itu; kalau tidak, pengelompokan (atau lebar glyph) salah dan
        # semua angka di bawah tidak bisa dipercaya.
        cls.clusters_by_row: dict[int, list[tuple[int, int]]] = {}
        cls.cols_by_row: dict[int, list[int]] = {}
        for row, band in ((0, BAND_ROW0), (1, BAND_ROW1)):
            cols = _ink_columns(cls.frame, *band)
            cls.cols_by_row[row] = cols
            cls.clusters_by_row[row] = _cluster_words(cols)

    # -- struktur ---------------------------------------------------------

    def test_style_fontsize_is_em_times_cell_height_ratio(self) -> None:
        """Fontsize ASS = 84 x 1,347 = 113,148, bukan 84 (mutan (d))."""
        fields = self.style[len("Style: "):].split(",")
        ratio = fontmetrics.Font.load(FONT_FILE).cell_height_ratio
        self.assertAlmostEqual(float(fields[2]), SIZE * ratio, places=2, msg=self.style)
        self.assertAlmostEqual(ratio, 1.347, places=9)
        self.assertAlmostEqual(float(fields[2]), 113.148, places=2, msg=self.style)

    def test_one_cluster_per_word(self) -> None:
        """Jumlah klaster per baris = jumlah kata di baris itu."""
        for row in (0, 1):
            want = ROW_OF_WORD.count(row)
            got = len(self.clusters_by_row[row])
            self.assertEqual(
                got, want,
                msg=(
                    f"baris {row}: {got} klaster, harus {want}. Klaster: "
                    f"{self.clusters_by_row[row]}. Celah kolom: "
                    f"{_gaps(self.cols_by_row[row])}"
                ),
            )

    def test_word_gap_threshold_has_margin_on_both_sides(self) -> None:
        """Pengaman: celah dalam-kata < 16 px DAN celah antar-kata > 16 px.

        Kalau font atau ukuran berubah sehingga margin hilang, tes ini gagal
        dengan pesan jelas alih-alih salah mengelompokkan kata diam-diam.
        """
        for row in (0, 1):
            gaps = _gaps(self.cols_by_row[row])
            n_words = ROW_OF_WORD.count(row)
            self.assertTrue(gaps, msg=f"baris {row} hanya satu rentang kolom")
            # Celah terbesar ke-(n_words-1) adalah celah antar-kata; sisanya
            # celah di dalam kata.
            ordered = sorted(gaps, reverse=True)
            between = ordered[: n_words - 1]
            inside = ordered[n_words - 1 :]
            self.assertTrue(inside, msg=f"baris {row}: tidak ada celah dalam kata")
            self.assertLess(
                max(inside), WORD_GAP_PX,
                msg=f"baris {row}: celah dalam-kata {max(inside)} px >= {WORD_GAP_PX}",
            )
            self.assertGreater(
                min(between), WORD_GAP_PX,
                msg=f"baris {row}: celah antar-kata {min(between)} px <= {WORD_GAP_PX}",
            )

    # -- lebar ------------------------------------------------------------

    def test_ink_width_matches_prediction_for_every_word(self) -> None:
        """0,94 <= lebar tinta / (font.width x skala) <= 1,02 untuk tiap kata.

        Pada kode SEBELUM perbaikan (Fontsize = 84) rasio ini 0,707-0,724,
        jadi asersi ini adalah penangkap utama mutan (a), (b), (c), (d).
        """
        measured = self._measured_widths()
        for word, got, pred in zip(WORDS, measured, self.pred):
            ratio = got / pred
            self.assertGreaterEqual(
                ratio, RATIO_MIN,
                msg=f"{word!r}: tinta {got} px / prediksi {pred:.2f} px = {ratio:.4f}",
            )
            self.assertLessEqual(
                ratio, RATIO_MAX,
                msg=f"{word!r}: tinta {got} px / prediksi {pred:.2f} px = {ratio:.4f}",
            )

    def test_ratio_spread_across_words_is_tight(self) -> None:
        """Sebaran rasio antar-kata < 0,04: satu faktor skala berlaku seragam."""
        ratios = [g / p for g, p in zip(self._measured_widths(), self.pred)]
        spread = max(ratios) - min(ratios)
        self.assertLess(
            spread, SPREAD_MAX,
            msg=f"rasio {[round(r, 4) for r in ratios]}, sebaran {spread:.4f}",
        )

    def test_ink_narrower_than_advance(self) -> None:
        """Margin 1,0 masuk akal: tinta memang lebih sempit dari advance (sisi glyph)."""
        for word, got, pred in zip(WORDS, self._measured_widths(), self.pred):
            self.assertLess(got, pred, msg=f"{word!r}: tinta {got} >= advance {pred:.2f}")

    # -- posisi -----------------------------------------------------------

    def test_center_matches_pos_for_every_word(self) -> None:
        """Pusat tinta tiap kata dalam +-3 px dari `\\pos` hasil layout_phrase.

        Ini membuktikan `\\an5\\pos` dan rantai `\\t` tidak ikut bergeser saat
        skala diperbaiki — hanya ukurannya yang berubah.
        """
        for i, word in enumerate(WORDS):
            x0, x1 = self._cluster_for_word(i)
            center = (x0 + x1) / 2.0
            want = self.layout[i]["x"]
            self.assertAlmostEqual(
                center, want, delta=CENTER_TOL_PX,
                msg=f"{word!r}: pusat tinta {center:.2f} vs pos {want:.2f}",
            )

    def test_ink_gap_first_two_words_matches_target_plus_bearings(self) -> None:
        """Jarak tinta Pertama, -> pasti = target celah tinta, +-6 px.

        Turunan (3b-iv). `layout_phrase` menempatkan kotak BERSKALA tiap kata
        dengan celah kotak `max(0, T - rsb_a x s_a - lsb_b x s_b)`, dengan
        `T = 2 x OUTLINE_PX + CLEARANCE_EM x size` = 32,48 px pada em 84.
        Tinta kata kiri berhenti `rsb_a x s_a` di dalam tepi kanan kotaknya dan
        tinta kata kanan mulai `lsb_b x s_b` di dalam tepi kiri kotaknya, jadi

            jarak_tinta = celah_kotak + rsb_a x s_a + lsb_b x s_b = T

        selama celah kotak tidak dijepit 0 (di sini 21,70 px karena lsb kata
        emphasis ikut diskalakan). Angka nyata: 32,48 px; terukur pada render
        libass 34 px (kolom tinta, pembulatan 1 px).

        `celah_kotak` dibaca dari layout produk, bearing dari berkas font, dan
        target dari konstanta - tiga sumber terpisah. Asersi terakhir menolak
        regresi ke `GAP_EM` lama (23,52 px), yang sudah deprecated.
        """
        x0, x1 = self._cluster_for_word(0)
        y0, y1 = self._cluster_for_word(1)
        measured = y0 - x1 - 1

        font = fontmetrics.Font.load(FONT_FILE)
        box_gap = (
            (self.layout[1]["x"] - self.layout[1]["w"] / 2.0)
            - (self.layout[0]["x"] + self.layout[0]["w"] / 2.0)
        )
        rsb_a = kinetic.word_bearings(font, WORDS[0], SIZE)[1] * SCALES[0]
        lsb_b = kinetic.word_bearings(font, WORDS[1], SIZE)[0] * SCALES[1]
        predicted = box_gap + rsb_a + lsb_b
        target = kinetic.ink_gap_target(SIZE)

        self.assertAlmostEqual(
            box_gap, target - rsb_a - lsb_b, places=6,
            msg=f"celah kotak {box_gap:.4f} vs rumus {target - rsb_a - lsb_b:.4f}",
        )
        self.assertAlmostEqual(
            measured, predicted, delta=INK_GAP_TOL_PX,
            msg=f"jarak tinta {measured} px vs rumus {predicted:.2f} px",
        )
        self.assertAlmostEqual(
            measured, target, delta=INK_GAP_TOL_PX,
            msg=f"jarak tinta {measured} px vs target {target:.2f} px",
        )
        # Varian GAP_EM lama memang TIDAK cocok: asersi ini membedakan.
        self.assertGreater(abs(measured - kinetic.GAP_EM * SIZE), INK_GAP_TOL_PX)

    # -- helper -----------------------------------------------------------

    def _cluster_for_word(self, index: int) -> tuple[int, int]:
        row = ROW_OF_WORD[index]
        order_in_row = sum(1 for k in range(index) if ROW_OF_WORD[k] == row)
        clusters = self.clusters_by_row[row]
        self.assertGreater(
            len(clusters), order_in_row,
            msg=f"kata {WORDS[index]!r}: klaster baris {row} = {clusters}",
        )
        return clusters[order_in_row]

    def _measured_widths(self) -> list[int]:
        return [b - a + 1 for a, b in (self._cluster_for_word(i) for i in range(len(WORDS)))]

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class LibassFallbackControlTest(unittest.TestCase):
    """Kontrol: render tanpa font bundel harus TERBEDA (membuktikan tes bisa gagal).

    Kalau font sistem kebetulan identik dengan Archivo Black, kontrol ini tidak
    bisa membedakan apa pun; dalam kasus itu tes di-skip dengan pesan, bukan
    lulus palsu.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.ass = kinetic.build_ass(CLIP, fps=FPS)
        cls.pred = _predictions()
        cls.bundled = _render_frame(cls.ass, str(FONT_DIR))

        cls._tmp = tempfile.TemporaryDirectory()
        empty_dir = Path(cls._tmp.name) / "empty_fonts"
        empty_dir.mkdir()
        # fontsdir kosong: libass tidak menemukan Archivo Black dan jatuh ke
        # font sistem (DejaVu/Helvetica). Ini meniru risiko R4.
        cls.fallback = _render_frame(cls.ass, str(empty_dir))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _ratios(self, frame: bytes) -> list[float]:
        out: list[float] = []
        for i, band in enumerate((BAND_ROW0, BAND_ROW1)):
            clusters = _cluster_words(_ink_columns(frame, *band))
            want = ROW_OF_WORD.count(i)
            if len(clusters) != want:
                # Font fallback bisa mengubah lebar sampai pengelompokan
                # berbeda; lewati kata yang tidak bisa dipisah dengan yakin.
                return []
            for k, (a, b) in enumerate(clusters):
                idx = [j for j in range(len(WORDS)) if ROW_OF_WORD[j] == i][k]
                out.append((b - a + 1) / self.pred[idx])
        return out

    def test_fallback_render_differs_from_bundled_font(self) -> None:
        """Sebaran rasio fallback >= 0,04 ATAU rata-rata beda > 0,03 dari bundel."""
        bundled = self._ratios(self.bundled)
        fallback = self._ratios(self.fallback)
        self.assertEqual(len(bundled), len(WORDS), msg=f"rasio bundel: {bundled}")

        if not fallback:
            self.skipTest(
                "font sistem tidak menghasilkan empat klaster kata yang bisa "
                "dipisah pada render fontsdir-kosong, jadi kontrol tidak bisa "
                "membedakan font; bukan bukti tes lulus."
            )

        spread_fallback = max(fallback) - min(fallback)
        mean_bundled = sum(bundled) / len(bundled)
        mean_fallback = sum(fallback) / len(fallback)
        delta = abs(mean_bundled - mean_fallback)

        differs = spread_fallback >= CONTROL_SPREAD_MIN or delta > CONTROL_MEAN_DELTA_MIN
        if not differs:
            self.skipTest(
                "font sistem kebetulan menghasilkan metrik yang sama dengan font "
                f"bundel (sebaran fallback {spread_fallback:.4f}, beda rata-rata "
                f"{delta:.4f}); kontrol tidak bisa membedakan, bukan bukti lulus."
            )
        self.assertTrue(
            differs,
            msg=(
                f"render fallback TIDAK bisa dibedakan dari font bundel: "
                f"sebaran {spread_fallback:.4f} < {CONTROL_SPREAD_MIN} dan beda "
                f"rata-rata {delta:.4f} <= {CONTROL_MEAN_DELTA_MIN}. "
                f"bundel={[round(r, 4) for r in bundled]}, "
                f"fallback={[round(r, 4) for r in fallback]}"
            ),
        )

if __name__ == "__main__":
    unittest.main()
