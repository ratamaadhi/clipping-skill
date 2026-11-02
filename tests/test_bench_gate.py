"""Tes vonis gate Remotion.

Gate ditetapkan SEBELUM mengukur. Kalau ambang ditentukan setelah melihat angka,
hasilnya selalu "lolos".
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks import gate


def result(rss=700.0, fps=4.0, swap=0, alpha=True) -> dict:
    return {"rss_mb": rss, "fps": fps, "swap_pages": swap, "alpha_ok": alpha}


class VerdictTest(unittest.TestCase):
    def test_rss_over_budget_is_no_go(self) -> None:
        self.assertEqual(gate.verdict(result(rss=1200.0)), "NO_GO")

    def test_good_numbers_are_go(self) -> None:
        self.assertEqual(gate.verdict(result(rss=800.0, fps=3.1, swap=1000)), "GO")

    def test_middling_fps_is_sparse_only(self) -> None:
        self.assertEqual(gate.verdict(result(fps=2.0)), "GO_SPARSE")

    def test_slow_is_no_go(self) -> None:
        self.assertEqual(gate.verdict(result(fps=1.0)), "NO_GO")

    def test_alpha_failure_is_no_go(self) -> None:
        self.assertEqual(gate.verdict(result(alpha=False)), "NO_GO")

    def test_heavy_swap_is_no_go(self) -> None:
        self.assertEqual(gate.verdict(result(swap=50000)), "NO_GO")

    def test_rss_at_budget_passes(self) -> None:
        self.assertEqual(gate.verdict(result(rss=gate.RSS_MAX_MB)), "GO")

    def test_fps_at_go_threshold_passes(self) -> None:
        self.assertEqual(gate.verdict(result(fps=gate.FPS_GO)), "GO")

    def test_verdict_ignores_missing_keys_gracefully(self) -> None:
        self.assertEqual(gate.verdict({}), "NO_GO")


class CliTest(unittest.TestCase):
    def test_prints_verdict_for_file(self) -> None:
        payload = {
            "runs": [
                {"width": 1080, "height": 1920, "concurrency": 1, **result(fps=3.2)},
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.json"
            path.write_text(json.dumps(payload))
            out = subprocess.run(
                [sys.executable, "-m", "benchmarks.gate", str(path)],
                capture_output=True,
                text=True,
                check=True,
            )
        self.assertIn("GO", out.stdout)

    def test_exit_code_zero_even_when_no_go(self) -> None:
        payload = {"runs": [{"width": 1080, "height": 1920, "concurrency": 1, **result(fps=0.5)}]}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.json"
            path.write_text(json.dumps(payload))
            out = subprocess.run(
                [sys.executable, "-m", "benchmarks.gate", str(path)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(out.returncode, 0, "NO_GO bukan kegagalan perintah")
        self.assertIn("NO_GO", out.stdout)


if __name__ == "__main__":
    unittest.main()
