"""Pemilihan biner ffmpeg yang benar-benar punya libass (filter `subtitles`).

Kenapa modul terpisah: `render.py` tidak boleh berisi logika deteksi, dan tes
`tests/ffmpeg_libass.py` sudah membuktikan bahwa `ffmpeg` Homebrew biasa di
mesin pengembang dibangun TANPA libass. Tanpa pemilihan ini, `render` tier-1
pun gagal membakar caption di mesin tersebut.

Urutan kandidat (`resolve`):

1. env `CLIP_FFMPEG` bila diset — WAJIB dipakai apa adanya. Kalau biner itu
   tidak punya libass, `FFmpegError` yang menyebut variabelnya. Tidak boleh
   diam-diam pindah ke kandidat lain: pengguna yang menyetel variabel ini
   sedang menunjuk biner tertentu, dan memakai biner lain membuat hasil render
   berbeda dari yang ia kira.
2. `ffmpeg` di PATH bila punya filter `subtitles`/`ass`.
3. Dua path Homebrew `ffmpeg-full` (Apple Silicon lalu Intel).
4. Tidak ada → `FFmpegError` berisi petunjuk pemasangan.

Pencocokan filter dilakukan pada KOLOM NAMA, bukan substring seluruh baris:
deskripsi filter `ass` berbunyi "Render ASS subtitles onto input video", jadi
pencarian substring akan salah menerima biner yang tidak punya libass.

Hasil probe di-cache per jalur: deteksi memanggil subprocess, dan `render_all`
memanggil `resolve()` untuk setiap klip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Mapping

__all__ = [
    "FILTER_PROBE_TIMEOUT",
    "FFmpegError",
    "HOMEBREW_CANDIDATES",
    "clear_cache",
    "has_subtitles_filter",
    "resolve",
]

# `ffmpeg -filters` hanya membaca tabel filter; 15 s sangat longgar bahkan
# untuk biner yang dijalankan dari disk jaringan. Timeout berarti False.
FILTER_PROBE_TIMEOUT = 15

# Path Homebrew yang lazim. `ffmpeg-full` adalah formula yang dibangun dengan
# libass; formula `ffmpeg` biasa tidak.
HOMEBREW_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
)

# Filter yang membuktikan libass tersedia. `subtitles` adalah yang dipakai
# filtergraph; `ass` diterima karena dibangun dari pustaka yang sama.
_SUBTITLE_FILTERS = frozenset({"subtitles", "ass"})

_INSTALL_HINT = (
    "Pasang dengan `brew install ffmpeg-full` (Apple Silicon: "
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg, Intel: "
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg) atau set env CLIP_FFMPEG ke path "
    "ffmpeg berlibass. Formula `ffmpeg` Homebrew biasa dibangun tanpa libass."
)

class FFmpegError(RuntimeError):
    """ffmpeg tidak ditemukan atau tidak bisa membakar subtitle."""

# jalur -> bool. Cache sengaja per jalur (bukan satu nilai) supaya tes bisa
# membandingkan biner baik dan buruk dalam satu proses.
_FILTER_CACHE: dict[str, bool] = {}

def clear_cache() -> None:
    """Kosongkan cache probe. Dipakai tes; tidak dipanggil kode produksi."""
    _FILTER_CACHE.clear()

def _probe_timeout(timeout: float | None) -> float:
    return FILTER_PROBE_TIMEOUT if timeout is None else float(timeout)

def _run_filters(path: str, timeout: float) -> str | None:
    try:
        proc = subprocess.run(
            [path, "-hide_banner", "-filters"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace")

def _parse_filter_names(text: str) -> set[str]:
    """Ambil KOLOM NAMA dari tabel `ffmpeg -filters`.

    Baris tabel berbentuk ` <flag> <nama> <in->out> <deskripsi>`, jadi nama
    selalu token kedua. Baris header (`Filters:`, `T.. = Timeline support`)
    tidak punya token kedua yang cocok dan otomatis terlewati. Nama dengan
    sufiks `=` (mis. `... = Timeline support`) dibuang.
    """
    names: set[str] = set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and "->" in fields[2]:
            names.add(fields[1])
    return names

def has_subtitles_filter(path: str, timeout: float | None = None) -> bool:
    """True bila `path -filters` mencantumkan filter bernama `subtitles`/`ass`.

    Galat, kode keluar bukan nol, dan timeout semuanya berarti False — bukan
    exception: kandidat yang buruk cukup dilewati.
    """
    key = str(path)
    if key in _FILTER_CACHE:
        return _FILTER_CACHE[key]

    text = _run_filters(key, _probe_timeout(timeout))
    ok = bool(text) and bool(_parse_filter_names(text) & _SUBTITLE_FILTERS)
    _FILTER_CACHE[key] = ok
    return ok

def _executable(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)

def resolve(
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """Path ffmpeg ber-libass, atau `FFmpegError` bila tidak ada.

    `env` dan `which` dapat diganti tes. Pemanggilan dilakukan SAAT RUNTIME
    (di dalam `render_clip`), bukan saat import, supaya perubahan env terbaca.
    """
    environ = os.environ if env is None else env

    raw = (environ.get("CLIP_FFMPEG") or "").strip()
    if raw:
        # Dipakai APA ADANYA. Bila tidak layak, berhenti dengan pesan yang
        # menyebut variabelnya — jangan diam-diam memakai kandidat lain.
        if not _executable(raw):
            raise FFmpegError(
                f"CLIP_FFMPEG menunjuk ke ffmpeg yang tidak ada/tidak bisa "
                f"dieksekusi: {raw}. Perbaiki path-nya atau hapus variabel ini. "
                f"{_INSTALL_HINT}"
            )
        if not has_subtitles_filter(raw):
            raise FFmpegError(
                f"CLIP_FFMPEG menunjuk ke ffmpeg tanpa filter 'subtitles' "
                f"(libass): {raw}. Set CLIP_FFMPEG ke ffmpeg berlibass atau "
                f"hapus variabelnya. {_INSTALL_HINT}"
            )
        return raw

    found = which("ffmpeg")
    if found and _executable(found) and has_subtitles_filter(found):
        return found

    for candidate in HOMEBREW_CANDIDATES:
        if _executable(candidate) and has_subtitles_filter(candidate):
            return candidate

    raise FFmpegError("Tidak ada ffmpeg dengan filter 'subtitles' (libass). " + _INSTALL_HINT)
