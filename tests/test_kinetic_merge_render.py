"""Tes render NYATA (ffmpeg ber-libass): frasa pendek tidak boleh hilang.

Kasus F2: `Lu,` (kata 80 ms) hanya mendapat jendela 40 ms karena
`DEFAULT_LEAD` + `NEXT_GUARD`; satu-satunya frame yang memuatnya beralfa ~39%
dan berskala ~65%, jadi kata itu tidak pernah terbaca. `effective_captions`
menggabungkannya ke frasa berikutnya SAAT RENDER; waktu kata tidak berubah.

Fixture sintetis meniru kasus itu: dua frasa, yang pertama 80 ms, yang kedua
1,12 s. Setelah penggabungan kata pertama harus punya tinta pada >= 6 frame
berturut-turut (kontrol `min_visible=0` <= 2 frame), dan tintanya masih ada
pada frame tepat setelah kata kedua mencapai skala penuh.

Catatan spesifikasi (dikoreksi koordinator, 2026-11-02): asersi ">= 6 frame
sebelum kata KEDUA mulai" tidak mungkin, karena penggabungan tidak mengubah
waktu kata - jarak kata1->kata2 tetap 80 ms (~2-3 frame) pada kedua kasus.
Yang diperbaiki adalah kata pertama yang ikut menghilang setelah 40 ms; jadi
yang diuji adalah kelangsungan tampilnya, bukan jaraknya ke kata kedua.

Skip bila tidak ada ffmpeg ber-libass (lihat `tests/ffmpeg_libass.py`).
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.helpers import ROOT

from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts import kinetic
from scripts import render
from scripts.lib import fontmetrics
from scripts.lib import spring

_FFMPEG = find_ffmpeg_with_libass()
_FFPROBE = str(Path(_FFMPEG).with_name("ffprobe")) if _FFMPEG else None
if _FFPROBE and not Path(_FFPROBE).exists():
    _FFPROBE = shutil.which("ffprobe")

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` atau set env CLIP_FFMPEG ke path ffmpeg berlibass."
)

SRC_W, SRC_H = 1920, 1080
SRC_FPS = 30
SRC_DUR = 5.0
FPS = 30
OUT_W, OUT_H = 1080, 1920
CLIP_DUR = 3.0
SIZE = 84.0
LEAD = kinetic.DEFAULT_LEAD
FULL_FRAMES = round(CLIP_DUR * FPS)

FONT_PATH = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"

# Dua frasa F2: kata pertama 80 ms, frasa kedua 1,12 s. Waktu kata TIDAK
# diubah oleh penggabungan.
PHRASES = [
    {
        "start": 1.00,
        "end": 1.08,
        "text": "Lu,",
        "words": [{"w": "Lu,", "start": 1.00, "end": 1.08}],
    },
    {
        "start": 1.08,
        "end": 2.20,
        "text": "lu ngerasain nggak sih",
        "emphasis": "nggak",
        "words": [
            {"w": "lu", "start": 1.08, "end": 1.30},
            {"w": "ngerasain", "start": 1.30, "end": 1.90},
            {"w": "nggak", "start": 1.90, "end": 2.05},
            {"w": "sih", "start": 2.05, "end": 2.20},
        ],
    },
]

BOX_MARGIN_PX = 10.0
BAND_Y = 1250
BAND_H = 350


def _is_ink(r: int, g: int, b: int) -> bool:
    return r > 200 and g > 200 and (b > 200 or b < 90)


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AssertionError(
            f"perintah gagal ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.decode('utf-8', errors='replace')[:1500]}"
        )
    return proc


def _make_source(path: Path) -> None:
    assert _FFMPEG is not None
    _run([
        _FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={SRC_W}x{SRC_H}:r={SRC_FPS}:d={SRC_DUR:g}",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=5",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(path),
    ])


def _probe(path: Path) -> dict[str, Any]:
    assert _FFPROBE is not None
    proc = _run([
        _FFPROBE, "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ])
    data = json.loads(proc.stdout.decode("utf-8"))
    out: dict[str, Any] = {}
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind in out:
            continue
        out[kind] = stream
    return out


def _edl() -> dict[str, Any]:
    return {
        "version": "0.1.0",
        "source": {"path": "src.mp4", "width": SRC_W, "height": SRC_H,
                   "fps": float(SRC_FPS), "audio_rate": 48000},
        "output": {"fps": float(FPS), "loudness_lufs": -14.0, "true_peak_db": -1.0},
    }


def _clip() -> dict[str, Any]:
    return {
        "id": "clip_01",
        "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
        "reframe": {"mode": "center"},
        "punch": [],
        "progress": False,
        "caption_style": "kinetic",
        "captions": [dict(cap) for cap in PHRASES],
    }


def _font() -> fontmetrics.Font:
    return fontmetrics.Font.load(FONT_PATH)


def _merged_layout() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    effective = kinetic.effective_captions(PHRASES)
    assert len(effective) == 1, f"fixture harus tergabung, dapat {len(effective)}"
    cap = effective[0]
    scales = kinetic._scales_for_emphasis(cap["words"], cap.get("emphasis") or "")
    layout = kinetic.layout_phrase(
        cap["words"], _font(), SIZE, max_lines=2, scales=scales
    )
    return layout, cap


def _control_layout() -> list[dict[str, Any]]:
    return kinetic.layout_phrase(PHRASES[0]["words"], _font(), SIZE)


def _crop(point: dict[str, Any]) -> tuple[int, int, int, int]:
    half = point["w"] / 2.0 + BOX_MARGIN_PX
    x = max(0, int(math.floor(point["x"] - half)))
    x -= x % 2
    w = int(math.ceil(2.0 * half))
    w += w % 2
    return x, BAND_Y, w, BAND_H


def _raw_frames(video: Path, crop: tuple[int, int, int, int], count: int) -> list[bytes]:
    """Semua frame `count` pertama sebagai rgb24 di dalam kotak `crop`."""
    assert _FFMPEG is not None
    x, y, w, h = crop
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frames.raw"
        _run([
            _FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(video),
            "-vf", f"crop={w}:{h}:{x}:{y}",
            "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24",
            str(out),
        ])
        data = out.read_bytes()
    stride = w * h * 3
    return [data[i * stride:(i + 1) * stride] for i in range(count)]


def _ink_bbox(frame: bytes, width: int, height: int) -> tuple[int, int, int, int] | None:
    cols: list[int] = []
    rows: list[int] = []
    for yy in range(height):
        base = yy * width * 3
        for xx in range(width):
            i = base + xx * 3
            if i + 2 >= len(frame):
                continue
            if _is_ink(frame[i], frame[i + 1], frame[i + 2]):
                cols.append(xx)
                rows.append(yy)
    if not cols:
        return None
    return min(cols), max(cols), min(rows), max(rows)


def _ink_per_frame(video: Path, crop: tuple[int, int, int, int]) -> list[bool]:
    frames = _raw_frames(video, crop, FULL_FRAMES)
    w, h = crop[2], crop[3]
    return [_ink_bbox(frame, w, h) is not None for frame in frames]


def _longest_run(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class KineticMergeRealRenderTest(unittest.TestCase):
    """Dua render: dengan penggabungan, dan kontrol `min_visible=0`."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")
        cls.edl = _edl()
        clip = _clip()

        cls.out_merged = cls.wd / "out" / "merged.mp4"
        render.render_clip(cls.edl, clip, cls.wd, cls.out_merged)
        cls.ass_merged = (cls.wd / "captions" / "clip_01.ass").read_text(encoding="utf-8")
        cls.probe_merged = _probe(cls.out_merged)

        # Kontrol: paksa `effective_captions(min_visible=0)` sehingga tidak ada
        # penggabungan, lalu render jalur produk yang sama.
        real = kinetic.effective_captions
        cls.out_control = cls.wd / "out" / "control.mp4"
        with mock.patch.object(
            kinetic,
            "effective_captions",
            side_effect=lambda caps, **kw: real(caps, min_visible=0.0),
        ):
            render.render_clip(cls.edl, clip, cls.wd, cls.out_control)
        cls.ass_control = (cls.wd / "captions" / "clip_01.ass").read_text(encoding="utf-8")
        cls.probe_control = _probe(cls.out_control)

        cls.layout_merged, cls.merged_cap = _merged_layout()
        cls.layout_control = _control_layout()
        cls.crop_merged = _crop(cls.layout_merged[0])
        cls.crop_control = _crop(cls.layout_control[0])
        cls.ink_merged = _ink_per_frame(cls.out_merged, cls.crop_merged)
        cls.ink_control = _ink_per_frame(cls.out_control, cls.crop_control)

        cls.window_merged = kinetic.display_window([cls.merged_cap], 0)
        cls.window_control = kinetic.display_window(PHRASES, 0)
        # Kata kedua (indeks 1 frasa gabungan) mulai di `word.start - lead`.
        cls.word2_event = max(cls.window_merged[0], PHRASES[1]["words"][0]["start"] - LEAD)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # -- struktur ASS ------------------------------------------------------

    def test_merged_ass_extends_first_word_window_control_does_not(self) -> None:
        from tests.test_kinetic import _ass_seconds, _fields

        merged = [ln for ln in self.ass_merged.splitlines() if ln.startswith("Dialogue:")]
        control = [ln for ln in self.ass_control.splitlines() if ln.startswith("Dialogue:")]
        self.assertEqual(len(merged), 5)
        self.assertEqual(len(control), 5)
        self.assertAlmostEqual(
            _ass_seconds(_fields(merged[0])[2]), 2.32, delta=0.001,
            msg="frasa gabungan: End kata pertama = akhir jendela gabungan",
        )
        self.assertAlmostEqual(
            _ass_seconds(_fields(control[0])[2]), 1.00, delta=0.001,
            msg="kontrol: End kata pertama tetap jendela pendek 40 ms",
        )

    # -- kelangsungan tampil kata pertama ----------------------------------

    def test_merged_first_word_has_at_least_six_consecutive_ink_frames(self) -> None:
        run = _longest_run(self.ink_merged)
        self.assertGreaterEqual(
            run, 6,
            msg=f"kata pertama hanya ber-tinta {run} frame berturut-turut; "
                f"pola={self.ink_merged}",
        )

    def test_merged_first_word_still_visible_when_second_word_is_settled(self) -> None:
        full_time = self.word2_event + spring.settle_time()
        frame = int(math.ceil(round(full_time * FPS, 9)))
        self.assertLess(frame, FULL_FRAMES)
        self.assertTrue(
            self.ink_merged[frame],
            msg=f"kata pertama sudah hilang di frame {frame} "
                f"(t={frame / FPS:.3f}s) padahal kata kedua settle di {full_time:.3f}s",
        )

    # -- kontrol: tanpa penggabungan ---------------------------------------

    def test_control_first_word_visible_at_most_two_frames(self) -> None:
        start, end = self.window_control
        visible = [
            frame for frame, ink in enumerate(self.ink_control)
            if ink and start <= frame / FPS < end
        ]
        self.assertLessEqual(
            len(visible), 2,
            msg=f"kontrol seharusnya nyaris tak terlihat, dapat frame {visible} "
                f"(jendela {start:.3f}-{end:.3f}s)",
        )

    # -- jumlah frame dan durasi tidak berubah -----------------------------

    def test_frame_count_and_duration_unchanged(self) -> None:
        for label, probe in (("merged", self.probe_merged), ("control", self.probe_control)):
            video = probe["video"]
            self.assertEqual(
                (int(video["width"]), int(video["height"])), (OUT_W, OUT_H), msg=label
            )
            self.assertEqual(int(video["nb_frames"]), FULL_FRAMES, msg=label)
            self.assertAlmostEqual(
                float(video["duration"]), CLIP_DUR, delta=1.0 / FPS, msg=label
            )
        merged_dur = float(self.probe_merged["video"]["duration"])
        control_dur = float(self.probe_control["video"]["duration"])
        self.assertLessEqual(abs(merged_dur - control_dur), 1.0 / 48.0)
        merged_audio = float(self.probe_merged["audio"]["duration"])
        control_audio = float(self.probe_control["audio"]["duration"])
        self.assertLessEqual(abs(merged_audio - control_audio), 1.0 / 48.0)


if __name__ == "__main__":
    unittest.main()
