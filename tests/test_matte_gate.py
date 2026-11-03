"""Tes vonis gate matte (Langkah 1b).

Ambang ditetapkan SEBELUM mengukur (docs/MOTION-TIER2-PLAN.md, Langkah 1b).
Dua hal yang dijaga di sini:
  1. kualitas dan kecepatan dinilai terpisah;
  2. di luar mesin target, `GO` tidak pernah keluar.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks import matte_gate as g


def run(**kw) -> dict:
    base = {
        "id": "pphumanseg@x",
        "model_kind": "pphumanseg",
        "fps_e2e": 9.0,
        "rss_mb": 600.0,
        "face_in_matte": 0.98,
        "flicker_p50": 0.3,
        "flicker_p95": 1.0,
        "area_ok_ratio": 1.0,
        "human_ok": True,
    }
    base.update(kw)
    return base


class SpeedTest(unittest.TestCase):
    def test_bands(self) -> None:
        self.assertEqual(g.speed(run(fps_e2e=2.0)), "NO_GO")
        self.assertEqual(g.speed(run(fps_e2e=5.0)), "GO_SPARSE")
        self.assertEqual(g.speed(run(fps_e2e=9.0)), "GO")

    def test_thresholds_are_inclusive(self) -> None:
        self.assertEqual(g.speed(run(fps_e2e=g.FPS_GO)), "GO")
        self.assertEqual(g.speed(run(fps_e2e=g.FPS_SPARSE_MIN)), "GO_SPARSE")

    def test_rss_over_budget_is_no_go(self) -> None:
        self.assertEqual(g.speed(run(rss_mb=g.RSS_MAX_MB + 1)), "NO_GO")
        self.assertEqual(g.speed(run(rss_mb=g.RSS_MAX_MB)), "GO")

    def test_empty_result_is_no_go(self) -> None:
        self.assertEqual(g.speed({}), "NO_GO")


class QualityTest(unittest.TestCase):
    def test_good_run_is_ok(self) -> None:
        self.assertEqual(g.quality(run()), "OK")

    def test_each_automated_check_can_fail_alone(self) -> None:
        for key, bad in [
            ("face_in_matte", 0.94),
            ("face_in_matte", None),
            ("flicker_p50", 0.6),
            ("flicker_p95", 1.6),
            ("flicker_p50", None),
            ("area_ok_ratio", 0.9),
        ]:
            with self.subTest(key=key, bad=bad):
                self.assertEqual(g.quality(run(**{key: bad})), "FAIL")

    def test_boundaries_pass(self) -> None:
        r = run(
            face_in_matte=g.FACE_MIN,
            flicker_p50=g.FLICKER_P50_MAX,
            flicker_p95=g.FLICKER_P95_MAX,
            area_ok_ratio=g.AREA_OK_MIN,
        )
        self.assertEqual(g.quality(r), "OK")

    def test_human_review_is_required(self) -> None:
        self.assertEqual(g.quality(run(human_ok=None)), "PENDING")
        self.assertEqual(g.quality(run(human_ok=False)), "FAIL")

    def test_automated_failure_wins_over_pending(self) -> None:
        self.assertEqual(g.quality(run(face_in_matte=0.5, human_ok=None)), "FAIL")

    def test_empty_result_fails(self) -> None:
        self.assertEqual(g.quality({}), "FAIL")


class VerdictTest(unittest.TestCase):
    def test_good_on_target_is_go(self) -> None:
        self.assertEqual(g.verdict(run(), on_target=True), "GO")

    def test_sparse_speed_gives_go_sparse(self) -> None:
        self.assertEqual(g.verdict(run(fps_e2e=5.0), on_target=True), "GO_SPARSE")

    def test_pending_human_blocks_go(self) -> None:
        self.assertEqual(g.verdict(run(human_ok=None), on_target=True), "PENDING")

    def test_fast_but_ugly_is_no_go(self) -> None:
        self.assertEqual(g.verdict(run(fps_e2e=30.0, face_in_matte=0.7), on_target=True), "NO_GO")

    def test_clean_but_slow_is_no_go(self) -> None:
        self.assertEqual(g.verdict(run(fps_e2e=1.0), on_target=True), "NO_GO")

    def test_off_target_never_says_go(self) -> None:
        for fps in (1.0, 5.0, 9.0, 60.0):
            with self.subTest(fps=fps):
                self.assertNotIn(g.verdict(run(fps_e2e=fps), on_target=False), ("GO", "GO_SPARSE"))
        self.assertEqual(g.verdict(run(), on_target=False), "OFF_TARGET")

    def test_off_target_still_rejects_bad_quality(self) -> None:
        # kualitas tidak bergantung CPU, jadi di Mac pun bisa dipakai menyaring model jelek
        self.assertEqual(g.verdict(run(face_in_matte=0.5), on_target=False), "NO_GO")
        self.assertEqual(g.verdict(run(human_ok=False), on_target=False), "NO_GO")


class AggregateTest(unittest.TestCase):
    def test_model_verdict_is_worst_run(self) -> None:
        runs = [run(), run(fps_e2e=5.0), run(fps_e2e=9.5)]
        self.assertEqual(g.model_verdict(runs, on_target=True), "GO_SPARSE")
        runs.append(run(face_in_matte=0.5))
        self.assertEqual(g.model_verdict(runs, on_target=True), "NO_GO")

    def test_empty_is_no_go(self) -> None:
        self.assertEqual(g.model_verdict([], on_target=True), "NO_GO")
        self.assertEqual(g.overall([], on_target=True), "NO_GO")

    def test_overall_is_best_model_not_worst(self) -> None:
        runs = [
            run(model_kind="pphumanseg", face_in_matte=0.6),
            run(model_kind="modnet", fps_e2e=5.0),
        ]
        by = g.by_model(runs)
        self.assertEqual(set(by), {"pphumanseg", "modnet"})
        self.assertEqual(g.overall(runs, on_target=True), "GO_SPARSE")

    def test_is_target(self) -> None:
        self.assertTrue(g.is_target({"cpu": "Intel(R) Core(TM) i5-7300U CPU @ 2.60GHz"}))
        self.assertFalse(g.is_target({"cpu": "Apple M3"}))
        self.assertFalse(g.is_target({}))


class ReviewsTest(unittest.TestCase):
    """Satu preview ditonton sekali; keputusannya berlaku untuk semua run dengan id sama."""

    def test_review_fills_every_run_with_that_id(self) -> None:
        runs = [run(id="a", human_ok=None), run(id="a", human_ok=None), run(id="b", human_ok=None)]
        out = g.apply_reviews(runs, {"a": True})
        self.assertEqual([r["human_ok"] for r in out], [True, True, None])

    def test_review_can_reject(self) -> None:
        out = g.apply_reviews([run(id="a", human_ok=None)], {"a": False})
        self.assertEqual(g.quality(out[0]), "FAIL")

    def test_does_not_override_explicit_decision_or_mutate_input(self) -> None:
        runs = [run(id="a", human_ok=False)]
        out = g.apply_reviews(runs, {"a": True})
        self.assertIs(out[0]["human_ok"], False)
        src = [run(id="a", human_ok=None)]
        g.apply_reviews(src, {"a": True})
        self.assertIsNone(src[0]["human_ok"])

    def test_cli_reads_reviews_block(self) -> None:
        payload = {
            "meta": {"cpu": "i5-7300U"},
            "reviews": {"pphumanseg@x": True},
            "runs": [run(id="pphumanseg@x", human_ok=None)],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.json"
            path.write_text(json.dumps(payload))
            out = subprocess.run(
                [sys.executable, "-m", "benchmarks.matte_gate", str(path)],
                capture_output=True,
                text=True,
            )
        self.assertIn("VONIS: GO", out.stdout)


class ExplainTest(unittest.TestCase):
    def test_lists_failed_checks_by_name(self) -> None:
        why = g.failures(run(face_in_matte=0.5, fps_e2e=1.0, flicker_p95=9.0))
        joined = " ".join(why)
        for name in ("face_in_matte", "fps_e2e", "flicker_p95"):
            self.assertIn(name, joined)

    def test_edge_shift_is_diagnostic_only(self) -> None:
        # total pergeseran tepi mencampur gerak asli dengan jitter; tidak boleh menggugurkan run
        self.assertEqual(g.quality(run(edge_shift_p50=40.0, edge_shift_p95=90.0)), "OK")

    def test_constants_are_the_locked_ones(self) -> None:
        # dikunci sebelum flicker pernah dihitung pada data nyata (docs/MOTION-TIER2-PLAN.md)
        self.assertEqual((g.FLICKER_P50_MAX, g.FLICKER_P95_MAX), (0.5, 1.5))
        self.assertEqual((g.FACE_MIN, g.AREA_OK_MIN), (0.95, 0.95))
        self.assertEqual((g.FPS_GO, g.FPS_SPARSE_MIN, g.RSS_MAX_MB), (7.5, 2.5, 1024.0))

    def test_good_run_has_no_failures(self) -> None:
        self.assertEqual(g.failures(run()), [])


class LagGateTest(unittest.TestCase):
    """Putaran 2: `lag` (biaya penghalusan) dinilai bila ada, dan WAJIB ada bila
    `smooth_w < 0,6` (tanpa metrik = gagal). Ambang dikunci sebelum ada angka."""

    def test_lag_thresholds_are_the_locked_ones(self) -> None:
        self.assertEqual((g.LAG_P50_MAX, g.LAG_P95_MAX), (1.0, 2.5))

    def test_old_constants_did_not_move(self) -> None:
        self.assertEqual((g.FLICKER_P50_MAX, g.FLICKER_P95_MAX), (0.5, 1.5))
        self.assertEqual((g.FACE_MIN, g.AREA_OK_MIN), (0.95, 0.95))

    def test_lag_boundaries_are_inclusive(self) -> None:
        r = run(lag_p50=g.LAG_P50_MAX, lag_p95=g.LAG_P95_MAX, smooth_w=0.3)
        self.assertEqual(g.quality(r), "OK")
        self.assertEqual(g.failures(r), [])

    def test_lag_above_threshold_fails(self) -> None:
        for key, bad in [
            ("lag_p50", g.LAG_P50_MAX + 0.1),
            ("lag_p95", g.LAG_P95_MAX + 0.1),
        ]:
            with self.subTest(key=key):
                base = {"lag_p50": 0.5, "lag_p95": 1.0, "smooth_w": 0.3}
                base[key] = bad
                r = run(**base)
                self.assertEqual(g.quality(r), "FAIL")
                self.assertIn(key, " ".join(g.failures(r)))

    def test_absent_lag_is_not_judged_at_weight_06(self) -> None:
        self.assertEqual(g.quality(run(smooth_w=0.6)), "OK")
        self.assertEqual(g.failures(run(smooth_w=0.6)), [])

    def test_absent_lag_fails_at_weight_03(self) -> None:
        r = run(smooth_w=0.3)
        self.assertEqual(g.quality(r), "FAIL")
        self.assertIn("lag", " ".join(g.failures(r)))

    def test_absent_lag_and_absent_weight_is_not_judged(self) -> None:
        # kompatibel dengan benchmarks/matte.json lama yang tidak punya lag/smooth_w
        self.assertEqual(g.quality(run()), "OK")
        self.assertEqual(g.failures(run()), [])

    def test_lag_is_not_a_required_key(self) -> None:
        self.assertNotIn("lag_p50", g.REQUIRED_KEYS)
        self.assertNotIn("lag_p95", g.REQUIRED_KEYS)

    def test_cli_old_file_without_lag_is_fine(self) -> None:
        payload = {"meta": {"cpu": "i5-7300U"}, "runs": [run(), run(smooth_w=0.6)]}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.json"
            path.write_text(json.dumps(payload))
            out = subprocess.run(
                [sys.executable, "-m", "benchmarks.matte_gate", str(path)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(out.returncode, 0)
        self.assertIn("VONIS: GO", out.stdout)
        self.assertIn("lag50", out.stdout)

    def test_cli_prints_lag_columns(self) -> None:
        payload = {
            "meta": {"cpu": "i5-7300U"},
            "runs": [run(lag_p50=0.4, lag_p95=1.2, smooth_w=0.3)],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.json"
            path.write_text(json.dumps(payload))
            out = subprocess.run(
                [sys.executable, "-m", "benchmarks.matte_gate", str(path)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(out.returncode, 0)
        self.assertIn("lag50", out.stdout)
        self.assertIn("lag95", out.stdout)
        self.assertIn("0.40", out.stdout)
        self.assertIn("1.20", out.stdout)


class CliTest(unittest.TestCase):
    def _run(self, payload: dict) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.json"
            path.write_text(json.dumps(payload))
            return subprocess.run(
                [sys.executable, "-m", "benchmarks.matte_gate", str(path)],
                capture_output=True,
                text=True,
            )

    def test_off_target_is_labelled(self) -> None:
        out = self._run({"meta": {"cpu": "Apple M3"}, "runs": [run()]})
        self.assertEqual(out.returncode, 0)
        self.assertIn("BUKAN MESIN TARGET", out.stdout)

    def test_exit_zero_even_when_no_go(self) -> None:
        out = self._run(
            {"meta": {"cpu": "i5-7300U"}, "runs": [run(face_in_matte=0.1)]}
        )
        self.assertEqual(out.returncode, 0, "NO_GO bukan kegagalan perintah")
        self.assertIn("NO_GO", out.stdout)

    def test_usage_without_args(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m", "benchmarks.matte_gate"], capture_output=True, text=True
        )
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
