"""Uji gabungan SEMUA preset efek referensi (Langkah 5b-7).

Menguji klip sintetis ≥ 20 detik @30 fps dengan SATU overlay dari tiap jenis:
* `zoom_through_text`
* `checklist`
* `chart_grow`
* `ui_panel`
* `phone_frame`

pada jendela waktu yang TIDAK tumpang tindih.

Tegasan kontrak:
* (a) hanya SATU dokumen fx (`captions/<id>.fx.ass`) dan hanya SATU filter `subtitles` fx di `filter_complex`;
  Style `Serif` dan `Sans` masing-masing tepat satu baris; total `Dialogue` terhitung dan ≤ batas wajar;
* (b) di tengah tiap jendela ada piksel overlay yang jenisnya benar (bbox/warna khas tiap jenis)
  dan di luar semua jendela piksel IDENTIK dengan render tanpa preset;
* (c) jumlah frame dan durasi audio sama dengan tanpa preset;
* (d) urutan filter: panel tier-1 -> fx subtitles -> (pratinjau) -> caption subtitles;
* (e) peringatan: overlay di luar durasi klip dilewati dengan satu `PERINGATAN:` sedangkan yang lain tetap tampil.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.ffmpeg_libass import find_ffmpeg_with_libass
from tests.helpers import ROOT

from scripts import motion
from scripts import presets
from scripts import render

_FFMPEG = find_ffmpeg_with_libass()
SKIP_REASON = "tidak ada ffmpeg dengan filter 'subtitles' (libass)."

ARCHIVO_FILE = ROOT / "assets" / "fonts" / "ArchivoBlack-Regular.ttf"
SERIF_FILE = ROOT / "assets" / "fonts" / "DMSerifDisplay-Italic.ttf"

FPS = 30
SRC_FPS = 30
SRC_W = 1920
SRC_H = 1080
OUT_W = 1080
OUT_H = 1920
CLIP_DUR = 20.0


def _ffmpeg_bin() -> str:
    assert _FFMPEG is not None
    return _FFMPEG


def _run(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AssertionError(
            f"perintah gagal ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.decode('utf-8', errors='replace')[:1500]}"
        )
    return proc


def _make_source(path: Path) -> None:
    _run([
        _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i",
        f"color=c=black:s={SRC_W}x{SRC_H}:r={SRC_FPS}:d={CLIP_DUR:g}",
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={CLIP_DUR:g}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(path),
    ])


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = Path(_ffmpeg_bin()).with_name("ffprobe")
    proc = _run([
        str(ffprobe), "-v", "error",
        "-show_entries", "stream=nb_frames,duration,codec_type",
        "-of", "json", str(path),
    ])
    data = json.loads(proc.stdout.decode("utf-8"))
    streams = data.get("streams", [])
    video = next(s for s in streams if s.get("codec_type") == "video")
    audio = next(s for s in streams if s.get("codec_type") == "audio")
    return {"video": video, "audio": audio}


def _frame_rgb(path: Path, index: int) -> bytes:
    vf = f"trim=start_frame={index}:end_frame={index + 1},setpts=PTS-STARTPTS"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.raw"
        _run([
            _ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-vf", vf, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ])
        return out.read_bytes()


def _px(data: bytes, x: int, y: int) -> tuple[int, int, int]:
    base = (y * OUT_W + x) * 3
    return data[base], data[base + 1], data[base + 2]


EDL: dict[str, Any] = {
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


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class AllPresetsIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = Path(cls._tmp.name).resolve()
        cls.src_mp4 = cls.wd / "src.mp4"
        _make_source(cls.src_mp4)

        cls.caption_item = {
            "start": 0.5,
            "end": 1.5,
            "text": "KAPSI DI LAPISAN ATAS",
            "words": [{"word": "KAPSI", "start": 0.5, "end": 1.0}],
        }

        # 5 overlay pada jendela waktu non-overlapping
        cls.overlays_all = [
            # 1. zoom_through_text: 0.5s - 2.0s
            {
                "type": "zoom_through_text",
                "start": 0.5,
                "end": 2.0,
                "props": {"text": "5 JAM", "duration": 1.0},
            },
            # 2. checklist: 3.5s - 6.5s (done_at = 4.5s)
            {
                "type": "checklist",
                "start": 3.5,
                "end": 6.5,
                "props": {
                    "title": "CHECKLIST",
                    "items": [
                        {"text": "Satu", "done_at": 4.5},
                        {"text": "Dua", "done_at": None},
                    ],
                },
            },
            # 3. chart_grow: 7.5s - 10.5s
            {
                "type": "chart_grow",
                "start": 7.5,
                "end": 10.5,
                "props": {
                    "title": "GROWTH",
                    "labels": ["A", "B", "C"],
                    "values": [10.0, 50.0, 80.0],
                    "tag": "+150%",
                },
            },
            # 4. ui_panel: 11.5s - 14.5s
            {
                "type": "ui_panel",
                "start": 11.5,
                "end": 14.5,
                "props": {
                    "title": "COMPONENTS",
                    "tag": "NEW",
                    "thumbs": 3,
                    "input": "Search...",
                },
            },
            # 5. phone_frame: 15.5s - 18.5s
            {
                "type": "phone_frame",
                "start": 15.5,
                "end": 18.5,
                "props": {
                    "title": "NOTIFIKASI",
                    "lines": ["Baris satu", "Baris dua", "Baris tiga"],
                    "side": "right",
                },
            },
        ]

        cls.clip_all = {
            "id": "clip_all_fx",
            "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
            "reframe": {"mode": "center"},
            "punch": [],
            "progress": False,
            "captions": [cls.caption_item],
            "overlays": list(cls.overlays_all),
        }

        cls.clip_plain = {
            "id": "clip_all_plain",
            "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
            "reframe": {"mode": "center"},
            "punch": [],
            "progress": False,
            "captions": [cls.caption_item],
            "overlays": [],
        }

        cls.out_all = cls.wd / "out" / "clip_all_fx.mp4"
        cls.out_plain = cls.wd / "out" / "clip_all_plain.mp4"
        render.render_clip(EDL, cls.clip_all, cls.wd, cls.out_all)
        render.render_clip(EDL, cls.clip_plain, cls.wd, cls.out_plain)

        cls.probe_all = _probe(cls.out_all)
        cls.probe_plain = _probe(cls.out_plain)
        cls._cache: dict[tuple[str, int], bytes] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _frame(self, kind: str, index: int) -> bytes:
        key = (kind, index)
        if key not in self._cache:
            p = self.out_all if kind == "all" else self.out_plain
            self._cache[key] = _frame_rgb(p, index)
        return self._cache[key]

    # -----------------------------------------------------------------------
    # (a) Struktur dokumen ASS gabungan & filter subtitles
    # -----------------------------------------------------------------------

    def test_a_single_fx_document_and_styles_and_dialogue_budget(self) -> None:
        """(a) Tepat satu dokumen fx ASS, satu baris Serif & Sans, Dialogue ≤ batas wajar."""
        fx_files = list((self.wd / "captions").glob("*.fx.ass"))
        self.assertEqual(len(fx_files), 1, "hanya boleh ada tepat satu berkas .fx.ass")
        fx_doc = fx_files[0].read_text(encoding="utf-8")

        # Tepat satu baris Style Serif dan tepat satu baris Style Sans
        self.assertEqual(
            fx_doc.count("Style: Serif,"), 1,
            msg="Style Serif harus muncul tepat satu baris",
        )
        self.assertEqual(
            fx_doc.count("Style: Sans,"), 1,
            msg="Style Sans harus muncul tepat satu baris tanpa duplikasi",
        )

        # Hitung Dialogue
        dialogues = [line for line in fx_doc.splitlines() if line.startswith("Dialogue: ")]
        self.assertEqual(len(dialogues), 57)
        self.assertLessEqual(
            len(dialogues), 100,
            msg=f"total Dialogue {len(dialogues)} melebihi batas wajar",
        )

    # -----------------------------------------------------------------------
    # (b) Piksel di tengah tiap jendela benar & di luar jendela identik
    # -----------------------------------------------------------------------

    def test_b_distinct_pixels_at_center_of_each_window(self) -> None:
        """(b) Di tengah tiap jendela ada piksel overlay khas tiap jenis."""
        # 1. zoom_through_text: tengah jendela t = 1.0 s (frame 30)
        # Teks DM Serif putih/kuning di area pusat kanvas (x: 350..750, y: 850..1050)
        f30 = self._frame("all", 30)
        zoom_bright = sum(
            1 for y in range(850, 1050, 4) for x in range(350, 750, 4)
            if _px(f30, x, y)[0] > 150
        )
        self.assertGreater(zoom_bright, 100, msg="teks zoom_through_text tidak terlihat di frame 30")

        # 2. checklist: tengah jendela t = 5.0 s (frame 150)
        # Centang hijau #22C55E (R < 50, G > 180, B < 110) pada butir done_at=4.5s
        f150 = self._frame("all", 150)
        check_green = sum(
            1 for y in range(300, 700, 4) for x in range(100, 300, 4)
            if _px(f150, x, y)[1] > 180 and _px(f150, x, y)[0] < 50
        )
        self.assertGreater(check_green, 20, msg="centang hijau checklist tidak terlihat di frame 150")

        # 3. chart_grow: tengah jendela t = 9.0 s (frame 270)
        # Garis grafik kuning #FFD60A (R > 230, G > 190, B < 50)
        f270 = self._frame("all", 270)
        chart_yellow = sum(
            1 for y in range(300, 700, 4) for x in range(200, 900, 4)
            if _px(f270, x, y)[0] > 230 and _px(f270, x, y)[1] > 190 and _px(f270, x, y)[2] < 50
        )
        self.assertGreater(chart_yellow, 50, msg="garis grafik kuning tidak terlihat di frame 270")

        # 4. ui_panel: tengah jendela t = 13.0 s (frame 390)
        # Kartu krem #F6EEDC (R > 220, G > 215, B > 195)
        f390 = self._frame("all", 390)
        ui_krem = sum(
            1 for y in range(300, 600, 4) for x in range(100, 900, 4)
            if _px(f390, x, y)[0] > 220 and _px(f390, x, y)[1] > 215 and _px(f390, x, y)[2] > 195
        )
        self.assertGreater(ui_krem, 1000, msg="kartu krem ui_panel tidak terlihat di frame 390")

        # 5. phone_frame: tengah jendela t = 17.0 s (frame 510)
        # Bezel badan ponsel #0B0C10 pada (646, 450)
        f510 = self._frame("all", 510)
        phone_px = _px(f510, 646, 450)
        for ch, (got, want) in enumerate(zip(phone_px, (11, 12, 16))):
            self.assertAlmostEqual(
                got, want, delta=4,
                msg=f"warna badan ponsel kanal {ch} {got} vs {want}",
            )

    def test_b_pixels_outside_all_windows_are_identical_to_plain(self) -> None:
        """(b) Di luar semua jendela preset, piksel IDENTIK dengan render tanpa preset."""
        # Gap frames:
        # frame 6 (t=0.20s): sebelum zoom
        # frame 75 (t=2.50s): antara zoom dan checklist
        # frame 210 (t=7.00s): antara checklist dan chart
        # frame 330 (t=11.00s): antara chart dan ui_panel
        # frame 450 (t=15.00s): antara ui_panel dan phone_frame
        # frame 585 (t=19.50s): setelah phone_frame keluar
        gap_frames = [6, 75, 210, 330, 450, 585]
        for f in gap_frames:
            with self.subTest(frame=f):
                self.assertEqual(
                    self._frame("all", f),
                    self._frame("plain", f),
                    msg=f"frame {f} di luar jendela preset berbeda dari render polos",
                )

    # -----------------------------------------------------------------------
    # (c) Jumlah frame dan durasi audio sama
    # -----------------------------------------------------------------------

    def test_c_frame_count_and_audio_duration_are_identical(self) -> None:
        """(c) Jumlah frame dan durasi audio klip gabungan sama dengan tanpa preset."""
        want_frames = round(CLIP_DUR * FPS)  # 600
        self.assertEqual(int(self.probe_all["video"]["nb_frames"]), want_frames)
        self.assertEqual(int(self.probe_plain["video"]["nb_frames"]), want_frames)

        dur_all = float(self.probe_all["audio"]["duration"])
        dur_plain = float(self.probe_plain["audio"]["duration"])
        self.assertLessEqual(
            abs(dur_all - dur_plain), 1.0 / 48.0,
            msg=f"durasi audio selisih {abs(dur_all - dur_plain)} > 1/48 s",
        )

    # -----------------------------------------------------------------------
    # (d) Urutan filter: panel tier-1 -> fx subtitles -> pratinjau -> caption
    # -----------------------------------------------------------------------

    def test_d_filter_chain_order(self) -> None:
        """(d) Urutan: panel tier-1 -> fx subtitles -> (pratinjau) -> caption subtitles."""
        captured_cmds: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess:
            captured_cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        test_clip = {
            "id": "clip_order_test",
            "segments": [{"src_start": 0.0, "src_end": 4.0, "speed": 1.0}],
            "reframe": {"mode": "center"},
            "punch": [],
            "progress": False,
            "captions": [{"start": 0.5, "end": 2.5, "text": "CAP", "words": [{"word": "CAP", "start": 0.5, "end": 1.0}]}],
            "overlays": [
                # Tier-1 panel
                {"type": "vs", "start": 0.2, "end": 2.5, "left": "Kopi", "right": "Teh"},
                # Tier-2 fx
                {"type": "zoom_through_text", "start": 0.5, "end": 2.0, "props": {"text": "5 JAM"}},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_wd = Path(tmp).resolve()
            (tmp_wd / "src.mp4").write_bytes(b"")
            with (
                mock.patch.object(render.subprocess, "run", side_effect=fake_run),
                mock.patch.object(render.ffmpegbin, "resolve", return_value="/mock/ffmpeg"),
                mock.patch.object(render.motion, "_font_path", return_value="/fonts/mock.ttf"),
            ):
                render.render_clip(
                    EDL, test_clip, tmp_wd, tmp_wd / "out.mp4", preview=True
                )

        self.assertEqual(len(captured_cmds), 1)
        cmd = captured_cmds[0]
        fc_idx = cmd.index("-filter_complex")
        fc = cmd[fc_idx + 1]

        # Pastikan ada tepat satu subtitles fx
        self.assertEqual(fc.count("subtitles=captions/clip_order_test.fx.ass"), 1)

        # Cek urutan: panel -> fx -> preview -> caption
        idx_panel = fc.index("drawtext=fontfile=/fonts/mock.ttf")
        idx_fx = fc.index("subtitles=captions/clip_order_test.fx.ass")
        idx_preview = fc.index("scale=540:960:flags=bilinear")
        idx_caption = fc.index("subtitles=captions/clip_order_test.ass")

        self.assertLess(idx_panel, idx_fx, "panel tier-1 harus mendahului fx subtitles")
        self.assertLess(idx_fx, idx_preview, "fx subtitles harus mendahului pratinjau")
        self.assertLess(idx_preview, idx_caption, "pratinjau harus mendahului caption subtitles")
        # Caption tetap yang paling akhir
        self.assertEqual(fc.rindex("subtitles="), idx_caption)

    # -----------------------------------------------------------------------
    # (e) Peringatan overlay di luar klip dilewati
    # -----------------------------------------------------------------------

    def test_e_overlay_outside_clip_skipped_with_warning_and_others_rendered(self) -> None:
        """(e) Overlay di luar durasi dilewati dengan PERINGATAN:, overlay lain tetap tampil."""
        clip_with_outside = {
            "id": "clip_outside_test",
            "segments": [{"src_start": 0.0, "src_end": CLIP_DUR, "speed": 1.0}],
            "reframe": {"mode": "center"},
            "punch": [],
            "progress": False,
            "captions": [],
            "overlays": list(self.overlays_all) + [
                # Overlay ke-6: di luar durasi klip 20.0s (start=25.0, end=28.0)
                {
                    "type": "phone_frame",
                    "start": 25.0,
                    "end": 28.0,
                    "props": {
                        "title": "LUAR",
                        "lines": ["Di luar", "Durasi"],
                    },
                }
            ],
        }

        # 1. presets.build_fx_ass menghasilkan tepat satu peringatan untuk overlay[5]
        ass_doc, warnings = presets.build_fx_ass(clip_with_outside, fps=FPS)
        self.assertIsNotNone(ass_doc)
        assert ass_doc is not None
        self.assertEqual(len(warnings), 1)
        self.assertIn("overlay[5] tipe 'phone_frame'", warnings[0])
        self.assertIn("sepenuhnya di luar durasi klip", warnings[0])

        # Dokumen tetap memuat 57 Dialogue dari 5 preset lainnya
        dialogues = [line for line in ass_doc.splitlines() if line.startswith("Dialogue: ")]
        self.assertEqual(len(dialogues), 57)

        # 2. render_clip mencetak awalan PERINGATAN: ke stderr
        captured_stderr = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch("sys.stderr", captured_stderr),
        ):
            tmp_wd = Path(tmp).resolve()
            (tmp_wd / "src.mp4").write_bytes(self.src_mp4.read_bytes())
            out_test = tmp_wd / "out_test.mp4"
            render.render_clip(EDL, clip_with_outside, tmp_wd, out_test)

        stderr_output = captured_stderr.getvalue()
        self.assertIn("PERINGATAN:", stderr_output)
        self.assertIn("overlay[5] tipe 'phone_frame'", stderr_output)
        self.assertIn("sepenuhnya di luar durasi klip", stderr_output)
