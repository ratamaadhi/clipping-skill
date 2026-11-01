"""Motion graphics tier-1 — semuanya lewat ffmpeg, tanpa dependency baru.

Empat lapisan:
  1. punch-in     — ganti framing (wide/medium/tight) tiap 2,5–4,5 detik,
                    jatuh di batas atom supaya terasa disengaja, bukan acak
  2. progress bar — indikator durasi di atas frame (retention device)
  3. SFX          — hit pendek di setiap punch, disintesis sendiri (bebas lisensi)
  4. overlay      — panel VS untuk klip yang membandingkan dua hal

Prinsip: semua lapisan hanya mengubah tampilan, TIDAK mengubah timing.
Jadi caption di EDL tetap valid tanpa perlu dihitung ulang.

Kenapa zoompan dan bukan potong-lalu-concat: zoompan satu pass, tidak menambah
generasi encoding kedua, dan durasi output tetap identik dengan input.
"""

from __future__ import annotations

import array
import math
import random
import re
import wave
from pathlib import Path
from typing import Any

# Framing yang dipakai bergantian. 1.0 = wide (crop penuh), >1 = lebih ketat.
PUNCH_SCALES = (1.0, 1.14, 1.0, 1.20)
MIN_PUNCH_GAP = 2.5
MAX_PUNCH_GAP = 4.5

PROGRESS_H = 8
PROGRESS_TRACK = "black@0.35"
PROGRESS_FILL = "0x00E5FF"

SFX_RATE = 48000
SFX_GAIN_DB = -19.0

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


# ---------------------------------------------------------------------------
# 1. Punch-in
# ---------------------------------------------------------------------------


def punch_schedule(
    boundaries: list[float],
    duration: float,
    min_gap: float = MIN_PUNCH_GAP,
    max_gap: float = MAX_PUNCH_GAP,
) -> list[dict[str, Any]]:
    """Jadwal punch dari batas atom.

    `boundaries` = waktu relatif klip (detik) di mana kalimat berganti.
    Punch dipasang di batas terdekat setelah min_gap, dipaksa sebelum max_gap.
    """
    if duration <= 0:
        return [{"t": 0.0, "scale": 1.0}]

    schedule: list[dict[str, Any]] = [{"t": 0.0, "scale": PUNCH_SCALES[0]}]
    last = 0.0
    idx = 1

    for b in sorted(boundaries):
        if b <= last + 1e-6 or b >= duration - 0.4:
            continue
        if b - last < min_gap:
            continue
        if b - last > max_gap:
            b = last + max_gap
        schedule.append({"t": round(b, 3), "scale": PUNCH_SCALES[idx % len(PUNCH_SCALES)]})
        last = b
        idx += 1
        if last >= duration - 0.4:
            break

    # kalau masih ada sisa panjang tanpa punch, paksa di max_gap
    while duration - last > max_gap:
        last = round(last + max_gap, 3)
        schedule.append({"t": last, "scale": PUNCH_SCALES[idx % len(PUNCH_SCALES)]})
        idx += 1

    return schedule


def zoom_expression(schedule: list[dict[str, Any]], fps: float) -> str:
    """Ekspresi zoompan: skala berubah menurut nomor frame input (`in`)."""
    if len(schedule) <= 1:
        return "1.0"

    frames = [max(0, int(round(float(p["t"]) * fps))) for p in schedule]
    scales = [float(p["scale"]) for p in schedule]

    expr = f"{scales[-1]:.4f}"
    for i in range(len(frames) - 2, -1, -1):
        expr = f"if(lt(in,{frames[i + 1]}),{scales[i]:.4f},{expr})"
    return expr


def zoompan_filter(schedule: list[dict[str, Any]], fps: float, width: int, height: int) -> str | None:
    if len(schedule) <= 1:
        return None
    expr = zoom_expression(schedule, fps)
    return (
        f"zoompan=z='{expr}'"
        f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={width}x{height}:fps={fps:g}"
    )


# ---------------------------------------------------------------------------
# 2. Progress bar
# ---------------------------------------------------------------------------
# Catatan penting: `drawbox` mengevaluasi w/h SEKALI saat init, jadi
# `w='iw*t/DUR'` akan menghasilkan bar selebar frame sejak detik nol.
# Yang bekerja per-frame adalah `overlay` dengan ekspresi `x`.
# Jadi: track statis pakai drawbox, isi yang bergerak pakai overlay.


def progress_track_filter(height: int = PROGRESS_H) -> str:
    """Latar bar statis selebar frame."""
    return (
        f"drawbox=x=0:y=0:w=iw:h={height}"
        f":color={PROGRESS_TRACK}:t=fill"
    )


def progress_fill_source(
    duration: float, fps: float, width: int, height: int = PROGRESS_H
) -> str:
    """Sumber warna untuk isi bar. Dipakai sebagai input kedua di filter_complex."""
    if duration <= 0:
        return ""
    return (
        f"color=c={PROGRESS_FILL}:s={width}x{height}"
        f":r={fps:g}:d={duration:.3f}[bar]"
    )


def progress_fill_overlay(duration: float) -> str:
    """Overlay yang menggeser isi bar dari kiri ke kanan sepanjang klip."""
    if duration <= 0:
        return ""
    return f"overlay=x='-w+w*t/{duration:.3f}':y=0:shortest=1"


# ---------------------------------------------------------------------------
# 3. SFX (disintesis, bebas lisensi)
# ---------------------------------------------------------------------------


def _hit(rate: int = SFX_RATE) -> list[float]:
    n = int(rate * 0.085)
    out = []
    for i in range(n):
        t = i / rate
        env = math.exp(-t * 42.0)
        s = 0.62 * math.sin(2 * math.pi * 132.0 * t) + 0.24 * math.sin(2 * math.pi * 264.0 * t)
        out.append(env * s)
    return out


def _whoosh(rate: int = SFX_RATE, seed: int = 7) -> list[float]:
    rnd = random.Random(seed)
    n = int(rate * 0.20)
    out = []
    prev = 0.0
    for i in range(n):
        t = i / rate
        x = rnd.uniform(-1.0, 1.0)
        prev = prev + 0.10 * (x - prev)  # low-pass sederhana
        env = math.sin(math.pi * t / (n / rate)) ** 1.6
        out.append(prev * env * 1.35)
    return out


def write_sfx_wav(
    path: str | Path,
    events: list[dict[str, Any]],
    duration: float,
    rate: int = SFX_RATE,
) -> Path | None:
    """Tulis satu track SFX: senyap sepanjang klip, dengan hit di titik event."""
    if not events or duration <= 0:
        return None

    total = int(rate * duration) + 1
    buf = [0.0] * total
    cache = {"hit": _hit(rate), "whoosh": _whoosh(rate)}

    for ev in events:
        kind = str(ev.get("kind", "hit"))
        samples = cache.get(kind) or cache["hit"]
        start = int(max(0.0, float(ev.get("t", 0.0))) * rate)
        gain = 10.0 ** (float(ev.get("gain_db", SFX_GAIN_DB)) / 20.0)
        for i, s in enumerate(samples):
            j = start + i
            if j >= total:
                break
            buf[j] += s * gain

    peak = max((abs(v) for v in buf), default=0.0)
    if peak > 0.95:
        buf = [v * (0.95 / peak) for v in buf]

    pcm = array.array("h", (int(max(-1.0, min(1.0, v)) * 32767) for v in buf))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(pcm.tobytes())
    return out


# ---------------------------------------------------------------------------
# 4. Overlay panel (VS)
# ---------------------------------------------------------------------------

_VS_PATTERN = re.compile(
    r"\b([A-Z][\w.+-]{1,18})\s+(?:atau|vs\.?|versus|dibanding(?:kan)?)\s+([A-Z][\w.+-]{1,18})\b"
)

# Kata berhuruf kapital yang bukan nama — jangan dianggap entitas.
_VS_STOPWORDS = frozenset(
    w.lower()
    for w in (
        "Jika", "Atau", "Tapi", "Dan", "Yang", "Ini", "Itu", "Anda", "Saya",
        "Mereka", "Kita", "Kami", "Orang", "Mungkin", "Jadi", "Namun", "Tetapi",
        "Karena", "Dengan", "Untuk", "Dalam", "Pada", "Dari", "Ada", "Tidak",
        "Bukan", "Semua", "Setiap", "Banyak", "Satu", "Dua", "Pertama", "Kedua",
        "Meskipun", "Walaupun", "Namun", "Sedangkan", "Sementara",
    )
)

# Prefiks turunan Indonesia (verba/nominal). Kata seperti "Membatasi" atau
# "Memblokir" berhuruf kapital di awal kalimat, tapi jelas bukan nama entitas.
_VERB_PREFIX = re.compile(r"^(me|mem|men|meng|meny|ber|be|di|ter|pe|per)[a-z]", re.IGNORECASE)


def _looks_like_entity(word: str) -> bool:
    if word.lower() in _VS_STOPWORDS:
        return False
    if len(word) >= 6 and _VERB_PREFIX.match(word):
        return False
    return True


def detect_vs(text: str) -> tuple[str, str] | None:
    """Cari pasangan yang dibandingkan.

    Sengaja case-sensitive: hanya nama diri (huruf kapital) yang dianggap entitas.
    Pola longgar tanpa case membuat "ini atau itu" ikut terdeteksi sebagai VS.
    """
    for match in _VS_PATTERN.finditer(text):
        left, right = match.group(1), match.group(2)
        if left.lower() == right.lower():
            continue
        if not _looks_like_entity(left) or not _looks_like_entity(right):
            continue
        return left, right
    return None


def _font_path() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _safe_text(text: str) -> str:
    """drawtext mudah rusak oleh karakter khusus — sisakan yang aman saja."""
    cleaned = re.sub(r"[^A-Za-z0-9 ._+-]", "", text).strip()
    return cleaned[:18] or "?"


def overlay_filters(overlays: list[dict[str, Any]]) -> list[str]:
    """Panel VS sederhana: dua kotak, dua label, teks VS di tengah."""
    filters: list[str] = []
    font = _font_path()
    if not font:
        return filters

    for ov in overlays:
        if ov.get("type") != "vs":
            continue
        start = float(ov.get("start", 0.0))
        end = float(ov.get("end", start + 3.0))
        left_raw = str(ov.get("left", "")).strip()
        right_raw = str(ov.get("right", "")).strip()
        if not left_raw or not right_raw:
            continue
        left = _safe_text(left_raw)
        right = _safe_text(right_raw)

        window = f"between(t,{start:.2f},{end:.2f})"
        # slide-in 0.25s dari kiri/kanan
        slide = 0.25
        lx = f"if(lt(t,{start + slide:.2f}),-460+460*(t-{start:.2f})/{slide:.2f},40)"
        rx = f"if(lt(t,{start + slide:.2f}),1100-460*(t-{start:.2f})/{slide:.2f},590)"

        filters.append(
            f"drawbox=x='{lx}':y=470:w=450:h=104:color=black@0.62:t=fill:enable='{window}'"
        )
        filters.append(
            f"drawbox=x='{rx}':y=470:w=450:h=104:color=black@0.62:t=fill:enable='{window}'"
        )
        filters.append(
            f"drawtext=fontfile={font}:text='{left}':x='{lx}+225-tw/2':y=470+52-th/2"
            f":fontsize=52:fontcolor=white:enable='{window}'"
        )
        filters.append(
            f"drawtext=fontfile={font}:text='{right}':x='{rx}+225-tw/2':y=470+52-th/2"
            f":fontsize=52:fontcolor=0x00E5FF:enable='{window}'"
        )
        filters.append(
            f"drawtext=fontfile={font}:text='VS':x=(w-tw)/2:y=470+52-th/2"
            f":fontsize=46:fontcolor=white:borderw=3:bordercolor=black@0.8:enable='{window}'"
        )
    return filters
