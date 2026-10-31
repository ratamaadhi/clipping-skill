"""Tokenisasi dan penanda discourse Bahasa Indonesia.

Semua daftar di sini adalah *heuristik awal*, bukan kebenaran linguistik.
Tujuannya menaikkan presisi boundary atom dan memberi fitur murah ke scoring.
Kalibrasi ulang setelah ada data nyata.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Karakter yang dibuang saat normalisasi kata
# ---------------------------------------------------------------------------

PUNCT_STRIP = ".,!?;:\"'()[]{}…—–-“”‘’"

_SENTENCE_END = (".", "!", "?", "…")


# ---------------------------------------------------------------------------
# Discourse markers
# ---------------------------------------------------------------------------

# Presisi tinggi: hampir selalu menandai awal poin baru.
# Boleh memicu boundary tanpa jeda sebelum.
STRONG_MARKERS = frozenset(
    {
        "pertama",
        "kedua",
        "ketiga",
        "keempat",
        "kelima",
        "intinya",
        "poinnya",
        "contohnya",
        "misalnya",
        "sebenernya",
        "sebenarnya",
        "faktanya",
        "kenyataannya",
        "makanya",
        "berikutnya",
        "selanjutnya",
        "singkatnya",
        "kesimpulannya",
        "akhirnya",
        "bayangkan",
        "bayangin",
    }
)

# Presisi rendah: umum, sering muncul di tengah kalimat.
# Hanya memicu boundary bila ada jeda >= MARKER_PAUSE sebelumnya.
WEAK_MARKERS = frozenset(
    {
        "jadi",
        "nah",
        "tapi",
        "tetapi",
        "cuma",
        "oke",
        "karena",
        "soalnya",
        "terus",
        "lalu",
        "sekarang",
        "sementara",
        "padahal",
    }
)

MARKER_PAUSE = 0.15  # detik


# ---------------------------------------------------------------------------
# Disfluency vs particle
# ---------------------------------------------------------------------------

# Disfluency murni — dihitung sebagai filler.
DISFLUENCY = frozenset(
    {
        "eee",
        "ee",
        "eeee",
        "emm",
        "em",
        "ehm",
        "hmm",
        "hm",
        "aa",
        "aaa",
        "eh",
        "uh",
        "uhh",
        "anu",
        "hmmm",
    }
)

# Frasa disfluency multi-kata. Dicek pada teks lowercase penuh.
DISFLUENCY_PHRASES = (
    "apa ya",
    "apa namanya",
    "gimana ya",
    "kayak gitu",
    "gitu deh",
    "gitu ya",
)

# Particle wacana — TIDAK dihitung filler, hanya informatif (formality).
PARTICLES = frozenset(
    {"kan", "sih", "deh", "nih", "tuh", "dong", "lah", "kok", "ya", "pun", "deh"}
)


# ---------------------------------------------------------------------------
# Sinyal "ada poin di sini"
# ---------------------------------------------------------------------------

POINT_MARKERS = frozenset(
    {
        "artinya",
        "intinya",
        "masalahnya",
        "solusinya",
        "bedanya",
        "faktanya",
        "sebenarnya",
        "sebenernya",
        "karena",
        "makanya",
        "jadi",
        "paling",
        "lebih",
        "harus",
        "jangan",
        "salah",
        "benar",
        "bikin",
        "bisa",
        "gak",
        "tidak",
        "nggak",
        "cuma",
        "tapi",
    }
)

QUESTION_WORDS = frozenset(
    {
        "apa",
        "kenapa",
        "mengapa",
        "gimana",
        "bagaimana",
        "kapan",
        "siapa",
        "mana",
        "berapa",
        "apakah",
        "bisakah",
        "bolehkah",
        "mau",
        "pernah",
    }
)

# Kata sambung yang menggantung bila jadi kata pertama sebuah klip.
HANGING_CONJUNCTIONS = frozenset(
    {"dan", "atau", "tapi", "tetapi", "karena", "jadi", "makanya", "soalnya", "terus", "lalu", "namun", "padahal"}
)


# ---------------------------------------------------------------------------
# Fungsi
# ---------------------------------------------------------------------------

_DIGIT_RE = re.compile(r"\d")
_NUMBER_WORD_RE = re.compile(
    r"\b(satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|"
    r"seratus|seribu|sejuta|juta|ribu|persen|perseratus)\b",
    re.IGNORECASE,
)


def clean(word: str) -> str:
    """Kata tanpa tanda baca, lowercase."""
    return word.strip().strip(PUNCT_STRIP).lower()


def is_sentence_end(word: str) -> bool:
    return word.rstrip().endswith(_SENTENCE_END)


def has_digit(text: str) -> bool:
    return bool(_DIGIT_RE.search(text))


def count_numbers(text: str) -> int:
    """Hitung angka eksplisit: digit atau kata bilangan.

    "3x lebih cepat" -> 1, "Rp200 ribu" -> 2 (200 + ribu).
    """
    digits = len(_DIGIT_RE.findall(text))
    words = len(_NUMBER_WORD_RE.findall(text))
    return digits + words



def is_question(text: str) -> bool:
    t = text.strip()
    if t.endswith("?"):
        return True
    words = [clean(w) for w in t.split() if clean(w)]
    return bool(words) and words[0] in QUESTION_WORDS


def count_fillers(text: str) -> int:
    """Hitung disfluency. Frasa multi-kata dihitung sekali lalu dibuang dari teks."""
    low = " " + text.lower() + " "
    n = 0
    for phrase in DISFLUENCY_PHRASES:
        c = low.count(" " + phrase + " ")
        if c:
            n += c
            low = low.replace(" " + phrase + " ", " ")
    for w in low.split():
        if clean(w) in DISFLUENCY:
            n += 1
    return n


def count_particles(text: str) -> int:
    return sum(1 for w in text.split() if clean(w) in PARTICLES)


def starts_with_hanging_conjunction(text: str) -> bool:
    words = [clean(w) for w in text.split() if clean(w)]
    return bool(words) and words[0] in HANGING_CONJUNCTIONS


def has_point_marker(text: str) -> bool:
    return any(clean(w) in POINT_MARKERS for w in text.split())


def word_tokens(text: str) -> list[str]:
    return [w for w in text.split() if clean(w)]


def type_token_ratio(text: str) -> float:
    toks = [clean(w) for w in text.split() if clean(w)]
    if not toks:
        return 0.0
    return len(set(toks)) / len(toks)


def titlecase_upper(text: str) -> str:
    return text.upper()


def shingles(tokens: list[str], n: int = 2) -> set[tuple[str, ...]]:
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}
