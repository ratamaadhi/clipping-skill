"""Ukur memori pohon proses dan matikan kalau melewati batas.

Kenapa pohon: Remotion menjalankan Node yang men-spawn Chromium. `/usr/bin/time -v`
hanya melaporkan satu proses terbesar, jadi pemakaian sebenarnya bisa dua kali lipat
dari yang terlihat. Di mesin ini RAM tersedia hanya ~1,6 GiB, jadi salah ukur =
OOM tanpa peringatan.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

PROC = Path("/proc")


def _children(pid: int) -> list[int]:
    """PID anak langsung. Pakai /proc/<pid>/task/*/children bila tersedia."""
    out: list[int] = []
    base = PROC / str(pid) / "task"
    try:
        for task in base.iterdir():
            f = task / "children"
            if f.exists():
                out.extend(int(tok) for tok in f.read_text().split())
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    if out:
        return out

    # fallback: pindai PPid di /proc/*/stat
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[1]) == pid:
                out.append(int(entry.name))
        except (OSError, IndexError, ValueError):
            continue
    return out


def tree_pids(pid: int) -> list[int]:
    """Semua PID dalam pohon, termasuk akar."""
    seen: list[int] = []
    stack = [pid]
    while stack:
        cur = stack.pop()
        if cur in seen or not (PROC / str(cur)).exists():
            continue
        seen.append(cur)
        stack.extend(_children(cur))
    return seen


def _rss_kb(pid: int) -> int:
    try:
        text = (PROC / str(pid) / "status").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return 0
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def tree_rss_mb(pid: int) -> float:
    """Total RSS pohon proses dalam MB."""
    return sum(_rss_kb(p) for p in tree_pids(pid)) / 1024.0


def _kill_tree(pid: int) -> None:
    pids = tree_pids(pid) or [pid]
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.time() + 1.5
    while time.time() < deadline:
        if not any((PROC / str(p)).exists() for p in pids):
            return
        time.sleep(0.05)
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def enforce(pid: int, limit_mb: float, interval: float = 0.4, timeout: float = 10.0) -> bool:
    """Pantau pohon proses; bunuh kalau RSS melewati limit.

    Mengembalikan True kalau dibunuh, False kalau proses selesai sendiri atau
    waktu habis tanpa melewati batas.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not (PROC / str(pid)).exists():
            return False
        if tree_rss_mb(pid) > limit_mb:
            _kill_tree(pid)
            return True
        time.sleep(interval)
    return False


def mem_available_mb() -> float:
    """MemAvailable dari /proc/meminfo (MB)."""
    try:
        for line in (PROC / "meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024.0
    except (FileNotFoundError, PermissionError):
        pass
    return 0.0


def swap_counters() -> tuple[int, int]:
    """(pswpin, pswpout) kumulatif dalam halaman. Selisihnya menunjukkan thrash."""
    pin = pout = 0
    try:
        for line in (PROC / "vmstat").read_text().splitlines():
            if line.startswith("pswpin "):
                pin = int(line.split()[1])
            elif line.startswith("pswpout "):
                pout = int(line.split()[1])
    except (FileNotFoundError, PermissionError):
        pass
    return pin, pout
