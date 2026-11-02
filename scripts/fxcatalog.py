"""Katalog efek overlay tier-2 (Langkah 7a): sumber kebenaran efek untuk agen.

Modul ini murni dan deterministik: mendefinisikan katalog efek yang dapat dibaca
mesin dan manusia, batas props yang terikat langsung ke konstanta modul preset,
anggaran overlay, dan deskripsi kemampuan tiap efek.

Agen (LLM) memakai katalog ini untuk memilih efek; kode tidak memilih efek.
"""

from __future__ import annotations

import json
from typing import Any

from . import presets
from . import presets_phone
from . import pullback

__all__ = [
    "CARD_MIN_GAP_SECONDS",
    "EFFECTS",
    "END_MARGIN",
    "HOOK_WINDOW_SECONDS",
    "MAX_ACCENT_PER_CLIP",
    "MAX_OVERLAYS_PER_CLIP",
    "MAX_TRANSFORM_PER_CLIP",
    "MIN_GAP_SECONDS",
    "MIN_STABLE_SECONDS_PULLBACK",
    "catalog_markdown",
    "get",
    "names",
    "required_size",
]

# ---------------------------------------------------------------------------
# Konstanta Anggaran Overlay (docs/MOTION-TIER2-PLAN.md Bagian Langkah 7)
# ---------------------------------------------------------------------------

MAX_OVERLAYS_PER_CLIP: int = 3
"""Maksimum total overlay (aksen + kartu + transform) per klip."""

MIN_GAP_SECONDS: float = 4.0
"""Jeda minimum antar-overlay sembarang jenis (detik) agar visual tidak bertumpukan padat."""

CARD_MIN_GAP_SECONDS: float = 10.0
"""Jeda minimum antar-overlay jenis kartu (detik) agar penonton tidak kewalahan membaca."""

MAX_ACCENT_PER_CLIP: int = 2
"""Maksimum overlay kelas 'accent' (zoom_through_text) per klip."""

MAX_TRANSFORM_PER_CLIP: int = 1
"""Maksimum overlay kelas 'transform' (pullback) per klip."""

HOOK_WINDOW_SECONDS: float = 2.0
"""Jendela hook awal klip (0-2s); kartu dan transform dilarang mulai di sini."""

MIN_STABLE_SECONDS_PULLBACK: float = 1.5
"""Fase stabil minimum setelah shrink selesai pada efek pullback."""

END_MARGIN: float = 0.4
"""Margin sebelum akhir klip (detik) untuk membatasi akhir overlay."""

# Catatan: digital zoom (`punch` tier-1) bukan overlay dan tidak dipilih agen di sini.


# ---------------------------------------------------------------------------
# Ukuran Kebutuhan per Props (required_size) & Ukuran Bawaan Kartu
# ---------------------------------------------------------------------------

def required_size(
    eff_type: str,
    props: dict[str, Any] | None = None,
) -> tuple[float, float] | None:
    """Hitung ukuran kebutuhan (w, h) per efek dan props dari geometri preset asli.

    Mengembalikan None untuk efek tanpa kebutuhan kotak (zoom_through_text, pullback).
    """
    if eff_type == "checklist":
        item_count = 3
        if isinstance(props, dict):
            items = props.get("items")
            if isinstance(items, list):
                item_count = len(items)
        h = 2.0 * presets.CARD_PAD_Y + presets.CARD_HEADER_H + item_count * presets.CARD_ROW_H
        return (float(presets.CARD_W), float(h))

    if eff_type == "phone_frame":
        line_count = 3
        if isinstance(props, dict):
            lines = props.get("lines")
            if isinstance(lines, list):
                line_count = len(lines)
        h = presets_phone.PHONE_BASE_H + line_count * presets_phone.PHONE_LINE_ROW_H
        return (float(presets_phone.PHONE_DEFAULT_W), float(h))

    if eff_type == "ui_panel":
        thumbs = presets.UI_DEFAULT_THUMBS
        if isinstance(props, dict):
            t_val = props.get("thumbs")
            if isinstance(t_val, int) and not isinstance(t_val, bool) and t_val >= 1:
                thumbs = t_val
        h = presets._ui_required_height(thumbs)
        return (float(presets.UI_CARD_W), float(h))

    if eff_type == "chart_grow":
        return (float(presets.CHART_CARD_W), float(presets.CHART_CARD_H))

    return None


_CHECKLIST_DEFAULT_SIZE = required_size("checklist")
_CHART_GROW_DEFAULT_SIZE = required_size("chart_grow")
_UI_PANEL_DEFAULT_SIZE = required_size("ui_panel")
_PHONE_FRAME_DEFAULT_SIZE = required_size("phone_frame")


# ---------------------------------------------------------------------------
# Katalog Efek (EFFECTS)
# ---------------------------------------------------------------------------

EFFECTS: dict[str, dict[str, Any]] = {
    "zoom_through_text": {
        "summary": "Teks serif miring besar yang memuai menembus kamera untuk aksen kata kunci atau punchline pendek.",
        "use_when": [
            "satu angka atau persen kunci",
            "punchline pendek atau penegasan frasa",
            "kata beraksen tier-1 (emphasis)",
        ],
        "avoid_when": [
            f"teks lebih dari {presets.MAX_TEXT} karakter",
            "jeda antar-overlay kurang dari 4 detik",
            "lebih dari 2 kali dalam satu klip",
        ],
        "budget_class": "accent",
        "needs_free_area": False,
        "default_size": None,
        "window": {
            "min": presets.MIN_DURATION,
            "typical": presets.DEFAULT_DURATION,
            "max": presets.MAX_DURATION,
        },
        "props": {
            "text": {
                "required": True,
                "type": "str",
                "min": presets.MIN_TEXT,
                "max": presets.MAX_TEXT,
                "doc": f"Teks 1 baris tanpa newline ({presets.MIN_TEXT}-{presets.MAX_TEXT} karakter)",
            },
            "colour": {
                "required": False,
                "type": "str",
                "default": presets.DEFAULT_COLOUR,
                "doc": "Warna teks format #RRGGBB",
            },
            "size_em": {
                "required": False,
                "type": "float",
                "min": presets.MIN_SIZE_EM,
                "max": presets.MAX_SIZE_EM,
                "default": presets.DEFAULT_SIZE_EM,
                "doc": f"Ukuran teks em ({presets.MIN_SIZE_EM}-{presets.MAX_SIZE_EM})",
            },
            "duration": {
                "required": False,
                "type": "float",
                "min": presets.MIN_DURATION,
                "max": presets.MAX_DURATION,
                "default": presets.DEFAULT_DURATION,
                "doc": f"Durasi animasi memuai detik ({presets.MIN_DURATION}-{presets.MAX_DURATION}s)",
            },
        },
        "example": {
            "text": "Fokus!",
            "colour": presets.DEFAULT_COLOUR,
            "size_em": presets.DEFAULT_SIZE_EM,
            "duration": presets.DEFAULT_DURATION,
        },
        "conflicts": ["transform"],
    },
    "checklist": {
        "summary": "Kartu butir berurutan dengan kotak centang animasi spring dan penghitung n of N.",
        "use_when": [
            "daftar butir atau langkah berurutan (2-6 butir)",
            "poin kriteria atau tips bertahap yang diucapkan satu per satu",
        ],
        "avoid_when": [
            "shot close-up talking head tanpa slot bebas",
            f"kurang dari {presets.CHECK_MIN_ITEMS} butir atau lebih dari {presets.CHECK_MAX_ITEMS} butir",
            "dimulai di jendela hook (0-2 detik pertama)",
        ],
        "budget_class": "card",
        "needs_free_area": True,
        "default_size": _CHECKLIST_DEFAULT_SIZE,
        "window": {
            "min": round(presets.CHECK_ENTRY + presets.CHECK_EXIT + 1.5, 2),
            "typical": 6.0,
            "max": 10.0,
        },
        "props": {
            "title": {
                "required": True,
                "type": "str",
                "min": 1,
                "max": presets.CHECK_MAX_TITLE,
                "doc": f"Judul kartu (1-{presets.CHECK_MAX_TITLE} karakter)",
            },
            "items": {
                "required": True,
                "type": "list[dict]",
                "min": presets.CHECK_MIN_ITEMS,
                "max": presets.CHECK_MAX_ITEMS,
                "doc": (
                    f"Daftar {presets.CHECK_MIN_ITEMS}-{presets.CHECK_MAX_ITEMS} butir, "
                    f"tiap butir {{'text': str (maks {presets.CHECK_MAX_ITEM_TEXT} kar), 'done_at': float|None}}"
                ),
            },
        },
        "example": {
            "title": "3 Langkah Sukses",
            "items": [
                {"text": "Mulai dari sekarang", "done_at": 2.0},
                {"text": "Fokus satu hal", "done_at": 3.5},
                {"text": "Konsisten evaluasi", "done_at": 5.0},
            ],
        },
        "conflicts": ["card", "transform"],
    },
    "chart_grow": {
        "summary": "Kartu grafik garis yang tumbuh dari kiri ke kanan dengan titik ujung dan tag nilai/persentase.",
        "use_when": [
            "tren kenaikan atau penurunan statistik dari waktu ke waktu",
            "deret angka berurutan (mis. perbandingan antar tahun)",
        ],
        "avoid_when": [
            "shot close-up talking head tanpa slot bebas",
            f"kurang dari {presets.CHART_MIN_LABELS} label atau lebih dari {presets.CHART_MAX_LABELS} label",
            "dimulai di jendela hook (0-2 detik pertama)",
        ],
        "budget_class": "card",
        "needs_free_area": True,
        "default_size": _CHART_GROW_DEFAULT_SIZE,
        "window": {
            "min": round(presets.CHART_ENTRY + presets.CHART_GROW_MIN + presets.CHART_EXIT, 2),
            "typical": round(presets.CHART_ENTRY + presets.CHART_GROW_DEFAULT + 2.0 + presets.CHART_EXIT, 2),
            "max": 10.0,
        },
        "props": {
            "title": {
                "required": False,
                "type": "str",
                "min": 0,
                "max": presets.CHART_MAX_TITLE,
                "doc": f"Judul grafik opsional (maks {presets.CHART_MAX_TITLE} karakter)",
            },
            "labels": {
                "required": True,
                "type": "list[str]",
                "min": presets.CHART_MIN_LABELS,
                "max": presets.CHART_MAX_LABELS,
                "doc": f"Label sumbu x ({presets.CHART_MIN_LABELS}-{presets.CHART_MAX_LABELS} label, maks {presets.CHART_MAX_LABEL_CHARS} kar)",
            },
            "values": {
                "required": True,
                "type": "list[float]",
                "min": presets.CHART_MIN_LABELS,
                "max": presets.CHART_MAX_LABELS,
                "doc": "Nilai numerik untuk tiap label (panjang sama dengan labels, tidak seragam)",
            },
            "tag": {
                "required": True,
                "type": "str",
                "min": 1,
                "max": presets.CHART_MAX_TAG_CHARS,
                "doc": f"Tag pop-up di titik ujung grafik (maks {presets.CHART_MAX_TAG_CHARS} karakter)",
            },
            "grow": {
                "required": False,
                "type": "float",
                "min": presets.CHART_GROW_MIN,
                "max": presets.CHART_GROW_MAX,
                "default": presets.CHART_GROW_DEFAULT,
                "doc": f"Durasi animasi garis tumbuh detik ({presets.CHART_GROW_MIN}-{presets.CHART_GROW_MAX}s)",
            },
        },
        "example": {
            "title": "Tren Pengguna",
            "labels": ["2021", "2022", "2023"],
            "values": [12.0, 35.0, 80.0],
            "tag": "+566%",
            "grow": presets.CHART_GROW_DEFAULT,
        },
        "conflicts": ["card", "transform"],
    },
    "ui_panel": {
        "summary": "Kartu antarmuka web krem dengan deretan kotak thumbnail dan bilah pencarian/input.",
        "use_when": [
            "menyebutkan situs, aplikasi, direktori, atau galeri kasus",
            "menampilkan kompilasi konten atau thumbnail",
        ],
        "avoid_when": [
            "shot close-up talking head tanpa slot bebas",
            "dimulai di jendela hook (0-2 detik pertama)",
        ],
        "budget_class": "card",
        "needs_free_area": True,
        "default_size": _UI_PANEL_DEFAULT_SIZE,
        "window": {
            "min": round(presets.UI_ENTRY + presets.UI_EXIT + 1.5, 2),
            "typical": 6.0,
            "max": 10.0,
        },
        "props": {
            "title": {
                "required": True,
                "type": "str",
                "min": presets.UI_MIN_TITLE_CHARS,
                "max": presets.UI_MAX_TITLE_CHARS,
                "doc": f"Judul panel ({presets.UI_MIN_TITLE_CHARS}-{presets.UI_MAX_TITLE_CHARS} karakter)",
            },
            "tag": {
                "required": True,
                "type": "str",
                "min": presets.UI_MIN_TAG_CHARS,
                "max": presets.UI_MAX_TAG_CHARS,
                "doc": f"Tag pil kuning ({presets.UI_MIN_TAG_CHARS}-{presets.UI_MAX_TAG_CHARS} karakter)",
            },
            "thumbs": {
                "required": False,
                "type": "int",
                "min": presets.UI_MIN_THUMBS,
                "max": presets.UI_MAX_THUMBS,
                "default": presets.UI_DEFAULT_THUMBS,
                "doc": f"Jumlah thumbnail ({presets.UI_MIN_THUMBS}-{presets.UI_MAX_THUMBS})",
            },
            "input": {
                "required": False,
                "type": "str",
                "min": 0,
                "max": presets.UI_MAX_INPUT_CHARS,
                "doc": f"Teks placeholder bilah input (maks {presets.UI_MAX_INPUT_CHARS} karakter)",
            },
        },
        "example": {
            "title": "Kompilasi Kasus",
            "tag": "VIRAL",
            "thumbs": presets.UI_DEFAULT_THUMBS,
            "input": "Cari topik",
        },
        "conflicts": ["card", "transform"],
    },
    "phone_frame": {
        "summary": "Bingkai ponsel datar vertikal dengan notch, judul, dan deretan baris teks bertahap.",
        "use_when": [
            "menyebutkan aplikasi seluler, chat, DM, notifikasi, atau posting medsos",
            "menampilkan daftar ringkas dalam konteks smartphone",
        ],
        "avoid_when": [
            "shot close-up talking head tanpa slot bebas",
            f"kurang dari {presets_phone.PHONE_MIN_LINES} baris atau lebih dari {presets_phone.PHONE_MAX_LINES} baris",
            "dimulai di jendela hook (0-2 detik pertama)",
        ],
        "budget_class": "card",
        "needs_free_area": True,
        "default_size": _PHONE_FRAME_DEFAULT_SIZE,
        "window": {
            "min": round(presets_phone.PHONE_ENTRY + presets_phone.PHONE_EXIT + 1.5, 2),
            "typical": 6.0,
            "max": 10.0,
        },
        "props": {
            "title": {
                "required": True,
                "type": "str",
                "min": presets_phone.PHONE_MIN_TITLE_CHARS,
                "max": presets_phone.PHONE_MAX_TITLE_CHARS,
                "doc": f"Judul layar ({presets_phone.PHONE_MIN_TITLE_CHARS}-{presets_phone.PHONE_MAX_TITLE_CHARS} karakter)",
            },
            "lines": {
                "required": True,
                "type": "list[str]",
                "min": presets_phone.PHONE_MIN_LINES,
                "max": presets_phone.PHONE_MAX_LINES,
                "doc": (
                    f"Daftar {presets_phone.PHONE_MIN_LINES}-{presets_phone.PHONE_MAX_LINES} baris teks "
                    f"({presets_phone.PHONE_MIN_LINE_CHARS}-{presets_phone.PHONE_MAX_LINE_CHARS} kar per baris)"
                ),
            },
            "accent": {
                "required": False,
                "type": "str",
                "default": presets_phone.PHONE_DEFAULT_ACCENT,
                "doc": "Warna aksen garis format #RRGGBB",
            },
            "side": {
                "required": False,
                "type": "str",
                "default": "right",
                "doc": "Posisi sisi layar ponsel ('right' atau 'left')",
            },
        },
        "example": {
            "title": "Notifikasi Baru",
            "lines": ["Laporan masuk", "Verifikasi data", "Status selesai"],
            "accent": presets_phone.PHONE_DEFAULT_ACCENT,
            "side": "right",
        },
        "conflicts": ["card", "transform"],
    },
    "pullback": {
        "summary": "Video mengecil mengungkap kanvas latar dengan angka statistik count-up besar.",
        "use_when": [
            "pengungkapan angka statistik besar atau perubahan sebelum-sesudah",
            "momen klimaks pengungkapan fakta numerik",
        ],
        "avoid_when": [
            "klip tanpa angka pengungkapan yang dramatis",
            f"fase stabil kurang dari {MIN_STABLE_SECONDS_PULLBACK} detik",
            "lebih dari 1 kali dalam satu klip",
            "dimulai di jendela hook (0-2 detik pertama)",
        ],
        "budget_class": "transform",
        "needs_free_area": False,
        "default_size": None,
        "window": {
            "min": round(pullback.MIN_SHRINK + pullback.MIN_COUNT + pullback.MIN_GROW + MIN_STABLE_SECONDS_PULLBACK, 2),
            "typical": round(pullback.DEFAULT_SHRINK + pullback.DEFAULT_COUNT + pullback.DEFAULT_GROW + 2.0, 2),
            "max": 10.0,
        },
        "props": {
            "from": {
                "required": True,
                "type": "float",
                "doc": "Nilai numerik awal count-up",
            },
            "to": {
                "required": True,
                "type": "float",
                "doc": "Nilai numerik akhir count-up (harus berbeda dari from)",
            },
            "decimals": {
                "required": False,
                "type": "int",
                "min": 0,
                "max": 2,
                "default": 0,
                "doc": "Jumlah digit desimal angka (0-2)",
            },
            "suffix": {
                "required": False,
                "type": "str",
                "min": 0,
                "max": 4,
                "doc": "Akhiran teks angka (mis. '%', 'jt', maks 4 karakter)",
            },
            "title": {
                "required": False,
                "type": "str",
                "min": 0,
                "max": 28,
                "doc": "Judul atas kartu (maks 28 karakter)",
            },
            "label": {
                "required": False,
                "type": "str",
                "min": 0,
                "max": 28,
                "doc": "Label bawah kartu (maks 28 karakter)",
            },
            "shrink": {
                "required": False,
                "type": "float",
                "min": pullback.MIN_SHRINK,
                "max": pullback.MAX_SHRINK,
                "default": pullback.DEFAULT_SHRINK,
                "doc": f"Durasi mengecil detik ({pullback.MIN_SHRINK}-{pullback.MAX_SHRINK}s)",
            },
            "grow": {
                "required": False,
                "type": "float",
                "min": pullback.MIN_GROW,
                "max": pullback.MAX_GROW,
                "default": pullback.DEFAULT_GROW,
                "doc": f"Durasi membesar kembali detik ({pullback.MIN_GROW}-{pullback.MAX_GROW}s)",
            },
            "count": {
                "required": False,
                "type": "float",
                "min": pullback.MIN_COUNT,
                "max": pullback.MAX_COUNT,
                "default": pullback.DEFAULT_COUNT,
                "doc": f"Durasi count-up detik ({pullback.MIN_COUNT}-{pullback.MAX_COUNT}s)",
            },
            "window": {
                "required": False,
                "type": "dict",
                "doc": "Jendela video posisi akhir {x, y, w, h}",
            },
        },
        "example": {
            "from": 10.0,
            "to": 95.0,
            "decimals": 0,
            "suffix": "%",
            "title": "Tingkat Kepuasan",
            "label": "Sebelum vs Sesudah",
            "shrink": pullback.DEFAULT_SHRINK,
            "grow": pullback.DEFAULT_GROW,
            "count": pullback.DEFAULT_COUNT,
        },
        "conflicts": ["accent", "card", "transform"],
    },
}


# ---------------------------------------------------------------------------
# API Publik
# ---------------------------------------------------------------------------

def names() -> tuple[str, ...]:
    """Daftar nama efek yang didukung: jenis presets.PRESET_TYPES + 'pullback'."""
    return tuple(presets.PRESET_TYPES) + ("pullback",)


def get(name: str) -> dict[str, Any]:
    """Ambil entri katalog berdasarkan nama efek."""
    if name not in EFFECTS:
        raise KeyError(f"Efek {name!r} tidak terdaftar di katalog. Sah: {names()}")
    return EFFECTS[name]


def catalog_markdown() -> str:
    """Ringkasan katalog efek dalam Bahasa Indonesia untuk dibaca agen / manusia."""
    lines: list[str] = [
        "# Katalog Efek Video (Tier-2)",
        "",
        "Katalog efek overlay untuk direktur efek (mode `suggest`). "
        "Efek overlay bersifat aditif dan opsional; bawaan klip adalah tanpa overlay.",
        "",
        "## 1. Aturan Anggaran per Klip",
        "",
        f"- **Maksimum total overlay**: {MAX_OVERLAYS_PER_CLIP} per klip",
        f"- **Jeda minimum antar-overlay**: {MIN_GAP_SECONDS:.1f} detik",
        f"- **Jeda minimum antar-kartu**: {CARD_MIN_GAP_SECONDS:.1f} detik",
        f"- **Maksimum aksen (zoom_through_text)**: {MAX_ACCENT_PER_CLIP} per klip",
        f"- **Maksimum transform (pullback)**: {MAX_TRANSFORM_PER_CLIP} per klip",
        f"- **Jendela hook awal klip**: 0 - {HOOK_WINDOW_SECONDS:.1f} detik (kartu/transform dilarang mulai di sini)",
        f"- **Fase stabil pullback minimum**: {MIN_STABLE_SECONDS_PULLBACK:.1f} detik",
        "- *Catatan*: Digital zoom (`punch` tier-1) dikelola otomatis oleh pipeline gerak, bukan overlay pilihan agen.",
        "",
        "## 2. Daftar Efek",
        "",
        "| Efek | Kelas | Area Bebas? | Durasi Tipikal | Kapan Cocok | Hindari Bila |",
        "|---|---|---|---|---|---|",
    ]

    for eff_name in names():
        entry = EFFECTS[eff_name]
        w = entry["window"]
        free_str = "Ya (wajib slot)" if entry["needs_free_area"] else "Tidak (bebas wajah)"
        dur_str = f"{w['min']}..{w['max']} s (tipikal {w['typical']} s)"
        use_str = "; ".join(entry["use_when"])
        avoid_str = "; ".join(entry["avoid_when"])
        lines.append(
            f"| `{eff_name}` | `{entry['budget_class']}` | {free_str} | {dur_str} | {use_str} | {avoid_str} |"
        )

    lines.extend([
        "",
        "## 3. Spesifikasi Props dan Contoh",
        "",
    ])

    for eff_name in names():
        entry = EFFECTS[eff_name]
        lines.append(f"### `{eff_name}`")
        lines.append(f"{entry['summary']}")
        lines.append("")
        lines.append("**Props:**")
        for prop_name, pinfo in entry["props"].items():
            req_str = "wajib" if pinfo.get("required") else "opsional"
            limits = []
            if "min" in pinfo:
                limits.append(f"min={pinfo['min']}")
            if "max" in pinfo:
                limits.append(f"max={pinfo['max']}")
            if "default" in pinfo:
                limits.append(f"bawaan={pinfo['default']!r}")
            limit_str = f" ({', '.join(limits)})" if limits else ""
            lines.append(f"- `{prop_name}` ({pinfo['type']}, {req_str}{limit_str}): {pinfo['doc']}")
        lines.append("")
        lines.append("**Contoh props sah:**")
        lines.append("```json")
        lines.append(json.dumps(entry["example"], indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)
