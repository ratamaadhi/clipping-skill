"""Timing per kata untuk caption tier-2 (`--motion 2`).

`words` adalah satu-satunya sumber waktu kinetic; ia harus berada di timeline
OUTPUT dan tidak boleh mengubah apa pun pada `captions[]` tier-1.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import make_work

from scripts import candidates as cand_mod
from scripts import demo as demo_mod
from scripts import edl as edl_mod
from scripts import features as feat_mod
from scripts import score as score_mod
from scripts import segment
from scripts.lib import jsonio


def _caption_word_sources(
    clip: dict[str, Any], transcript_words: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    """Kembalikan kata sumber untuk tiap caption, berurutan sesuai teks caption.

    Caption dibentuk dari `group_words`, jadi teksnya adalah join kata sumber
    yang bersebelahan. Pencocokan sekuensial ini memastikan asumsi itu.
    """
    segs = clip["segments"]
    lo = min(float(s["src_start"]) for s in segs)
    hi = max(float(s["src_end"]) for s in segs)
    in_range = [
        w for w in transcript_words if lo - 1e-6 <= float(w["start"]) <= hi + 1e-6
    ]
    out: list[list[dict[str, Any]]] = []
    idx = 0
    for cap in clip["captions"]:
        n = len(str(cap["text"]).split())
        chunk = in_range[idx : idx + n]
        joined = " ".join(str(w["w"]).strip() for w in chunk)
        if joined != cap["text"]:
            raise AssertionError(
                f"{clip['id']}: caption {cap['text']!r} != kata sumber {joined!r}"
            )
        out.append(chunk)
        idx += n
    return out


class Tier2WordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = make_work(Path(cls._tmp.name), top_n=10, top=3)
        cls.tier1 = jsonio.read_json(cls.wd / "edl.json")
        cls.tier2 = edl_mod.build(cls.wd, top_n=3, motion_tier=2)
        cls.transcript = jsonio.read_json(cls.wd / "transcript.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_every_caption_has_words(self) -> None:
        for clip in self.tier2["clips"]:
            for cap in clip["captions"]:
                self.assertIn("words", cap, msg=f"{clip['id']} {cap['text']!r}")
                self.assertTrue(cap["words"], msg=f"{clip['id']} {cap['text']!r}")

    def test_word_shape_and_rounding(self) -> None:
        for clip in self.tier2["clips"]:
            for cap in clip["captions"]:
                for w in cap["words"]:
                    self.assertEqual(sorted(w), ["end", "start", "w"])
                    self.assertIsInstance(w["w"], str)
                    self.assertTrue(w["w"].strip())
                    for key in ("start", "end"):
                        self.assertIsInstance(w[key], float, msg=f"{clip['id']} {w}")
                        self.assertEqual(round(w[key], 3), w[key], msg=f"{clip['id']} {w}")

    def test_words_are_monotonic_and_non_negative_duration(self) -> None:
        for clip in self.tier2["clips"]:
            starts: list[float] = []
            for cap in clip["captions"]:
                for w in cap["words"]:
                    self.assertGreaterEqual(w["start"], -0.001, msg=f"{clip['id']} {w}")
                    self.assertGreaterEqual(w["end"], w["start"], msg=f"{clip['id']} {w}")
                    starts.append(w["start"])
            self.assertEqual(starts, sorted(starts), msg=clip["id"])

    def test_word_starts_match_map_time_of_source(self) -> None:
        for clip in self.tier2["clips"]:
            sources = _caption_word_sources(clip, self.transcript["words"])
            for cap, srcs in zip(clip["captions"], sources):
                self.assertEqual(len(cap["words"]), len(srcs), msg=f"{clip['id']} {cap['text']!r}")
                for w, src in zip(cap["words"], srcs):
                    expected = edl_mod.map_time(clip["segments"], float(src["start"]))
                    self.assertIsNotNone(expected, msg=f"{clip['id']} {src}")
                    assert expected is not None
                    self.assertLessEqual(
                        abs(w["start"] - expected), 0.001,
                        msg=f"{clip['id']} {w['w']!r}: {w['start']} vs {expected}",
                    )

    def test_first_word_does_not_start_before_caption(self) -> None:
        for clip in self.tier2["clips"]:
            for cap in clip["captions"]:
                self.assertGreaterEqual(
                    cap["words"][0]["start"], cap["start"] - 0.001,
                    msg=f"{clip['id']} {cap['text']!r}",
                )

    def test_last_word_starts_before_next_caption(self) -> None:
        """Kata tidak boleh melompati caption berikutnya."""
        for clip in self.tier2["clips"]:
            caps = clip["captions"]
            for cap, nxt in zip(caps, caps[1:]):
                self.assertLess(
                    cap["words"][-1]["start"], nxt["start"] + 0.001,
                    msg=f"{clip['id']} {cap['text']!r} → {nxt['text']!r}",
                )

    def test_caption_fields_identical_to_tier1(self) -> None:
        self.assertEqual(len(self.tier1["clips"]), len(self.tier2["clips"]))
        for c1, c2 in zip(self.tier1["clips"], self.tier2["clips"]):
            self.assertEqual(c1["id"], c2["id"])
            self.assertEqual(len(c1["captions"]), len(c2["captions"]))
            for a, b in zip(c1["captions"], c2["captions"]):
                for field in ("start", "end", "text", "emphasis"):
                    self.assertEqual(a.get(field), b.get(field), msg=f"{c1['id']} {field}")
            # sisa klip juga tidak berubah
            self.assertEqual(c1["segments"], c2["segments"], msg=c1["id"])
            self.assertEqual(c1["punch"], c2["punch"], msg=c1["id"])
            self.assertEqual(c1["reframe"], c2["reframe"], msg=c1["id"])
            self.assertEqual(c1["overlays"], c2["overlays"], msg=c1["id"])

    def test_tier2_clips_are_kinetic(self) -> None:
        for clip in self.tier2["clips"]:
            self.assertEqual(clip["caption_style"], "kinetic", msg=clip["id"])

    def test_tier1_has_no_tier2_keys(self) -> None:
        for clip in self.tier1["clips"]:
            self.assertNotIn("caption_style", clip, msg=clip["id"])
            for cap in clip["captions"]:
                self.assertNotIn("words", cap, msg=clip["id"])

    def test_tier2_keeps_version_and_reframe_default(self) -> None:
        self.assertEqual(self.tier2["version"], "0.1.0")
        for clip in self.tier2["clips"]:
            self.assertEqual(clip["reframe"]["mode"], "center", msg=clip["id"])

    def test_legacy_call_signature_still_works(self) -> None:
        """Panggilan lama tanpa keyword harus tetap sama persis."""
        again = edl_mod.build(self.wd, top_n=3)
        self.assertEqual(again, self.tier1)


class DroppedGapWordsTest(unittest.TestCase):
    """Kata yang jatuh di jeda yang dibuang tidak boleh muncul di `words`."""

    def _work_with_isolated_word(self, tmp: Path) -> tuple[Path, dict[str, Any], float]:
        wd = make_work(tmp, top_n=10, top=3)
        tr = jsonio.read_json(wd / "transcript.json")
        words = tr["words"]
        cut = next(i for i, w in enumerate(words) if float(w["start"]) > 90.0)
        for w in words[cut:]:
            w["start"] = round(float(w["start"]) + 1.2, 3)
            w["end"] = round(float(w["end"]) + 1.2, 3)
        start = round(float(words[cut - 1]["end"]) + 0.6, 3)
        words.insert(
            cut,
            {
                "i": 0,
                "w": "zzzgap",
                "start": start,
                "end": round(start + 0.15, 3),
                "speaker": 0,
                "conf": 0.9,
            },
        )
        for i, w in enumerate(words):
            w["i"] = i
        tr["duration"] = round(float(words[-1]["end"]) + 0.5, 3)

        jsonio.write_json(wd / "transcript.json", tr)
        meta = jsonio.read_json(wd / "meta.json")
        meta["duration"] = tr["duration"]
        jsonio.write_json(wd / "meta.json", meta)
        atoms = segment.build_atoms(tr["words"])
        jsonio.write_json(wd / "atoms.json", atoms)
        cands = cand_mod.generate(atoms, top_n=10)
        feat_mod.attach(cands, atoms)
        jsonio.write_json(wd / "candidates.json", cands)
        jsonio.write_json(wd / "selection.json", demo_mod.synthetic_selection(cands))
        score_mod.score(wd)
        return wd, tr, start

    def test_dropped_gap_word_is_absent_from_words(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wd, tr, injected_start = self._work_with_isolated_word(Path(td))
            tier1 = edl_mod.build(wd, top_n=3)
            tier2 = edl_mod.build(wd, top_n=3, motion_tier=2)

        multi = [c for c in tier2["clips"] if len(c["segments"]) > 1]
        self.assertTrue(multi, "fixture harus punya klip multi-segmen")

        dropped_seen = False
        for clip in multi:
            segs = clip["segments"]
            lo = min(float(s["src_start"]) for s in segs)
            hi = max(float(s["src_end"]) for s in segs)
            for w in tr["words"]:
                t = float(w["start"])
                if not (lo - 1e-6 <= t <= hi + 1e-6):
                    continue
                if edl_mod.map_time(segs, t) is None:
                    dropped_seen = True
                    self.assertNotIn(
                        str(w["w"]),
                        [x["w"] for cap in clip["captions"] for x in cap["words"]],
                        msg=f"{clip['id']} memuat kata dari jeda: {w}",
                    )
            for cap in clip["captions"]:
                for w in cap["words"]:
                    self.assertNotEqual(w["w"], "zzzgap", msg=clip["id"])

        self.assertTrue(dropped_seen, "fixture harus menghasilkan kata di jeda terbuang")
        # Kata yang diinjeksi tetap ada di sumber, hanya dibuang dari output.
        self.assertTrue(any(w["w"] == "zzzgap" for w in tr["words"]))
        # dan ia tidak boleh masuk ke teks caption mana pun
        for clip in tier1["clips"]:
            for cap in clip["captions"]:
                self.assertNotIn("zzzgap", cap["text"], msg=clip["id"])
        self.assertGreater(injected_start, 0.0)


class KineticWordsUnitTest(unittest.TestCase):
    """Tes unit langsung `_kinetic_words`, tanpa fixture `make_work`.

    Dua segmen sumber 10.0-12.0 dan 13.0-15.0 dengan jeda 12.0-13.0 dibuang:
    output 0.0-2.0 dan 2.0-4.0. `segments` dibentuk oleh `plan_segments`
    sendiri, jadi kunci dan pembulatannya sama dengan jalur produksi.
    """

    SRC_START = 10.0
    SRC_END = 15.0

    def setUp(self) -> None:
        self.segments = edl_mod.plan_segments(
            [(10.0, 12.0), (13.0, 15.0)], self.SRC_START, self.SRC_END
        )

    def test_segments_fixture_shape_matches_plan_segments(self) -> None:
        """Jaga agar tes tidak diam-diam menguji bentuk segmen yang salah."""
        self.assertEqual(len(self.segments), 2)
        for seg in self.segments:
            self.assertEqual(
                sorted(seg), ["out_start", "speed", "src_end", "src_start"]
            )
        self.assertEqual(self.segments[0]["src_start"], 10.0)
        self.assertEqual(self.segments[0]["src_end"], 12.0)
        self.assertEqual(self.segments[0]["out_start"], 0.0)
        self.assertEqual(self.segments[1]["src_start"], 13.0)
        self.assertEqual(self.segments[1]["src_end"], 15.0)
        self.assertEqual(self.segments[1]["out_start"], 2.0)

    def test_word_crossing_dropped_gap_does_not_swallow_it(self) -> None:
        """(a) kata menyeberangi jeda: durasi tidak menggelembung menyerap jeda."""
        src_start, src_end = 11.8, 13.2
        src_dur = src_end - src_start  # 1.4 s

        out = edl_mod._kinetic_words(
            self.segments, [{"w": "lintas", "start": src_start, "end": src_end}]
        )
        self.assertEqual(len(out), 1)
        word = out[0]

        self.assertEqual(word["start"], 1.8, msg="start harus map_time(11.8)")
        self.assertAlmostEqual(
            word["start"], edl_mod.map_time(self.segments, src_start), places=3
        )

        dur = round(word["end"] - word["start"], 3)
        self.assertLessEqual(
            dur, src_dur + 0.001,
            msg=f"durasi kata {dur}s menyerap jeda 1.0s yang sudah dibuang",
        )
        # Batas di atas saja TIDAK cukup: implementasi yang menyerap jeda
        # menghasilkan dur == src_dur == 1.4 dan tetap lolos. Nilai persisnya
        # yang membuktikan jeda dibuang: sisa kata di segmen 2 = 13.0-13.2.
        self.assertEqual(
            word["end"], 2.2,
            msg=f"end harus 2.0 + (13.2-13.0) = 2.2, bukan {word['end']}",
        )
        self.assertEqual(dur, 0.4)

    def test_word_entirely_in_dropped_gap_is_absent(self) -> None:
        """(b) kata yang seluruhnya di jeda tidak punya padanan output."""
        out = edl_mod._kinetic_words(
            self.segments,
            [
                {"w": "sebelum", "start": 11.0, "end": 11.4},
                {"w": "jeda", "start": 12.3, "end": 12.7},
                {"w": "sesudah", "start": 14.0, "end": 14.4},
            ],
        )
        self.assertEqual([w["w"] for w in out], ["sebelum", "sesudah"])
        self.assertNotIn("jeda", [w["w"] for w in out])

    def test_word_inside_one_segment_uses_map_time_for_both_ends(self) -> None:
        """(c) kata biasa: start/end = map_time kedua ujung, 3 desimal."""
        for src_start, src_end in ((10.5, 10.9), (11.25, 11.875), (13.4, 14.05)):
            with self.subTest(src=(src_start, src_end)):
                out = edl_mod._kinetic_words(
                    self.segments, [{"w": "biasa", "start": src_start, "end": src_end}]
                )
                self.assertEqual(len(out), 1)
                word = out[0]
                exp_start = edl_mod.map_time(self.segments, src_start)
                exp_end = edl_mod.map_time(self.segments, src_end)
                self.assertIsNotNone(exp_start)
                self.assertIsNotNone(exp_end)
                self.assertEqual(word["start"], round(float(exp_start), 3))
                self.assertEqual(word["end"], round(float(exp_end), 3))
                for key in ("start", "end"):
                    self.assertEqual(round(word[key], 3), word[key])

    def test_output_is_monotonic_and_end_not_before_start(self) -> None:
        """(d) hasil selalu monoton dan end >= start, termasuk lintas jeda."""
        src_words = [
            {"w": "a", "start": 10.1, "end": 10.4},
            {"w": "b", "start": 11.0, "end": 11.3},
            {"w": "cross", "start": 11.8, "end": 13.2},
            {"w": "gap", "start": 12.3, "end": 12.7},
            {"w": "c", "start": 13.1, "end": 13.5},
            {"w": "d", "start": 14.6, "end": 14.9},
        ]
        out = edl_mod._kinetic_words(self.segments, src_words)
        starts = [w["start"] for w in out]
        self.assertEqual(starts, sorted(starts), msg=f"tidak monoton: {starts}")
        for w in out:
            self.assertGreaterEqual(w["end"], w["start"], msg=str(w))

    def test_empty_input(self) -> None:
        self.assertEqual(edl_mod._kinetic_words(self.segments, []), [])

    def test_single_segment_maps_by_subtraction(self) -> None:
        """Satu segmen: murni pengurangan, tidak ada jeda yang perlu dibuang."""
        segs = edl_mod.plan_segments([(10.0, 15.0)], 10.0, 15.0)
        out = edl_mod._kinetic_words(
            segs, [{"w": "a", "start": 11.0, "end": 11.5}, {"w": "b", "start": 14.0, "end": 14.25}]
        )
        self.assertEqual(
            out,
            [
                {"w": "a", "start": 1.0, "end": 1.5},
                {"w": "b", "start": 4.0, "end": 4.25},
            ],
        )


class MotionTierValidationTest(unittest.TestCase):
    """`motion_tier` di luar {1,2} harus ditolak dengan ValueError."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = make_work(Path(cls._tmp.name), top_n=10, top=3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_invalid_tiers_raise_value_error_mentioning_value(self) -> None:
        for bad in (0, 3, -1, 99):
            with self.subTest(motion_tier=bad):
                with self.assertRaises(ValueError) as ctx:
                    edl_mod.build(self.wd, top_n=3, motion_tier=bad)
                self.assertIn(str(bad), str(ctx.exception))

    def test_invalid_tier_raises_value_error_before_touching_files(self) -> None:
        """Validasi tidak boleh bergantung pada isi direktori kerja."""
        with tempfile.TemporaryDirectory() as empty:
            for bad in (0, 3):
                with self.subTest(motion_tier=bad):
                    with self.assertRaises(ValueError) as ctx:
                        edl_mod.build(Path(empty), motion_tier=bad)
                    self.assertIn(str(bad), str(ctx.exception))

    def test_valid_tiers_still_build(self) -> None:
        for tier in (1, 2):
            with self.subTest(motion_tier=tier):
                built = edl_mod.build(self.wd, top_n=3, motion_tier=tier)
                self.assertEqual(len(built["clips"]), 3)
                self.assertEqual(built["version"], "0.1.0")
                if tier == 1:
                    for clip in built["clips"]:
                        self.assertNotIn("caption_style", clip)
                        for cap in clip["captions"]:
                            self.assertNotIn("words", cap)
                else:
                    for clip in built["clips"]:
                        self.assertEqual(clip["caption_style"], "kinetic")
                        for cap in clip["captions"]:
                            self.assertIn("words", cap)

    def test_tier1_default_matches_explicit_one(self) -> None:
        self.assertEqual(
            edl_mod.build(self.wd, top_n=3),
            edl_mod.build(self.wd, top_n=3, motion_tier=1),
        )


if __name__ == "__main__":
    unittest.main()
