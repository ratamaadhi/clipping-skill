"""Tes `scripts.kinetic` — penulis ASS kinetic per kata (murni, tanpa ffmpeg).

Nilai eksak di bawah dihitung dari metrik font bundel (Archivo Black, sha256
dipin di `assets/fonts/SOURCES.md`), jadi tidak berubah tanpa perubahan berkas
font. Toleransi sengaja ketat: pelajaran Langkah 2/3a adalah batas yang longgar
meloloskan implementasi yang salah. Setiap angka di sini punya mutan yang
ditangkapnya (lihat laporan tugas).
"""

from __future__ import annotations

import math
import re
import unittest
from pathlib import Path

from tests.helpers import ROOT

from scripts import kinetic
from scripts.lib import fontmetrics
from scripts.lib import spring

FONT_PATH = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"

# Konstanta tampilan dari docs/MOTION-TIER2-PLAN.md (Langkah 3) — dikunci di tes.
SIZE = 84.0
GAP_EM = 0.28
MAX_WIDTH = 972.0
CENTER_X = 540.0
CENTER_Y = 1400.0
LINE_HEIGHT_EM = 1.15
GAP = GAP_EM * SIZE  # 23,52 px; `gap_em` DEPRECATED sejak 3b-iii
LINE_H = LINE_HEIGHT_EM * SIZE  # 96.6 px

# Skala kata: 60% -> 100% (biasa) atau -> 112% (emphasis).
SCALE_START = 60.0
SCALE_END = 100.0
SCALE_EMPHASIS = 112.0

_FONT: fontmetrics.Font | None = None


def _font() -> fontmetrics.Font:
    global _FONT
    if _FONT is None:
        _FONT = fontmetrics.Font.load(FONT_PATH)
    return _FONT


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _words(*pairs: tuple[str, float, float]) -> list[dict]:
    return [{"w": w, "start": s, "end": e} for (w, s, e) in pairs]


# 4 kata, dua baris: (Pertama, pasti) / (nenekmu bangga.)
W4 = _words(
    ("Pertama,", 1.02, 1.38),
    ("pasti", 1.38, 1.62),
    ("nenekmu", 1.62, 2.02),
    ("bangga.", 2.02, 2.34),
)

# 5 kata, dua baris: (Jangan pernah) / (bilang tidak bisa.)
W5 = _words(
    ("Jangan", 3.00, 3.34),
    ("pernah", 3.34, 3.70),
    ("bilang", 3.70, 4.02),
    ("tidak", 4.02, 4.32),
    ("bisa.", 4.32, 4.62),
)


def _clip(*caps: dict) -> dict:
    return {"caption_style": "kinetic", "captions": list(caps)}


def _phrases() -> list[dict]:
    """Dua frasa berurutan yang jendelanya tidak tumpang tindih."""
    return [
        {"start": 1.0, "end": 2.34, "text": "Pertama, pasti nenekmu bangga.",
         "emphasis": "pasti", "words": W4},
        {"start": 2.9, "end": 4.62, "text": "Jangan pernah bilang tidak bisa.",
         "words": W5},
    ]


def _dialogue_lines(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def _fields(line: str) -> list[str]:
    return line.split(",", 9)


def _ass_seconds(stamp: str) -> float:
    h, m, s = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _pos(line: str) -> tuple[float, float]:
    m = re.search(r"\\pos\(([-\d.]+),([-\d.]+)\)", line)
    if not m:
        raise AssertionError(f"tidak ada \\pos di baris: {line!r}")
    return float(m.group(1)), float(m.group(2))


def _scale_chain(line: str) -> list[tuple[int, int, float]]:
    """Ambil rantai `\\t(...)` yang mengubah `\\fscx` -> [(t0_ms, t1_ms, nilai)]."""
    out: list[tuple[int, int, float]] = []
    for m in re.finditer(r"\\t\((\d+),(\d+),([^)]*)\)", line):
        body = m.group(3)
        fm_ = re.search(r"\\fscx(\d+(?:\.\d+)?)", body)
        if not fm_:
            continue
        out.append((int(m.group(1)), int(m.group(2)), float(fm_.group(1))))
    return out


def _alpha_chain(line: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"\\t\((\d+),(\d+),([^)]*)\)", line):
        if "\\alpha" in m.group(3):
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def _event_text(line: str) -> str:
    """Teks setelah blok override penutup terakhir."""
    return _fields(line)[9].rsplit("}", 1)[-1]


def _override_block(line: str) -> str:
    text = _fields(line)[9]
    end = text.find("}")
    return text[: end + 1]


# ---------------------------------------------------------------------------
# display_window
# ---------------------------------------------------------------------------

class DisplayWindowTest(unittest.TestCase):
    def test_normal_phrase_uses_tail(self) -> None:
        """(i) end = max(cap.end, last.end + 0.12); start = first.start - lead."""
        caps = [
            {"start": 1.0, "end": 2.0,
             "words": _words(("a", 1.02, 1.40), ("b", 1.40, 1.95))},
            {"start": 9.0, "end": 10.0, "words": _words(("c", 9.02, 9.9))},
        ]
        self.assertEqual(kinetic.display_window(caps, 0), (0.98, 2.07))

    def test_clamped_by_next_phrase_start(self) -> None:
        """(ii) terpotong tepat di next_start - 0.04, bukan di tail 0.12."""
        caps = [
            {"start": 1.0, "end": 2.0,
             "words": _words(("a", 1.02, 1.40), ("b", 1.40, 1.95))},
            # next_start = 2.00 - 0.04 = 1.96; 1.96 - 0.04 = 1.92
            {"start": 2.1, "end": 2.9, "words": _words(("c", 2.00, 2.8))},
        ]
        start, end = kinetic.display_window(caps, 0)
        self.assertEqual(start, 0.98)
        self.assertEqual(end, 1.92)
        self.assertLess(end, 2.07)  # tail 0.12 akan memberi 2.07: batas menang

    def test_lead_clamped_to_zero(self) -> None:
        """(iii) mulai < 0 dijepit 0."""
        caps = [{"start": 0.0, "end": 1.0, "words": _words(("a", 0.02, 0.9))}]
        self.assertEqual(kinetic.display_window(caps, 0), (0.0, 1.02))

    def test_squeezed_window_gets_minimum_length(self) -> None:
        """(iv) end <= start -> end = start + 0.05."""
        caps = [
            {"start": 1.0, "end": 1.0, "words": _words(("a", 1.00, 1.00))},
            # next_start - 0.04 = 0.90 < start 0.96
            {"start": 1.2, "end": 1.5, "words": _words(("b", 0.98, 1.4))},
        ]
        start, end = kinetic.display_window(caps, 0)
        self.assertEqual(start, 0.96)
        self.assertEqual(end, 1.01)

    def test_last_phrase_has_no_next(self) -> None:
        """(v) frasa terakhir: end = max(cap.end, last.end + 0.12)."""
        caps = [{"start": 5.0, "end": 6.0, "words": _words(("a", 5.02, 5.9))}]
        self.assertEqual(kinetic.display_window(caps, 0), (4.98, 6.02))

    def test_no_two_consecutive_windows_overlap(self) -> None:
        caps = _phrases() + [
            {"start": 5.0, "end": 6.2, "text": "tiga", "words": _words(("x", 5.02, 6.1))},
        ]
        wins = [kinetic.display_window(caps, i) for i in range(len(caps))]
        for (_, end), (start, _) in zip(wins, wins[1:]):
            self.assertLessEqual(end, start, msg=f"jendela tumpang tindih: {wins}")
        for start, end in wins:
            self.assertGreater(end, start)

    def test_lead_is_configurable(self) -> None:
        caps = [{"start": 5.0, "end": 6.0, "words": _words(("a", 5.20, 5.9))}]
        self.assertEqual(kinetic.display_window(caps, 0, lead=0.0), (5.20, 6.02))
        self.assertEqual(kinetic.display_window(caps, 0, lead=0.10), (5.10, 6.02))

    def test_does_not_mutate_captions(self) -> None:
        caps = _phrases()
        before = [dict(c) for c in caps]
        kinetic.display_window(caps, 0)
        self.assertEqual(caps, before)


# ---------------------------------------------------------------------------
# layout_phrase
# ---------------------------------------------------------------------------

class LayoutPhraseTest(unittest.TestCase):
    def test_exact_positions_four_words(self) -> None:
        """Nilai eksak dari metrik Archivo Black pada size 84 (tanpa kerning).

        Rumus (Langkah 3b-iv):
        `target = 2 x OUTLINE_PX + CLEARANCE_EM x size = 32,48 px`, dan
        `celah_kotak = target - rsb(kiri) - lsb(kanan)` dengan bearing analitik
        `kinetic.word_bearings`. Untuk pasangan yang benar-benar bersebelahan
        di frasa ini hasilnya 22,316 (Pertama,|pasti) dan 22,232
        (nenekmu|bangga.); pasangan pasti|nenekmu terpisah baris. `expected_x`
        di bawah dihitung TANGAN dari rumus itu (lebar baris + pusat), bukan
        disalin dari keluaran `layout_phrase`; asersi pertama menegaskan
        keduanya cocok sebelum membandingkan hasil produk. Lebar kata
        (`expected_w`) tidak berubah karena `scales` bawaan = 1,0.

        Clearance 0,10 em dari 3b-iii (target 22,4 px) diganti 0,22 em pada
        3b-iv: alasan lama "sama dengan celah Pertama,|pasti di oracle" keliru
        karena pasangan itu melibatkan kata beremphasis yang tintanya memakan
        celah. Jarak alami Archivo Black pada transkrip nyata ~35,3 px.
        """
        target = kinetic.ink_gap_target(SIZE)
        bearings = [
            kinetic.word_bearings(_font(), w["w"], SIZE) for w in W4
        ]
        gap_01 = target - bearings[0][1] - bearings[1][0]
        gap_23 = target - bearings[2][1] - bearings[3][0]
        self.assertAlmostEqual(gap_01, 22.316, places=3)
        self.assertAlmostEqual(gap_23, 22.232, places=3)

        expected_w = [415.296, 228.648, 420.168, 364.140]
        row0_w = expected_w[0] + gap_01 + expected_w[1]
        row1_w = expected_w[2] + gap_23 + expected_w[3]
        x0 = CENTER_X - row0_w / 2 + expected_w[0] / 2
        x1 = x0 + expected_w[0] / 2 + gap_01 + expected_w[1] / 2
        x2 = CENTER_X - row1_w / 2 + expected_w[2] / 2
        x3 = x2 + expected_w[2] / 2 + gap_23 + expected_w[3] / 2
        expected_x = [414.518, 758.806, 346.814, 761.200]
        for got, want in zip(expected_x, [x0, x1, x2, x3]):
            self.assertAlmostEqual(got, want, places=3)

        res = kinetic.layout_phrase(W4, _font(), SIZE)
        self.assertEqual([r["i"] for r in res], [0, 1, 2, 3])
        self.assertEqual([r["line"] for r in res], [0, 0, 1, 1])
        expected_y = [CENTER_Y - LINE_H / 2, CENTER_Y - LINE_H / 2,
                      CENTER_Y + LINE_H / 2, CENTER_Y + LINE_H / 2]
        for r, w, x, y in zip(res, expected_w, expected_x, expected_y):
            self.assertAlmostEqual(r["w"], w, places=3, msg=f"lebar kata {r['i']}")
            self.assertAlmostEqual(r["x"], x, places=3, msg=f"x kata {r['i']}")
            self.assertAlmostEqual(r["y"], y, places=3, msg=f"y kata {r['i']}")

    def test_line_width_under_limit(self) -> None:
        for words in (W4, W5):
            res = kinetic.layout_phrase(words, _font(), SIZE)
            for line in sorted({r["line"] for r in res}):
                ws = [r for r in res if r["line"] == line]
                left = min(r["x"] - r["w"] / 2 for r in ws)
                right = max(r["x"] + r["w"] / 2 for r in ws)
                self.assertLessEqual(right - left, MAX_WIDTH + 1e-6,
                                     msg=f"baris {line} lebar {right - left}")

    def test_at_most_two_lines(self) -> None:
        long_words = _words(*[(f"kata{i}", 0.0, 0.1) for i in range(9)])
        res = kinetic.layout_phrase(long_words, _font(), SIZE)
        self.assertLessEqual(max(r["line"] for r in res), 1)
        self.assertEqual(len(res), 9, "tidak boleh ada kata yang dibuang")

    def test_word_order_preserved(self) -> None:
        res = kinetic.layout_phrase(W5, _font(), SIZE)
        self.assertEqual([r["i"] for r in res], list(range(len(W5))))
        # Dalam satu baris, x harus naik monoton.
        for line in (0, 1):
            xs = [r["x"] for r in res if r["line"] == line]
            self.assertEqual(xs, sorted(xs))

    def test_each_line_centered_on_center_x(self) -> None:
        res = kinetic.layout_phrase(W4, _font(), SIZE)
        for line in (0, 1):
            ws = [r for r in res if r["line"] == line]
            left = min(r["x"] - r["w"] / 2 for r in ws)
            right = max(r["x"] + r["w"] / 2 for r in ws)
            self.assertAlmostEqual((left + right) / 2, CENTER_X, delta=1.0)

    def test_block_centered_on_center_y(self) -> None:
        res = kinetic.layout_phrase(W4, _font(), SIZE)
        top = min(r["y"] for r in res)
        bottom = max(r["y"] for r in res)
        self.assertAlmostEqual((top + bottom) / 2, CENTER_Y, delta=1.0)
        # Satu baris: pusatnya tepat di center_y, bukan di atasnya.
        single = kinetic.layout_phrase(_words(("ya", 0.0, 0.1)), _font(), SIZE)
        self.assertAlmostEqual(single[0]["y"], CENTER_Y, delta=1e-9)

    def test_line_gap_is_line_height_em(self) -> None:
        res = kinetic.layout_phrase(W4, _font(), SIZE)
        y0 = {r["y"] for r in res if r["line"] == 0}.pop()
        y1 = {r["y"] for r in res if r["line"] == 1}.pop()
        self.assertAlmostEqual(y1 - y0, LINE_H, places=6)

    def test_gap_between_words_follows_ink_gap_formula(self) -> None:
        """Celah kotak = target celah tinta - rsb kata kiri - lsb kata kanan.

        Sebelum Langkah 3b-iii asersi ini mengunci `gap_em x size` = 23,52 px
        (nama lama: `test_gap_between_words_is_gap_em_times_size`). `gap_em`
        sekarang deprecated dan tidak lagi menentukan celah; nilai eksaknya
        diturunkan dari `ink_gap_target` + bearing nyata tiap pasangan.
        """
        res = kinetic.layout_phrase(W4, _font(), SIZE)
        target = kinetic.ink_gap_target(SIZE)
        checked = 0
        for a, b in zip(res, res[1:]):
            if a["line"] != b["line"]:
                continue
            rsb = kinetic.word_bearings(_font(), W4[a["i"]]["w"], SIZE)[1]
            lsb = kinetic.word_bearings(_font(), W4[b["i"]]["w"], SIZE)[0]
            want = max(0.0, target - rsb - lsb)
            self.assertAlmostEqual(
                (b["x"] - b["w"] / 2) - (a["x"] + a["w"] / 2), want, places=6
            )
            checked += 1
        self.assertEqual(checked, 2, "harus ada dua pasangan dalam satu baris")
        # Angka eksak pasangan pertama ("Pertama,|pasti") diturunkan dari
        # rumus: 32,48 (target 3b-iv) - 5,04 (rsb) - 5,124 (lsb) = 22,316.
        self.assertAlmostEqual(
            (res[1]["x"] - res[1]["w"] / 2) - (res[0]["x"] + res[0]["w"] / 2),
            22.316, places=3,
        )

    def test_custom_geometry(self) -> None:
        res = kinetic.layout_phrase(
            W4, _font(), SIZE, center_x=500.0, center_y=1000.0, line_height_em=2.0
        )
        top = min(r["y"] for r in res)
        bottom = max(r["y"] for r in res)
        self.assertAlmostEqual((top + bottom) / 2, 1000.0, delta=1e-9)
        self.assertAlmostEqual(bottom - top, 2.0 * SIZE, places=6)
        for line in (0, 1):
            ws = [r for r in res if r["line"] == line]
            left = min(r["x"] - r["w"] / 2 for r in ws)
            right = max(r["x"] + r["w"] / 2 for r in ws)
            self.assertAlmostEqual((left + right) / 2, 500.0, delta=1e-9)

    def test_narrow_max_width_wraps_earlier(self) -> None:
        wide = kinetic.layout_phrase(W4, _font(), SIZE, max_width=MAX_WIDTH)
        narrow = kinetic.layout_phrase(W4, _font(), SIZE, max_width=500.0)
        self.assertEqual(max(r["line"] for r in wide), 1)
        # Pada 500 px hanya "Pertama," yang muat sendirian; sisanya digabung ke
        # baris kedua (batas 2 baris, tidak ada kata yang dibuang).
        self.assertEqual(len(narrow), 4)
        self.assertEqual([r["line"] for r in narrow], [0, 1, 1, 1])
        # Baris kedua melebar melewati max_width: itu konsekuensi "kata tidak
        # pernah dibuang", bukan bug.
        line1 = [r for r in narrow if r["line"] == 1]
        self.assertGreater(
            max(r["x"] + r["w"] / 2 for r in line1)
            - min(r["x"] - r["w"] / 2 for r in line1),
            500.0,
        )


# ---------------------------------------------------------------------------
# Struktur ASS
# ---------------------------------------------------------------------------

class BuildAssStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ass = kinetic.build_ass(_clip(*_phrases()), font_path=FONT_PATH)
        self.lines = _dialogue_lines(self.ass)

    def test_one_dialogue_per_word(self) -> None:
        self.assertEqual(len(self.lines), len(W4) + len(W5))
        self.assertEqual(len(_dialogue_lines(kinetic.build_ass(_clip(), font_path=FONT_PATH))), 0)

    def test_every_dialogue_has_exactly_ten_fields(self) -> None:
        for line in self.lines:
            self.assertEqual(len(_fields(line)), 10, msg=line)

    def test_layer_is_one(self) -> None:
        for line in self.lines:
            self.assertEqual(_fields(line)[0], "Dialogue: 1", msg=line)

    def test_start_is_max_of_window_and_word_minus_lead(self) -> None:
        """Tiap Start = max(window_start, word.start - lead) +-10 ms."""
        caps = _phrases()
        idx = 0
        for i, cap in enumerate(caps):
            w_start, _ = kinetic.display_window(caps, i)
            for w in cap["words"]:
                got = _ass_seconds(_fields(self.lines[idx])[1])
                want = max(w_start, w["start"] - 0.04)
                self.assertAlmostEqual(got, want, delta=0.010,
                                       msg=f"kata {w['w']!r} event {idx}")
                idx += 1

    def test_end_is_phrase_window_end_for_every_word(self) -> None:
        caps = _phrases()
        idx = 0
        for i, cap in enumerate(caps):
            _, w_end = kinetic.display_window(caps, i)
            ends = []
            for _ in cap["words"]:
                ends.append(_ass_seconds(_fields(self.lines[idx])[2]))
                idx += 1
            for e in ends:
                self.assertAlmostEqual(e, w_end, delta=0.010)
            self.assertEqual(len(set(round(e, 2) for e in ends)), 1,
                             msg=f"End tidak seragam dalam frasa {i}: {ends}")

    def test_style_name_and_script_header(self) -> None:
        self.assertIn("PlayResX: 1080", self.ass)
        self.assertIn("PlayResY: 1920", self.ass)
        self.assertIn("ScaledBorderAndShadow: yes", self.ass)
        self.assertIn("WrapStyle: 2", self.ass)
        self.assertIn("Style: Kinetic,", self.ass)
        self.assertIn("Alignment", self.ass)
        self.assertTrue(self.ass.startswith("[Script Info]"))

    def test_style_alignment_is_five(self) -> None:
        style = [ln for ln in self.ass.splitlines() if ln.startswith("Style: Kinetic,")][0]
        fields = style[len("Style: "):].split(",")
        self.assertEqual(fields[18], "5", msg=style)  # Alignment

    def test_override_block_opens_with_an5_pos_and_scale(self) -> None:
        for line in self.lines:
            block = _override_block(line)
            self.assertTrue(block.startswith("{\\an5\\pos("), msg=block)
            self.assertIn("\\fscx60\\fscy60", block)
            self.assertIn("\\alpha&HFF&", block)

    def test_pos_matches_layout_phrase_for_every_word(self) -> None:
        """Posisi dari frasa LENGKAP: event kata ke-0 tidak bergeser."""
        caps = _phrases()
        idx = 0
        for cap in caps:
            # `build_ass` menghitung layout dengan skala akhir tiap kata (kata
            # beremphasis 1,12), jadi tes harus memakai skala yang sama supaya
            # membandingkan dua hal yang sama (Langkah 3b-iii).
            scales = [
                kinetic.SCALE_EMPHASIS / 100.0
                if w["w"] == cap.get("emphasis") else 1.0
                for w in cap["words"]
            ]
            expected = kinetic.layout_phrase(cap["words"], _font(), SIZE,
                                             center_y=CENTER_Y, scales=scales)
            for k, exp in enumerate(expected):
                x, y = _pos(self.lines[idx])
                self.assertAlmostEqual(x, exp["x"], delta=0.01, msg=f"x kata {k}")
                self.assertAlmostEqual(y, exp["y"], delta=0.01, msg=f"y kata {k}")
                idx += 1

    def test_first_word_y_is_two_line_position_not_single_line(self) -> None:
        """Mutan 'posisi dihitung per kata' memberi y=1400 untuk kata pertama."""
        x, y = _pos(self.lines[0])
        self.assertAlmostEqual(y, CENTER_Y - LINE_H / 2, delta=0.01)
        self.assertNotAlmostEqual(y, CENTER_Y, delta=1.0)

    def test_pos_is_identical_for_a_word_across_prefixes(self) -> None:
        """Prefix layout berbeda; posisi event tidak boleh memakai prefix."""
        prefix = kinetic.layout_phrase(W4[:1], _font(), SIZE)
        full = kinetic.layout_phrase(W4, _font(), SIZE)
        self.assertNotAlmostEqual(prefix[0]["y"], full[0]["y"], delta=1.0)
        self.assertAlmostEqual(_pos(self.lines[0])[1], full[0]["y"], delta=0.01)

    def test_center_y_is_configurable(self) -> None:
        ass = kinetic.build_ass(_clip(_phrases()[0]), font_path=FONT_PATH, center_y=900.0)
        line = _dialogue_lines(ass)[0]
        self.assertAlmostEqual(_pos(line)[1], 900.0 - LINE_H / 2, delta=0.01)

    def test_play_res_override(self) -> None:
        ass = kinetic.build_ass(_clip(), font_path=FONT_PATH, play_res=(720, 1280))
        self.assertIn("PlayResX: 720", ass)
        self.assertIn("PlayResY: 1280", ass)


# ---------------------------------------------------------------------------
# Rantai spring
# ---------------------------------------------------------------------------

class SpringChainTest(unittest.TestCase):
    FPS = 30.0

    def setUp(self) -> None:
        self.line = _dialogue_lines(
            kinetic.build_ass(_clip(_phrases()[0]), font_path=FONT_PATH, fps=self.FPS)
        )[0]
        self.chain = _scale_chain(self.line)

    def test_segment_count_at_most_ten(self) -> None:
        self.assertGreaterEqual(len(self.chain), 1)
        self.assertLessEqual(len(self.chain), 10, msg=str(self.chain))

    def test_times_are_integer_milliseconds_and_monotonic(self) -> None:
        for t0, t1, _ in self.chain:
            self.assertIsInstance(t0, int)
            self.assertIsInstance(t1, int)
            self.assertLess(t0, t1)
        for (_, t1, _), (t0, _, _) in zip(self.chain, self.chain[1:]):
            self.assertEqual(t1, t0, "rantai \\t harus bersambung")
        self.assertEqual(self.chain[0][0], 0)

    def test_times_are_milliseconds_not_seconds(self) -> None:
        """Mutan satuan detik menghasilkan t1 = 0 atau 1, bukan puluhan-ratusan."""
        last = self.chain[-1][1]
        self.assertGreater(last, 100, msg=f"rantai berakhir di {last} ms")
        self.assertLess(last, 1000)

    def test_scale_starts_at_sixty_and_ends_at_one_hundred(self) -> None:
        self.assertAlmostEqual(self.chain[0][2], 63.0, delta=2.0)
        self.assertAlmostEqual(self.chain[-1][2], SCALE_END, delta=0.01)

    def test_chain_tracks_analytic_spring_within_two_percent(self) -> None:
        """Interpolasi linear rantai pada pertengahan frame = spring analitik +-2%."""
        nodes = [(t / 1000.0, v) for t0, t1, v in self.chain for t in (t0, t1)]
        # Titik awal eksplisit (t=0, 60) lalu tiap titik akhir segmen.
        nodes = [(self.chain[0][0] / 1000.0, SCALE_START)] + [
            (t1 / 1000.0, v) for _, t1, v in self.chain
        ]
        end = nodes[-1][0]
        frame = 0
        while (frame + 0.5) / self.FPS <= end:
            tm = (frame + 0.5) / self.FPS
            got = None
            for (ta, va), (tb, vb) in zip(nodes, nodes[1:]):
                if ta <= tm <= tb:
                    f = 0.0 if tb == ta else (tm - ta) / (tb - ta)
                    got = va + (vb - va) * f
                    break
            self.assertIsNotNone(got, msg=f"t={tm} di luar rantai")
            want = SCALE_START + (SCALE_END - SCALE_START) * spring.spring(tm)
            self.assertLessEqual(
                abs(got - want) / want, 0.02,
                msg=f"t={tm:.4f}: rantai {got:.3f} vs analitik {want:.3f}",
            )
            frame += 1

    def test_alpha_fades_in_over_two_frames(self) -> None:
        alpha = _alpha_chain(self.line)
        self.assertEqual(len(alpha), 1, msg=f"alpha chain: {alpha}")
        t0, t1 = alpha[0]
        self.assertEqual(t0, 0)
        self.assertEqual(t1, int(2 * 1000.0 / self.FPS))  # 66 ms pada 30 fps
        # Frame ke-2 (t = 2/fps) harus sudah penuh.
        self.assertGreaterEqual(2 * 1000.0 / self.FPS, t1)

    def test_fps_changes_chain_length_but_not_target(self) -> None:
        for fps in (24.0, 25.0, 60.0):
            line = _dialogue_lines(
                kinetic.build_ass(_clip(_phrases()[0]), font_path=FONT_PATH, fps=fps)
            )[0]
            chain = _scale_chain(line)
            self.assertLessEqual(len(chain), 10)
            self.assertAlmostEqual(chain[-1][2], SCALE_END, delta=0.01)
            self.assertEqual(_alpha_chain(line)[0][1], int(2 * 1000.0 / fps))

    def test_chain_deterministic(self) -> None:
        again = _dialogue_lines(
            kinetic.build_ass(_clip(_phrases()[0]), font_path=FONT_PATH, fps=self.FPS)
        )[0]
        self.assertEqual(self.line, again)


# ---------------------------------------------------------------------------
# Emphasis
# ---------------------------------------------------------------------------

class EmphasisTest(unittest.TestCase):
    def test_exactly_one_accented_word_and_scale_112(self) -> None:
        cap = {"start": 1.0, "end": 2.34, "text": "Pertama, pasti nenekmu bangga.",
               "emphasis": "pasti", "words": W4}
        ass = kinetic.build_ass(_clip(cap), font_path=FONT_PATH)
        lines = _dialogue_lines(ass)
        self.assertEqual(len(lines), 4)
        accented = [ln for ln in lines if "\\c" in _override_block(ln)]
        self.assertEqual(len(accented), 1, msg=str(accented))
        self.assertEqual(_event_text(accented[0]), "pasti")
        self.assertAlmostEqual(_scale_chain(accented[0])[-1][2], SCALE_EMPHASIS, delta=0.01)
        for ln in lines:
            if ln is not accented[0]:
                self.assertAlmostEqual(_scale_chain(ln)[-1][2], SCALE_END, delta=0.01)

    def test_accent_colour_matches_tier1_constant(self) -> None:
        from scripts import captions as cap_mod
        cap = {"start": 1.0, "end": 2.34, "text": "x pasti y",
               "emphasis": "pasti", "words": W4}
        ass = kinetic.build_ass(_clip(cap), font_path=FONT_PATH)
        accented = [ln for ln in _dialogue_lines(ass) if "\\c" in _override_block(ln)][0]
        self.assertIn(f"\\c{cap_mod.ACCENT}", _override_block(accented))

    def test_no_emphasis_means_no_accent(self) -> None:
        cap = {"start": 1.0, "end": 2.34, "text": "Pertama, pasti nenekmu bangga.",
               "words": W4}
        ass = kinetic.build_ass(_clip(cap), font_path=FONT_PATH)
        for ln in _dialogue_lines(ass):
            self.assertNotIn("\\c", _override_block(ln))
            self.assertAlmostEqual(_scale_chain(ln)[-1][2], SCALE_END, delta=0.01)

    def test_emphasis_matching_normalises_like_captions(self) -> None:
        """`emphasis` di EDL sudah di-`clean`; kata di `words` masih bertanda baca."""
        cap = {"start": 1.0, "end": 2.34, "text": "Pertama, PASTI! nenekmu bangga.",
               "emphasis": "pasti",
               "words": _words(("Pertama,", 1.02, 1.38), ("PASTI!", 1.38, 1.62),
                               ("nenekmu", 1.62, 2.02), ("bangga.", 2.02, 2.34))}
        ass = kinetic.build_ass(_clip(cap), font_path=FONT_PATH)
        accented = [ln for ln in _dialogue_lines(ass) if "\\c" in _override_block(ln)]
        self.assertEqual(len(accented), 1)
        self.assertEqual(_event_text(accented[0]), "PASTI!")

    def test_repeated_emphasis_word_accented_at_most_once(self) -> None:
        cap = {"start": 1.0, "end": 2.0, "text": "tidak tidak tidak",
               "emphasis": "tidak",
               "words": _words(("tidak", 1.02, 1.3), ("tidak", 1.3, 1.6),
                               ("tidak", 1.6, 1.9))}
        ass = kinetic.build_ass(_clip(cap), font_path=FONT_PATH)
        accented = [ln for ln in _dialogue_lines(ass) if "\\c" in _override_block(ln)]
        self.assertEqual(len(accented), 1)
        self.assertEqual(_event_text(accented[0]), "tidak")


# ---------------------------------------------------------------------------
# Escape
# ---------------------------------------------------------------------------

class EscapeTest(unittest.TestCase):
    def test_braces_and_backslash_cannot_inject_override(self) -> None:
        cap = {"start": 1.0, "end": 2.0, "text": "a{b}\\c",
               "words": _words(("a{b}\\c", 1.02, 1.9))}
        ass = kinetic.build_ass(_clip(cap), font_path=FONT_PATH)
        line = _dialogue_lines(ass)[0]
        text = _fields(line)[9]
        tail = text.rsplit("}", 1)[-1]
        self.assertEqual(tail, "a(b)/c")
        for ch in "{}":
            self.assertNotIn(ch, tail, msg=f"{ch!r} bocor ke teks: {tail!r}")
        self.assertNotIn("\\", tail)
        self.assertEqual(len(_fields(line)), 10)

    def test_override_block_count_is_exactly_one(self) -> None:
        cap = {"start": 1.0, "end": 2.0, "text": "x",
               "words": _words(("{evil}", 1.02, 1.9))}
        line = _dialogue_lines(kinetic.build_ass(_clip(cap), font_path=FONT_PATH))[0]
        self.assertEqual(_fields(line)[9].count("{"), 1)
        self.assertEqual(_fields(line)[9].count("}"), 1)

    def test_comma_in_word_is_safe(self) -> None:
        cap = {"start": 1.0, "end": 2.0, "text": "3,5",
               "words": _words(("3,5", 1.02, 1.9))}
        line = _dialogue_lines(kinetic.build_ass(_clip(cap), font_path=FONT_PATH))[0]
        self.assertEqual(len(_fields(line)), 10)
        self.assertEqual(_event_text(line), "3,5")

    def test_ampersand_and_quotes_are_preserved(self) -> None:
        cap = {"start": 1.0, "end": 2.0, "text": "a & b 'c' \"d\"",
               "words": _words(("a & b 'c' \"d\"", 1.02, 1.9))}
        line = _dialogue_lines(kinetic.build_ass(_clip(cap), font_path=FONT_PATH))[0]
        self.assertEqual(_event_text(line), "a & b 'c' \"d\"")


# ---------------------------------------------------------------------------
# Input degenerate
# ---------------------------------------------------------------------------

class DegenerateInputTest(unittest.TestCase):
    def test_phrase_without_words_is_skipped(self) -> None:
        caps = [
            {"start": 0.0, "end": 1.0, "text": "tanpa kata"},
            {"start": 1.5, "end": 2.5, "text": "dengan kata", "words": _words(("ok", 1.52, 2.4))},
        ]
        ass = kinetic.build_ass(_clip(*caps), font_path=FONT_PATH)
        self.assertEqual(len(_dialogue_lines(ass)), 1)

    def test_empty_captions_gives_valid_ass_without_dialogue(self) -> None:
        for clip in (_clip(), {"caption_style": "kinetic"}, {"captions": []}):
            ass = kinetic.build_ass(clip, font_path=FONT_PATH)
            self.assertEqual(_dialogue_lines(ass), [])
            self.assertIn("[Events]", ass)
            self.assertIn("[V4+ Styles]", ass)

    def test_empty_words_list_is_skipped(self) -> None:
        caps = [{"start": 0.0, "end": 1.0, "text": "x", "words": []}]
        self.assertEqual(_dialogue_lines(kinetic.build_ass(_clip(*caps),
                                                          font_path=FONT_PATH)), [])

    def test_single_word_phrase(self) -> None:
        cap = {"start": 0.0, "end": 1.0, "text": "ya", "words": _words(("ya", 0.02, 0.9))}
        lines = _dialogue_lines(kinetic.build_ass(_clip(cap), font_path=FONT_PATH))
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(_pos(lines[0])[1], CENTER_Y, delta=0.01)


# ---------------------------------------------------------------------------
# Determinisme dan font
# ---------------------------------------------------------------------------

class DeterminismAndFontTest(unittest.TestCase):
    def test_two_calls_are_byte_identical(self) -> None:
        clip = _clip(*_phrases())
        self.assertEqual(kinetic.build_ass(clip, font_path=FONT_PATH),
                         kinetic.build_ass(clip, font_path=FONT_PATH))

    def test_missing_font_path_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError) as ctx:
            kinetic.build_ass(_clip(*_phrases()), font_path="/nonexistent/Font.ttf")
        self.assertIn("Font.ttf", str(ctx.exception))

    def test_default_font_is_bundled_archivo_black(self) -> None:
        """font_path=None wajib memakai font bundel, bukan fallback DejaVu (R4)."""
        ass = kinetic.build_ass(_clip(*_phrases()))
        family = _font().family
        self.assertEqual(family, "Archivo Black")
        style = [ln for ln in ass.splitlines() if ln.startswith("Style: Kinetic,")][0]
        self.assertEqual(style[len("Style: "):].split(",")[1], family)
        self.assertNotIn("DejaVu", ass)

    def test_bundled_font_constant_points_at_real_file(self) -> None:
        p = ROOT / kinetic.BUNDLED_FONT
        self.assertTrue(p.is_file(), msg=str(p))
        self.assertEqual(p.name, FONT_PATH.name)

    def test_font_size_and_bold_written_to_style(self) -> None:
        """`Fontsize` ASS = em x cell_height_ratio, bukan em mentah.

        `size` di `build_ass` berarti em dalam piksel (dipakai `layout_phrase`);
        libass menafsirkan `Fontsize` sebagai tinggi sel OS/2, jadi penulis ASS
        mengalikannya dengan `font.cell_height_ratio` (Archivo Black 1,347).
        Asersi lama (`fields[2] == "72"`) mengkodekan perilaku yang salah dan
        diganti pada Langkah 3b-ii-a; lihat tests/test_kinetic_libass_oracle.py
        untuk bukti render sungguhan.
        """
        ass = kinetic.build_ass(_clip(*_phrases()), font_path=FONT_PATH, size=72.0)
        style = [ln for ln in ass.splitlines() if ln.startswith("Style: Kinetic,")][0]
        fields = style[len("Style: "):].split(",")
        ratio = fontmetrics.Font.load(FONT_PATH).cell_height_ratio
        self.assertEqual(fields[2], f"{round(72.0 * ratio, 2):g}")
        self.assertEqual(fields[2], "96.98", "72 x 1,347 = 96,984 -> 96,98")
        self.assertNotEqual(fields[2], "72", "em mentah: glyph 26% terlalu kecil")
        self.assertEqual(fields[7], "0", "berkas sudah Black: jangan minta bold sintetik")


# ---------------------------------------------------------------------------
# uppercase (keputusan koordinator: default False = case asli)
# ---------------------------------------------------------------------------

class UppercaseTest(unittest.TestCase):
    def test_default_keeps_original_case(self) -> None:
        cap = {"start": 1.0, "end": 2.34, "text": "Pertama, pasti nenekmu bangga.",
               "words": W4}
        lines = _dialogue_lines(kinetic.build_ass(_clip(cap), font_path=FONT_PATH))
        self.assertEqual([_event_text(ln) for ln in lines],
                         ["Pertama,", "pasti", "nenekmu", "bangga."])

    def test_uppercase_true_shifts_layout_using_uppercase_widths(self) -> None:
        cap = {"start": 1.0, "end": 2.34, "text": "Pertama, pasti nenekmu bangga.",
               "words": W4}
        lower = _dialogue_lines(kinetic.build_ass(_clip(cap), font_path=FONT_PATH))
        upper = _dialogue_lines(
            kinetic.build_ass(_clip(cap), font_path=FONT_PATH, uppercase=True)
        )
        self.assertEqual([_event_text(ln) for ln in upper],
                         ["PERTAMA,", "PASTI", "NEKEKMU".replace("KEK", "NEK"), "BANGGA."])
        # Lebar Archivo Black berbeda untuk kapital -> x kata pertama bergeser.
        self.assertNotAlmostEqual(_pos(lower[0])[0], _pos(upper[0])[0], delta=0.5)
        # Dan posisi itu HARUS sama dengan layout_phrase atas teks kapital.
        font = _font()
        expected = kinetic.layout_phrase(
            [{"w": "PERTAMA,"}, {"w": "PASTI"}, {"w": "NENEKMU"}, {"w": "BANGGA."}],
            font, SIZE,
        )
        for ln, exp in zip(upper, expected):
            self.assertAlmostEqual(_pos(ln)[0], exp["x"], delta=0.01)
            self.assertAlmostEqual(_pos(ln)[1], exp["y"], delta=0.01)


if __name__ == "__main__":
    unittest.main()
