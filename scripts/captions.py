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
MAX_WORDS_PER_PHRASE = 3
MAX_PHRASE_DUR = 1.9
GAP_BREAK = 0.45

FONT = "DejaVu Sans"
FONT_SIZE = 84
MARGIN_V = 520
PRIMARY = "&H00FFFFFF"  # putih
ACCENT = "&H0000E5FF"   # kuning (BGR)


def group_words(
    words: list[dict[str, Any]],
    max_words: int = MAX_WORDS_PER_PHRASE,
    max_dur: float = MAX_PHRASE_DUR,
    gap_break: float = GAP_BREAK,
) -> list[dict[str, Any]]:
    """Kelompokkan kata jadi frasa pendek. Ini yang bikin caption terbaca, bukan dinding teks."""
    phrases: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def flush() -> None:
        if not cur:
            return
        phrases.append(
            {
                "words": list(cur),
                "start": round(float(cur[0]["start"]), 3),
                "end": round(float(cur[-1]["end"]), 3),
                "text": " ".join(str(w["w"]).strip() for w in cur),
            }
        )
        cur.clear()

    for i, w in enumerate(words):
        cur.append(w)
        dur = float(w["end"]) - float(cur[0]["start"])
        next_gap = (
            float(words[i + 1]["start"]) - float(w["end"]) if i + 1 < len(words) else 99.0
        )
        if (
            len(cur) >= max_words
            or dur >= max_dur
            or next_gap >= gap_break
            or T.is_sentence_end(str(w["w"]))
        ):
            flush()
    flush()
    return phrases


def pick_emphasis(phrase: dict[str, Any]) -> int | None:
    """Pilih SATU kata untuk ditekankan. Lebih dari satu = tidak ada yang menonjol."""
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
        if clean in {"paling", "harus", "jangan", "gak", "tidak", "nggak", "salah", "benar", "cuma", "tapi"}:
            score += 2.0
        if clean and clean.isupper():
            score += 1.5
        score += min(len(clean) / 12.0, 1.0)
        if idx == 0:
            score += 0.3
        if score > best_score:
            best_idx, best_score = idx, score

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
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{{FONT}},{{FONTSIZE}},{{PRIMARY}},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,7,3,2,90,90,{{MARGIN_V}},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{{EVENTS}}
"""
