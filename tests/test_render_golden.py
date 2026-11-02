"""Golden perintah ffmpeg tier-1: pagar yang membuktikan caption frasa tidak berubah.

Kenapa ada: Langkah 3b-ii menambah penulis ASS kinetic, pemilihan biner ffmpeg,
dan pratinjau ke `render.py`. Tier-1 (caption frasa) HARUS menghasilkan perintah
ffmpeg yang sama persis seperti sebelum perubahan. Satu-satunya cara membuktikan
itu adalah mengunci perintahnya sebagai hash dan menghitung hash itu pada kode
TAK TERUBAH.

Cara kerja: `render.render_clip` dipanggil dengan `subprocess.run` di-patch,
sehingga tidak ada ffmpeg yang dijalankan; yang ditangkap hanya `cmd`. Berkas
sumber cukup berupa berkas kosong karena kode hanya memeriksa `exists()`.

Yang di-hash adalah `cmd[1:]`, BUKAN `cmd`: `cmd[0]` menjadi biner ffmpeg
terpilih (bagian 2 tugas) dan itu bergantung mesin. Sisa argumen tidak boleh
berubah sama sekali.

Dua hal yang membuat hash bisa dibandingkan antar-mesin:

* Akar direktori kerja sementara diganti token `<WD>` sebelum di-hash. Tanpa
  itu hash bergantung pada nama direktori acak `tempfile` dan tidak bisa
  dijadikan konstanta. Jumlah kemunculan token diperiksa (harus tepat 2: jalur
  sumber `-i` dan jalur keluaran), jadi penggantian tidak bisa menyembunyikan
  jalur yang hilang.
* `motion._font_path` di-patch ke nilai tetap. Tanpa patch, panel `vs` hanya
  muncul di mesin yang punya DejaVu (jalur `motion.FONT_CANDIDATES`), sehingga
  perintahnya berbeda antara macOS dan Linux — dan overlay `vs` tidak akan
  ikut terkunci di mesin ini.

Nilai GOLDEN_CMD / GOLDEN_CMD_FONTSDIR / GOLDEN_ASS dihitung pada kode
`scripts/render.py` SEBELUM perubahan Langkah 3b-ii, di dua proses Python
berbeda (venv tugas dan `python3` sistem), dan hasilnya identik.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.helpers import ROOT  # noqa: F401  (memasukkan akar repo ke sys.path)

from scripts import render

# --- konstanta golden (dihitung pada kode tier-1 TAK TERUBAH) ---------------

GOLDEN_CMD = "5522506da5397c88a2aa71c01e5b58e4beb1a2379a22db0cdc76290683e7df28"
GOLDEN_CMD_FONTSDIR = "80a382ba2c18d2709204a6ce19999e5efb4f11e5dcec56ea39b58be824003781"
GOLDEN_ASS = "83c668373ffee9f2cd096b83de7f83bb26f8e58e8df877e242f8553bc7d095fb"

# Font tetap untuk panel `vs`, supaya golden tidak bergantung font sistem.
FIXED_FONT = "/fonts/DejaVuSans-Bold.ttf"

# EDL kecil: dua segmen (jalur trim/concat), audio 48 kHz, fps 30.
EDL: dict[str, Any] = {
    "version": "0.1.0",
    "source": {
        "path": "src.mp4",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "audio_rate": 48000,
    },
    "output": {"fps": 30.0, "loudness_lufs": -14.0, "true_peak_db": -1.0},
}

# Klip tier-1: punch satu entri (tanpa zoompan), progress bar, satu panel VS,
# dua caption frasa dengan satu kata emphasis.
CLIP: dict[str, Any] = {
    "id": "clip_01",
    "segments": [
        {"src_start": 0.0, "src_end": 2.0, "speed": 1.0},
        {"src_start": 3.0, "src_end": 5.0, "speed": 1.0},
    ],
    "reframe": {"mode": "center"},
    "punch": [{"t": 0.0, "scale": 1.0}],
    "progress": True,
    "overlays": [
        {"type": "vs", "start": 0.5, "end": 2.5, "left": "Kopi", "right": "Teh"}
    ],
    "captions": [
        {"start": 0.20, "end": 1.60, "text": "Kopi atau teh", "emphasis": "teh"},
        {"start": 1.80, "end": 3.40, "text": "pilih salah satu."},
    ],
}

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(cmd, 0, "", "")

def _canonical(cmd: list[str], root: Path) -> str:
    """JSON `cmd[1:]` dengan akar direktori sementara diganti `<WD>`."""
    raw = json.dumps(cmd[1:], ensure_ascii=False)
    return raw.replace(str(root), "<WD>")

def capture(root: Path, fontsdir: str | None = None) -> tuple[list[str], str, str]:
    """Jalankan `render_clip` tanpa ffmpeg; balikkan (cmd, cmd kanonik, ASS)."""
    captured: list[list[str]] = []

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        captured.append(list(cmd))
        return _fake_run(cmd, **kwargs)

    patches = [
        mock.patch.object(render.subprocess, "run", side_effect=run),
        mock.patch.object(render.motion, "_font_path", return_value=FIXED_FONT),
    ]
    # `ffmpegbin` baru ada setelah Langkah 3b-ii. Patch bila ada supaya tes ini
    # tetap sah di kode sebelum dan sesudah perubahan (deteksi biner asli akan
    # memanggil subprocess.run yang sedang di-patch dan selalu gagal).
    ffmpegbin = getattr(render, "ffmpegbin", None)
    if ffmpegbin is not None:
        patches.append(mock.patch.object(ffmpegbin, "resolve", return_value="/fake/ffmpeg"))

    for p in patches:
        p.start()
    try:
        render.render_clip(
            EDL,
            CLIP,
            root,
            root / "out" / "clip_01.mp4",
            fontsdir=fontsdir,
        )
    finally:
        for p in reversed(patches):
            p.stop()

    if len(captured) != 1:
        raise AssertionError(f"subprocess.run dipanggil {len(captured)} kali, harus 1")
    cmd = captured[0]
    ass = (root / "captions" / "clip_01.ass").read_text(encoding="utf-8")
    return cmd, _canonical(cmd, root), ass

class RenderGoldenTier1Test(unittest.TestCase):
    """Perintah ffmpeg + ASS tier-1 terkunci byte demi byte."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "src.mp4").write_bytes(b"")  # hanya perlu `exists()`

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cmd_matches_golden(self) -> None:
        _cmd, canon, _ass = capture(self.root)
        self.assertEqual(
            canon.count("<WD>"), 2,
            msg=f"jalur sumber/keluaran tidak terkanonikalisasi: {canon}",
        )
        self.assertEqual(_sha(canon), GOLDEN_CMD, msg=canon)

    def test_ass_matches_golden(self) -> None:
        _cmd, _canon, ass = capture(self.root)
        self.assertEqual(_sha(ass), GOLDEN_ASS, msg=ass)

    def test_fontsdir_cmd_matches_golden(self) -> None:
        _cmd, canon, _ass = capture(self.root, fontsdir="/x")
        self.assertIn(":fontsdir=/x", canon)
        self.assertEqual(_sha(canon), GOLDEN_CMD_FONTSDIR, msg=canon)

    def test_golden_contains_expected_pieces(self) -> None:
        """Pengaman: golden bukan hash dari perintah kosong/rusak."""
        _cmd, canon, _ass = capture(self.root)
        for needle in (
            "-filter_complex",
            "trim=start=0.000:end=2.000",
            "trim=start=3.000:end=5.000",
            "concat=n=2:v=1:a=0",
            "zoompan",
            "drawbox=x=0:y=0:w=iw:h=8",
            "drawtext=fontfile=/fonts/DejaVuSans-Bold.ttf",
            "subtitles=captions/clip_01.ass",
            "-fps_mode",
            "cfr",
            "-movflags",
            "+faststart",
        ):
            if needle == "zoompan":
                self.assertNotIn(needle, canon, msg="punch satu entri tidak boleh zoompan")
                continue
            self.assertIn(needle, canon, msg=needle)

if __name__ == "__main__":
    unittest.main()
