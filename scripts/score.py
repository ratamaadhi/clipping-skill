"""Scoring: prompt untuk agent + validasi + skor komposit.

Pembagian tugas yang disengaja (docs/DECISIONS.md D-005):
  * agent  -> menilai 6 axis + evidence + fix_suggestion
  * script -> memvalidasi, menghitung komposit, menghitung percentile

Agent DILARANG menulis skor total. Kalau ada field total/final di selection.json,
validasi gagal — karena skor total dari LLM akan meng-anchor axis lain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .lib import jsonio

AXES = ("hook", "payoff", "self_contained", "emotional", "concrete", "loop")

WEIGHTS = {
    "hook": 0.30,
    "payoff": 0.20,
    "self_contained": 0.20,
    "emotional": 0.15,
    "concrete": 0.10,
    "loop": 0.05,
}

# Penalti non-linear: axis kritis tidak boleh tertutup rata-rata.
HOOK_FLOOR = 5.0
HOOK_PENALTY = 0.5
SELF_CONTAINED_FLOOR = 4.0
SELF_CONTAINED_PENALTY = 0.7

# Batas durasi klip yang masuk akal untuk short vertikal.
MIN_CLIP_S = 8.0
MAX_CLIP_S = 90.0

FORBIDDEN_FIELDS = ("total", "final", "score_total", "overall", "virality", "viral_score")

AXIS_GUIDE = {
    "hook": "Apakah 1.5 detik pertama menciptakan ketegangan/rasa penasaran? Klaim, pertanyaan, angka, atau kontradiksi.",
    "payoff": "Apakah ada resolusi/insight? Apakah hook dibayar di akhir?",
    "self_contained": "Bisa dipahami tanpa konteks sebelumnya? Tidak ada pronomina menggantung atau 'seperti tadi saya bilang'.",
    "emotional": "Ada muatan emosi: opini, kejutan, kontroversi, humor, frustrasi?",
    "concrete": "Spesifik (angka, contoh, cerita) atau abstrak?",
    "loop": "Kalau diulang, ending-nya nyambung ke awal? Mendorong rewatch?",
}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def build_prompt(work_dir: str | Path) -> str:
    wd = Path(work_dir)
    cands = jsonio.read_json(wd / "candidates.json")
    meta_path = wd / "meta.json"
    meta = jsonio.read_json(meta_path) if meta_path.exists() else {}

    lines: list[str] = []
    lines.append("# Tugas: nilai kandidat klip")
    lines.append("")
    lines.append(
        "Kamu menilai kandidat klip short-form. Nilai 6 axis secara **independen**, "
        "skala 0-10. Wajib sertakan `evidence` berupa kutipan persis dari teks kandidat."
    )
    lines.append("")
    lines.append("## Rubrik")
    lines.append("")
    for axis in AXES:
        lines.append(f"- **{axis}** (bobot {WEIGHTS[axis]:.2f}) — {AXIS_GUIDE[axis]}")
    lines.append("")
    lines.append("## Aturan")
    lines.append("")
    lines.append("1. **Jangan menulis skor total.** Script yang menghitung. Field `total`/`final` = validasi gagal.")
    lines.append("2. **Jangan mengubah `atom_start`/`atom_end`.** Kalau tidak layak, turunkan skornya.")
    lines.append("3. `evidence` wajib kutipan persis. Tidak bisa mengutip = turunkan skor.")
    lines.append("4. `weakest_axis` + `fix_suggestion` harus konkret dan bisa dieksekusi.")
    lines.append("5. Nilai ke-6 axis sebelum melihat fitur. Fitur hanya konteks tambahan.")
    lines.append("")
    lines.append("## Output")
    lines.append("")
    lines.append(f"Tulis ke `{wd / 'selection.json'}` dengan format `schema/selection.schema.json`.")
    lines.append("")

    if meta:
        lines.append("## Konteks video")
        lines.append("")
        for key in ("source", "duration", "language", "clip_count"):
            if key in meta:
                lines.append(f"- {key}: `{meta[key]}`")
        lines.append("")

    lines.append(f"## Kandidat ({len(cands)})")
    lines.append("")

    for c in cands:
        feats = c.get("features", {})
        lines.append(f"### Kandidat {c['id']}")
        lines.append("")
        lines.append(
            f"`atom_start={c['atom_start']}` `atom_end={c['atom_end']}` "
            f"`start={c['start']}s` `end={c['end']}s` `durasi={c['duration']}s` "
            f"`strategi={c['strategy']}`"
        )
        lines.append("")
        lines.append("```text")
        lines.append(str(c["text"]))
        lines.append("```")
        lines.append("")
        lines.append("Fitur deterministik (konteks, bukan penentu):")
        lines.append("")
        for key in (
            "wpm",
            "filler_ratio",
            "hook_latency",
            "number_density",
            "type_token_ratio",
            "starts_with_conjunction",
            "ends_mid_thought",
            "prosody_score",
            "silence_ratio",
        ):
            if key in feats:
                lines.append(f"- {key}: `{feats[key]}`")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Setelah menulis selection.json, jalankan "
        "`python3 -m scripts.cli score-validate <work_dir>`."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------


def validate_selection(
    sel: dict[str, Any],
    cands: list[dict[str, Any]],
    atoms: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Kembalikan daftar error. Kosong = valid.

    `atoms` opsional. Kalau diberikan, agent boleh mengusulkan rentang atom
    sendiri (bukan hanya yang ada di candidates.json) selama masih di dalam
    batas dan durasinya wajar. Alasannya: prefilter memilih berdasarkan sinyal
    murah (WPM, energi), dan untuk talkshow itu justru melewatkan puncak
    naratif. Agent yang membaca transkrip harus bisa mengoreksi batasnya.
    """
    errors: list[str] = []
    by_id = {int(c["id"]): c for c in cands}

    if not isinstance(sel, dict):
        return ["selection.json harus object"]
    if str(sel.get("version")) != "0.1.0":
        errors.append(f"version harus '0.1.0', dapat {sel.get('version')!r}")

    entries = sel.get("candidates")
    if not isinstance(entries, list) or not entries:
        return errors + ["candidates harus array tidak kosong"]

    seen: set[int] = set()
    for idx, entry in enumerate(entries):
        where = f"candidates[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: harus object")
            continue

        for bad in FORBIDDEN_FIELDS:
            if bad in entry:
                errors.append(
                    f"{where}: field '{bad}' dilarang — skor total dihitung script, bukan agent"
                )

        cid = entry.get("id")
        if not isinstance(cid, int) or isinstance(cid, bool):
            errors.append(f"{where}: id harus integer")
            continue
        if cid in seen:
            errors.append(f"{where}: id {cid} duplikat")
        seen.add(cid)

        a0, a1 = entry.get("atom_start"), entry.get("atom_end")
        if (
            not isinstance(a0, int)
            or not isinstance(a1, int)
            or isinstance(a0, bool)
            or isinstance(a1, bool)
        ):
            errors.append(f"{where}: atom_start/atom_end harus integer")
            continue

        if atoms is not None:
            n = len(atoms)
            if not (0 <= a0 < a1 < n):
                errors.append(
                    f"{where}: rentang atom {a0}-{a1} tidak valid "
                    f"(harus 0 <= start < end <= {n - 1})"
                )
                continue
            dur = float(atoms[a1]["end"]) - float(atoms[a0]["start"])
            if not (MIN_CLIP_S <= dur <= MAX_CLIP_S):
                errors.append(
                    f"{where}: durasi {dur:.1f}s di luar batas {MIN_CLIP_S:g}-{MAX_CLIP_S:g}s"
                )
        elif cid not in by_id:
            errors.append(f"{where}: id {cid} tidak ada di candidates.json")
            continue
        else:
            ref = by_id[cid]
            if a0 != ref["atom_start"] or a1 != ref["atom_end"]:
                errors.append(
                    f"{where}: atom_start/atom_end {a0}-{a1} != "
                    f"{ref['atom_start']}-{ref['atom_end']} "
                    "(tanpa atoms, batas tidak boleh diubah)"
                )

        axes = entry.get("axes")
        if not isinstance(axes, dict):
            errors.append(f"{where}: axes hilang")
            continue

        extra = set(axes) - set(AXES)
        if extra:
            errors.append(f"{where}: axis tidak dikenal {sorted(extra)}")
        missing = set(AXES) - set(axes)
        if missing:
            errors.append(f"{where}: axis belum dinilai {sorted(missing)}")

        for axis in AXES:
            node = axes.get(axis)
            if not isinstance(node, dict):
                errors.append(f"{where}.{axis}: harus object {{score, evidence}}")
                continue
            score = node.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                errors.append(f"{where}.{axis}.score: harus angka")
            elif not (0 <= float(score) <= 10):
                errors.append(f"{where}.{axis}.score: {score} di luar 0-10")
            ev = node.get("evidence")
            if not isinstance(ev, str) or len(ev.strip()) < 3:
                errors.append(f"{where}.{axis}.evidence: wajib kutipan, minimal 3 karakter")

        weakest = entry.get("weakest_axis")
        if weakest not in AXES:
            errors.append(f"{where}.weakest_axis: harus salah satu {AXES}")

        fix = entry.get("fix_suggestion")
        if not isinstance(fix, str) or len(fix.strip()) < 8:
            errors.append(f"{where}.fix_suggestion: minimal 8 karakter, harus konkret")

    return errors


# ---------------------------------------------------------------------------
# Komposit
# ---------------------------------------------------------------------------


def composite(axes: dict[str, dict[str, Any]]) -> tuple[float, float, float]:
    """(base, penalty, final_0_10)."""
    scores = {k: float(axes[k]["score"]) for k in AXES}
    base = sum(WEIGHTS[k] * scores[k] for k in AXES)

    penalty = 1.0
    if scores["hook"] < HOOK_FLOOR:
        penalty *= HOOK_PENALTY
    if scores["self_contained"] < SELF_CONTAINED_FLOOR:
        penalty *= SELF_CONTAINED_PENALTY

    return round(base, 4), round(penalty, 4), round(base * penalty, 4)


def _percentile(values: list[float], value: float) -> float:
    """Persentil dalam set ini. Butuh >=2 nilai untuk bermakna."""
    if len(values) < 2:
        return 50.0
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return round((below + 0.5 * (equal - 1)) / (len(values) - 1) * 100.0, 1)


def score(work_dir: str | Path) -> dict[str, Any]:
    """Validasi selection.json lalu tulis scored.json. Raise ValueError bila tidak valid."""
    wd = Path(work_dir)
    cands = jsonio.read_json(wd / "candidates.json")
    sel = jsonio.read_json(wd / "selection.json")
    atoms_doc = jsonio.read_json(wd / "atoms.json")
    atoms = atoms_doc["atoms"] if isinstance(atoms_doc, dict) else atoms_doc

    errors = validate_selection(sel, cands, atoms)
    if errors:
        raise ValueError(
            "selection.json tidak valid:\n  - " + "\n  - ".join(errors)
        )

    by_id = {int(c["id"]): c for c in cands}
    finals = [composite(e["axes"])[2] for e in sel["candidates"]]

    scored: list[dict[str, Any]] = []
    from .candidates import span as _span

    for entry in sel["candidates"]:
        cid = int(entry["id"])
        a0, a1 = int(entry["atom_start"]), int(entry["atom_end"])
        ref = by_id.get(cid)
        if ref is not None and (a0, a1) == (int(ref["atom_start"]), int(ref["atom_end"])):
            span = ref
            strategy = str(ref.get("strategy", "unknown"))
        else:
            # Agent mengoreksi batas dari prefilter (atau mengusulkan rentang baru).
            span = _span(atoms, a0, a1)
            strategy = "agent" if ref is None else f"agent:{ref.get('strategy', '?')}"
        base, penalty, final = composite(entry["axes"])
        scored.append(
            {
                "id": cid,
                "atom_start": span["atom_start"],
                "atom_end": span["atom_end"],
                "start": span["start"],
                "end": span["end"],
                "duration": span["duration"],
                "strategy": strategy,
                "text": span["text"],
                "features": (ref or {}).get("features", {}),
                "axes": {k: float(entry["axes"][k]["score"]) for k in AXES},
                "evidence": {k: entry["axes"][k]["evidence"] for k in AXES},
                "base": base,
                "penalty": penalty,
                "final_0_10": final,
                "final": round(final * 10.0, 1),
                "percentile": _percentile(finals, final),
                "weakest_axis": entry["weakest_axis"],
                "fix_suggestion": entry["fix_suggestion"],
            }
        )

    scored.sort(key=lambda s: (-s["final"], s["id"]))
    for rank, item in enumerate(scored, start=1):
        item["rank"] = rank

    payload = {
        "version": "0.1.0",
        "weights": WEIGHTS,
        "penalty_rules": {
            "hook_below": [HOOK_FLOOR, HOOK_PENALTY],
            "self_contained_below": [SELF_CONTAINED_FLOOR, SELF_CONTAINED_PENALTY],
        },
        "note": "percentile dihitung dalam batch ini; bermakna setelah library >=20 klip",
        "scored": scored,
    }
    jsonio.write_json(wd / "scored.json", payload)
    return payload


def report(payload: dict[str, Any], top: int = 5) -> str:
    lines = ["# Laporan klip", ""]
    lines.append(
        f"Total kandidat dinilai: **{len(payload['scored'])}**. "
        "Skor = ranker relatif, bukan prediksi viral."
    )
    lines.append("")
    for item in payload["scored"][:top]:
        lines.append(f"## #{item['rank']} — klip {item['id']} · skor {item['final']}/100")
        lines.append("")
        lines.append(
            f"`{item['start']}s → {item['end']}s` ({item['duration']}s) · "
            f"persentil {item['percentile']} · strategi `{item['strategy']}`"
        )
        lines.append("")
        lines.append("| axis | skor | bukti |")
        lines.append("|---|---|---|")
        for axis in AXES:
            ev = str(item["evidence"][axis]).replace("|", "\\|")
            lines.append(f"| {axis} | {item['axes'][axis]:.0f} | {ev} |")
        lines.append("")
        lines.append(
            f"**Axis terlemah:** `{item['weakest_axis']}` — {item['fix_suggestion']}"
        )
        lines.append("")
        lines.append("> " + item["text"][:400].replace("\n", " "))
        lines.append("")
    return "\n".join(lines)


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
