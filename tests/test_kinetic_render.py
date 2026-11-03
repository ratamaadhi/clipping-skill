"""Tes render NYATA (ffmpeg ber-libass): buktikan caption kinetic benar-benar terbakar.

Tes lain memakai `subprocess.run` di-patch, jadi mereka hanya membuktikan
perintahnya berbentuk benar. Di sini ffmpeg sungguhan dijalankan pada sumber
sintetis (hitam 1920x1080 @30 fps + sinus) dan hasilnya diukur tanpa numpy:
dimensi, jumlah frame, durasi audio, dan piksel tinta di kotak tiap kata.

Skip bila tidak ada ffmpeg ber-libass (lihat `tests/ffmpeg_libass.py`). Mesin
pengembang ini punya `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`; formula
`ffmpeg` Homebrew biasa TIDAK punya filter `subtitles`.

Skenario klip = skenario oracle (`Pertama, pasti nenekmu bangga.`), digeser
supaya kata pertama mulai di 0,30 s (≥ 0,3 s sesuai spesifikasi tugas), dengan
`progress: False` dan `punch: []` agar tidak ada elemen lain yang menambah
piksel terang di kotak kata.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import ROOT

from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts import kinetic
from scripts import render
from scripts.lib import fontmetrics

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

# Waktu kata = skenario oracle digeser +0,30 s - 1,02 s + 1,02 s ... yaitu
# seluruh frasa digeser sehingga kata pertama mulai tepat di 0,30 s.
WORDS = [
    {"w": "Pertama,", "start": 0.30, "end": 0.62},
    {"w": "pasti", "start": 0.66, "end": 0.86},
    {"w": "nenekmu", "start": 0.90, "end": 1.22},
    {"w": "bangga.", "start": 1.30, "end": 1.62},
]
CAPTION = {
    "start": 0.30,
    "end": 1.62,
    "text": "Pertama, pasti nenekmu bangga.",
    "emphasis": "pasti",
    "words": WORDS,
}

# Baris hasil layout: kata 0,1 di baris 0; kata 2,3 di baris 1. Pita dipisah
# di 1407/1408 karena descender baris 0 berhenti di y=1403 (terukur) dan tinta
# baris 1 mulai di y=1418.
ROW_BAND = {0: (1250, 1407), 1: (1408, 1600)}
ROW_OF_WORD = [0, 0, 1, 1]

# Toleransi pusat tinta terhadap `\pos`. Oracle libass memakai ±3 px pada
# render tanpa penskalaan; di sini jalurnya sama (PlayRes 1080x1920), jadi
# ambang yang sama dipakai.
CENTER_TOL_PX = 3.0

# Margin kotak kata di sekitar lebar prediksi: cukup untuk menampung tinta
# yang membesar saat spring (112% untuk kata emphasis), tanpa menyerempet kata
# tetangga (celah antar-kata 32,5 px pada 3b-iv).
BOX_MARGIN_PX = 10.0

# Piksel "tinta": putih atau kuning aksen, sama dengan oracle.
def _is_ink(r: int, g: int, b: int) -> bool:
    return r > 200 and g > 200 and (b > 200 or b < 90)

def _ffmpeg_bin() -> str:
    assert _FFMPEG is not None
    return _FFMPEG

def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AssertionError(
            f"perintah gagal ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.decode('utf-8', errors='replace')[:1500]}"
        )
    return proc

def _make_source(path: Path) -> None:
    """Video hitam 1920x1080 @30 fps 5 s + nada sinus, sekali encode."""
    _run([
        _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={SRC_W}x{SRC_H}:r={SRC_FPS}:d={SRC_DUR:g}",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=5",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(path),
    ])

def _probe(path: Path) -> dict[str, Any]:
    """Baca dimensi/frame/durasi lewat ffprobe JSON (tanpa numpy)."""
    assert _FFPROBE is not None
    proc = _run([
        _FFPROBE, "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ])
    import json

    data = json.loads(proc.stdout.decode("utf-8"))
    out: dict[str, Any] = {}
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind in out:
            continue
        out[kind] = stream
    return out

def _frame_rgb(path: Path, index: int, crop: tuple[int, int, int, int] | None = None) -> bytes:
    """Satu frame `index` sebagai rgb24, opsional dipotong (x, y, w, h)."""
    vf = f"trim=start_frame={index}:end_frame={index + 1}"
    if crop:
        x, y, w, h = crop
        vf += f",crop={w}:{h}:{x}:{y}"
    vf += ",setpts=PTS-STARTPTS"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.raw"
        _run([
            _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-vf", vf, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ])
        return out.read_bytes()

def _ink_bbox(data: bytes, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Kotak pembatas piksel tinta di frame potongan, atau None bila kosong."""
    cols: list[int] = []
    rows: list[int] = []
    for y in range(height):
        base = y * width * 3
        for x in range(width):
            i = base + x * 3
            if i + 2 >= len(data):
                continue
            if _is_ink(data[i], data[i + 1], data[i + 2]):
                cols.append(x)
                rows.append(y)
    if not cols:
        return None
    return min(cols), max(cols), min(rows), max(rows)

def _layout_and_widths() -> tuple[list[dict[str, Any]], list[float]]:
    font = fontmetrics.Font.load(ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf")
    # Skala akhir tiap kata harus sama dengan yang dipakai `build_ass`, kalau
    # tidak posisi yang dibandingkan bukan posisi yang dikirim ke renderer.
    # Konstanta diambil dari `kinetic` (sumber tunggal), bukan angka 1,12.
    scales = [
        kinetic.SCALE_EMPHASIS / 100.0 if w["w"] == CAPTION["emphasis"] else 1.0
        for w in WORDS
    ]
    layout = kinetic.layout_phrase(
        [{"w": w["w"]} for w in WORDS], font, SIZE, scales=scales
    )
    widths = [font.width(w["w"], SIZE) for w in WORDS]
    return layout, widths

def _word_crop(layout: list[dict[str, Any]], widths: list[float], i: int) -> tuple[int, int, int, int]:
    """Kotak (x, y, w, h) tempat kata `i` digambar, dari `\\pos` + lebar prediksi."""
    scale = kinetic.SCALE_EMPHASIS / 100.0 if WORDS[i]["w"] == "pasti" else 1.0
    half = widths[i] * scale / 2.0 + BOX_MARGIN_PX
    x = max(0, int(math.floor(layout[i]["x"] - half)))
    x -= x % 2  # crop ffmpeg menuntut dimensi genap untuk yuv420p; rgb24 longgar,
    y0, y1 = ROW_BAND[ROW_OF_WORD[i]]
    w = int(math.ceil(2.0 * half))
    w += w % 2
    h = (y1 - y0) // 2 * 2
    return x, y0, w, h

def _edl() -> dict[str, Any]:
    return {
        "version": "0.1.0",
        "source": {
            "path": "src.mp4",
            "width": SRC_W,
            "height": SRC_H,
            "fps": float(SRC_FPS),
            "audio_rate": 48000,
        },
        "output": {"fps": float(FPS), "loudness_lufs": -14.0, "true_peak_db": -1.0},
    }

def _kinetic_clip() -> dict[str, Any]:
    return {
        "id": "clip_01",
        "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
        "reframe": {"mode": "center"},
        "punch": [],
        "progress": False,
        "caption_style": "kinetic",
        "captions": [dict(CAPTION)],
    }

def _phrase_clip() -> dict[str, Any]:
    return {
        "id": "clip_01",
        "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
        "reframe": {"mode": "center"},
        "punch": [],
        "progress": False,
        "captions": [
            {"start": 0.30, "end": 1.62, "text": "Pertama, pasti nenekmu bangga.",
             "emphasis": "pasti"}
        ],
    }

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class KineticRealRenderTest(unittest.TestCase):
    """Render kinetic sungguhan: dimensi, timing, dan piksel tinta per kata."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")

        cls.edl = _edl()
        cls.clip = _kinetic_clip()
        cls.out = cls.wd / "out" / "clip_01.mp4"
        render.render_clip(cls.edl, cls.clip, cls.wd, cls.out)

        cls.probe = _probe(cls.out)
        cls.layout, cls.widths = _layout_and_widths()
        cls.ass = (cls.wd / "captions" / "clip_01.ass").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # -- dimensi dan timing ----------------------------------------------

    def test_output_is_1080x1920(self) -> None:
        video = self.probe["video"]
        self.assertEqual((int(video["width"]), int(video["height"])), (OUT_W, OUT_H))

    def test_frame_count_equals_duration_times_fps(self) -> None:
        video = self.probe["video"]
        self.assertEqual(int(video["nb_frames"]), round(CLIP_DUR * FPS))

    def test_audio_duration_within_one_aac_frame_of_video(self) -> None:
        video_dur = float(self.probe["video"]["duration"])
        audio_dur = float(self.probe["audio"]["duration"])
        self.assertLessEqual(abs(audio_dur - video_dur), 1.0 / 48.0, msg=(
            f"video {video_dur:.4f}s vs audio {audio_dur:.4f}s"
        ))

    def test_ass_is_kinetic(self) -> None:
        self.assertIn("Style: Kinetic", self.ass)
        self.assertEqual(self.ass.count("Dialogue:"), len(WORDS))
        for i, w in enumerate(WORDS):
            self.assertIn(f"\\pos({self.layout[i]['x']:.2f},{self.layout[i]['y']:.2f})", self.ass,
                          msg=w["w"])

    # -- piksel per kata --------------------------------------------------

    def test_no_ink_before_word_start(self) -> None:
        """Frame 0,10 s sebelum kata mulai: kotak kata harus kosong."""
        for i, word in enumerate(WORDS):
            frame_idx = int(round((word["start"] - 0.10) * FPS))
            crop = _word_crop(self.layout, self.widths, i)
            data = _frame_rgb(self.out, frame_idx, crop)
            bbox = _ink_bbox(data, crop[2], crop[3])
            self.assertIsNone(
                bbox,
                msg=f"{word['w']!r} sudah punya tinta {bbox} di frame {frame_idx} "
                    f"(t={frame_idx / FPS:.3f}s, start={word['start']:.3f}s)",
            )

    def test_ink_present_two_frames_after_word_start(self) -> None:
        for i, word in enumerate(WORDS):
            frame_idx = int(round((word["start"] + 2.0 / FPS) * FPS))
            crop = _word_crop(self.layout, self.widths, i)
            data = _frame_rgb(self.out, frame_idx, crop)
            bbox = _ink_bbox(data, crop[2], crop[3])
            self.assertIsNotNone(
                bbox,
                msg=f"{word['w']!r} belum punya tinta di frame {frame_idx} "
                    f"(t={frame_idx / FPS:.3f}s, start={word['start']:.3f}s)",
            )

    def test_ink_present_after_settle(self) -> None:
        """+0,30 s setelah mulai: spring sudah settle, tinta tetap ada."""
        for i, word in enumerate(WORDS):
            frame_idx = int(round((word["start"] + 0.30) * FPS))
            if frame_idx >= round(CLIP_DUR * FPS):
                continue
            crop = _word_crop(self.layout, self.widths, i)
            data = _frame_rgb(self.out, frame_idx, crop)
            bbox = _ink_bbox(data, crop[2], crop[3])
            self.assertIsNotNone(
                bbox,
                msg=f"{word['w']!r} hilang setelah settle di frame {frame_idx}",
            )

    def test_settled_ink_center_matches_pos(self) -> None:
        """Pusat tinta tiap kata ±3 px dari `\\pos` saat semua kata sudah settle.

        Frame 48 (t = 1,60 s): kata terakhir mulai 1,30 s, jadi seluruh frasa
        sudah settle dan belum keluar (window_end = 1,74 s).
        """
        frame_idx = int(round(1.60 * FPS))
        for i, word in enumerate(WORDS):
            crop = _word_crop(self.layout, self.widths, i)
            data = _frame_rgb(self.out, frame_idx, crop)
            bbox = _ink_bbox(data, crop[2], crop[3])
            self.assertIsNotNone(bbox, msg=f"{word['w']!r} tanpa tinta di frame {frame_idx}")
            assert bbox is not None
            center_x = crop[0] + (bbox[0] + bbox[1]) / 2.0
            self.assertAlmostEqual(
                center_x, self.layout[i]["x"], delta=CENTER_TOL_PX,
                msg=f"{word['w']!r}: pusat tinta {center_x:.2f} vs pos "
                    f"{self.layout[i]['x']:.2f}",
            )

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class PreviewRealRenderTest(unittest.TestCase):
    """Pratinjau sungguhan: 540x960, 15 fps, durasi sama."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        _make_source(cls.wd / "src.mp4")
        cls.edl = _edl()
        cls.clip = _kinetic_clip()
        cls.out = cls.wd / "out" / "clip_01.preview.mp4"
        render.render_clip(cls.edl, cls.clip, cls.wd, cls.out, preview=True)
        cls.probe = _probe(cls.out)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_preview_is_540x960(self) -> None:
        video = self.probe["video"]
        self.assertEqual((int(video["width"]), int(video["height"])), (540, 960))

    def test_preview_is_15_fps(self) -> None:
        self.assertEqual(self.probe["video"]["r_frame_rate"], "15/1")

    def test_preview_duration_within_one_frame(self) -> None:
        self.assertAlmostEqual(
            float(self.probe["video"]["duration"]), CLIP_DUR, delta=1.0 / render.PREVIEW_FPS
        )

    def test_preview_frame_count(self) -> None:
        self.assertEqual(
            int(self.probe["video"]["nb_frames"]),
            round(CLIP_DUR * render.PREVIEW_FPS),
        )

    def test_preview_still_has_caption_ink(self) -> None:
        """Caption ikut terskala: ada tinta di paruh bawah frame."""
        data = _frame_rgb(self.out, int(round(1.60 * render.PREVIEW_FPS)))
        bbox = _ink_bbox(data, 540, 960)
        self.assertIsNotNone(bbox)
        assert bbox is not None
        self.assertGreater(bbox[2], 600, msg=f"tinta terlalu tinggi: {bbox}")

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class PhraseTier1RealRenderTest(unittest.TestCase):
    """Regresi: klip frasa (tier-1) masih bisa dirender tanpa error."""

    def test_phrase_clip_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp).resolve()
            _make_source(wd / "src.mp4")
            out = wd / "out" / "clip_01.mp4"
            render.render_clip(_edl(), _phrase_clip(), wd, out)
            self.assertTrue(out.is_file())
            probe = _probe(out)
            self.assertEqual((int(probe["video"]["width"]), int(probe["video"]["height"])),
                             (OUT_W, OUT_H))
            self.assertEqual(int(probe["video"]["nb_frames"]), round(CLIP_DUR * FPS))
            ass = (wd / "captions" / "clip_01.ass").read_text(encoding="utf-8")
            self.assertIn("Style: Base", ass)
            self.assertNotIn("Style: Kinetic", ass)

if __name__ == "__main__":
    unittest.main()
