"""Karakterisasi tier-1: EDL default tidak boleh berubah satu byte pun.

Hash di bawah dihitung pada kode SEBELUM Langkah 2 (dua proses terpisah,
nilai identik) dan dikunci di sini. Kalau tes ini merah, ada perubahan yang
bocor ke jalur tier-1 — bukan tesnya yang perlu diperbarui.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_work

from scripts.lib import jsonio

# sha256(json.dumps(edl, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
# dari make_work(tmp, top_n=10, top=3) pada HEAD sebelum Langkah 2.
GOLDEN = "605a3efabdae674da232565a52fb1da6dee55dd7a1c16e5ac88f210f1a751860"


def canonical_hash(edl: dict) -> str:
    blob = json.dumps(edl, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Tier1GoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = make_work(Path(cls._tmp.name), top_n=10, top=3)
        cls.edl = jsonio.read_json(cls.wd / "edl.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_edl_matches_golden_hash(self) -> None:
        self.assertEqual(canonical_hash(self.edl), GOLDEN)

    def test_two_builds_in_different_dirs_are_identical(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            wd2 = make_work(Path(other), top_n=10, top=3)
            edl2 = jsonio.read_json(wd2 / "edl.json")
        self.assertEqual(canonical_hash(edl2), canonical_hash(self.edl))

    def test_edl_bytes_are_stable(self) -> None:
        """Dua tulisan berturut-turut ke direktori berbeda: byte file sama."""
        with tempfile.TemporaryDirectory() as other:
            wd2 = make_work(Path(other), top_n=10, top=3)
            a = (self.wd / "edl.json").read_bytes()
            b = (wd2 / "edl.json").read_bytes()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
