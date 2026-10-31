"""Chunking audio panjang + merge timestamp tanpa drift.

Kenapa perlu chunk walau file muat:
  * satu kegagalan request membuang seluruh transkrip
  * loop halusinasi Whisper menjalar di audio sangat panjang
  * kuota per jam (ASH) lebih baik dipakai bertahap

Aturan anti-drift:
  * potong dari WAV 16k (seek akurat sampai level sampel), JANGAN `-c copy` dari
    mp3/aac — encoder delay memberi drift puluhan ms
  * offset chunk = posisi sampel / 16000, eksak
  * kata diambil dari chunk yang "memilikinya" berdasarkan titik tengah kata,
    sehingga kata yang terpotong di tepi tidak pernah terpilih dua kali
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TARGET = 600.0  # detik per chunk
DEFAULT_OVERLAP = 5.0   # detik tumpang tindih
SILENCE_SEARCH = 60.0   # jendela pencarian jeda di sekitar target


@dataclass(frozen=True)
class Chunk:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def _silence_midpoints(silences: list[tuple[float, float]]) -> list[float]:
    return [round((s + e) / 2.0, 3) for s, e in silences if e > s]


def plan(
    duration: float,
    target: float = DEFAULT_TARGET,
    overlap: float = DEFAULT_OVERLAP,
    search: float = SILENCE_SEARCH,
    silences: list[tuple[float, float]] | None = None,
) -> list[Chunk]:
    """Bagi durasi jadi chunk. Potongan diusahakan jatuh di tengah jeda bicara."""
    if duration <= 0:
        return [Chunk(0, 0.0, 0.0)]
    if target <= 0:
        raise ValueError("target harus > 0")
    overlap = max(0.0, min(overlap, target * 0.5))

    if duration <= target * 1.05:
        return [Chunk(0, 0.0, round(duration, 3))]

    mids = _silence_midpoints(silences or [])
    chunks: list[Chunk] = []
    pos = 0.0
    idx = 0

    while pos < duration:
        end = min(pos + target, duration)

        if end >= duration - 1e-6:
            chunks.append(Chunk(idx, round(pos, 3), round(duration, 3)))
            break

        # geser batas ke jeda terdekat, tapi jangan memotong terlalu pendek
        if mids:
            window = [m for m in mids if abs(m - end) <= search]
            if window:
                candidate = min(window, key=lambda m: abs(m - end))
                if candidate > pos + target * 0.5:
                    end = candidate

        chunks.append(Chunk(idx, round(pos, 3), round(end, 3)))
        nxt = end - overlap
        if nxt <= pos:  # jaring pengaman anti loop
            nxt = pos + target * 0.5
        pos = nxt
        idx += 1

        if idx > 10_000:
            raise RuntimeError("perencanaan chunk tidak konvergen")

    return chunks


def cuts(chunks: list[Chunk]) -> list[float]:
    """Titik milik antar chunk = tengah wilayah tumpang tindih."""
    out = []
    for a, b in zip(chunks, chunks[1:]):
        out.append(round((b.start + a.end) / 2.0, 3))
    return out


def merge(
    per_chunk_words: list[list[dict]],
    chunks: list[Chunk],
) -> list[dict]:
    """Gabungkan kata dari banyak chunk, tanpa duplikat dan tanpa drift.

    Setiap kata dipakai oleh chunk yang titik tengahnya berada di wilayah milik
    chunk tersebut. Karena cut selalu >= overlap/2 dari tepi, kata yang terpotong
    di boundary tidak pernah ikut terpilih dari dua sisi.
    """
    if len(per_chunk_words) != len(chunks):
        raise ValueError("jumlah hasil per chunk tidak cocok dengan jumlah chunk")

    boundaries = cuts(chunks)
    merged: list[dict] = []

    for i, (words, chunk) in enumerate(zip(per_chunk_words, chunks)):
        lo = boundaries[i - 1] if i > 0 else float("-inf")
        hi = boundaries[i] if i < len(boundaries) else float("inf")
        for w in words:
            gs = round(chunk.start + float(w["start"]), 3)
            ge = round(chunk.start + float(w["end"]), 3)
            mid = (gs + ge) / 2.0
            if not (lo <= mid < hi):
                continue
            merged.append({**w, "start": gs, "end": ge})

    merged.sort(key=lambda w: (w["start"], w["end"]))
    merged = _dedupe(merged)
    _normalize_times(merged)

    for i, w in enumerate(merged):
        w["i"] = i
    return merged


def _dedupe(words: list[dict], window: float = 0.30) -> list[dict]:
    """Buang kata berurutan yang identik dan nyaris bersamaan (artefak overlap)."""
    out: list[dict] = []
    for w in words:
        if out:
            prev = out[-1]
            same = str(w["w"]).strip().lower() == str(prev["w"]).strip().lower()
            if same and abs(float(w["start"]) - float(prev["start"])) < window:
                continue
        out.append(w)
    return out


def _normalize_times(words: list[dict], min_dur: float = 0.02) -> None:
    """Paksa monoton dan berdurasi wajar. Timestamp ASR kadang menumpuk di jeda."""
    for w in words:
        start = max(0.0, float(w["start"]))
        end = float(w["end"])
        if end - start < min_dur:
            end = start + min_dur
        w["start"] = round(start, 3)
        w["end"] = round(end, 3)

    for i in range(len(words) - 1):
        if words[i]["end"] > words[i + 1]["start"]:
            words[i]["end"] = round(
                max(words[i]["start"] + min_dur, words[i + 1]["start"]), 3
            )
