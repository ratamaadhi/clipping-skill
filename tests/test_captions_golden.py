"""Karakterisasi tier-1: `captions.build_ass` tidak boleh berubah satu byte pun.

Langkah 3b-i menyentuh pipeline caption (menambah penulis ASS kinetic), jadi
jalur tier-1 dikunci lebih dulu. Hash di bawah dihitung pada kode yang BELUM
diubah, di dua proses python berbeda (venv pekerja dan `python3` sistem),
nilainya identik. Kalau tes ini merah: ada perubahan yang bocor ke tier-1,
bukan tesnya yang perlu diperbarui.

Input sengaja memuat tiga kasus yang paling mudah rusak oleh refactor:
  * emphasis (kata beraksen + `{\\r}`),
  * `{`, `}` dan `\\` di teks (jalur escape),
  * koma dan angka (koma aman karena `Text` adalah field ke-10).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest

from tests.helpers import ROOT  # noqa: F401

from scripts import captions as cap

# sha256 dari captions.build_ass(CAPTIONS) pada HEAD sebelum Langkah 3b-i.
GOLDEN = "5472ee9887a7627af5812672b95f513bf060c18a55b715bc70366bd14523b207"

CAPTIONS: list[dict] = [
    {
        "start": 0.0,
        "end": 1.4,
        "text": "Pertama, pasti nenekmu bangga.",
        "emphasis": "pasti",
    },
    {
        "start": 1.5,
        "end": 2.9,
        "text": "Jangan {pernah} bilang \\ tidak bisa.",
        "emphasis": "jangan",
    },
    {"start": 3.0, "end": 4.25, "text": "angka 2026 dan 3,5 persen"},
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Skrip anak: dijalankan di proses python lain supaya determinisme lintas
# proses (bukan hanya lintas panggilan) benar-benar diuji.
_CHILD = """
import hashlib, sys
sys.path.insert(0, {root!r})
from scripts import captions as cap
from tests.test_captions_golden import CAPTIONS
print(hashlib.sha256(cap.build_ass(CAPTIONS).encode("utf-8")).hexdigest())
"""


class CaptionsGoldenTest(unittest.TestCase):
    def test_build_ass_matches_golden_hash(self) -> None:
        self.assertEqual(_sha(cap.build_ass(CAPTIONS)), GOLDEN)

    def test_two_calls_are_byte_identical(self) -> None:
        self.assertEqual(cap.build_ass(CAPTIONS), cap.build_ass(CAPTIONS))

    def test_deterministic_across_processes(self) -> None:
        """Dua proses python berbeda (venv pekerja & `python3`) -> hash sama."""
        code = _CHILD.format(root=str(ROOT))
        hashes = set()
        for exe in (sys.executable, "python3"):
            out = subprocess.run(
                [exe, "-c", code],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(
                out.returncode,
                0,
                msg=f"{exe} gagal: {out.stderr.strip()[:800]}",
            )
            hashes.add(out.stdout.strip())
        self.assertEqual(hashes, {GOLDEN})

    def test_emphasis_and_escape_survive(self) -> None:
        """Gerbang cepat: dua perilaku tier-1 yang paling mudah rusak."""
        ass = cap.build_ass(CAPTIONS)
        self.assertIn(f"{{\\c{cap.ACCENT}\\fscx112\\fscy112}}PASTI{{\\r}}", ass)
        # Escape tier-1: `{`->`(`, `}`->`)`, `\`->`/`. Emphasis membungkus
        # "JANGAN", jadi yang diperiksa adalah sisa kalimatnya.
        self.assertIn(" (PERNAH) BILANG / TIDAK BISA.", ass)
        self.assertNotIn("{PERNAH}", ass)
        self.assertNotIn("}PERNAH{", ass)


if __name__ == "__main__":
    unittest.main()
