"""`faces.face_track` + `analyze_edl(face_track=...)` (Langkah 4b-1).

Semua tes di sini murni: `sample()` di-stub, tidak ada OpenCV/ffmpeg. Yang
dikunci adalah geometri (kotak keluaran px 1080x1920), definisi shot (cut +
sambungan segmen), pengelompokan wajah per `cx`, dan perilaku aditif
`analyze_edl` (tanpa flag harus byte-identik dengan HEAD).
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import faces
from scripts.edl import map_time
from scripts.lib import jsonio

SRC_W, SRC_H = 1920, 1080
CROP_W = 608
FREE_X = SRC_W - CROP_W
SAMPLE = (640, 360)


def _face(cx: float, cy: float, w: float, h: float, motion: float = 0.0) -> dict:
    return {"cx": cx, "cy": cy, "w": w, "h": h, "motion": motion}


def _sample(t: float, faces_: list[dict], cut: bool = False) -> dict:
    return {"t": t, "cut": cut, "faces": faces_}


def _single_segment(src_start: float = 0.0, src_end: float = 10.0) -> list[dict]:
    return [{
        "src_start": src_start,
        "src_end": src_end,
        "speed": 1.0,
        "out_start": 0.0,
    }]


def _rect(entry: dict, i: int = 0) -> tuple[float, float, float, float]:
    f = entry["faces"][i]
    return (f["x"], f["y"], f["w"], f["h"])


class FaceTrackGeometryTest(unittest.TestCase):
    def _two_shot_samples(self) -> list[dict]:
        # Shot 1 (out 0,0-1,2): crop bergerak -0,5 -> +0,5 pada t=1,0.
        # Shot 2 (cut di 1,2): tanpa wajah.
        return [
            _sample(0.0, [_face(0.25, 0.30, 0.10, 0.20),
                          _face(0.75, 0.30, 0.10, 0.20)]),
            _sample(0.8, [_face(0.26, 0.30, 0.12, 0.22)]),
            _sample(1.2, [], cut=True),
            _sample(1.4, [], cut=False),
        ]

    def test_output_coordinates_hand_numbers_with_moving_crop(self) -> None:
        """Rumus: x=(x_src-crop_x(t))·1080/crop_w, y=(y_src-crop_y)·1920/crop_h."""
        track = faces.face_track(
            self._two_shot_samples(),
            _single_segment(),
            SRC_W, SRC_H, CROP_W, FREE_X,
            [(0.0, -0.5), (1.0, 0.5)],
            sample_size=SAMPLE,
        )
        self.assertEqual(len(track), 2)
        first = track[0]
        self.assertEqual(first["t"], 0.0)
        self.assertEqual(len(first["faces"]), 2)

        # Amplop shot 1: sampel t=0 memakai crop_x=328, sampel t=0,8 memakai
        # crop_x=656 (ramp 50% menuju x=984 di t=1,0).
        # f1@t=0:   x_src=(0,25-0,05)·1920=384 -> (384-328)·1080/608
        # f1@t=0,8: x_src=(0,26-0,06)·1920=384 -> (384-656)·1080/608
        # min x = -483,157895; max x = max(99,473684+341,052632,
        #                                    -483,157895+409,263158) = 440,526316
        self.assertAlmostEqual(_rect(first, 0)[0], -483.158, places=5)
        self.assertAlmostEqual(_rect(first, 0)[1], 364.8, places=6)
        self.assertAlmostEqual(_rect(first, 0)[2], 923.684, places=5)
        self.assertAlmostEqual(_rect(first, 0)[3], 422.4, places=6)

        # f2 hanya ada di sampel t=0: x_src=(0,75-0,05)·1920=1344.
        self.assertAlmostEqual(_rect(first, 1)[0], (1344 - 328) * 1080 / 608, places=3)
        self.assertAlmostEqual(_rect(first, 1)[0], 1804.737, places=5)

        # y kotak f2: y_src=(0,30-0,10)·1080=216 -> 216·1920/1080.
        self.assertAlmostEqual(_rect(first, 1)[1], 384.0, places=6)
        self.assertAlmostEqual(_rect(first, 1)[2], 341.053, places=5)
        self.assertAlmostEqual(_rect(first, 1)[3], 384.0, places=6)

        self.assertEqual(track[1]["t"], 1.2)
        self.assertEqual(track[1]["faces"], [])

    def test_faces_sorted_by_x_ascending(self) -> None:
        track = faces.face_track(
            self._two_shot_samples(), _single_segment(),
            SRC_W, SRC_H, CROP_W, FREE_X, [(0.0, -0.5), (1.0, 0.5)],
            sample_size=SAMPLE,
        )
        xs = [f["x"] for f in track[0]["faces"]]
        self.assertEqual(xs, sorted(xs))

    def test_two_separated_faces_are_two_clusters(self) -> None:
        track = faces.face_track(
            self._two_shot_samples(), _single_segment(),
            SRC_W, SRC_H, CROP_W, FREE_X, [(0.0, -0.5), (1.0, 0.5)],
            sample_size=SAMPLE,
        )
        self.assertEqual(len(track[0]["faces"]), 2,
                         "dua wajah terpisah harus tetap dua, bukan digabung")

    def test_at_most_four_faces_per_shot(self) -> None:
        faces_ = [_face(0.1 + 0.15 * i, 0.3, 0.08, 0.12) for i in range(6)]
        track = faces.face_track(
            [_sample(0.0, faces_)], _single_segment(),
            SRC_W, SRC_H, CROP_W, FREE_X, [],
            sample_size=SAMPLE,
        )
        self.assertEqual(len(track), 1)
        self.assertLessEqual(len(track[0]["faces"]), 4)
        xs = [f["x"] for f in track[0]["faces"]]
        self.assertEqual(xs, sorted(xs))

    def test_y_mapping_uses_crop_params_for_portrait_source(self) -> None:
        """Sumber 1080x2048: crop 1080x1920, crop_y=64 (bias_y=0)."""
        src_w, src_h = 1080, 2048
        track = faces.face_track(
            [_sample(0.0, [_face(0.5, 0.5, 0.2, 0.1)])],
            _single_segment(),
            src_w, src_h, 1080, 0, [],
            sample_size=(360, 640),
        )
        got = track[0]["faces"][0]
        # Kotak kiri = (cx - w/2)·1080 = (0,5-0,1)·1080 = 432.
        # y_src=(0,5-0,05)·2048=921,6; crop_y=64.
        self.assertAlmostEqual(got["x"], 432.0, places=6)
        self.assertAlmostEqual(got["y"], (921.6 - 64) * 1920 / 1920, places=6)
        self.assertAlmostEqual(got["w"], 216.0, places=6)
        self.assertAlmostEqual(got["h"], 204.8, places=6)


class FaceTrackShotTest(unittest.TestCase):
    def _one_face(self, cx: float = 0.5) -> list[dict]:
        return [_face(cx, 0.3, 0.1, 0.2)]

    def test_cut_splits_shots(self) -> None:
        samples = [
            _sample(0.0, self._one_face()),
            _sample(0.2, self._one_face()),
            _sample(0.4, self._one_face(), cut=True),
            _sample(0.6, self._one_face()),
        ]
        with_cut = faces.face_track(
            samples, _single_segment(), SRC_W, SRC_H, CROP_W, FREE_X, [],
            sample_size=SAMPLE,
        )
        no_cut = faces.face_track(
            [dict(s, cut=False) for s in samples], _single_segment(),
            SRC_W, SRC_H, CROP_W, FREE_X, [],
            sample_size=SAMPLE,
        )
        self.assertEqual([e["t"] for e in with_cut], [0.0, 0.4])
        self.assertEqual([e["t"] for e in no_cut], [0.0])

    def test_segment_join_splits_shots_and_maps_output_time(self) -> None:
        segments = [
            {"src_start": 0.0, "src_end": 2.0, "speed": 1.0, "out_start": 0.0},
            {"src_start": 5.0, "src_end": 7.0, "speed": 1.0, "out_start": 2.0},
        ]
        samples = [
            _sample(0.0, self._one_face()),
            _sample(1.0, self._one_face()),
            _sample(3.0, self._one_face()),  # jeda dibuang
            _sample(4.0, self._one_face()),  # jeda dibuang
            _sample(5.0, self._one_face()),
            _sample(6.0, self._one_face()),
        ]
        track = faces.face_track(
            samples, segments, SRC_W, SRC_H, CROP_W, FREE_X, [],
            sample_size=SAMPLE,
        )
        self.assertEqual([e["t"] for e in track], [0.0, 2.0],
                         "waktu harus waktu OUTPUT, dan sambungan segmen memecah shot")

    def test_sample_in_discarded_gap_is_skipped(self) -> None:
        segments = [
            {"src_start": 0.0, "src_end": 2.0, "speed": 1.0, "out_start": 0.0},
            {"src_start": 5.0, "src_end": 7.0, "speed": 1.0, "out_start": 2.0},
        ]
        samples = [
            _sample(0.0, self._one_face()),
            _sample(3.0, self._one_face()),  # jeda -> tidak ada entri
            _sample(5.0, self._one_face()),
        ]
        track = faces.face_track(
            samples, segments, SRC_W, SRC_H, CROP_W, FREE_X, [],
            sample_size=SAMPLE,
        )
        self.assertEqual([e["t"] for e in track], [0.0, 2.0])
        self.assertEqual(len(track), 2)

    def test_shot_without_faces_gets_empty_entry(self) -> None:
        samples = [
            _sample(0.0, self._one_face()),
            _sample(0.2, [], cut=True),
            _sample(0.4, []),
        ]
        track = faces.face_track(
            samples, _single_segment(), SRC_W, SRC_H, CROP_W, FREE_X, [],
            sample_size=SAMPLE,
        )
        self.assertEqual([e["t"] for e in track], [0.0, 0.2])
        self.assertEqual(track[1]["faces"], [])

    def test_empty_samples(self) -> None:
        self.assertEqual(
            faces.face_track([], _single_segment(), SRC_W, SRC_H, CROP_W, FREE_X, [],
                             sample_size=SAMPLE),
            [],
        )

    def test_deterministic(self) -> None:
        samples = [
            _sample(0.0, [_face(0.2, 0.3, 0.1, 0.2), _face(0.7, 0.3, 0.1, 0.2)]),
            _sample(0.2, [_face(0.21, 0.3, 0.1, 0.2), _face(0.69, 0.3, 0.1, 0.2)]),
        ]
        a = faces.face_track(samples, _single_segment(), SRC_W, SRC_H, CROP_W,
                             FREE_X, [], sample_size=SAMPLE)
        b = faces.face_track(samples, _single_segment(), SRC_W, SRC_H, CROP_W,
                             FREE_X, [], sample_size=SAMPLE)
        self.assertEqual(a, b)


# --- salinan VERBATIM `faces.analyze_edl` di HEAD -------------------------
def _head_analyze_edl(wd: Path, sample_fn) -> dict:
    edl = jsonio.read_json(wd / "edl.json")
    meta = jsonio.read_json(wd / "meta.json")

    src = meta.get("mezzanine") or meta.get("source")
    src_w = int(meta["width"])
    src_h = int(meta["height"])
    crop_w = int(round(src_h * 9.0 / 16.0 / 2.0)) * 2
    crop_w = min(crop_w, src_w)

    if not faces.available():
        return {"clips": 0, "reason": "opencv atau model tidak tersedia"}

    done = 0
    for clip in edl.get("clips", []):
        segs = clip.get("segments") or []
        if not segs:
            continue
        first = min(float(s["src_start"]) for s in segs)
        last = max(float(s["src_end"]) for s in segs)
        samples = sample_fn(src, first, last)

        timed: list[tuple[float, float]] = []
        for s in samples:
            fs = s.get("faces") or []
            if not fs:
                continue
            f = max(fs, key=lambda x: x.get("w", 0.0))
            hh = float(f.get("h") or f.get("w", 0.0))
            m = float(f.get("cy", 0.5)) - hh / 2.0
            out_t = map_time(segs, float(s["t"]))
            if out_t is not None:
                timed.append((out_t, round(m, 4)))
        if timed:
            clip.setdefault("reframe", {})["face_top"] = round(
                sorted(m for _, m in timed)[len(timed) // 2], 4
            )

        timeline = faces.bias_timeline(samples, src_w, crop_w, first)
        if not timeline:
            continue
        mapped: list[list[float]] = []
        for t_rel, b in timeline:
            out_t = map_time(segs, first + t_rel)
            if out_t is not None:
                mapped.append([out_t, b])
        if mapped:
            reframe = clip.setdefault("reframe", {})
            reframe["mode"] = "track"
            reframe["bias_track"] = mapped
            done += 1

    jsonio.write_json(wd / "edl.json", edl)
    return {"clips": done, "total": len(edl.get("clips", []))}


def _synthetic_samples(src, start: float, end: float) -> list[dict]:
    return [
        _sample(start + 0.0, [_face(0.3, 0.30, 0.10, 0.20), _face(0.7, 0.32, 0.08, 0.16)]),
        _sample(start + 0.2, [_face(0.31, 0.30, 0.10, 0.20), _face(0.69, 0.32, 0.08, 0.16)]),
        _sample(start + 0.4, [_face(0.32, 0.28, 0.11, 0.22)], cut=True),
        _sample(start + 0.6, [_face(0.32, 0.28, 0.11, 0.22)]),
        _sample(start + 0.8, []),
    ]


def _write_synthetic_work(wd: Path, *, kinetic: bool = False) -> None:
    wd.mkdir(parents=True, exist_ok=True)
    jsonio.write_json(wd / "meta.json", {
        "version": "0.1.0",
        "source": "synthetic://x",
        "source_sha256": "x",
        "duration": 10.0,
        "fps": 30.0,
        "width": SRC_W,
        "height": SRC_H,
        "has_audio": False,
        "audio_rate": 48000,
        "loudness_lufs": -18.0,
        "mezzanine": "synthetic://x",
        "language": "id",
    })
    clip = {
        "id": "clip_00",
        "score": {
            "axes": {"hook": 1.0},
            "base": 1.0, "penalty": 0.0, "final": 50.0, "percentile": 50.0,
        },
        "segments": [{"src_start": 4.0, "src_end": 9.0, "speed": 1.0, "out_start": 0.0}],
        "captions": [
            {"start": 0.0, "end": 1.0, "text": "Halo dunia", "emphasis": "dunia",
             "words": [
                 {"w": "Halo", "start": 0.0, "end": 0.4},
                 {"w": "dunia", "start": 0.4, "end": 0.8},
             ]},
        ],
        "reframe": {"mode": "center", "bias_x": 0.0, "bias_y": 0.0},
        "punch": [{"t": 0.0, "scale": 1.0}, {"t": 2.0, "scale": 1.14}],
        "progress": True,
        "overlays": [],
    }
    if kinetic:
        clip["caption_style"] = "kinetic"
    jsonio.write_json(wd / "edl.json", {
        "version": "0.1.0",
        "source": {
            "path": "synthetic://x", "duration": 10.0, "fps": 30.0,
            "width": SRC_W, "height": SRC_H, "audio_rate": 48000,
            "loudness_lufs": -18.0,
        },
        "output": {
            "width": 1080, "height": 1920, "fps": 30.0,
            "loudness_lufs": -14.0, "true_peak_db": -1.0,
        },
        "clips": [clip],
    })


class AnalyzeEdlFaceTrackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _patched(self, wd: Path):
        return (
            mock.patch.object(faces, "available", return_value=True),
            mock.patch.object(faces, "sample", side_effect=_synthetic_samples),
        )

    def test_default_output_byte_identical_to_head(self) -> None:
        new_wd = self.root / "new"
        head_wd = self.root / "head"
        _write_synthetic_work(new_wd)
        _write_synthetic_work(head_wd)

        avail, samp = self._patched(new_wd)
        with avail, samp:
            faces.analyze_edl(new_wd)
        avail, samp = self._patched(head_wd)
        with avail, samp:
            _head_analyze_edl(head_wd, _synthetic_samples)

        self.assertEqual(
            (new_wd / "edl.json").read_bytes(),
            (head_wd / "edl.json").read_bytes(),
            "analyze_edl bawaan harus byte-identik dengan HEAD",
        )

    def test_face_track_flag_only_adds_face_track(self) -> None:
        base_wd = self.root / "base"
        ft_wd = self.root / "ft"
        _write_synthetic_work(base_wd)
        _write_synthetic_work(ft_wd)

        avail, samp = self._patched(base_wd)
        with avail, samp:
            faces.analyze_edl(base_wd, face_track=False)
        avail, samp = self._patched(ft_wd)
        with avail, samp:
            info = faces.analyze_edl(ft_wd, face_track=True)

        base = jsonio.read_json(base_wd / "edl.json")
        got = jsonio.read_json(ft_wd / "edl.json")
        track = got["clips"][0]["reframe"].pop("face_track")
        self.assertEqual(got, base, "flag hanya boleh menambah reframe.face_track")
        self.assertIsInstance(track, list)
        self.assertTrue(track)
        self.assertEqual(track[0]["t"], 0.0)
        self.assertEqual(len(track[0]["faces"]), 2)
        self.assertIn("clips", info)

    def test_available_false_writes_nothing(self) -> None:
        wd = self.root / "off"
        _write_synthetic_work(wd)
        before = (wd / "edl.json").read_bytes()
        with mock.patch.object(faces, "available", return_value=False):
            info = faces.analyze_edl(wd, face_track=True)
        self.assertEqual((wd / "edl.json").read_bytes(), before)
        self.assertEqual(info["clips"], 0)
        self.assertNotIn("face_track", jsonio.read_json(wd / "edl.json")["clips"][0]["reframe"])

    def test_flag_is_keyword_only(self) -> None:
        with self.assertRaises(TypeError):
            faces.analyze_edl(self.root, True)  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
