"""Tes chunking dan merge timestamp.

Inti yang diuji: tidak ada kata yang hilang di boundary, tidak ada yang dobel,
dan offset chunk tidak menimbulkan drift.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401

from scripts.lib import audio as A
from scripts.lib import chunk as C


class PlanTest(unittest.TestCase):
    def test_short_audio_single_chunk(self) -> None:
        chunks = C.plan(300.0, target=600.0)
        self.assertEqual(len(chunks), 1)
        self.assertAlmostEqual(chunks[0].start, 0.0)
        self.assertAlmostEqual(chunks[0].end, 300.0)

    def test_exactly_target_single_chunk(self) -> None:
        self.assertEqual(len(C.plan(600.0, target=600.0)), 1)

    def test_long_audio_splits(self) -> None:
        chunks = C.plan(1800.0, target=600.0)
        self.assertGreaterEqual(len(chunks), 3)

    def test_chunks_cover_whole_duration(self) -> None:
        chunks = C.plan(1800.0, target=600.0)
        self.assertAlmostEqual(chunks[0].start, 0.0)
        self.assertAlmostEqual(chunks[-1].end, 1800.0)
        for a, b in zip(chunks, chunks[1:]):
            self.assertLessEqual(b.start, a.end, "chunk berikutnya harus mulai sebelum yang sebelumnya berakhir")

    def test_overlap_respected(self) -> None:
        chunks = C.plan(1800.0, target=600.0, overlap=5.0)
        for a, b in zip(chunks, chunks[1:]):
            self.assertAlmostEqual(a.end - b.start, 5.0, places=2)

    def test_monotonic_and_positive(self) -> None:
        prev_start, prev_end = -1.0, -1.0
        for ch in C.plan(5000.0, target=600.0):
            self.assertGreater(ch.start, prev_start)
            self.assertGreater(ch.end, prev_end)
            prev_start, prev_end = ch.start, ch.end

    def test_snaps_to_silence(self) -> None:
        # target 600, ada jeda di 604-608 (mid 606) → harus menempel ke 606
        chunks = C.plan(1800.0, target=600.0, overlap=5.0, silences=[(604.0, 608.0)])
        self.assertAlmostEqual(chunks[0].end, 606.0, places=2)

    def test_ignores_far_silence(self) -> None:
        chunks = C.plan(1800.0, target=600.0, silences=[(200.0, 204.0)])
        self.assertAlmostEqual(chunks[0].end, 600.0, places=2)

    def test_zero_duration(self) -> None:
        chunks = C.plan(0.0)
        self.assertEqual(len(chunks), 1)

    def test_invalid_target(self) -> None:
        with self.assertRaises(ValueError):
            C.plan(100.0, target=0.0)


class CutsTest(unittest.TestCase):
    def test_cut_is_midpoint_of_overlap(self) -> None:
        chunks = [C.Chunk(0, 0.0, 600.0), C.Chunk(1, 595.0, 1200.0)]
        self.assertAlmostEqual(C.cuts(chunks)[0], 597.5, places=3)

    def test_single_chunk_no_cuts(self) -> None:
        self.assertEqual(C.cuts([C.Chunk(0, 0.0, 100.0)]), [])


def _w(text: str, start: float, end: float) -> dict:
    return {"w": text, "start": start, "end": end, "speaker": None, "conf": None}


class MergeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [C.Chunk(0, 0.0, 600.0), C.Chunk(1, 595.0, 1200.0)]
        self.cut = 597.5  # (595 + 600) / 2

    def test_offsets_applied(self) -> None:
        merged = C.merge([[_w("a", 10.0, 10.5)], [_w("b", 10.0, 10.5)]], self.chunks)
        self.assertAlmostEqual(merged[0]["start"], 10.0, places=2)
        self.assertAlmostEqual(merged[1]["start"], 605.0, places=2)

    def test_no_duplicate_at_boundary(self) -> None:
        # kata yang sama muncul di kedua chunk karena overlap
        left = [_w("boundary", 597.0, 598.0)]          # global 597.0-598.0, mid 597.5
        right = [_w("boundary", 2.0, 3.0)]             # global 597.0-598.0, mid 597.5
        merged = C.merge([left, right], self.chunks)
        self.assertEqual(len(merged), 1, msg=f"dapat {merged}")

    def test_word_just_before_cut_from_left(self) -> None:
        left = [_w("kiri", 596.0, 597.0)]   # mid 596.5 < 597.5
        right: list[dict] = []
        merged = C.merge([left, right], self.chunks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["w"], "kiri")

    def test_word_just_after_cut_from_right(self) -> None:
        left: list[dict] = []
        right = [_w("kanan", 3.0, 4.0)]     # global 598-599, mid 598.5 > 597.5
        merged = C.merge([left, right], self.chunks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["w"], "kanan")

    def test_no_word_lost(self) -> None:
        left = [_w(f"L{i}", float(i), float(i) + 0.4) for i in range(0, 600)]
        right = [_w(f"R{i}", float(i), float(i) + 0.4) for i in range(0, 605)]
        merged = C.merge([left, right], self.chunks)
        texts = {w["w"] for w in merged}
        self.assertIn("L0", texts)
        self.assertIn("R604", texts)

    def test_monotonic_output(self) -> None:
        left = [_w("a", 590.0, 591.0), _w("b", 592.0, 593.0)]
        right = [_w("c", 0.0, 1.0), _w("d", 2.0, 3.0)]
        merged = C.merge([left, right], self.chunks)
        starts = [w["start"] for w in merged]
        self.assertEqual(starts, sorted(starts))

    def test_no_overlapping_times(self) -> None:
        left = [_w("a", 10.0, 12.0), _w("b", 11.0, 13.0)]
        right: list[dict] = []
        merged = C.merge([left, right], self.chunks)
        for a, b in zip(merged, merged[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-6)

    def test_indices_renumbered(self) -> None:
        merged = C.merge(
            [[_w("a", 1.0, 1.5), _w("b", 2.0, 2.5)], [_w("c", 1.0, 1.5)]],
            self.chunks,
        )
        self.assertEqual([w["i"] for w in merged], list(range(len(merged))))

    def test_mismatched_lengths_raise(self) -> None:
        with self.assertRaises(ValueError):
            C.merge([[]], self.chunks)

    def test_zero_duration_word_fixed(self) -> None:
        merged = C.merge([[_w("x", 5.0, 5.0)], []], self.chunks)
        self.assertGreater(merged[0]["end"], merged[0]["start"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg tidak tersedia")
class SilenceDetectTest(unittest.TestCase):
    def test_detects_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "gap.wav"
            # 1s tone, 1.5s senyap, 1s tone
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1.5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
                    "-map", "[out]", "-ar", "16000", "-ac", "1", str(wav),
                ],
                check=True,
                capture_output=True,
            )
            found = A.detect_silences(str(wav), noise_db=-40.0, min_dur=0.3)
            self.assertTrue(found, msg="tidak ada silence terdeteksi")
            start, end = found[0]
            self.assertLess(abs(start - 1.0), 0.25, msg=f"start {start}")
            self.assertGreater(end - start, 1.0)


if __name__ == "__main__":
    unittest.main()
