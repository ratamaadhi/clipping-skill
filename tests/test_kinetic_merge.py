"""Tes murni `kinetic.effective_captions` (Langkah 3b-v, temuan produk F2).

Fungsi ini menggabungkan frasa yang jendela tampilnya lebih pendek dari
`MIN_VISIBLE` SAAT RENDER; EDL tidak diubah. Tabel kasus di bawah mengunci
perilaku yang diminta: arah penggabungan (depan dulu, lalu belakang), batas
`max_words`, syarat muat dua baris, pewarisan emphasis, urutan/waktu kata,
kemurnian masukan, determinisme, batas eksak, dan integrasi `build_ass`.
"""

from __future__ import annotations

import copy
import hashlib
import unittest

from tests.helpers import ROOT
from tests.test_kinetic import FONT_PATH, _clip, _phrases

from scripts import kinetic
from scripts.lib import fontmetrics

SIZE = 84.0


def _w(*pairs: tuple[str, float, float]) -> list[dict]:
    return [{"w": w, "start": s, "end": e} for (w, s, e) in pairs]


def _cap(start: float, end: float, text: str, words: list[dict], **extra) -> dict:
    cap = {"start": start, "end": end, "text": text, "words": words}
    cap.update(extra)
    return cap


def _short_then_normal() -> list[dict]:
    """`Lu,` (80 ms, jendela 40 ms) + frasa normal 4 kata: kasus F2."""
    return [
        _cap(
            1.00,
            1.08,
            "Lu,",
            _w(("Lu,", 1.00, 1.08)),
            src_start=10.0,
        ),
        _cap(
            1.08,
            2.20,
            "lu ngerasain nggak sih",
            _w(
                ("lu", 1.08, 1.30),
                ("ngerasain", 1.30, 1.90),
                ("nggak", 1.90, 2.05),
                ("sih", 2.05, 2.20),
            ),
            emphasis="nggak",
            src_start=11.0,
        ),
    ]


def _normal_then_short() -> list[dict]:
    """Frasa normal di depan, frasa pendek di AKHIR (tanpa frasa berikutnya)."""
    return [
        _cap(
            1.00,
            2.00,
            "Pertama, pasti",
            _w(("Pertama,", 1.00, 1.50), ("pasti", 1.50, 1.95)),
            src_start=20.0,
        ),
        _cap(
            2.00,
            2.08,
            "Lu,",
            _w(("Lu,", 2.00, 2.05)),
            src_start=21.0,
        ),
    ]


def _long_phrase(start: float, end: float, count: int = 6) -> dict:
    """Kata-kata sangat lebar (~800 px) yang tidak muat dua baris bersama."""
    texts = [
        "menyeramkannya,",
        "membanggakannya,",
        "menyebalkannya,",
        "memperlihatkannya,",
        "mempertanggungjawabkannya,",
        "menghancurkannya,",
    ][:count]
    step = (end - start) / len(texts)
    words = [
        {"w": text, "start": round(start + k * step, 3),
         "end": round(start + (k + 1) * step, 3)}
        for k, text in enumerate(texts)
    ]
    return _cap(start, end, " ".join(texts), words)


class EffectiveCaptionsTest(unittest.TestCase):
    # -- (a) tidak ada frasa pendek -> nilai sama, objek baru ---------------

    def test_no_short_phrase_returns_equal_but_new_objects(self) -> None:
        caps = copy.deepcopy(_phrases())
        result = kinetic.effective_captions(caps)
        self.assertEqual(result, caps)
        self.assertIsNot(result, caps)
        for got, src in zip(result, caps):
            self.assertIsNot(got, src)
            self.assertIsNot(got["words"], src["words"])
            for gw, sw in zip(got["words"], src["words"]):
                self.assertIsNot(gw, sw)

    # -- (b) pendek + normal -> digabung ke depan ---------------------------

    def test_short_phrase_merges_into_next(self) -> None:
        caps = _short_then_normal()
        start0, end0 = kinetic.display_window(caps, 0)
        self.assertLess(end0 - start0, kinetic.MIN_VISIBLE)

        result = kinetic.effective_captions(caps)

        self.assertEqual(len(result), 1)
        merged = result[0]
        self.assertEqual(merged["text"], "Lu, lu ngerasain nggak sih")
        self.assertEqual(merged["start"], 1.00)
        self.assertEqual(merged["end"], 2.20)
        self.assertEqual(
            [w["w"] for w in merged["words"]],
            ["Lu,", "lu", "ngerasain", "nggak", "sih"],
        )
        self.assertEqual(merged["src_start"], 10.0, "kunci lain dari frasa PERTAMA")
        self.assertEqual(merged["emphasis"], "nggak")
        start, end = kinetic.display_window(result, 0)
        self.assertGreaterEqual(
            end - start, kinetic.MIN_VISIBLE,
            msg=f"jendela gabungan masih pendek: {end - start:.3f}s",
        )

    # -- (c) pendek di akhir -> digabung ke belakang ------------------------

    def test_short_phrase_at_end_merges_into_previous(self) -> None:
        caps = _normal_then_short()
        self.assertLess(
            kinetic.display_window(caps, 1)[1] - kinetic.display_window(caps, 1)[0],
            kinetic.MIN_VISIBLE,
        )

        result = kinetic.effective_captions(caps)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "Pertama, pasti Lu,")
        self.assertEqual(result[0]["start"], 1.00)
        self.assertEqual(result[0]["end"], 2.08)
        self.assertEqual(
            [w["w"] for w in result[0]["words"]],
            ["Pertama,", "pasti", "Lu,"],
        )
        self.assertEqual(result[0]["src_start"], 20.0)

    # -- (d) frasa berikutnya terlalu panjang ------------------------------

    def test_short_phrase_not_merged_when_next_exceeds_max_words(self) -> None:
        caps = [
            _cap(1.00, 1.08, "Lu,", _w(("Lu,", 1.00, 1.08))),
            _long_phrase(1.08, 2.60),
        ]
        result = kinetic.effective_captions(caps)
        self.assertEqual(len(result), 2, "1 + 6 kata > max_words tidak boleh digabung")
        self.assertEqual(result[0]["text"], "Lu,")
        self.assertEqual(result[1]["text"], caps[1]["text"])

    def test_short_phrase_falls_back_to_previous_when_next_is_too_long(self) -> None:
        caps = [
            _cap(
                1.00,
                2.00,
                "Pertama, pasti",
                _w(("Pertama,", 1.00, 1.50), ("pasti", 1.50, 1.95)),
            ),
            _cap(2.00, 2.05, "Lu,", _w(("Lu,", 2.00, 2.05))),
            _long_phrase(2.05, 3.50),
        ]
        result = kinetic.effective_captions(caps)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "Pertama, pasti Lu,")
        self.assertEqual(len(result[0]["words"]), 3)
        self.assertEqual(result[1]["text"], caps[2]["text"])

    def test_short_phrase_not_merged_when_merged_text_needs_three_lines(self) -> None:
        caps = [
            _cap(1.00, 1.08, "Lu,", _w(("Lu,", 1.00, 1.08))),
            _long_phrase(1.08, 2.60, count=5),
        ]
        # 1 + 5 = 6 kata <= max_words, tetapi tiap kata ~800 px -> >= 3 baris.
        merged_words = caps[0]["words"] + caps[1]["words"]
        self.assertFalse(
            kinetic._fits_two_lines(merged_words, "", _font(), SIZE),
            "fixture tidak menguji syarat dua baris",
        )
        result = kinetic.effective_captions(caps)
        self.assertEqual(len(result), 2)

    # -- (e) gabungan berantai ---------------------------------------------

    def test_chain_of_short_phrases_stops_at_max_words(self) -> None:
        caps = [
            _cap(1.00, 1.08, "Lu,", _w(("Lu,", 1.00, 1.08))),
            _cap(1.08, 1.16, "lu", _w(("lu", 1.08, 1.16))),
            _cap(
                1.16,
                2.40,
                "ngerasain nggak",
                _w(("ngerasain", 1.16, 1.60), ("nggak", 1.60, 2.40)),
            ),
        ]
        self.assertLess(
            kinetic.display_window(caps, 0)[1] - kinetic.display_window(caps, 0)[0],
            kinetic.MIN_VISIBLE,
        )
        self.assertLess(
            kinetic.display_window(caps, 1)[1] - kinetic.display_window(caps, 1)[0],
            kinetic.MIN_VISIBLE,
        )

        result = kinetic.effective_captions(caps)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "Lu, lu ngerasain nggak")
        self.assertEqual(len(result[0]["words"]), 4)

    def test_chain_is_bounded_by_max_words(self) -> None:
        caps = [
            _cap(1.00, 1.08, "Lu,", _w(("Lu,", 1.00, 1.08))),
            _cap(1.08, 1.16, "lu", _w(("lu", 1.08, 1.16))),
            _cap(
                1.16,
                2.40,
                "ngerasain nggak sih",
                _w(
                    ("ngerasain", 1.16, 1.60),
                    ("nggak", 1.60, 1.90),
                    ("sih", 1.90, 2.40),
                ),
            ),
        ]
        # 2 + 3 = 5 kata; dengan max_words=4 rantai harus berhenti.
        result = kinetic.effective_captions(caps, max_words=4)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "Lu, lu")
        self.assertEqual(result[1]["text"], "ngerasain nggak sih")

    # -- (f) emphasis ------------------------------------------------------

    def test_emphasis_from_first_when_second_has_none(self) -> None:
        caps = _short_then_normal()
        caps[0]["emphasis"] = "Lu,"
        del caps[1]["emphasis"]
        result = kinetic.effective_captions(caps)
        self.assertEqual(result[0]["emphasis"], "Lu,")

    def test_emphasis_from_second_when_first_has_none(self) -> None:
        result = kinetic.effective_captions(_short_then_normal())
        self.assertEqual(result[0]["emphasis"], "nggak")

    def test_second_emphasis_wins_when_both_have_one(self) -> None:
        caps = _short_then_normal()
        caps[0]["emphasis"] = "Lu,"
        result = kinetic.effective_captions(caps)
        self.assertEqual(
            result[0]["emphasis"], "nggak",
            "frasa kedua harus menang bila keduanya punya emphasis",
        )

    def test_no_emphasis_key_when_neither_has_one(self) -> None:
        caps = _short_then_normal()
        del caps[1]["emphasis"]
        result = kinetic.effective_captions(caps)
        self.assertNotIn("emphasis", result[0])

    # -- (g) urutan kata dan waktu kata tidak berubah ----------------------

    def test_merged_words_are_in_order_and_times_unchanged(self) -> None:
        caps = _short_then_normal()
        original = copy.deepcopy(
            [(w["w"], w["start"], w["end"]) for cap in caps for w in cap["words"]]
        )
        result = kinetic.effective_captions(caps)
        self.assertEqual(
            [(w["w"], w["start"], w["end"]) for w in result[0]["words"]],
            original,
        )

    # -- (h) masukan tidak dimodifikasi ------------------------------------

    def test_input_is_not_mutated_even_when_merging(self) -> None:
        caps = _short_then_normal()
        snapshot = copy.deepcopy(caps)
        result = kinetic.effective_captions(caps)
        self.assertEqual(caps, snapshot)
        # Mutasi hasil tidak boleh merambat ke masukan -> salinan dalam.
        result[0]["words"][0]["w"] = "BERUBAH"
        result[0]["text"] = "BERUBAH"
        result[0]["start"] = 99.0
        self.assertEqual(caps, snapshot)

    # -- (i) determinisme --------------------------------------------------

    def test_two_calls_are_equal_and_independent(self) -> None:
        caps = _short_then_normal()
        first = kinetic.effective_captions(caps)
        second = kinetic.effective_captions(caps)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first[0], second[0])

    # -- (j) min_visible dan max_words kustom -------------------------------

    def test_custom_min_visible_controls_merge(self) -> None:
        caps = _short_then_normal()
        self.assertEqual(len(kinetic.effective_captions(caps, min_visible=0.0)), 2)
        self.assertEqual(len(kinetic.effective_captions(caps, min_visible=0.05)), 1)

    def test_custom_max_words_controls_merge(self) -> None:
        caps = _short_then_normal()
        self.assertEqual(len(kinetic.effective_captions(caps, max_words=4)), 2)
        self.assertEqual(len(kinetic.effective_captions(caps, max_words=5)), 1)

    # -- (k) caption tanpa words dilewati tanpa galat -----------------------

    def test_caption_without_words_is_skipped_without_error(self) -> None:
        caps = [
            {"start": 0.0, "end": 0.04, "text": "tanpa kata"},
            copy.deepcopy(_short_then_normal()[1]),
        ]
        result = kinetic.effective_captions(caps)
        self.assertEqual(result, caps)

    def test_wordless_caption_between_phrases_is_not_a_merge_target(self) -> None:
        caps = [
            _cap(1.00, 1.08, "Lu,", _w(("Lu,", 1.00, 1.08))),
            {"start": 1.08, "end": 1.10, "text": "tanpa kata"},
            copy.deepcopy(_short_then_normal()[1]),
        ]
        result = kinetic.effective_captions(caps)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1], caps[1])

    # -- (l) batas eksak: jendela == min_visible TIDAK digabung ------------

    def test_window_exactly_min_visible_is_not_merged(self) -> None:
        caps = _short_then_normal()
        start, end = kinetic.display_window(caps, 0)
        exact = end - start
        self.assertLess(exact, kinetic.MIN_VISIBLE)

        kept = kinetic.effective_captions(caps, min_visible=exact)
        self.assertEqual(len(kept), 2, "end - start == min_visible bukan '<'")

        merged = kinetic.effective_captions(caps, min_visible=exact + 1e-9)
        self.assertEqual(len(merged), 1)


def _font() -> fontmetrics.Font:
    return fontmetrics.Font.load(FONT_PATH)


class BuildAssMergeTest(unittest.TestCase):
    """`build_ass` wajib memakai `effective_captions` sebelum layout."""

    # Hash ASS untuk `_phrases()` (tanpa frasa pendek) diukur SEBELUM
    # perubahan 3b-v. Klip tanpa frasa pendek harus tetap byte-identik.
    GOLDEN_NO_SHORT = (
        "444bd2c2123c395a3768bc5d19b5de81d6ec8ebf71662d24e62ad5fca5140312"
    )

    def test_no_short_phrase_ass_is_byte_identical(self) -> None:
        ass = kinetic.build_ass(_clip(*_phrases()), font_path=str(FONT_PATH))
        self.assertEqual(
            hashlib.sha256(ass.encode("utf-8")).hexdigest(),
            self.GOLDEN_NO_SHORT,
        )

    def test_build_ass_uses_merged_phrase(self) -> None:
        ass = kinetic.build_ass(
            _clip(*_short_then_normal()), font_path=str(FONT_PATH)
        )
        lines = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
        self.assertEqual(len(lines), 5, "6 kata mentah -> 5 kata setelah gabung")
        texts = [ln.split(",", 9)[9].rsplit("}", 1)[-1] for ln in lines]
        self.assertEqual(texts, ["Lu,", "lu", "ngerasain", "nggak", "sih"])

        from tests.test_kinetic import _ass_seconds, _fields

        # Jendela gabungan: 0,96 s (kata pertama - lead) sampai 2,32 s
        # (kata terakhir + TAIL_PAD). Tanpa penggabungan baris pertama akan
        # berakhir di 1,00 s (jendela 40 ms).
        self.assertAlmostEqual(_ass_seconds(_fields(lines[0])[1]), 0.96, delta=0.001)
        for line in lines:
            self.assertAlmostEqual(
                _ass_seconds(_fields(line)[2]), 2.32, delta=0.001,
                msg=f"End bukan akhir jendela gabungan: {line}",
            )


if __name__ == "__main__":
    unittest.main()
