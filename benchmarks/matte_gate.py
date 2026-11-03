"""Vonis gate person matte (docs/MOTION-TIER2-PLAN.md, Langkah 1b).

Ambang ditetapkan lebih dulu, sebelum ada angka. Semuanya [P] di rencana: bila ada
yang perlu diubah, ubah SEBELUM mengukur, bukan sesudah melihat hasil.

Dua vonis yang sengaja tidak dicampur:

  kualitas   face_in_matte, edge_shift, area_ok, human_ok
             tidak bergantung CPU, jadi sah di mesin mana pun untuk menyaring model jelek.
  kecepatan  fps_e2e, rss_mb
             bergantung penuh pada mesin. Hanya sah bila meta.cpu memuat TARGET_CPU.

Di luar mesin target, `GO` dan `GO_SPARSE` tidak pernah keluar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TARGET_CPU = "i5-7300U"

# klip 20 s x 15 langkah mask = 300 mask <= 40 s  -> 7,5 fps
# mode sparse: <= 150 mask <= 60 s                -> 2,5 fps
FPS_GO = 7.5
FPS_SPARSE_MIN = 2.5
RSS_MAX_MB = 1024.0  # sama dengan gate Remotion; ffmpeg tidak berjalan bersamaan

FACE_MIN = 0.95      # sama dengan gate reframe v1 di SCOPE.md
# kedip tepi (A->B->A), px amplitudo per langkah mask di lebar 540. Dikunci sebelum
# `flicker` pernah dihitung pada data nyata. edge_shift (total pergeseran) hanya
# diagnostik: ia menghitung gerak asli sebagai getaran.
FLICKER_P50_MAX = 0.5
FLICKER_P95_MAX = 1.5
AREA_OK_MIN = 0.95

# biaya penghalusan temporal (putaran 2). Dikunci sebelum ada angka putaran 2:
# lag_p50 <= 1,0 px, lag_p95 <= 2,5 px. 2,5 px di lebar 540 ~ 5 px di 1080; di atas itu
# tepi tangan yang bergerak terlihat meninggalkan teks di belakangnya.
LAG_P50_MAX = 1.0
LAG_P95_MAX = 2.5
# di bawah bobot ini penghalusan cukup kuat untuk WAJIB membuktikan biayanya: run tanpa
# `lag` tidak boleh lolos diam-diam (mask lamban tampak "lebih tenang").
SMOOTH_REQUIRE_LAG = 0.6

REQUIRED_KEYS = (
    "id",
    "model_kind",
    "fps_e2e",
    "fps_infer",
    "rss_mb",
    "load_ms",
    "face_in_matte",
    "flicker_p50",
    "flicker_p95",
    "area_ok_ratio",
    "human_ok",
)

# urutan dari terburuk ke terbaik; "terburuk" dipakai untuk menggabungkan run
RANK = {"NO_GO": 0, "OFF_TARGET": 1, "PENDING": 2, "GO_SPARSE": 3, "GO": 4}


def _num(run: dict[str, Any], key: str) -> float | None:
    v = run.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_target(meta: dict[str, Any] | None) -> bool:
    return TARGET_CPU in str((meta or {}).get("cpu", ""))


def speed(run: dict[str, Any]) -> str:
    """GO / GO_SPARSE / NO_GO dari kecepatan dan memori saja."""
    rss = _num(run, "rss_mb") or 0.0
    if rss > RSS_MAX_MB:
        return "NO_GO"
    fps = _num(run, "fps_e2e") or 0.0
    if fps >= FPS_GO:
        return "GO"
    if fps >= FPS_SPARSE_MIN:
        return "GO_SPARSE"
    return "NO_GO"


def _automated_failures(run: dict[str, Any]) -> list[str]:
    out: list[str] = []
    face = _num(run, "face_in_matte")
    if face is None:
        out.append("face_in_matte: tidak ada (kurang dari 10 frame berwajah, atau deteksi mati)")
    elif face < FACE_MIN:
        out.append(f"face_in_matte {face:.3f} < {FACE_MIN}")

    p50 = _num(run, "flicker_p50")
    if p50 is None:
        out.append("flicker_p50: tidak ada")
    elif p50 > FLICKER_P50_MAX:
        out.append(f"flicker_p50 {p50:.2f} px > {FLICKER_P50_MAX}")

    p95 = _num(run, "flicker_p95")
    if p95 is None:
        out.append("flicker_p95: tidak ada")
    elif p95 > FLICKER_P95_MAX:
        out.append(f"flicker_p95 {p95:.2f} px > {FLICKER_P95_MAX}")

    area = _num(run, "area_ok_ratio")
    if area is None:
        out.append("area_ok_ratio: tidak ada")
    elif area < AREA_OK_MIN:
        out.append(f"area_ok_ratio {area:.3f} < {AREA_OK_MIN}")

    # `lag` tidak masuk REQUIRED_KEYS: berkas lama (tanpa lag) tetap bisa dinilai.
    # Ia dinilai bila ada, dan wajib ada bila penghalusannya lebih kuat dari kontrol.
    lag50 = _num(run, "lag_p50")
    lag95 = _num(run, "lag_p95")
    smooth_w = _num(run, "smooth_w")
    has_lag = lag50 is not None or lag95 is not None
    if not has_lag:
        if smooth_w is not None and smooth_w < SMOOTH_REQUIRE_LAG:
            out.append(
                f"lag: tidak ada (wajib bila smooth_w {smooth_w:.2f} < {SMOOTH_REQUIRE_LAG})"
            )
    else:
        if lag50 is None:
            out.append("lag_p50: tidak ada")
        elif lag50 > LAG_P50_MAX:
            out.append(f"lag_p50 {lag50:.2f} px > {LAG_P50_MAX}")
        if lag95 is None:
            out.append("lag_p95: tidak ada")
        elif lag95 > LAG_P95_MAX:
            out.append(f"lag_p95 {lag95:.2f} px > {LAG_P95_MAX}")
    return out


def quality(run: dict[str, Any]) -> str:
    """OK / PENDING / FAIL. PENDING = angka lolos tapi belum ada mata manusia."""
    if _automated_failures(run):
        return "FAIL"
    human = run.get("human_ok")
    if human is False:
        return "FAIL"
    if human is None:
        return "PENDING"
    return "OK"


def failures(run: dict[str, Any]) -> list[str]:
    """Alasan tertulis kenapa satu run tidak lolos (kosong bila lolos penuh)."""
    out = list(_automated_failures(run))
    if run.get("error"):
        out.append(f"error: {run['error']}")
    fps = _num(run, "fps_e2e") or 0.0
    if fps < FPS_SPARSE_MIN:
        out.append(f"fps_e2e {fps:.2f} < {FPS_SPARSE_MIN}")
    rss = _num(run, "rss_mb") or 0.0
    if rss > RSS_MAX_MB:
        out.append(f"rss_mb {rss:.0f} > {RSS_MAX_MB:.0f}")
    if run.get("human_ok") is False:
        out.append("human_ok: ditolak")
    return out


def verdict(run: dict[str, Any], on_target: bool) -> str:
    q = quality(run)
    if q == "FAIL":
        return "NO_GO"
    if not on_target:
        # kecepatan di mesin lain tidak membuktikan apa pun tentang mesin target
        return "OFF_TARGET"
    s = speed(run)
    if s == "NO_GO":
        return "NO_GO"
    if q == "PENDING":
        return "PENDING"
    return s


def apply_reviews(runs: list[dict[str, Any]], reviews: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Terapkan keputusan manusia per id. Tidak menimpa keputusan yang sudah ada di
    run, dan tidak mengubah daftar masukan."""
    reviews = reviews or {}
    out: list[dict[str, Any]] = []
    for r in runs:
        r2 = dict(r)
        if r2.get("human_ok") is None and r2.get("id") in reviews:
            r2["human_ok"] = reviews[r2["id"]]
        out.append(r2)
    return out


def by_model(runs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        groups.setdefault(str(r.get("model_kind", "?")), []).append(r)
    return groups


def model_verdict(runs: list[dict[str, Any]], on_target: bool) -> str:
    """Satu model dinilai dari run terburuknya: satu run jelek cukup untuk membuat
    pemakaian di produksi tidak bisa diandalkan."""
    if not runs:
        return "NO_GO"
    return min((verdict(r, on_target) for r in runs), key=lambda v: RANK[v])


def overall(runs: list[dict[str, Any]], on_target: bool) -> str:
    """Spike memilih satu model, jadi vonis keseluruhan = model terbaik."""
    groups = by_model(runs)
    if not groups:
        return "NO_GO"
    return max((model_verdict(g, on_target) for g in groups.values()), key=lambda v: RANK[v])


def _fmt(v: Any, spec: str) -> str:
    if v is None:
        return "-"
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("pakai: python3 -m benchmarks.matte_gate <matte.json>")
        return 2
    data = json.loads(Path(argv[0]).read_text())
    meta = data.get("meta", {})
    runs = apply_reviews(data.get("runs", []), data.get("reviews"))
    target = is_target(meta)

    print(f"mesin : {meta.get('cpu', '?')}  ({meta.get('platform', '?')}, nproc={meta.get('nproc', '?')})")
    if not target:
        print(f"        BUKAN MESIN TARGET ({TARGET_CPU}): kecepatan dan memori tidak disahkan;")
        print("        hanya vonis kualitas yang berlaku.")
    print()

    head = f"{'run':<34} {'fps':>6} {'RSS':>6} {'wajah':>6} {'kdp50':>5} {'kdp95':>5} {'lag50':>5} {'lag95':>5} {'area':>5} {'mata':>5}  {'kual':<7} {'kec':<9} vonis"
    print(head)
    for r in runs:
        human = {True: "ya", False: "tidak", None: "?"}[r.get("human_ok")]
        print(
            f"{str(r.get('id', '?'))[:34]:<34} {_fmt(r.get('fps_e2e'), '.2f'):>6} "
            f"{_fmt(r.get('rss_mb'), '.0f'):>6} {_fmt(r.get('face_in_matte'), '.3f'):>6} "
            f"{_fmt(r.get('flicker_p50'), '.2f'):>5} {_fmt(r.get('flicker_p95'), '.2f'):>5} "
            f"{_fmt(r.get('lag_p50'), '.2f'):>5} {_fmt(r.get('lag_p95'), '.2f'):>5} "
            f"{_fmt(r.get('area_ok_ratio'), '.2f'):>5} {human:>5}  "
            f"{quality(r):<7} {speed(r):<9} {verdict(r, target)}"
        )
    for r in runs:
        why = failures(r)
        if why and verdict(r, target) == "NO_GO":
            print(f"  ! {r.get('id', '?')}: " + "; ".join(why))

    print()
    for model, group in by_model(runs).items():
        print(f"model {model:<12} {model_verdict(group, target)}   ({len(group)} run)")
    final = overall(runs, target)
    print()
    print(f"VONIS: {final}")
    if final == "NO_GO":
        print("Matte dibekukan. Efek yang butuh mask tidak dikejar; Langkah 2-5 tetap jalan.")
    elif final == "OFF_TARGET":
        print("Kualitas belum gugur, tapi belum ada vonis kecepatan: ulangi di mesin target.")
    elif final == "PENDING":
        print("Angka lolos. Tonton preview.mp4, lalu isi human_ok (true/false) di JSON.")
    elif final == "GO_SPARSE":
        print("Matte hanya layak untuk jendela efek pendek (<= 150 mask per klip).")
    else:
        print("Matte layak untuk seluruh klip. Tulis D-012, lalu buka Langkah 7.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
