"""Generator transkrip sintetis untuk demo dan tes offline.

Tidak butuh video, tidak butuh API key. Dipakai oleh `make demo` dan oleh tes
supaya seluruh pipeline bisa diuji tanpa aset eksternal.
"""

from __future__ import annotations

from typing import Any

# Transkrip contoh: percakapan tech Indonesia dengan struktur yang realistis —
# ada hook pertanyaan, angka, discourse marker, filler, dan penutup.
SCRIPT_PARAGRAPHS: list[str] = [
    "Oke jadi hari ini gue mau bahas satu hal yang mungkin bikin kalian kaget.",
    "Eee jadi ceritanya gue udah nyoba dua tool coding AI selama tiga bulan terakhir.",
    "Pertama itu Codex, kedua itu Claude.",
    "Nah yang menarik itu bedanya bukan di kecepatan, tapi di cara mereka mikir.",
    "Contohnya waktu gue minta bikin endpoint baru, Codex langsung nulis kodenya.",
    "Tapi Claude malah balik nanya dulu, ini datanya dari mana dan siapa yang akses.",
    "Dan menurut gue itu justru yang bikin hasilnya lebih bener.",
    "Jadi intinya gue nemu tiga perbedaan besar yang bikin gue milih salah satunya.",
    "Yang pertama soal konteks, Claude bisa inget delapan file sekaligus tanpa gue ulang.",
    "Yang kedua soal debugging, dia bisa nemu bug yang gue sendiri udah nyerah nyari.",
    "Yang ketiga soal harga, ini yang paling bikin gue mikir ulang.",
    "Emm jadi total biaya gue per bulan itu sekitar dua ratus ribu rupiah.",
    "Kalau pakai yang satunya bisa tiga kali lebih mahal, dan itu gak masuk akal buat gue.",
    "Makanya gue akhirnya pindah total ke Claude bulan lalu.",
    "Tapi jujur ada satu hal yang masih bikin gue kesel sampai sekarang.",
    "Kalau projectnya udah gede banget, dia suka lupa konteks yang tadi udah gue kasih.",
    "Jadi saran gue, kalau kalian baru mulai, jangan langsung pilih yang paling mahal.",
    "Coba dulu yang gratis selama dua minggu, rasain sendiri ritmenya.",
    "Karena tool sebagus apapun tetap balik lagi ke cara kalian kerja.",
    "Oke segitu dulu, kalau kalian punya pengalaman beda tulis di komentar ya.",
]

PUNCT_PAUSE = {",": 0.22, ".": 0.55, "?": 0.60, "!": 0.45, ":": 0.30, ";": 0.30}


def synthesize(
    paragraphs: list[str] | None = None,
    wpm: float = 150.0,
    start: float = 0.0,
) -> dict[str, Any]:
    """Buat transcript.json sintetis dengan timing yang masuk akal."""
    paragraphs = paragraphs or SCRIPT_PARAGRAPHS
    base_word_dur = 60.0 / wpm
    words: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []

    t = start
    idx = 0
    for para in paragraphs:
        seg_start = t
        for token in para.split():
            core = token.rstrip(".,!?:;")
            # durasi proporsional panjang kata, dijepit supaya tidak ekstrem
            dur = max(0.14, min(1.1, base_word_dur * (max(1, len(core)) / 5.2)))
            words.append(
                {
                    "i": idx,
                    "w": token,
                    "start": round(t, 3),
                    "end": round(t + dur, 3),
                    "speaker": 0,
                    "conf": 0.94,
                }
            )
            idx += 1
            t += dur
            last = token[-1] if token else ""
            t += PUNCT_PAUSE.get(last, 0.06)

        segments.append(
            {"start": round(seg_start, 3), "end": round(t, 3), "text": para, "speaker": 0}
        )
        t += 0.35

    return {
        "version": "0.1.0",
        "source": "synthetic://demo",
        "language": "id",
        "duration": round(t, 3),
        "engine": "synthetic",
        "words": words,
        "segments": segments,
    }


def synthetic_selection(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Selection palsu untuk demo — deterministik, cukup untuk menguji jalur kode.

    Bukan penilaian nyata. Di pemakaian sebenarnya, agent yang mengisi ini.
    """
    out = []
    for c in candidates:
        n = int(c["id"])
        # pola deterministik supaya demo bisa diulang
        base = 7.0 - (n % 4) * 0.6
        axes = {
            "hook": base + (0.6 if n % 3 == 0 else -0.4),
            "payoff": base - 0.3,
            "self_contained": base + 0.2,
            "emotional": base - 0.8,
            "concrete": base + 0.1 if c["features"].get("number_count", 0) else base - 0.5,
            "loop": base - 1.4,
        }
        axes = {k: round(max(0.0, min(10.0, v)), 1) for k, v in axes.items()}
        text = str(c["text"]).split()
        quote = " ".join(text[:8]) if text else str(c["text"])[:40]
        out.append(
            {
                "id": n,
                "atom_start": c["atom_start"],
                "atom_end": c["atom_end"],
                "axes": {k: {"score": v, "evidence": quote} for k, v in axes.items()},
                "weakest_axis": min(axes, key=lambda k: axes[k]),
                "fix_suggestion": "tambahkan callback ke pertanyaan pembuka di 2 detik terakhir",
            }
        )
    return {"version": "0.1.0", "candidates": out}
