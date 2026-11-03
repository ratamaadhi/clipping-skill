"""Ekstraktor momen kandidat efek video tier-2 (Langkah 7a): murni dan deterministik.

Mengekstrak momen dan fitur dari klip EDL (timeline OUTPUT) untuk disajikan
kepada direktur efek (agen). Agen (LLM) yang memutuskan pemakaian efek; kode
ini hanya menyajikan fakta visual, leksikon pemicu, dan evaluasi geometri `fits`.

Formula Keyakinan (`confidence` ∈ [0, 1]):
- `number`:
    base = 0.70
    + 0.15 bila memuat kata skala ('juta', 'ribu', dll.) atau persen ('%')
    + 0.10 bila memuat digit angka (>= 2 digit)
    maksimal 0.95
- `trend`:
    0.90 untuk perubahan dari-ke numerik
    0.85 untuk deret tahun berurutan (>= 3 tahun)
- `list`:
    base = 0.75 + 0.05 per butir tambahan di atas 2 butir (maksimal 0.95)
- `question`:
    0.80 bila memuat penanda hook kuat ("tahu nggak", "kenapa", dll.)
    0.65 bila kalimat tanya biasa di jendela hook
- `product`:
    0.85 bila cocok dengan leksikon aplikasi/produk (APP_LEXICON)
    0.75 bila cocok dengan kata kerja layar + objek
    0.65 bila kata berkapital berulang di tengah kalimat
- `emphasis`:
    base = 0.60
    + min(len(kata) / 20.0, 0.20) (kata lebih panjang lebih berbobot)
    + 0.15 bila berada dekat dengan event punch (<= 0.5s)
    maksimal 0.95
- `reveal`:
    base = 0.80
    + 0.15 bila jarak kata pengungkapan ke angka/tren <= 1.5s (lainnya +0.05)

Kebijakan tanpa `face_track`:
- `shot_kind` disetel ke 'unknown' dengan `face_height_ratio = None`.
- Overlay kartu (`needs_free_area = True`) disetel `ok = False` dengan alasan
  "tanpa face_track: layout kartu memerlukan face_track untuk verifikasi area bebas".
- Overlay non-kartu (`zoom_through_text` dan `pullback`) tetap dievaluasi normal
  karena tidak memerlukan slot bebas wajah.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any

from . import fxcatalog
from . import layout
from .layout import Rect
from . import presets_phone
from .lib import text as lib_text

__all__ = [
    "APP_LEXICON",
    "CANVAS_HEIGHT",
    "HONORIFIC_TITLES",
    "MAX_MOMENTS_PER_CLIP",
    "NUMBER_IDIOMS",
    "PERCENT_WORDS",
    "PRODUCT_STOP_WORDS",
    "QUESTION_HOOK_MARKERS",
    "REVEAL_MARKERS",
    "SCALE_WORDS",
    "SCREEN_ACTION_VERBS",
    "SHOT_CLOSE_UP_THRESHOLD",
    "SHOT_MEDIUM_THRESHOLD",
    "TREND_VERBS",
    "extract",
    "extract_clip",
]

# ---------------------------------------------------------------------------
# Ambang dan Konstanta Shot & Kanvas
# ---------------------------------------------------------------------------

SHOT_CLOSE_UP_THRESHOLD: float = 0.35
"""Ambang rasio tinggi wajah terhadap kanvas untuk klasifikasi close_up (>= 0.35)."""

SHOT_MEDIUM_THRESHOLD: float = 0.20
"""Ambang rasio tinggi wajah terhadap kanvas untuk klasifikasi medium (0.20 - 0.35)."""

CANVAS_HEIGHT: float = 1920.0
"""Tinggi kanvas vertikal standar (piksel)."""

MAX_MOMENTS_PER_CLIP: int = 40
"""Batas maksimum momen yang dikembalikan per klip (dipotong berdasarkan confidence)."""

PUNCH_PROXIMITY_SECONDS: float = 0.5
"""Jarak toleransi waktu untuk mendeteksi kedekatan dengan event punch (detik)."""


# ---------------------------------------------------------------------------
# Leksikon Pemicu (Mudah disunting, konservatif: presisi di atas recall)
# ---------------------------------------------------------------------------

# Kata skala numerik
SCALE_WORDS: frozenset[str] = frozenset(
    {"ribu", "juta", "miliar", "triliun", "kali lipat"}
)

# Penanda persen
PERCENT_WORDS: frozenset[str] = frozenset({"persen", "%"})

# Idiom angka yang BUKAN merupakan angka statistik riil
NUMBER_IDIOMS: frozenset[str] = frozenset(
    {
        "satu-satunya",
        "satu satunya",
        "dua-duanya",
        "dua duanya",
        "tiga-tiganya",
        "tiga tiganya",
        "seribu satu",
        "seribu-satu",
        "salah satu",
        "satu sama lain",
        "satu persatu",
        "satu per satu",
    }
)

# Kata kerja tren perubahan
TREND_VERBS: frozenset[str] = frozenset(
    {
        "naik",
        "turun",
        "meningkat",
        "menurun",
        "melonjak",
        "anjlok",
        "tumbuh",
        "menyusut",
        "berkurang",
        "bertambah",
    }
)

# Penanda pertanyaan hook retoris di awal video
QUESTION_HOOK_MARKERS: tuple[str, ...] = (
    "tahu nggak",
    "tahu gak",
    "pernah nggak",
    "pernah gak",
    "kenapa",
    "mengapa",
    "bagaimana kalau",
    "gimana kalau",
    "tau nggak",
    "tau gak",
)

# Leksikon nama aplikasi/layanan digital umum (Indonesia & global)
APP_LEXICON: frozenset[str] = frozenset(
    {
        "instagram",
        "tiktok",
        "whatsapp",
        "telegram",
        "google",
        "youtube",
        "tokopedia",
        "shopee",
        "lazada",
        "bukalapak",
        "gojek",
        "grab",
        "traveloka",
        "excel",
        "word",
        "powerpoint",
        "notion",
        "figma",
        "canva",
        "chatgpt",
        "spotify",
        "netflix",
        "twitter",
        "facebook",
        "slack",
        "zoom",
        "linkedin",
        "trello",
        "jira",
        "discord",
        "threads",
        "capcut",
        "snackvideo",
        "dana",
        "ovo",
        "gopay",
        "linkaja",
        "flip",
        "bibit",
        "ajaib",
        "blibli",
    }
)

# Kata kerja interaksi layar aplikasi (spesifikasi: tanpa cari/pasang/tekan; cari HANYA sebagai 'cari di')
SCREEN_ACTION_VERBS: frozenset[str] = frozenset(
    {
        "buka",
        "klik",
        "download",
        "unduh",
        "install",
        "ketik",
        "login",
        "scroll",
        "search",
    }
)

# Daftar henti kapitalisasi ASR yang sering muncul di awal kalimat / acak
PRODUCT_STOP_WORDS: frozenset[str] = frozenset(
    {
        "oke",
        "deal",
        "tidak",
        "cukup",
        "ya",
        "iya",
        "gak",
        "nggak",
        "bener",
        "betul",
        "sekali",
        "jadi",
        "nah",
        "lho",
        "loh",
        "wah",
        "eh",
        "hmm",
        "kan",
        "dong",
        "sih",
        "kok",
        "yuk",
        "lah",
        "deh",
        "pun",
        "ini",
        "itu",
        "ada",
        "mau",
        "bisa",
        "udah",
        "sudah",
        "belum",
        "lagi",
        "terus",
        "apa",
        "siapa",
        "kapan",
        "dimana",
        "kenapa",
        "bagaimana",
        "mengapa",
        "tapi",
        "tetapi",
        "dan",
        "atau",
        "karena",
        "kalau",
        "jika",
        "bila",
        "supaya",
        "agar",
        "untuk",
        "dengan",
        "pada",
        "dari",
        "ke",
        "di",
        "sebelum",
        "sesudah",
        "setelah",
        "kemudian",
        "lalu",
        "mereka",
        "kita",
        "kami",
        "kamu",
        "saya",
        "aku",
        "dia",
        "beliau",
        "semua",
        "banyak",
        "sedikit",
        "sangat",
        "amat",
        "paling",
        "harus",
        "wajib",
        "boleh",
        "bukan",
    }
)

# Gelar/sebutan orang (bila mendahului token berkapital -> nama orang, bukan produk)
HONORIFIC_TITLES: frozenset[str] = frozenset(
    {
        "om",
        "mas",
        "mbak",
        "bang",
        "kak",
        "pak",
        "bu",
        "bapak",
        "ibu",
        "dr",
        "prof",
        "tuan",
        "nyonya",
    }
)


def _match_lexicon(word: str) -> str | None:
    """Cek apakah sebuah token cocok dengan leksikon produk, toleran akhiran '-nya'."""
    raw = word.strip(".,?!;:\"'()[]{}")
    if not raw:
        return None
    low = raw.lower()
    if low in APP_LEXICON:
        return raw

    # Toleran akhiran "-nya" atau "nya"
    if low.endswith("-nya") and len(low) > 4:
        base = low[:-4]
        if base in APP_LEXICON:
            return raw
    elif low.endswith("nya") and len(low) > 3:
        base = low[:-3]
        if base in APP_LEXICON:
            return raw

    return None

# Penanda kalimat pengungkapan fakta
REVEAL_MARKERS: frozenset[str] = frozenset(
    {"ternyata", "faktanya", "hasilnya", "rahasianya", "kenyataannya", "ujung-ujungnya", "nyatanya"}
)

END_MARGIN: float = fxcatalog.END_MARGIN
TRIGGER_LEAD_SECONDS: dict[str, float] = {"emphasis": 0.0, "number": 0.0}
DEFAULT_LEAD_SECONDS: float = 0.0
SUGGESTED_PRE_ROLL: float = 0.1

# Pola regex
_DIGIT_2PLUS_RE = re.compile(r"\b\d{2,}\b")
_SINGLE_DIGIT_RE = re.compile(r"\b\d\b")
_PERCENT_RE = re.compile(r"\b\d+\s*%\b|\bpersen\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19\d\d|20\d\d)\b")


# ---------------------------------------------------------------------------
# Helper Teks dan Waktu
# ---------------------------------------------------------------------------

def _clean_token(tok: str) -> str:
    return lib_text.clean(tok)


def _is_year_only(token: str) -> bool:
    m = _YEAR_RE.fullmatch(token.strip(lib_text.PUNCT_STRIP))
    return bool(m)


# ---------------------------------------------------------------------------
# Ekstraksi Fitur Shot dari face_track
# ---------------------------------------------------------------------------

def _analyze_shots(
    face_track: Any, duration: float
) -> list[dict[str, Any]]:
    """Klasifikasikan shot menjadi close_up, medium, wide, atau unknown."""
    if not face_track or not isinstance(face_track, list):
        return [
            {
                "t0": 0.0,
                "t1": round(duration, 3),
                "shot_kind": "unknown",
                "face_height_ratio": None,
            }
        ]

    try:
        raw_shots = layout.shots(face_track, duration)
    except Exception:
        return [
            {
                "t0": 0.0,
                "t1": round(duration, 3),
                "shot_kind": "unknown",
                "face_height_ratio": None,
            }
        ]

    out: list[dict[str, Any]] = []
    for t0, t1, faces in raw_shots:
        if faces:
            max_face = max(faces, key=lambda f: f.h)
            ratio = round(max_face.h / CANVAS_HEIGHT, 4)
            if ratio >= SHOT_CLOSE_UP_THRESHOLD:
                kind = "close_up"
            elif ratio >= SHOT_MEDIUM_THRESHOLD:
                kind = "medium"
            else:
                kind = "wide"
            bbox = {
                "x": round(max_face.x, 1),
                "y": round(max_face.y, 1),
                "w": round(max_face.w, 1),
                "h": round(max_face.h, 1),
            }
            out.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(t1, 3),
                    "shot_kind": kind,
                    "face_height_ratio": ratio,
                    "face_bbox": bbox,
                }
            )
        else:
            out.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(t1, 3),
                    "shot_kind": "wide",
                    "face_height_ratio": 0.0,
                }
            )
    return out


def _find_shot(shots: list[dict[str, Any]], t: float) -> dict[str, Any]:
    for s in shots:
        if s["t0"] <= t <= s["t1"]:
            return s
    return shots[-1] if shots else {
        "t0": 0.0,
        "t1": 0.0,
        "shot_kind": "unknown",
        "face_height_ratio": None,
    }


def _check_near_punch(punch: Any, t0: float, t1: float) -> bool:
    if not punch or not isinstance(punch, (list, tuple)):
        return False
    for item in punch:
        if not isinstance(item, dict) or "t" not in item:
            continue
        pt = float(item["t"])
        if (t0 - PUNCH_PROXIMITY_SECONDS) <= pt <= (t1 + PUNCH_PROXIMITY_SECONDS):
            return True
    return False


# ---------------------------------------------------------------------------
# Evaluasi Geometri fits
# ---------------------------------------------------------------------------

def _evaluate_fits(
    moment_t0: float,
    moment_t1: float,
    trigger: str,
    shot: dict[str, Any],
    in_hook: bool,
    raw_faces: list[Rect],
    punch: Any,
    caption_rects: list[Rect],
    taken_rects: list[Rect],
    available_window: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Evaluasi apakah setiap efek overlay cocok secara struktur dan geometri."""
    fits: dict[str, dict[str, Any]] = {}
    avail_start = float(available_window["start"])
    avail_end = float(available_window["end"])
    available_duration = max(0.0, avail_end - avail_start)
    shot_kind = shot.get("shot_kind", "unknown")

    for eff_name in fxcatalog.names():
        eff_meta = fxcatalog.get(eff_name)
        min_win = eff_meta["window"]["min"]

        # 1. Cek durasi jendela minimum memakai available_window
        if available_duration < min_win - 1e-6:
            fits[eff_name] = {
                "ok": False,
                "reason": f"jendela ({available_duration:.2f}s) < min ({min_win:.2f}s)",
                "rect": None,
                "suggested_window": None,
            }
            continue

        # 2. Cek jendela hook
        if in_hook and eff_meta["budget_class"] in ("card", "transform"):
            fits[eff_name] = {
                "ok": False,
                "reason": (
                    f"di jendela hook: overlay {eff_meta['budget_class']} "
                    f"tidak boleh mulai di hook window (0-{fxcatalog.HOOK_WINDOW_SECONDS:.1f}s)"
                ),
                "rect": None,
                "suggested_window": None,
            }
            continue

        # 3. Pemicu 'question' adalah penanda editorial
        if trigger == "question":
            fits[eff_name] = {
                "ok": False,
                "reason": "pemicu question: penanda editorial pertanyaan/hook, bukan pemicu overlay kartu",
                "rect": None,
                "suggested_window": None,
            }
            continue

        # Hitung suggested_window untuk efek yang berpotensi ok
        pre = 0.0 if in_hook else SUGGESTED_PRE_ROLL
        s_start = max(avail_start, moment_t0 - pre)
        target_len = eff_meta["window"]["typical"]
        target_end = s_start + target_len

        if trigger == "list" and isinstance(evidence, dict) and "items" in evidence and evidence["items"]:
            last_item = evidence["items"][-1]
            if isinstance(last_item, dict) and last_item.get("done_at") is not None:
                target_end = max(target_end, float(last_item["done_at"]) + 1.0)

        max_end = s_start + eff_meta["window"]["max"]
        target_end = min(target_end, max_end)
        s_end = min(avail_end, target_end)
        suggested_win = {"start": round(s_start, 3), "end": round(s_end, 3)}

        # 4. Efek yang tidak membutuhkan slot bebas (zoom_through_text dan pullback)
        if not eff_meta["needs_free_area"]:
            fits[eff_name] = {
                "ok": True,
                "reason": "efek tidak membutuhkan area bebas (bebas wajah)",
                "rect": None,
                "suggested_window": suggested_win,
            }
            continue

        # 5. Efek kartu membutuhkan area bebas
        if shot_kind == "unknown":
            fits[eff_name] = {
                "ok": False,
                "reason": "tanpa face_track: layout kartu memerlukan face_track untuk verifikasi area bebas",
                "rect": None,
                "suggested_window": None,
            }
            continue

        # Hitung zona terlarang wajah
        max_scale = layout.max_punch_scale(punch, moment_t0, moment_t1)
        zones = layout.forbidden_zones(raw_faces, max_scale)

        req_size = fxcatalog.required_size(eff_name, eff_meta.get("example"))
        if req_size is None:
            req_size = eff_meta.get("default_size")

        scan_x = 60.0
        if eff_name == "phone_frame":
            ex_props = eff_meta.get("example")
            side = "right"
            if isinstance(ex_props, dict):
                props_dict = ex_props.get("props") if isinstance(ex_props.get("props"), dict) else ex_props
                if isinstance(props_dict, dict):
                    side = props_dict.get("side", "right")
            if side == "left":
                scan_x = float(presets_phone.PHONE_DEFAULT_X_LEFT)
            elif side == "right" or side is None:
                scan_x = float(presets_phone.PHONE_DEFAULT_X_RIGHT)
            else:
                scan_x = 60.0

        fitted_rect = layout.scan_free_rect(
            req_size, zones, caption_rects, taken_rects, x=scan_x, avoid_caption=True
        )

        if fitted_rect is None:
            if shot_kind == "close_up":
                reason = "close_up: tidak ada slot bebas untuk kartu"
            else:
                reason = "tidak ada slot bebas untuk kartu"
            fits[eff_name] = {
                "ok": False,
                "reason": reason,
                "rect": None,
                "suggested_window": None,
            }
        else:
            fits[eff_name] = {
                "ok": True,
                "reason": f"slot bebas ditemukan di ({fitted_rect.x:.0f}, {fitted_rect.y:.0f})",
                "rect": {
                    "x": round(fitted_rect.x, 1),
                    "y": round(fitted_rect.y, 1),
                    "w": round(fitted_rect.w, 1),
                    "h": round(fitted_rect.h, 1),
                },
                "suggested_window": suggested_win,
            }

    return fits


# ---------------------------------------------------------------------------
# Ekstraktor Pemicu Momen
# ---------------------------------------------------------------------------

def _extract_moments(
    captions: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    raw_faces_by_shot: list[list[Rect]],
    punch: Any,
    existing_overlays: list[dict[str, Any]],
    clip_duration: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Ekstraksi momen kandidat dari caption."""
    raw_moments: list[dict[str, Any]] = []
    notes: list[str] = []

    # Siapkan kotak overlay yang sudah ada untuk uji irisan
    taken_rects: list[Rect] = []
    for ov in existing_overlays:
        if isinstance(ov, dict) and "rect" in ov and isinstance(ov["rect"], dict):
            r = ov["rect"]
            try:
                taken_rects.append(Rect(r["x"], r["y"], r["w"], r["h"]))
            except Exception:
                pass

    # Kumpulkan kata-kata dengan waktu
    words_flat: list[dict[str, Any]] = []
    has_words = any(bool(c.get("words")) for c in captions)

    for cap_idx, cap in enumerate(captions):
        cap_text = str(cap.get("text", "")).strip()
        c_start = float(cap.get("start", 0.0))
        c_end = float(cap.get("end", c_start))
        emp = cap.get("emphasis")

        if has_words and cap.get("words"):
            for w_idx, w in enumerate(cap["words"]):
                w_str = str(w.get("w", "")).strip()
                ws = float(w.get("start", c_start))
                we = float(w.get("end", c_end))
                words_flat.append(
                    {
                        "w": w_str,
                        "start": ws,
                        "end": we,
                        "cap_idx": cap_idx,
                        "w_idx": w_idx,
                        "cap_text": cap_text,
                        "emphasis": emp,
                    }
                )
        else:
            # Fallback tingkat frasa
            for w_idx, w_str in enumerate(cap_text.split()):
                words_flat.append(
                    {
                        "w": w_str,
                        "start": c_start,
                        "end": c_end,
                        "cap_idx": cap_idx,
                        "w_idx": w_idx,
                        "cap_text": cap_text,
                        "emphasis": emp,
                    }
                )

    # 1. Pemicu: NUMBER
    for cap in captions:
        text = str(cap.get("text", "")).strip()
        clean_text_lower = text.lower()
        t0 = float(cap.get("start", 0.0))
        t1 = float(cap.get("end", t0))

        # Abaikan idiom
        is_idiom = any(idiom in clean_text_lower for idiom in NUMBER_IDIOMS)
        if is_idiom:
            continue

        has_digits_2plus = bool(_DIGIT_2PLUS_RE.search(text))
        has_single_digit = bool(_SINGLE_DIGIT_RE.search(text))
        has_scale = any(sw in clean_text_lower for sw in SCALE_WORDS)
        has_percent = any(pw in clean_text_lower for pw in PERCENT_WORDS) or bool(
            _PERCENT_RE.search(text)
        )

        # Cek apakah hanya tahun saja (19xx / 20xx tanpa satuan/skala)
        clean_words = [_clean_token(w) for w in text.split()]
        only_year = False
        if has_digits_2plus and not has_scale and not has_percent:
            digits_found = _DIGIT_2PLUS_RE.findall(text)
            if all(_is_year_only(d) for d in digits_found):
                only_year = True

        if only_year:
            continue

        matched_num = False
        matched_str = ""
        conf = 0.70

        if has_percent:
            matched_num = True
            conf += 0.15
            matched_str = "persen"
        elif has_scale:
            matched_num = True
            conf += 0.15
            matched_str = "skala"
        elif has_digits_2plus:
            matched_num = True
            conf += 0.10
            matched_str = "digit>=2"
        elif has_single_digit and (has_scale or has_percent):
            matched_num = True
            conf += 0.10
            matched_str = "digit+satuan"

        if matched_num:
            # Pastikan durasi cukup untuk evaluasi awal
            eff_t1 = max(t1, t0 + 0.7)
            raw_moments.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(eff_t1, 3),
                    "trigger": "number",
                    "text": text,
                    "confidence": min(1.0, round(conf, 2)),
                    "evidence": {"matched": matched_str, "phrase": text},
                }
            )

    # 2. Pemicu: TREND
    # Pola A: perubahan dari-ke
    # Pola B: >= 3 tahun berurutan
    # Cari di caption atau rangkaian 2 caption berdekatan
    for i, cap in enumerate(captions):
        text = str(cap.get("text", "")).strip()
        t0 = float(cap.get("start", 0.0))
        t1 = float(cap.get("end", t0))

        # Cek teks gabungan dengan caption berikutnya bila jeda pendek
        combined_text = text
        eff_end = t1
        if i + 1 < len(captions):
            next_cap = captions[i + 1]
            if float(next_cap.get("start", 0.0)) - t1 <= 1.0:
                combined_text = f"{text} {next_cap.get('text', '')}"
                eff_end = float(next_cap.get("end", eff_end))

        low_text = combined_text.lower()
        has_trend_verb = any(v in low_text for v in TREND_VERBS)

        # Pola "dari X (ke|menjadi|jadi) Y"
        from_to_match = re.search(
            r"\bdari\s+([0-9]+(?:\.[0-9]+)?%?|[a-z0-9]+(?:\s+[a-z0-9]+)?)\s+(?:ke|menjadi|jadi)\s+([0-9]+(?:\.[0-9]+)?%?|[a-z0-9]+(?:\s+[a-z0-9]+)?)(?=$|\s|[.,!?;:])",
            low_text,
        )

        if from_to_match:
            from_val = from_to_match.group(1).strip()
            to_val = from_to_match.group(2).strip()
            # Pastikan bukan kata sembarang tanpa angka jika tanpa trend verb
            has_num = bool(re.search(r"\d", from_val + to_val)) or any(
                sw in from_val + to_val for sw in SCALE_WORDS | PERCENT_WORDS
            )
            if has_trend_verb or has_num:
                raw_moments.append(
                    {
                        "t0": round(t0, 3),
                        "t1": round(max(eff_end, t0 + 3.0), 3),
                        "trigger": "trend",
                        "text": combined_text,
                        "confidence": 0.90,
                        "evidence": {
                            "kind": "change",
                            "has_trend_verb": has_trend_verb,
                            "from": from_val,
                            "to": to_val,
                        },
                    }
                )

        # Pola deret tahun >= 3 tahun
        years_found = _YEAR_RE.findall(combined_text)
        if len(years_found) >= 3:
            raw_moments.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(max(eff_end, t0 + 3.5), 3),
                    "trigger": "trend",
                    "text": combined_text,
                    "confidence": 0.85,
                    "evidence": {
                        "kind": "years",
                        "years": years_found,
                    },
                }
            )

    # 3. Pemicu: LIST
    # Urutan kata penanda: "pertama" < "kedua" < "ketiga" dst. atau isyarat jumlah.
    # Wajib >= 2 penanda urutan BERBEDA dan BERURUTAN NAIK, ATAU isyarat jumlah diikuti >= 1 penanda.
    ordinal_map = {
        "pertama": 1,
        "kedua": 2,
        "ketiga": 3,
        "keempat": 4,
        "kelima": 5,
        "keenam": 6,
        "ketujuh": 7,
        "kedelapan": 8,
        "kesembilan": 9,
        "kesepuluh": 10,
    }
    cardinal_map = {
        "satu": 1,
        "dua": 2,
        "tiga": 3,
        "empat": 4,
        "lima": 5,
        "enam": 6,
        "tujuh": 7,
        "delapan": 8,
        "sembilan": 9,
        "sepuluh": 10,
    }
    count_cue_re = re.compile(
        r"(?:ada\s+)?(dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|\d+)\s+"
        r"(hal|cara|alasan|langkah|tips|poin|syarat)\b",
        re.IGNORECASE,
    )
    count_cues: list[dict[str, Any]] = []
    for cap in captions:
        cap_t = str(cap.get("text", ""))
        for m in count_cue_re.finditer(cap_t):
            count_cues.append(
                {
                    "start": float(cap.get("start", 0.0)),
                    "match": m.group(0),
                }
            )

    detected_markers: list[dict[str, Any]] = []
    for i, w in enumerate(words_flat):
        w_raw = str(w.get("w", ""))
        w_clean = _clean_token(w_raw).lower()
        if not w_clean:
            continue

        # Abaikan idiom "pertama kali", "pertama-tama"
        if w_clean == "pertama":
            if i + 1 < len(words_flat):
                next_clean = _clean_token(words_flat[i + 1]["w"]).lower()
                if next_clean in ("kali", "tama"):
                    continue
            if "pertama-tama" in w_raw.lower() or "pertama_tama" in w_raw.lower():
                continue

        # Abaikan "kedua kakinya", "kedua tangan", dll bila hanya merujuk sepasang anggota tubuh/orang
        if w_clean == "kedua":
            if i + 1 < len(words_flat):
                next_clean = _clean_token(words_flat[i + 1]["w"]).lower()
                if next_clean in ("kaki", "kakinya", "tangan", "tangannya", "mata", "orang", "belah", "pihak"):
                    continue

        rank = None
        marker_name = w_clean
        if w_clean in ordinal_map:
            rank = ordinal_map[w_clean]
        else:
            has_cue = any(c["start"] <= float(w.get("start", 0.0)) + 0.5 for c in count_cues)
            if has_cue and w_clean in cardinal_map:
                rank = cardinal_map[w_clean]

        if rank is not None:
            detected_markers.append(
                {
                    "marker": marker_name,
                    "rank": rank,
                    "done_at": round(float(w["start"]), 3),
                    "w": w_raw,
                    "cap_text": w.get("cap_text", ""),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                }
            )

    ascending_markers: list[dict[str, Any]] = []
    for m in detected_markers:
        if not ascending_markers:
            ascending_markers.append(m)
        elif m["rank"] > ascending_markers[-1]["rank"]:
            ascending_markers.append(m)
        # Penanda identik berulang atau urutan menurun tidak dihitung

    has_any_cue = bool(count_cues)
    if len(ascending_markers) >= 2 or (has_any_cue and len(ascending_markers) >= 1):
        first_m = ascending_markers[0]
        last_m = ascending_markers[-1]
        t0 = round(first_m["start"], 3)
        t1 = round(max(last_m["end"] + 1.5, t0 + 4.0), 3)

        items_evidence = []
        for idx, m in enumerate(ascending_markers):
            items_evidence.append(
                {
                    "index": idx + 1,
                    "marker": m["marker"],
                    "done_at": m["done_at"],
                    "text": m["cap_text"][:28],
                }
            )

        conf = min(0.95, round(0.75 + 0.05 * (len(ascending_markers) - 2), 2)) if len(ascending_markers) >= 2 else 0.80
        raw_moments.append(
            {
                "t0": t0,
                "t1": min(round(clip_duration, 3), t1),
                "trigger": "list",
                "text": f"Daftar {len(ascending_markers)} butir: {first_m['cap_text']}",
                "confidence": conf,
                "evidence": {"items": items_evidence},
            }
        )

    # 4. Pemicu: QUESTION
    for cap in captions:
        text = str(cap.get("text", "")).strip()
        low_text = text.lower()
        t0 = float(cap.get("start", 0.0))
        t1 = float(cap.get("end", t0))
        in_hook = t0 < fxcatalog.HOOK_WINDOW_SECONDS

        matched_hook_marker = None
        for qm in QUESTION_HOOK_MARKERS:
            if qm in low_text:
                matched_hook_marker = qm
                break

        is_q = text.endswith("?") or lib_text.is_question(text)
        if matched_hook_marker or (in_hook and is_q):
            conf = 0.80 if matched_hook_marker else 0.65
            raw_moments.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(max(t1, t0 + 1.5), 3),
                    "trigger": "question",
                    "text": text,
                    "confidence": conf,
                    "evidence": {
                        "marker": matched_hook_marker or "?",
                        "in_hook_window": in_hook,
                    },
                }
            )

    # 5. Pemicu: PRODUCT
    # Bukti: (a) leksikon merek/aplikasi/layanan, (b) kata kerja layar + objek,
    # (c) token berkapital berulang >= 2 kali di klip mid-sentence (bukan stop word, bukan gelar orang).
    # Kumpulkan kandidat repeated_capital di seluruh klip terlebih dahulu:
    mid_sentence_caps: list[str] = []
    for cap in captions:
        cap_text = str(cap.get("text", "")).strip()
        words_in_cap = cap_text.split()
        for idx, rw in enumerate(words_in_cap):
            if idx == 0:
                continue
            prev_word = words_in_cap[idx - 1]
            if prev_word.endswith((".", "?", "!", ",")):
                continue
            prev_clean = prev_word.strip(".,?!;:\"'()[]{}").lower()
            if prev_clean in HONORIFIC_TITLES:
                continue
            clean_cand = rw.strip(".,?!;:\"'()[]{}")
            if len(clean_cand) >= 2 and clean_cand[0].isupper() and clean_cand[1:].islower():
                low_cand = clean_cand.lower()
                if low_cand not in PRODUCT_STOP_WORDS and low_cand not in HONORIFIC_TITLES:
                    mid_sentence_caps.append(low_cand)

    repeated_cap_counts = Counter(mid_sentence_caps)
    qualified_repeated = {k for k, v in repeated_cap_counts.items() if v >= 2}

    for cap in captions:
        text = str(cap.get("text", "")).strip()
        t0 = float(cap.get("start", 0.0))
        t1 = float(cap.get("end", t0))
        raw_words = text.split()

        # 5a. Leksikon merek/aplikasi/layanan
        found_lexicon = None
        for rw in raw_words:
            matched = _match_lexicon(rw)
            if matched:
                found_lexicon = matched
                break

        if found_lexicon:
            raw_moments.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(max(t1, t0 + 2.5), 3),
                    "trigger": "product",
                    "text": text,
                    "confidence": 0.85,
                    "evidence": {"matched": found_lexicon, "source": "lexicon"},
                }
            )
            continue

        # 5b. Kata kerja layar (buka, klik, download, unduh, install, ketik, login, scroll, search, cari di)
        # diikuti <= 3 kata berisi token berkapital/leksikon/objek.
        # Pemindaian <= 3 kata objek berhenti SETELAH token yang berakhir . ? !
        # (token kata kerja sendiri yang berakhir tanda itu berarti TIDAK ada objek; koma tidak menghentikan).
        found_screen_action = False
        action_match_str = ""
        for idx, rw in enumerate(raw_words):
            c = _clean_token(rw).lower()
            is_action_verb = False
            verb_len = 1
            if c in SCREEN_ACTION_VERBS:
                is_action_verb = True
            elif c == "cari":
                if not rw.endswith((".", "?", "!")) and idx + 1 < len(raw_words):
                    if _clean_token(raw_words[idx + 1]).lower() == "di":
                        is_action_verb = True
                        verb_len = 2

            if is_action_verb:
                last_verb_word = raw_words[idx + verb_len - 1]
                if last_verb_word.endswith((".", "?", "!")):
                    continue

                start_k = idx + verb_len
                end_k = min(len(raw_words), start_k + 3)
                for k in range(start_k, end_k):
                    cand_word = raw_words[k]
                    clean_cand = cand_word.strip(".,?!;:\"'()[]{}")
                    if _match_lexicon(clean_cand) is not None:
                        found_screen_action = True
                        action_match_str = f"{rw} {clean_cand}"
                        break
                    if clean_cand.lower() in ("aplikasi", "aplikasinya", "profil", "akun", "halaman", "layar", "menu"):
                        found_screen_action = True
                        action_match_str = f"{rw} {clean_cand}"
                        break
                    prev_w = raw_words[k - 1].strip(".,?!;:\"'()[]{}").lower() if k > 0 else ""
                    if (
                        len(clean_cand) >= 2
                        and clean_cand[0].isupper()
                        and clean_cand.lower() not in PRODUCT_STOP_WORDS
                        and clean_cand.lower() not in HONORIFIC_TITLES
                        and prev_w not in HONORIFIC_TITLES
                    ):
                        found_screen_action = True
                        action_match_str = f"{rw} {clean_cand}"
                        break
                    if cand_word.endswith((".", "?", "!")):
                        break
            if found_screen_action:
                break

        if found_screen_action:
            raw_moments.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(max(t1, t0 + 2.5), 3),
                    "trigger": "product",
                    "text": text,
                    "confidence": 0.85,
                    "evidence": {"matched": action_match_str, "source": "screen_action"},
                }
            )
            continue

        # 5c. Token berkapital berulang >= 2 kali di klip mid-sentence
        found_repeated = None
        for idx, rw in enumerate(raw_words):
            if idx == 0:
                continue
            prev_word = raw_words[idx - 1]
            if prev_word.endswith((".", "?", "!", ",")):
                continue
            prev_clean = prev_word.strip(".,?!;:\"'()[]{}").lower()
            if prev_clean in HONORIFIC_TITLES:
                continue
            clean_cand = rw.strip(".,?!;:\"'()[]{}")
            if clean_cand.lower() in qualified_repeated:
                found_repeated = clean_cand
                break

        if found_repeated:
            raw_moments.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(max(t1, t0 + 2.5), 3),
                    "trigger": "product",
                    "text": text,
                    "confidence": 0.70,
                    "evidence": {"matched": found_repeated, "source": "repeated_capital"},
                }
            )
            continue

    # 6. Pemicu: EMPHASIS
    for w in words_flat:
        emp = w.get("emphasis")
        if not emp:
            continue
        w_str = w["w"].strip(lib_text.PUNCT_STRIP)
        is_emp = False
        if isinstance(emp, str) and emp.lower() in w_str.lower():
            is_emp = True
        elif isinstance(emp, (list, tuple)) and any(
            str(e).lower() in w_str.lower() for e in emp
        ):
            is_emp = True

        if is_emp:
            t0 = round(w["start"], 3)
            t1 = round(w["end"], 3)
            near_p = _check_near_punch(punch, t0, t1)

            # Confidence formula
            base_conf = 0.60
            len_bonus = min(len(w_str) / 20.0, 0.20)
            punch_bonus = 0.15 if near_p else 0.0
            conf = min(0.95, round(base_conf + len_bonus + punch_bonus, 2))

            raw_moments.append(
                {
                    "t0": t0,
                    "t1": t1,
                    "trigger": "emphasis",
                    "text": w["w"],
                    "confidence": conf,
                    "evidence": {"emphasis_word": w_str, "near_punch": near_p},
                }
            )

    # 7. Pemicu: REVEAL
    for i, cap in enumerate(captions):
        text = str(cap.get("text", "")).strip()
        low_text = text.lower()
        t0 = float(cap.get("start", 0.0))

        found_reveal = None
        earliest_pos = 999999
        for rm in sorted(REVEAL_MARKERS):
            pos = low_text.find(rm)
            if pos != -1 and pos < earliest_pos:
                earliest_pos = pos
                found_reveal = rm

        if found_reveal:
            # Periksa apakah ada pemicu number atau trend dalam <= 3.0 detik ATAU dalam kalimat yang sama
            num_target = None
            gap = 999.0
            is_same_sentence = False
            for m in raw_moments:
                if m["trigger"] in ("number", "trend"):
                    time_diff = m["t0"] - t0
                    # Tentukan apakah berada di kalimat yang sama
                    m_cap_idx = None
                    for c_idx, c in enumerate(captions):
                        cs = float(c.get("start", 0.0))
                        ce = float(c.get("end", cs))
                        if cs - 1e-4 <= m["t0"] <= ce + 1e-4:
                            m_cap_idx = c_idx
                            break

                    same_sent = False
                    if m_cap_idx is not None and m_cap_idx >= i:
                        same_sent = True
                        if m_cap_idx == i:
                            pos_reveal = low_text.find(found_reveal)
                            after_reveal = text[pos_reveal + len(found_reveal):]
                            pos_num = low_text.find(str(m["text"]).lower(), pos_reveal + len(found_reveal))
                            if pos_num != -1:
                                between = text[pos_reveal + len(found_reveal):pos_num]
                                if any(p in between for p in (".", "?", "!")):
                                    same_sent = False
                            else:
                                if any(p in after_reveal for p in (".", "?", "!")):
                                    same_sent = False
                        else:
                            pos_reveal = low_text.find(found_reveal)
                            after_reveal = text[pos_reveal + len(found_reveal):]
                            if any(p in after_reveal for p in (".", "?", "!")):
                                same_sent = False
                            for mid in range(i + 1, m_cap_idx):
                                mid_t = str(captions[mid].get("text", ""))
                                if any(p in mid_t for p in (".", "?", "!")):
                                    same_sent = False
                                    break
                            tgt_t = str(captions[m_cap_idx].get("text", ""))
                            pos_num = tgt_t.lower().find(str(m["text"]).lower())
                            if pos_num != -1:
                                if any(p in tgt_t[:pos_num] for p in (".", "?", "!")):
                                    same_sent = False
                            else:
                                if any(p in tgt_t for p in (".", "?", "!")):
                                    same_sent = False

                    if (0.0 <= time_diff <= 3.0) or same_sent:
                        if time_diff >= 0.0 and time_diff < gap:
                            gap = time_diff
                            num_target = m
                            is_same_sentence = same_sent

            if num_target is not None:
                eff_t1 = max(num_target["t1"], t0 + 3.5)
                conf = 0.95 if gap <= 1.5 else 0.85
                raw_moments.append(
                    {
                        "t0": round(t0, 3),
                        "t1": round(min(clip_duration, eff_t1), 3),
                        "trigger": "reveal",
                        "text": text if num_target["text"] in text else f"{text} -> {num_target['text']}",
                        "confidence": conf,
                        "evidence": {
                            "reveal_word": found_reveal,
                            "target_trigger": num_target["trigger"],
                            "gap": round(gap, 2),
                            "same_sentence": is_same_sentence,
                        },
                    }
                )

    # Deduplikasi & Batas Jumlah Momen
    # Urutkan berdasarkan t0, lalu confidence descending
    raw_moments.sort(key=lambda m: (m["t0"], -m["confidence"]))

    if len(raw_moments) > MAX_MOMENTS_PER_CLIP:
        # Pangkas berdasarkan confidence
        sorted_by_conf = sorted(raw_moments, key=lambda m: m["confidence"], reverse=True)
        selected_moments = sorted_by_conf[:MAX_MOMENTS_PER_CLIP]
        notes.append(
            f"Dipangkas dari {len(raw_moments)} menjadi {MAX_MOMENTS_PER_CLIP} momen berdasarkan confidence"
        )
        selected_moments.sort(key=lambda m: (m["t0"], -m["confidence"]))
        raw_moments = selected_moments

    # Bangun entri momen lengkap dengan id stabil m001..m040 dan fits
    final_moments: list[dict[str, Any]] = []
    for idx, m in enumerate(raw_moments):
        m_id = f"m{idx + 1:03d}"
        t0 = m["t0"]
        t1 = m["t1"]
        trigger_dur = round(t1 - t0, 3)
        shot = _find_shot(shots, t0)
        shot_kind = shot.get("shot_kind", "unknown")
        in_hook = t0 < fxcatalog.HOOK_WINDOW_SECONDS
        near_p = _check_near_punch(punch, t0, t1)

        # Hitung available_window untuk momen ini
        lead = TRIGGER_LEAD_SECONDS.get(m["trigger"], DEFAULT_LEAD_SECONDS)
        avail_start = round(max(0.0, t0 - lead), 3)
        clip_end_limit = max(avail_start, clip_duration - END_MARGIN)

        next_ov_starts = [
            float(ov["start"])
            for ov in existing_overlays
            if isinstance(ov, dict) and "start" in ov and float(ov["start"]) >= t0
        ]
        if next_ov_starts:
            earliest_next = min(next_ov_starts)
            ov_limit = earliest_next - fxcatalog.MIN_GAP_SECONDS
            if ov_limit < clip_end_limit:
                avail_end = round(max(avail_start, ov_limit), 3)
                limited_by = "existing_overlay"
            else:
                avail_end = round(clip_end_limit, 3)
                limited_by = "clip_end"
        else:
            avail_end = round(clip_end_limit, 3)
            limited_by = "clip_end"

        avail_win = {
            "start": avail_start,
            "end": avail_end,
            "limited_by": limited_by,
        }

        # Cari wajah untuk shot yang bersangkutan
        shot_faces: list[Rect] = []
        for s_idx, s in enumerate(shots):
            if s["t0"] == shot["t0"] and s["t1"] == shot["t1"]:
                if s_idx < len(raw_faces_by_shot):
                    shot_faces = raw_faces_by_shot[s_idx]
                break

        # Kotak caption pada jendela momen
        cap_rects: list[Rect] = []
        for c in captions:
            cs = float(c.get("start", 0.0))
            ce = float(c.get("end", cs))
            if not (ce < t0 or cs > t1):
                # Perkiraan kotak caption default bawah
                cap_rects.append(Rect(140.0, 1400.0, 800.0, 160.0))
                break

        fits = _evaluate_fits(
            t0,
            t1,
            m["trigger"],
            shot,
            in_hook,
            shot_faces,
            punch,
            cap_rects,
            taken_rects,
            avail_win,
            m.get("evidence"),
        )

        final_moments.append(
            {
                "id": m_id,
                "t0": t0,
                "t1": t1,
                "trigger_duration": trigger_dur,
                "trigger": m["trigger"],
                "text": m["text"],
                "confidence": m["confidence"],
                "evidence": m["evidence"],
                "shot_kind": shot_kind,
                "in_hook_window": in_hook,
                "near_punch": near_p,
                "available_window": avail_win,
                "fits": fits,
            }
        )

    return final_moments, notes


# ---------------------------------------------------------------------------
# API Publik
# ---------------------------------------------------------------------------

def extract_clip(
    clip: dict[str, Any],
    *,
    fps: float = 30.0,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ekstraksi kandidat momen dan evaluasi fits untuk satu klip EDL."""
    clip_id = str(clip.get("id", "clip_00"))

    # Hitung durasi klip dari segments
    segments = clip.get("segments") or []
    if segments:
        duration = sum(
            float(seg.get("src_end", 0.0)) - float(seg.get("src_start", 0.0))
            for seg in segments
        )
    else:
        duration = float(clip.get("duration", 0.0))
    duration = max(0.0, round(duration, 3))

    captions = clip.get("captions") or []
    has_words = any(bool(c.get("words")) for c in captions)
    time_precision = "word" if has_words else "phrase"

    reframe = clip.get("reframe") or {}
    face_track = reframe.get("face_track")

    # Analisis shots
    shots = _analyze_shots(face_track, duration)

    # Ambil raw Rect wajah per shot dari layout.shots bila ada face_track
    raw_faces_by_shot: list[list[Rect]] = []
    if face_track and isinstance(face_track, list):
        try:
            shot_tuples = layout.shots(face_track, duration)
            for _, _, faces in shot_tuples:
                raw_faces_by_shot.append(faces)
        except Exception:
            raw_faces_by_shot = [[] for _ in shots]
    else:
        raw_faces_by_shot = [[] for _ in shots]

    punch = clip.get("punch") or []
    existing_overlays = clip.get("overlays") or []

    moments, notes = _extract_moments(
        captions,
        shots,
        raw_faces_by_shot,
        punch,
        existing_overlays,
        duration,
    )

    return {
        "clip_id": clip_id,
        "duration": duration,
        "fps": float(fps),
        "time_precision": time_precision,
        "hook_window": [0.0, fxcatalog.HOOK_WINDOW_SECONDS],
        "shots": shots,
        "moments": moments,
        "existing_overlays": existing_overlays,
        "notes": notes,
    }


def extract(edl: dict[str, Any], *, fps: float = 30.0) -> dict[str, Any]:
    """Ekstraksi kandidat momen untuk seluruh klip pada dokumen EDL."""
    clips = edl.get("clips") or []
    source = edl.get("source")
    out_clips = [
        extract_clip(c, fps=fps, source=source)
        for c in clips
        if isinstance(c, dict)
    ]
    return {
        "version": "0.1.0",
        "clips": out_clips,
    }
