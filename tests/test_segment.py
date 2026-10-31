"""Tes segmentasi dan candidate generation."""

from __future__ import annotations

import unittest

from tests.helpers import ROOT  # noqa: F401  (memastikan sys.path siap)

from scripts import candidates as cand_mod
from scripts import demo as demo_mod
from scripts import features as feat_mod
from scripts import segment


class SegmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tr = demo_mod.synthesize()
        cls.atoms = segment.build_atoms(cls.tr["words"])

    def test_atoms_produced(self) -> None:
        self.assertGreater(len(self.atoms), 5)

    def test_ids_sequential(self) -> None:
        self.assertEqual([a["id"] for a in self.atoms], list(range(len(self.atoms))))

    def test_times_monotonic(self) -> None:
        prev_end = -1.0
        for a in self.atoms:
            self.assertGreaterEqual(a["start"], prev_end - 0.001, msg=f"atom {a['id']}")
            self.assertGreater(a["end"], a["start"], msg=f"atom {a['id']}")
            prev_end = a["end"]

    def test_word_range_contiguous(self) -> None:
        for a in self.atoms:
            self.assertEqual(a["words"], a["word_end"] - a["word_start"] + 1)

    def test_covers_all_words(self) -> None:
        covered = sum(a["words"] for a in self.atoms)
        self.assertEqual(covered, len(self.tr["words"]))

    def test_max_words_respected(self) -> None:
        for a in self.atoms:
            self.assertLessEqual(a["words"], segment.DEFAULTS["max_words"])

    def test_strong_marker_starts_atom(self) -> None:
        # "Pertama itu Codex" harus jadi awal atom sendiri
        starts = [a["text"].lower().split()[0] for a in self.atoms if a["text"]]
        self.assertTrue(
            any(s.strip(".,!?") in {"pertama", "kedua", "contohnya", "makanya"} for s in starts),
            msg=f"tidak ada atom yang dimulai discourse marker: {starts}",
        )


class CandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tr = demo_mod.synthesize()
        cls.atoms = segment.build_atoms(cls.tr["words"])
        cls.cands = cand_mod.generate(cls.atoms, top_n=10)
        feat_mod.attach(cls.cands, cls.atoms)

    def test_candidates_exist(self) -> None:
        self.assertGreaterEqual(len(self.cands), 3)

    def test_ids_sequential(self) -> None:
        self.assertEqual([c["id"] for c in self.cands], list(range(len(self.cands))))

    def test_duration_within_bounds(self) -> None:
        for c in self.cands:
            self.assertGreaterEqual(c["duration"], cand_mod.DEFAULT_MIN_DUR - 0.01)
            self.assertLessEqual(c["duration"], cand_mod.DEFAULT_MAX_DUR + 0.01)

    def test_atom_range_valid(self) -> None:
        for c in self.cands:
            self.assertLessEqual(c["atom_start"], c["atom_end"])
            self.assertLess(c["atom_end"], len(self.atoms))

    def test_timestamps_match_atoms(self) -> None:
        for c in self.cands:
            self.assertAlmostEqual(c["start"], self.atoms[c["atom_start"]]["start"], places=2)
            self.assertAlmostEqual(c["end"], self.atoms[c["atom_end"]]["end"], places=2)

    def test_candidates_diverse(self) -> None:
        # dua kandidat teratas tidak boleh hampir identik
        for i in range(len(self.cands)):
            for j in range(i + 1, len(self.cands)):
                ratio = cand_mod._overlap_ratio(self.cands[i], self.cands[j])
                self.assertLessEqual(ratio, 0.60, msg=f"{i} vs {j} overlap {ratio:.2f}")

    def test_no_hanging_conjunction_start(self) -> None:
        for c in self.cands:
            self.assertFalse(c["text"].lower().startswith(("dan ", "atau ", "tapi ")))

    def test_features_attached(self) -> None:
        required = {"wpm", "filler_ratio", "hook_latency", "number_density", "type_token_ratio"}
        for c in self.cands:
            self.assertTrue(required.issubset(c["features"]), msg=str(c["features"].keys()))

    def test_filler_detected(self) -> None:
        # transkrip demo mengandung "Eee" dan "Emm"
        total = sum(c["features"]["filler_count"] for c in self.cands)
        self.assertGreaterEqual(total, 1)

    def test_number_detected(self) -> None:
        total = sum(c["features"]["number_count"] for c in self.cands)
        self.assertGreaterEqual(total, 1)

    def test_hook_latency_bounded(self) -> None:
        for c in self.cands:
            self.assertGreaterEqual(c["features"]["hook_latency"], 0.0)
            self.assertLessEqual(c["features"]["hook_latency"], c["duration"] + 0.01)


if __name__ == "__main__":
    unittest.main()
