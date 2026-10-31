"""Tes caption: grouping, emphasis, dan format ASS."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401

from scripts import captions as cap
from scripts.lib import text as T


def _words(pairs: list[tuple[str, float, float]]) -> list[dict]:
    return [{"i": i, "w": w, "start": s, "end": e} for i, (w, s, e) in enumerate(pairs)]


class GroupWordsTest(unittest.TestCase):
    def test_max_words_per_phrase(self) -> None:
        words = _words([("satu", 0.0, 0.3), ("dua", 0.3, 0.6), ("tiga", 0.6, 0.9),
                        ("empat", 0.9, 1.2), ("lima", 1.2, 1.5), ("enam", 1.5, 1.8)])
        phrases = cap.group_words(words, max_words=3)
        for p in phrases:
            self.assertLessEqual(len(p["words"]), 3)

    def test_breaks_on_long_pause(self) -> None:
        words = _words([("halo", 0.0, 0.3), ("semua", 0.3, 0.6), ("kita", 2.0, 2.3)])
        phrases = cap.group_words(words, max_words=4, gap_break=0.4)
        self.assertGreaterEqual(len(phrases), 2)

    def test_breaks_on_sentence_end(self) -> None:
        words = _words([("selesai.", 0.0, 0.4), ("lanjut", 0.45, 0.8)])
        phrases = cap.group_words(words, max_words=4)
        self.assertEqual(len(phrases), 2)

    def test_phrase_text_matches_words(self) -> None:
        words = _words([("a", 0.0, 0.2), ("b", 0.2, 0.4)])
        phrases = cap.group_words(words)
        self.assertEqual(phrases[0]["text"], "a b")

    def test_phrase_times_within_bounds(self) -> None:
        words = _words([("a", 0.0, 0.2), ("b", 0.2, 0.4), ("c", 0.4, 0.6)])
        for p in cap.group_words(words):
            self.assertGreaterEqual(p["start"], 0.0)
            self.assertGreater(p["end"], p["start"])

    def test_empty_input(self) -> None:
        self.assertEqual(cap.group_words([]), [])


class EmphasisTest(unittest.TestCase):
    def _phrase(self, text: str) -> dict:
        toks = text.split()
        words = [{"i": i, "w": t, "start": i * 0.3, "end": i * 0.3 + 0.25}
                 for i, t in enumerate(toks)]
        return {"words": words, "start": 0.0, "end": len(toks) * 0.3, "text": text}

    def test_prefers_number(self) -> None:
        ph = self._phrase("harganya dua ratus ribu")
        idx = cap.pick_emphasis(ph)
        self.assertIsNotNone(idx)
        chosen = ph["words"][idx]["w"]
        self.assertGreater(T.count_numbers(chosen), 0, msg=f"terpilih {chosen!r}")

    def test_prefers_negation(self) -> None:
        ph = self._phrase("gue gak setuju")
        idx = cap.pick_emphasis(ph)
        self.assertEqual(ph["words"][idx]["w"], "gak")

    def test_returns_none_on_empty(self) -> None:
        self.assertIsNone(cap.pick_emphasis({"words": [], "start": 0, "end": 0, "text": ""}))

    def test_returns_single_index(self) -> None:
        idx = cap.pick_emphasis(self._phrase("ini cuma contoh biasa"))
        self.assertIsInstance(idx, int)


class AssTest(unittest.TestCase):
    def _caps(self) -> list[dict]:
        return [
            {"start": 0.0, "end": 1.2, "text": "CODEX ATAU", "emphasis": "codex"},
            {"start": 1.2, "end": 2.6, "text": "CLAUDE", "emphasis": "claude"},
        ]

    def test_contains_header(self) -> None:
        ass = cap.build_ass(self._caps())
        self.assertIn("[Script Info]", ass)
        self.assertIn("PlayResX: 1080", ass)
        self.assertIn("PlayResY: 1920", ass)
        self.assertIn("[V4+ Styles]", ass)

    def test_dialogue_count_matches(self) -> None:
        ass = cap.build_ass(self._caps())
        self.assertEqual(ass.count("Dialogue:"), 2)

    def test_time_format(self) -> None:
        self.assertEqual(cap._ass_time(0.0), "0:00:00.00")
        self.assertEqual(cap._ass_time(65.25), "0:01:05.25")
        self.assertEqual(cap._ass_time(3661.5), "1:01:01.50")

    def test_emphasis_colour_injected(self) -> None:
        ass = cap.build_ass(self._caps())
        self.assertIn(cap.ACCENT, ass)

    def test_uppercase_applied(self) -> None:
        ass = cap.build_ass(self._caps(), uppercase=True)
        self.assertIn("CODEX", ass)

    def test_no_placeholder_left(self) -> None:
        ass = cap.build_ass(self._caps())
        self.assertNotIn("{{", ass)

    def test_write_ass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = cap.write_ass(self._caps(), Path(tmp) / "c.ass")
            self.assertTrue(path.exists())
            self.assertIn("Dialogue:", path.read_text(encoding="utf-8"))

    def test_template_used(self) -> None:
        tpl = ROOT / "templates" / "caption_default.ass.tmpl"
        self.assertTrue(tpl.exists())
        ass = cap.build_ass(self._caps(), template_path=tpl)
        self.assertIn("YCbCr Matrix", ass)


if __name__ == "__main__":
    unittest.main()
