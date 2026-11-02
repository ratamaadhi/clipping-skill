"""Tes pengukuran memori pohon proses.

Kenapa pohon, bukan satu proses: Remotion menjalankan Node lalu Chromium sebagai
anak. `/usr/bin/time -v` hanya melaporkan satu proses terbesar, sehingga pemakaian
sebenarnya bisa dua kali lipat dari yang terlihat.
"""

from __future__ import annotations

import subprocess
import sys
import time
import unittest

from scripts.lib import procmem

ALLOC = "b=bytearray({mb}*1024*1024); import time; time.sleep(30)"


class TreeRssTest(unittest.TestCase):
    def test_includes_child_allocation(self) -> None:
        p = subprocess.Popen([sys.executable, "-c", ALLOC.format(mb=150)])
        try:
            time.sleep(1.2)
            rss = procmem.tree_rss_mb(p.pid)
            self.assertGreaterEqual(rss, 140.0, f"terbaca {rss:.0f} MB")
        finally:
            p.kill()
            p.wait()

    def test_missing_process_returns_zero(self) -> None:
        self.assertEqual(procmem.tree_rss_mb(999999), 0.0)

    def test_sums_descendants(self) -> None:
        # induk ringan yang punya satu anak berat
        code = (
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c','{ALLOC.format(mb=120)}']);"
            "time.sleep(30)"
        )
        p = subprocess.Popen([sys.executable, "-c", code])
        try:
            time.sleep(1.5)
            rss = procmem.tree_rss_mb(p.pid)
            self.assertGreaterEqual(rss, 110.0, f"anak tidak terhitung: {rss:.0f} MB")
        finally:
            subprocess.run(["pkill", "-P", str(p.pid)], check=False)
            p.kill()
            p.wait()


class EnforceTest(unittest.TestCase):
    def test_kills_tree_over_limit(self) -> None:
        p = subprocess.Popen([sys.executable, "-c", ALLOC.format(mb=120)])
        try:
            start = time.time()
            killed = procmem.enforce(p.pid, limit_mb=80, interval=0.1, timeout=5.0)
            elapsed = time.time() - start
            self.assertTrue(killed, "watchdog tidak membunuh")
            self.assertLess(elapsed, 2.0, f"terlalu lambat: {elapsed:.1f}s")
        finally:
            p.kill()
            p.wait()

    def test_leaves_small_tree_alive(self) -> None:
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.0)"])
        try:
            killed = procmem.enforce(p.pid, limit_mb=4096, interval=0.1, timeout=0.6)
            self.assertFalse(killed)
            self.assertIsNone(p.poll())
        finally:
            p.kill()
            p.wait()


class SystemInfoTest(unittest.TestCase):
    def test_mem_available_positive(self) -> None:
        self.assertGreater(procmem.mem_available_mb(), 0.0)

    def test_swap_counters_are_ints(self) -> None:
        pin, pout = procmem.swap_counters()
        self.assertIsInstance(pin, int)
        self.assertIsInstance(pout, int)
        self.assertGreaterEqual(pin, 0)
        self.assertGreaterEqual(pout, 0)


if __name__ == "__main__":
    unittest.main()
