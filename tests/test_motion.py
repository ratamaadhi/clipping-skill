"""Tes motion graphics tier-1: jadwal punch, ekspresi zoom, SFX, overlay."""

from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401

from scripts import motion


class PunchScheduleTest(unittest.TestCase):
    def test_short_clip_single_entry(self) -> None:
        sched = motion.punch_schedule([], 2.0)
        self.assertEqual(len(sched), 1)
        self.assertEqual(sched[0]["t"], 0.0)

    def test_starts_at_zero_wide(self) -> None:
        sched = motion.punch_schedule([3, 6, 9, 12, 15, 18, 21, 24], 30.0)
        self.assertEqual(sched[0]["t"], 0.0)
        self.assertEqual(sched[0]["scale"], motion.PUNCH_SCALES[0])

    def test_produces_multiple_punches(self) -> None:
        sched = motion.punch_schedule([3, 6, 9, 12, 15, 18, 21, 24], 30.0)
        self.assertGreaterEqual(len(sched), 4)

    def test_gap_within_bounds(self) -> None:
        sched = motion.punch_schedule([3, 6, 9, 12, 15, 18, 21, 24], 30.0)
        times = [p["t"] for p in sched]
        for a, b in zip(times, times[1:]):
            gap = b - a
            self.assertGreaterEqual(gap, motion.MIN_PUNCH_GAP - 1e-6, msg=f"gap {gap}")
            self.assertLessEqual(gap, motion.MAX_PUNCH_GAP + 1e-6, msg=f"gap {gap}")

    def test_respects_atom_boundaries(self) -> None:
        sched = motion.punch_schedule([4.0, 8.0, 12.0, 16.0], 20.0)
        times = {p["t"] for p in sched}
        self.assertIn(4.0, times)
        self.assertIn(8.0, times)

    def test_scales_alternate(self) -> None:
        sched = motion.punch_schedule([3, 6, 9, 12, 15, 18, 21, 24], 30.0)
        scales = [p["scale"] for p in sched]
        self.assertNotEqual(scales[0], scales[1])
        self.assertTrue(all(s >= 1.0 for s in scales))

    def test_no_punch_too_close_to_end(self) -> None:
        sched = motion.punch_schedule([19.8], 20.0)
        for p in sched[1:]:
            self.assertLess(p["t"], 20.0 - 0.3)

    def test_zero_duration(self) -> None:
        self.assertEqual(len(motion.punch_schedule([], 0.0)), 1)


class ZoomExpressionTest(unittest.TestCase):
    def test_single_returns_one(self) -> None:
        self.assertEqual(motion.zoom_expression([{"t": 0, "scale": 1.0}], 30), "1.0")

    def test_nested_if_built(self) -> None:
        sched = [{"t": 0.0, "scale": 1.0}, {"t": 3.0, "scale": 1.2}]
        expr = motion.zoom_expression(sched, 30)
        self.assertIn("if(lt(in,90)", expr)
        self.assertIn("1.0000", expr)
        self.assertIn("1.2000", expr)

    def test_three_steps(self) -> None:
        sched = [
            {"t": 0.0, "scale": 1.0},
            {"t": 2.0, "scale": 1.2},
            {"t": 4.0, "scale": 1.0},
        ]
        expr = motion.zoom_expression(sched, 30)
        self.assertEqual(expr.count("if("), 2)

    def test_filter_none_for_single(self) -> None:
        self.assertIsNone(motion.zoompan_filter([{"t": 0, "scale": 1.0}], 30, 1080, 1920))

    def test_filter_contains_size(self) -> None:
        sched = [{"t": 0.0, "scale": 1.0}, {"t": 3.0, "scale": 1.2}]
        f = motion.zoompan_filter(sched, 30, 1080, 1920)
        self.assertIsNotNone(f)
        assert f is not None
        self.assertIn("s=1080x1920", f)
        self.assertIn("zoompan", f)


class ProgressFilterTest(unittest.TestCase):
    def test_track_is_static_full_width(self) -> None:
        f = motion.progress_track_filter()
        self.assertIn("drawbox", f)
        self.assertIn("w=iw", f)
        self.assertNotIn("t/", f, msg="track tidak boleh bergantung waktu")

    def test_fill_source_has_duration(self) -> None:
        f = motion.progress_fill_source(41.2, 30, 1080)
        self.assertIn("color=c=", f)
        self.assertIn("s=1080x8", f)
        self.assertIn("d=41.200", f)
        self.assertIn("[bar]", f)

    def test_fill_overlay_moves_with_time(self) -> None:
        f = motion.progress_fill_overlay(41.2)
        self.assertIn("overlay", f)
        self.assertIn("x='-w+w*t/41.200'", f)
        self.assertIn("shortest=1", f)

    def test_empty_for_zero(self) -> None:
        self.assertEqual(motion.progress_fill_source(0.0, 30, 1080), "")
        self.assertEqual(motion.progress_fill_overlay(0.0), "")


class SfxTest(unittest.TestCase):
    def test_writes_valid_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = motion.write_sfx_wav(
                Path(tmp) / "s.wav", [{"t": 1.0, "kind": "hit"}], 3.0
            )
            self.assertIsNotNone(path)
            with wave.open(str(path), "rb") as fh:
                self.assertEqual(fh.getnchannels(), 1)
                self.assertEqual(fh.getsampwidth(), 2)
                self.assertEqual(fh.getframerate(), motion.SFX_RATE)
                frames = fh.getnframes()
            self.assertAlmostEqual(frames / motion.SFX_RATE, 3.0, delta=0.05)

    def test_silent_when_no_events(self) -> None:
        self.assertIsNone(motion.write_sfx_wav("/tmp/x.wav", [], 3.0))

    def test_multiple_events_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = [{"t": t, "kind": "hit" if i % 2 else "whoosh"} for i, t in enumerate([0.5, 1.5, 2.5])]
            path = motion.write_sfx_wav(Path(tmp) / "m.wav", events, 3.0)
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 1000)

    def test_no_clipping(self) -> None:
        """Banyak event bertumpuk tidak boleh melewati full-scale."""
        with tempfile.TemporaryDirectory() as tmp:
            events = [{"t": 1.0, "kind": "hit"} for _ in range(20)]
            path = motion.write_sfx_wav(Path(tmp) / "c.wav", events, 2.0)
            with wave.open(str(path), "rb") as fh:
                raw = fh.readframes(fh.getnframes())
            peak = max(abs(int.from_bytes(raw[i : i + 2], "little", signed=True)) for i in range(0, len(raw), 2))
            self.assertLessEqual(peak, 32767)


class DetectVsTest(unittest.TestCase):
    def test_finds_atau(self) -> None:
        self.assertEqual(motion.detect_vs("Codex atau Claude? Mana yang lebih oke"), ("Codex", "Claude"))

    def test_finds_vs(self) -> None:
        self.assertEqual(motion.detect_vs("Codex vs Claude"), ("Codex", "Claude"))

    def test_finds_dibanding(self) -> None:
        self.assertEqual(motion.detect_vs("Codex dibanding Claude"), ("Codex", "Claude"))

    def test_ignores_same_word(self) -> None:
        self.assertIsNone(motion.detect_vs("Claude atau Claude"))

    def test_ignores_lowercase(self) -> None:
        self.assertIsNone(motion.detect_vs("ini atau itu"))

    def test_ignores_stopwords(self) -> None:
        self.assertIsNone(motion.detect_vs("Jika Anda atau Mereka"))

    def test_ignores_verbs(self) -> None:
        """Kasus nyata: 'Membatasi atau Memblokir' bukan perbandingan entitas."""
        self.assertIsNone(motion.detect_vs("Meskipun Membatasi atau Memblokir seseorang"))

    def test_none_when_absent(self) -> None:
        self.assertIsNone(motion.detect_vs("tidak ada perbandingan di sini"))


class OverlayFilterTest(unittest.TestCase):
    def test_vs_overlay_produces_filters(self) -> None:
        filters = motion.overlay_filters(
            [{"type": "vs", "start": 0.5, "end": 3.5, "left": "Codex", "right": "Claude"}]
        )
        if not motion._font_path():
            self.skipTest("font tidak tersedia")
        joined = " ".join(filters)
        self.assertIn("Codex", joined)
        self.assertIn("Claude", joined)
        self.assertIn("between(t,0.50,3.50)", joined)

    def test_unknown_type_ignored(self) -> None:
        self.assertEqual(motion.overlay_filters([{"type": "unknown"}]), [])

    def test_expressions_are_quoted(self) -> None:
        """Ekspresi x yang mengandung koma WAJIB dikutip, kalau tidak filtergraph pecah."""
        filters = motion.overlay_filters(
            [{"type": "vs", "start": 0.5, "end": 3.5, "left": "A", "right": "B"}]
        )
        if not filters:
            self.skipTest("font tidak tersedia")
        checked = 0
        for f in filters:
            if "if(" in f:
                self.assertIn("x='if(", f, msg=f"tidak dikutip: {f[:90]}")
                checked += 1
        self.assertGreaterEqual(checked, 4, msg="ekspresi slide-in tidak ditemukan")

    def test_empty_labels_ignored(self) -> None:
        self.assertEqual(
            motion.overlay_filters([{"type": "vs", "left": "", "right": "X"}]), []
        )

    def test_safe_text_strips_dangerous_chars(self) -> None:
        self.assertEqual(motion._safe_text("a:b,c'd"), "abcd")
        self.assertEqual(motion._safe_text(""), "?")


if __name__ == "__main__":
    unittest.main()
