"""Tes pembentukan EDL: timing caption, integritas rentang, dan id klip."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_work

from scripts.lib import jsonio


class EdlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = make_work(Path(cls._tmp.name), top_n=10, top=3)
        cls.edl = jsonio.read_json(cls.wd / "edl.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_version_and_structure(self) -> None:
        self.assertEqual(self.edl["version"], "0.1.0")
        self.assertIn("source", self.edl)
        self.assertIn("output", self.edl)
        self.assertEqual(len(self.edl["clips"]), 3)

    def test_output_is_vertical(self) -> None:
        self.assertEqual(self.edl["output"]["width"], 1080)
        self.assertEqual(self.edl["output"]["height"], 1920)

    def test_clip_ids_format(self) -> None:
        for clip in self.edl["clips"]:
            self.assertRegex(clip["id"], r"^clip_\d{2,}$")

    def test_clip_ids_unique(self) -> None:
        ids = [c["id"] for c in self.edl["clips"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_single_segment_v0(self) -> None:
        for clip in self.edl["clips"]:
            self.assertEqual(len(clip["segments"]), 1)
            seg = clip["segments"][0]
            self.assertLess(seg["src_start"], seg["src_end"])

    def test_captions_within_clip(self) -> None:
        for clip in self.edl["clips"]:
            seg = clip["segments"][0]
            dur = seg["src_end"] - seg["src_start"]
            for cap in clip["captions"]:
                self.assertGreaterEqual(cap["start"], -0.001, msg=clip["id"])
                self.assertLessEqual(cap["end"], dur + 0.05, msg=f"{clip['id']} {cap}")
                self.assertLess(cap["start"], cap["end"])

    def test_captions_monotonic(self) -> None:
        for clip in self.edl["clips"]:
            starts = [c["start"] for c in clip["captions"]]
            self.assertEqual(starts, sorted(starts), msg=clip["id"])

    def test_captions_do_not_overlap(self) -> None:
        for clip in self.edl["clips"]:
            caps = clip["captions"]
            for a, b in zip(caps, caps[1:]):
                self.assertLessEqual(a["end"], b["start"] + 1e-6, msg=clip["id"])

    def test_no_flicker_gaps(self) -> None:
        """Gap kecil harus dirapatkan; caption yang berkedip terlihat murah.

        Toleransi 0.05s adalah margin sengaja supaya dua caption tidak bertumpuk.
        """
        for clip in self.edl["clips"]:
            caps = clip["captions"]
            for a, b in zip(caps, caps[1:]):
                gap = b["start"] - a["end"]
                self.assertFalse(0.05 < gap <= 0.30, msg=f"{clip['id']} gap {gap:.2f}s")

    def test_min_caption_duration(self) -> None:
        for clip in self.edl["clips"]:
            for cap in clip["captions"][:-1]:
                self.assertGreaterEqual(
                    round(cap["end"] - cap["start"], 3), 0.40,
                    msg=f"{clip['id']} {cap['text']!r}",
                )

    def test_captions_start_near_zero(self) -> None:
        for clip in self.edl["clips"]:
            self.assertLess(clip["captions"][0]["start"], 0.6, msg=clip["id"])

    def test_caption_has_src_trace(self) -> None:
        for clip in self.edl["clips"]:
            for cap in clip["captions"]:
                self.assertIn("src_start", cap)

    def test_caption_src_matches_output_offset(self) -> None:
        for clip in self.edl["clips"]:
            base = clip["segments"][0]["src_start"]
            for cap in clip["captions"]:
                self.assertAlmostEqual(cap["start"], cap["src_start"] - base, places=2)

    def test_emphasis_is_single_word_of_text(self) -> None:
        for clip in self.edl["clips"]:
            for cap in clip["captions"]:
                em = cap.get("emphasis")
                if em:
                    self.assertNotIn(" ", em)
                    words = [w.strip(".,!?…").lower() for w in cap["text"].split()]
                    self.assertIn(em, words, msg=f"{em!r} tidak ada di {cap['text']!r}")

    def test_score_block_present(self) -> None:
        for clip in self.edl["clips"]:
            s = clip["score"]
            for key in ("axes", "base", "penalty", "final", "percentile"):
                self.assertIn(key, s)
            self.assertGreaterEqual(s["final"], 0.0)
            self.assertLessEqual(s["final"], 100.0)

    def test_scores_descending(self) -> None:
        finals = [c["score"]["final"] for c in self.edl["clips"]]
        self.assertEqual(finals, sorted(finals, reverse=True))

    def test_reframe_mode(self) -> None:
        for clip in self.edl["clips"]:
            self.assertEqual(clip["reframe"]["mode"], "center")

    def test_serialisable(self) -> None:
        json.dumps(self.edl)

    def test_report_written(self) -> None:
        report = (self.wd / "report.md").read_text(encoding="utf-8")
        self.assertIn("Peta klip", report)
        for clip in self.edl["clips"]:
            self.assertIn(clip["id"], report)


if __name__ == "__main__":
    unittest.main()
