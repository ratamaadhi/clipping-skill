"""Tes scoring: validasi, penalti non-linear, dan urutan ranking."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_work

from scripts import score
from scripts.lib import jsonio


def _axes(**overrides: float) -> dict[str, dict[str, object]]:
    base = {k: {"score": 8.0, "evidence": "kutipan contoh"} for k in score.AXES}
    for k, v in overrides.items():
        base[k] = {"score": v, "evidence": "kutipan contoh"}
    return base


class ValidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = make_work(Path(self._tmp.name))
        self.cands = jsonio.read_json(self.wd / "candidates.json")
        self.valid = jsonio.read_json(self.wd / "selection.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_selection_passes(self) -> None:
        self.assertEqual(score.validate_selection(self.valid, self.cands), [])

    def test_agent_can_refine_bounds_with_atoms(self) -> None:
        """Prefilter cuma usul; agent boleh koreksi batas selama masih wajar."""
        atoms = jsonio.read_json(self.wd / "atoms.json")
        atoms = atoms["atoms"] if isinstance(atoms, dict) else atoms
        sel = copy.deepcopy(self.valid)
        entry = sel["candidates"][0]
        entry["atom_start"] = 0
        entry["atom_end"] = min(4, len(atoms) - 1)
        if atoms[entry["atom_end"]]["end"] - atoms[0]["start"] < score.MIN_CLIP_S:
            self.skipTest("atom sintetis terlalu pendek untuk batas minimum")
        errors = score.validate_selection(sel, self.cands, atoms)
        self.assertEqual(errors, [])

    def test_rejects_out_of_bounds_range(self) -> None:
        atoms = jsonio.read_json(self.wd / "atoms.json")
        atoms = atoms["atoms"] if isinstance(atoms, dict) else atoms
        sel = copy.deepcopy(self.valid)
        sel["candidates"][0]["atom_end"] = len(atoms) + 5
        errors = score.validate_selection(sel, self.cands, atoms)
        self.assertTrue(any("tidak valid" in e for e in errors), errors)

    def test_rejects_reversed_range(self) -> None:
        atoms = jsonio.read_json(self.wd / "atoms.json")
        atoms = atoms["atoms"] if isinstance(atoms, dict) else atoms
        sel = copy.deepcopy(self.valid)
        sel["candidates"][0]["atom_start"] = 5
        sel["candidates"][0]["atom_end"] = 3
        errors = score.validate_selection(sel, self.cands, atoms)
        self.assertTrue(any("tidak valid" in e for e in errors), errors)

    def test_rejects_missing_axis(self) -> None:
        bad = copy.deepcopy(self.valid)
        del bad["candidates"][0]["axes"]["loop"]
        errors = score.validate_selection(bad, self.cands)
        self.assertTrue(any("loop" in e for e in errors), msg=str(errors))

    def test_rejects_empty_evidence(self) -> None:
        bad = copy.deepcopy(self.valid)
        bad["candidates"][0]["axes"]["hook"]["evidence"] = ""
        errors = score.validate_selection(bad, self.cands)
        self.assertTrue(any("evidence" in e for e in errors), msg=str(errors))

    def test_rejects_agent_total_field(self) -> None:
        bad = copy.deepcopy(self.valid)
        bad["candidates"][0]["total"] = 92
        errors = score.validate_selection(bad, self.cands)
        self.assertTrue(any("total" in e and "dilarang" in e for e in errors), msg=str(errors))

    def test_rejects_tampered_atom_range(self) -> None:
        bad = copy.deepcopy(self.valid)
        bad["candidates"][0]["atom_end"] += 1
        errors = score.validate_selection(bad, self.cands)
        self.assertTrue(any("atom_end" in e for e in errors), msg=str(errors))

    def test_rejects_out_of_range_score(self) -> None:
        bad = copy.deepcopy(self.valid)
        bad["candidates"][0]["axes"]["hook"]["score"] = 11
        errors = score.validate_selection(bad, self.cands)
        self.assertTrue(any("0-10" in e for e in errors), msg=str(errors))

    def test_rejects_bad_weakest_axis(self) -> None:
        bad = copy.deepcopy(self.valid)
        bad["candidates"][0]["weakest_axis"] = "vibes"
        errors = score.validate_selection(bad, self.cands)
        self.assertTrue(any("weakest_axis" in e for e in errors), msg=str(errors))


class CompositeTest(unittest.TestCase):
    def test_all_eights(self) -> None:
        base, penalty, final = score.composite(_axes())
        self.assertAlmostEqual(base, 8.0, places=4)
        self.assertAlmostEqual(penalty, 1.0, places=4)
        self.assertAlmostEqual(final, 8.0, places=4)

    def test_low_hook_halves_score(self) -> None:
        base, penalty, final = score.composite(_axes(hook=3.0))
        self.assertAlmostEqual(base, 6.5, places=4)
        self.assertAlmostEqual(penalty, 0.5, places=4)
        self.assertAlmostEqual(final, 3.25, places=4)

    def test_low_self_contained_penalty_stacks(self) -> None:
        _, penalty, _ = score.composite(_axes(hook=3.0, self_contained=2.0))
        self.assertAlmostEqual(penalty, 0.5 * 0.7, places=4)

    def test_high_hook_not_penalised(self) -> None:
        _, penalty, _ = score.composite(_axes(hook=9.0))
        self.assertAlmostEqual(penalty, 1.0, places=4)

    def test_average_hides_fatal_axis(self) -> None:
        """Rata-rata 6.5 tapi hook 2 — harus kalah dari klip rata."""
        _, _, bad_hook = score.composite(_axes(hook=2.0, payoff=10.0, self_contained=10.0,
                                               emotional=10.0, concrete=10.0, loop=10.0))
        _, _, balanced = score.composite(_axes())
        self.assertLess(bad_hook, balanced)


class ScoreRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wd = make_work(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_writes_scored_json(self) -> None:
        payload = jsonio.read_json(self.wd / "scored.json")
        self.assertIn("scored", payload)
        self.assertGreater(len(payload["scored"]), 0)

    def test_sorted_descending(self) -> None:
        scored = jsonio.read_json(self.wd / "scored.json")["scored"]
        finals = [s["final"] for s in scored]
        self.assertEqual(finals, sorted(finals, reverse=True))

    def test_rank_sequential(self) -> None:
        scored = jsonio.read_json(self.wd / "scored.json")["scored"]
        self.assertEqual([s["rank"] for s in scored], list(range(1, len(scored) + 1)))

    def test_final_within_range(self) -> None:
        for s in jsonio.read_json(self.wd / "scored.json")["scored"]:
            self.assertGreaterEqual(s["final"], 0.0)
            self.assertLessEqual(s["final"], 100.0)

    def test_percentile_within_range(self) -> None:
        for s in jsonio.read_json(self.wd / "scored.json")["scored"]:
            self.assertGreaterEqual(s["percentile"], 0.0)
            self.assertLessEqual(s["percentile"], 100.0)

    def test_invalid_selection_raises(self) -> None:
        bad = jsonio.read_json(self.wd / "selection.json")
        bad["candidates"][0]["axes"]["hook"]["evidence"] = ""
        jsonio.write_json(self.wd / "selection.json", bad)
        with self.assertRaises(ValueError):
            score.score(self.wd)

    def test_report_disclaims_prediction(self) -> None:
        text = (self.wd / "report.md").read_text(encoding="utf-8")
        self.assertIn("persentil", text)
        self.assertIn("bukan prediksi viral", text.lower())

    def test_json_serialisable(self) -> None:
        json.dumps(jsonio.read_json(self.wd / "scored.json"))


if __name__ == "__main__":
    unittest.main()
