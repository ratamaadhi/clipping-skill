"""Deteksi ffmpeg yang benar-benar punya filter `subtitles` (libass).

Kenapa helper terpisah: ffmpeg Homebrew biasa di mesin pengembang dibangun
TANPA libass (filter `subtitles` dan `ass` tidak ada sama sekali), sedangkan
`ffmpeg-full` punya. Tes oracle harus memakai biner yang benar-benar bisa
membakar ASS; kalau tidak ada, tesnya harus SKIP dengan jujur — bukan lulus
palsu di atas gambar yang tidak pernah memuat teks.

Helper ini TIDAK mengubah PATH atau konfigurasi pengguna. Ia hanya membaca,
berurutan:

1. env `CLIP_FFMPEG` (jalan keluar untuk mesin yang menaruh ffmpeg-full di
   tempat lain),
2. `shutil.which("ffmpeg")`,
3. `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` (Homebrew Apple Silicon),
4. `/usr/local/opt/ffmpeg-full/bin/ffmpeg` (Homebrew Intel).

Kandidat hanya sah bila `-filters` memuat filter bernama persis `subtitles`.
Pencocokan dilakukan pada kolom NAMA filter, bukan substring seluruh baris:
deskripsi filter `ass` berbunyi "Render ASS subtitles onto input video", jadi
pencarian substring akan salah menerima biner tanpa filter `subtitles`.
"""

from __future__ import annotations

import os
import shutil
import subprocess

__all__ = ["FILTER_PROBE_TIMEOUT", "find_ffmpeg_with_libass"]

# Probe `-filters` hanya membaca tabel filter; 30 s sudah sangat longgar.
FILTER_PROBE_TIMEOUT = 30

# Path Homebrew yang lazim. `ffmpeg-full` adalah formula yang dibangun dengan
# libass; formula `ffmpeg` biasa tidak.
_HOMEBREW_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
)

def _has_subtitles_filter(ffmpeg: str) -> bool:
    """True bila `ffmpeg -filters` mencantumkan filter bernama `subtitles`.

    Baris tabel filter berbentuk ` <flag> <nama> <in->out> <deskripsi>`, jadi
    nama filter selalu token kedua. Baris header (`Filters:`, `T.. = Timeline
    support`) tidak punya token kedua yang cocok dan otomatis terlewati.
    """
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            timeout=FILTER_PROBE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    text = proc.stdout.decode("utf-8", errors="replace")
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "subtitles":
            return True
    return False

def find_ffmpeg_with_libass() -> str | None:
    """Path ffmpeg yang punya filter `subtitles`, atau None bila tidak ada.

    Urutan kandidat: `CLIP_FFMPEG`, `shutil.which("ffmpeg")`, lalu dua path
    Homebrew `ffmpeg-full`. Kandidat yang tidak ada / tidak bisa dieksekusi /
    tidak punya filter `subtitles` dilewati. Tidak ada efek samping ke
    lingkungan: PATH tidak diubah dan tidak ada berkas yang ditulis.
    """
    candidates: list[str] = []
    env = os.environ.get("CLIP_FFMPEG", "").strip()
    if env:
        candidates.append(env)
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)
    candidates.extend(_HOMEBREW_CANDIDATES)

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
            continue
        if _has_subtitles_filter(candidate):
            return candidate
    return None
