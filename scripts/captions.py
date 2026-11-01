"""Caption: grouping kata -> frasa, pemilihan emphasis, dan generate ASS.

Kenapa ASS dan bukan Remotion (docs/DECISIONS.md D-003):
  libass merender caption ~10x lebih cepat dari Chromium per frame dan tidak
  butuh Node di jalur kritis. Motion graphics premium menyusul di v1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .lib import text as T

# Parameter tampilan — satu tempat, gampang diubah.
MAX_WORDS_PER_PHRASE = 4
MAX_PHRASE_DUR = 2.2
GAP_BREAK = 0.45

FONT = "DejaVu Sans"
FONT_SIZE = 66
MARGIN_V = 520
PRIMARY = "&H00FFFFFF"  # putih
ACCENT = "&H0000E5FF"   # kuning (BGR)

PLAY_W = 1080
MAX_LINE_FRAC = 0.90   # caption tidak boleh lebih lebar dari 90% frame
MIN_PHRASE_DUR = 0.75  # di bawah ini mata tidak sempat membaca
MAX_WORD_DUR = 1.2     # timestamp ASR sering melar; satu kata tidak mungkin 2,6 s

# Kata yang menggantung kalau jadi akhir frasa ("Dengan" sendirian).
# Jangan berhenti di sini: tarik satu kata berikutnya.
NO_END_WORDS = frozenset(
    {
        "di", "ke", "dari", "dengan", "yang", "dan", "atau", "untuk", "pada",
        "dalam", "sama", "buat", "kalau", "karena", "sampai", "sampai",
        "terhadap", "tentang", "seperti", "sebagai", "oleh", "buat",
    }
)


def _char_width(ch: str) -> float:
    """Perkiraan lebar karakter dalam em, untuk font sans tebal."""
    if ch == " ":
        return 0.28
    if ch in ".,!?;:'\"()":
        return 0.30
    if ch.isdigit():
        return 0.60
    if ch.isupper():
        return 0.70
    return 0.55


def text_width(text: str, size: int = FONT_SIZE) -> float:
    """Lebar dalam piksel. Caption dirender HURUF BESAR, jadi ukur versi kapital.

    Versi pertama mengukur huruf campur dan hasilnya under-estimate ~30%:
    teks lolos batas di perhitungan tapi terpotong di frame.
    """
    return sum(_char_width(c) for c in text.upper()) * size


def fits_line(text: str, size: int = FONT_SIZE) -> bool:
    return text_width(text, size) <= PLAY_W * MAX_LINE_FRAC


def fits_block(text: str, lines: int = 2, size: int = FONT_SIZE) -> bool:
    """Muat dalam beberapa baris. Dipakai saat menggabung frasa yang terlalu cepat."""
    return text_width(text, size) <= PLAY_W * MAX_LINE_FRAC * lines * 0.95


def _norm(word: str) -> str:
    return "".join(c for c in str(word).lower() if c.isalpha())

# Kata yang layak diangkat. Sengaja sempit: kalau semua kata ditekankan,
# tidak ada yang menonjol. Sisa kata hanya diberi bobot panjang sebagai tie-break.
EMPHATIC_WORDS = frozenset(
    {
        "paling", "harus", "jangan", "gak", "nggak", "tidak", "bukan", "belum",
        "salah", "benar", "cuma", "tapi", "tetapi", "justru", "bahkan", "selalu",
        "apakah", "kenapa", "bagaimana", "gimana", "berapa", "siapa",
    }
)

# Ambang skor minimum supaya emphasis benar-benar selektif.
MIN_EMPHASIS_SCORE = 2.0

# Artefak ASR: kata yang muncul karena model "mendengar" bunyi tic verbal
# ("Eh, ya" -> "Ejaan"). Hanya dibuang kalau berdiri sendiri di awal ujaran,
# supaya "ejaan" yang benar-benar berarti ejaan tetap aman.
ARTIFACT_WORDS = frozenset({"ejaan", "ejaannya"})
ARTIFACT_GAP = 0.25
# Kalau artefak diikuti kata sambung, hampir pasti itu tic verbal, bukan kata asli.
_DISCOURSE_AFTER = frozenset(
    {"dan", "tapi", "jadi", "terus", "atau", "iya", "oh", "ya", "kan", "lalu",
     "karena", "kalau", "makanya", "terusnya", "gitu"}
)


def _drop_artifacts(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Buang artefak ASR dan rapikan durasi kata yang melar."""
    out: list[dict[str, Any]] = []
    for i, w in enumerate(words):
        norm = "".join(c for c in str(w["w"]).lower() if c.isalpha())
        if norm in ARTIFACT_WORDS:
            prev_end = float(words[i - 1]["end"]) if i else -99.0
            gap = float(w["start"]) - prev_end if i else 99.0
            nxt = _norm(words[i + 1]["w"]) if i + 1 < len(words) else ""
            if gap >= ARTIFACT_GAP or not nxt or nxt in _DISCOURSE_AFTER:
                continue
        w = dict(w)
        start = float(w["start"])
        end = float(w["end"])
        if end - start > MAX_WORD_DUR:
            w["end"] = round(start + MAX_WORD_DUR, 3)
        out.append(w)
    return out


def group_words(
    words: list[dict[str, Any]],
    max_words: int = MAX_WORDS_PER_PHRASE,
    max_dur: float = MAX_PHRASE_DUR,
    gap_break: float = GAP_BREAK,
) -> list[dict[str, Any]]:
    """Kelompokkan kata jadi frasa pendek yang enak dibaca.

    Tiga batas yang dijaga sekaligus:
      1. lebar  — diperkirakan dalam piksel, bukan jumlah karakter, supaya
                  kata panjang seperti "Sebenernya" tidak melewati frame
      2. durasi — frasa di bawah MIN_PHRASE_DUR digabung ke tetangganya
      3. frasa  — tidak berakhir di kata sambung ("Dengan" sendirian)
    """
    words = _drop_artifacts(words)
    if not words:
        return []

    def joined(chunk: list[dict[str, Any]]) -> str:
        return " ".join(str(w["w"]).strip() for w in chunk)

    def build(chunk: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "words": list(chunk),
            "start": round(float(chunk[0]["start"]), 3),
            "end": round(float(chunk[-1]["end"]), 3),
            "text": joined(chunk),
        }

    groups: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []

    for w in words:
        if not cur:
            cur = [w]
            continue
        prev = cur[-1]
        gap = float(w["start"]) - float(prev["end"])
        dangling = _norm(prev["w"]) in NO_END_WORDS
        limit = max_words + (1 if dangling else 0)

        candidate = cur + [w]
        too_wide = not fits_line(joined(candidate))
        too_long = (float(w["end"]) - float(cur[0]["start"])) > max_dur

        if gap >= gap_break or T.is_sentence_end(str(prev["w"])) or too_wide or too_long:
            groups.append(cur)
            cur = [w]
        elif len(cur) >= limit:
            groups.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        groups.append(cur)

    # Gabungkan frasa yang terlalu pendek ke tetangganya, boleh sampai dua baris.
    merged: list[list[dict[str, Any]]] = []
    for g in groups:
        if merged:
            prev = merged[-1]
            prev_dur = float(prev[-1]["end"]) - float(prev[0]["start"])
            g_dur = float(g[-1]["end"]) - float(g[0]["start"])
            gap = float(g[0]["start"]) - float(prev[-1]["end"])
            sentence = T.is_sentence_end(str(prev[-1]["w"]))
            combined = prev + g
            # Jangan gabung melintasi jeda panjang atau batas kalimat: di situ
            # justru pembaca butuh napas.
            if (
                not sentence
                and gap < gap_break
                and (prev_dur < MIN_PHRASE_DUR or g_dur < MIN_PHRASE_DUR)
                and len(combined) <= max_words + 1
                and fits_block(joined(combined), 2)
            ):
                merged[-1] = combined
                continue
        merged.append(g)

    return [build(g) for g in merged]


def pick_emphasis(phrase: dict[str, Any]) -> int | None:
    """Pilih SATU kata untuk ditekankan, atau None.

    Kembalian None itu normal dan disengaja — kalau setiap frasa punya kata
    kuning, tidak ada lagi yang menonjol. Emphasis hanya untuk sinyal kuat:
    angka, negasi, superlatif, kata tanya.
    """
    words = phrase["words"]
    if not words:
        return None

    best_idx, best_score = None, -1.0
    for idx, w in enumerate(words):
        raw = str(w["w"]).strip()
        clean = T.clean(raw)
        score = 0.0
        # angka (digit maupun kata bilangan) paling layak diangkat
        if T.count_numbers(raw) > 0:
            score += 3.0
        if clean in EMPHATIC_WORDS:
            score += 2.0
        if clean and clean.isupper():
            score += 1.5
        score += min(len(clean) / 12.0, 1.0)
        if idx == 0:
            score += 0.3
        if score > best_score:
            best_idx, best_score = idx, score

    if best_score < MIN_EMPHASIS_SCORE:
        return None
    return best_idx


def _ass_time(t: float) -> str:
    t = max(0.0, float(t))
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    seconds = t % 60
    return f"{hours}:{minutes:02d}:{seconds:05.2f}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "/")


def render_events(captions: list[dict[str, Any]], uppercase: bool = True) -> str:
    events: list[str] = []
    for cap in captions:
        start = _ass_time(float(cap["start"]))
        end = _ass_time(float(cap["end"]))
        text = str(cap["text"])
        emphasis = cap.get("emphasis")

        parts: list[str] = []
        for w in text.split():
            shown = w.upper() if uppercase else w
            shown = _escape(shown)
            if emphasis and T.clean(w) == T.clean(str(emphasis)):
                parts.append(
                    f"{{\\c{ACCENT}\\fscx112\\fscy112}}{shown}{{\\r}}"
                )
            else:
                parts.append(shown)

        body = " ".join(parts)
        # pop-in: mulai 88% lalu membesar ke 100% dalam 110ms.
        # fade-out sengaja nol — potongan keras lebih energik untuk gaya kinetic.
        effect = "{\\fad(50,0)\\fscx88\\fscy88\\t(0,110,\\fscx100\\fscy100)}"
        events.append(f"Dialogue: 0,{start},{end},Base,,0,0,0,,{effect}{body}")

    return "\n".join(events)


def build_ass(
    captions: list[dict[str, Any]],
    template_path: str | Path | None = None,
    font: str = FONT,
    font_size: int = FONT_SIZE,
    margin_v: int = MARGIN_V,
    uppercase: bool = True,
) -> str:
    tpl_path = Path(template_path) if template_path else (
        Path(__file__).resolve().parent.parent / "templates" / "caption_default.ass.tmpl"
    )
    if tpl_path.exists():
        tpl = tpl_path.read_text(encoding="utf-8")
    else:
        tpl = _FALLBACK_TEMPLATE

    return (
        tpl.replace("{{FONT}}", font)
        .replace("{{FONTSIZE}}", str(font_size))
        .replace("{{MARGIN_V}}", str(margin_v))
        .replace("{{PRIMARY}}", PRIMARY)
        .replace("{{ACCENT}}", ACCENT)
        .replace("{{EVENTS}}", render_events(captions, uppercase=uppercase))
    )


def write_ass(
    captions: list[dict[str, Any]], out_path: str | Path, **kwargs: Any
) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_ass(captions, **kwargs), encoding="utf-8")
    return p


_FALLBACK_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{{FONT}},{{FONTSIZE}},{{PRIMARY}},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,7,3,2,90,90,{{MARGIN_V}},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{{EVENTS}}
"""
