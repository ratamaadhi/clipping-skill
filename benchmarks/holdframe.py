"""Eksperimen "hold frame": render hanya frame yang berubah, tahan frame diam dengan ffmpeg.

Hipotesis: overlay 120 frame = masuk 15 + diam 90 + keluar 15. Frame diam identik,
jadi cukup render 15 + 1 + 15 = 31 frame lalu ffmpeg menggandakan frame diam.

Yang diukur (semua dari luar proses, waktu dinding):
  - render penuh 120 frame vs render subset 31 frame, komposisi/ukuran/konkurensi/browser sama,
    dijalankan bergantian (ABBA) supaya hanyut termal tidak memihak salah satu sisi
  - biaya rekonstruksi ffmpeg (tpad+concat) 31 -> 120 frame
  - kesetaraan visual: hash byte fase hold, subset vs penuh, dan piksel hasil rekonstruksi

Hasil: benchmarks/holdframe.json. Jalankan dengan `python3 -B` agar tidak menulis __pycache__.

  python3 -B benchmarks/holdframe.py                  # 300,600,1080 x 3 ulangan
  python3 -B benchmarks/holdframe.py --sizes=600 --reps=2
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageChops
except ImportError:  # perbandingan piksel PIL opsional; framemd5 tetap berjalan
    Image = ImageChops = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent
REMOTION = ROOT / "remotion"
WORK = ROOT / "holdframe_work"
OUT_JSON = ROOT / "holdframe.json"
DEFAULT_BROWSER = "/home/tama/.local/bin/chromium"

N = 120
IN_F = 15
EXIT_F = 15
FPS = 30
HOLD_FIRST = IN_F                      # 15
HOLD_LAST = N - EXIT_F - 1             # 104
HOLD_N = HOLD_LAST - HOLD_FIRST + 1    # 90
SUBSET = list(range(0, HOLD_FIRST + 1)) + list(range(N - EXIT_F, N))  # 0..15 + 105..119
SUBSET_SPEC = f"0-{HOLD_FIRST},{N - EXIT_F}-{N - 1}"
FULL_SPEC = f"0-{N - 1}"
assert len(SUBSET) == IN_F + 1 + EXIT_F == 31

SIZES = {
    "300": {"id": "Phases300", "width": 540, "height": 300},
    "600": {"id": "Phases600", "width": 1080, "height": 600},
    "1080": {"id": "Phases1080", "width": 1080, "height": 1920},
}

MIN_AVAIL_MB = 350.0   # di bawah ini render dihentikan: RAM mesin ini sempit dan swap penuh
SAMPLE_S = 0.3
COOLDOWN_S = 6.0
FFMPEG_REPS = 3


# ----------------------------------------------------------------------------- util sistem

def mem_available_mb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024.0
    return 0.0


def pswpout() -> int:
    for line in Path("/proc/vmstat").read_text().splitlines():
        if line.startswith("pswpout "):
            return int(line.split()[1])
    return 0


def stray_renderers() -> list[str]:
    """Proses Node render lain yang sedang jalan (aturan: tidak boleh ada dua render sekaligus).

    Dicocokkan pada baris perintah yang diawali `node`, supaya proses lain yang kebetulan
    menyebut nama skrip ini di argumennya tidak ikut terhitung.
    """
    out = subprocess.run(["pgrep", "-af", r"^node .*(holdframe_render|remotion_bench)\.mjs"], capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if ln]


def sh(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def med_range(xs: list[float], nd: int = 2) -> dict[str, Any]:
    return {
        "values": [round(x, nd) for x in xs],
        "median": round(statistics.median(xs), nd),
        "min": round(min(xs), nd),
        "max": round(max(xs), nd),
    }


# ----------------------------------------------------------------------------- render

def render(comp: str, spec: str, out_dir: Path, browser: str, log_dir: Path) -> dict[str, Any]:
    """Satu proses Node = satu render. Waktu dinding diukur dari sini, bukan dari dalam Node."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "node", "holdframe_render.mjs",
        f"--id={comp}", f"--out={out_dir}", f"--frames={spec}",
        "--concurrency=1", f"--browser={browser}",
    ]
    stdout_f = (log_dir / "stdout.txt").open("w")
    stderr_f = (log_dir / "stderr.txt").open("w")
    avail0, swap0, load0 = mem_available_mb(), pswpout(), os.getloadavg()[0]
    avail_min = avail0
    aborted = False

    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=REMOTION, stdout=stdout_f, stderr=stderr_f, text=True, start_new_session=True)
    # wait(timeout) kembali seketika saat proses selesai; sleep+poll akan membulatkan
    # waktu dinding ke kelipatan SAMPLE_S (artefak yang sempat terlihat di uji awal).
    while True:
        try:
            proc.wait(timeout=SAMPLE_S)
            break
        except subprocess.TimeoutExpired:
            pass
        avail = mem_available_mb()
        avail_min = min(avail_min, avail)
        if avail < MIN_AVAIL_MB:
            aborted = True
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            break
    wall = time.perf_counter() - t0
    stdout_f.close()
    stderr_f.close()

    out_txt = (log_dir / "stdout.txt").read_text().strip()
    inner: dict[str, Any] = {}
    if proc.returncode == 0 and not aborted:
        inner = json.loads(out_txt.splitlines()[-1])
    pngs = sorted(out_dir.glob("element-*.png"))
    return {
        "ok": proc.returncode == 0 and not aborted,
        "aborted_by_memory_watchdog": aborted,
        "error": None if proc.returncode == 0 and not aborted else (log_dir / "stderr.txt").read_text()[-400:] or out_txt[-400:],
        "wall_s": wall,
        "files": len(pngs),
        "inner": inner,
        "avail_before_mb": round(avail0),
        "avail_min_mb": round(avail_min),
        "swapout_pages_delta": pswpout() - swap0,
        "loadavg1_before": round(load0, 2),
    }


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def frame_path(d: Path, i: int) -> Path:
    return d / f"element-{i:03d}.png"


def check_pair(full_dir: Path, sub_dir: Path) -> dict[str, Any]:
    """Pemeriksaan byte pada satu pasangan render (penuh, subset) dari ulangan yang sama."""
    full_hash = {i: sha256(frame_path(full_dir, i)) for i in range(N)}
    hold_hashes = {full_hash[i] for i in range(HOLD_FIRST, HOLD_LAST + 1)}
    sub_hash = {i: sha256(frame_path(sub_dir, i)) for i in SUBSET}
    same = sum(1 for i in SUBSET if sub_hash[i] == full_hash[i])
    return {
        "hold_frames_in_full_render": HOLD_N,
        "hold_unique_sha256": len(hold_hashes),
        "subset_frames_compared_to_full_by_bytes": len(SUBSET),
        "subset_frames_byte_identical_to_full": same,
        "hold_frame_ref": HOLD_FIRST,
        "hold_ref_equals_all_hold_frames_of_full": all(sub_hash[HOLD_FIRST] == full_hash[i] for i in range(HOLD_FIRST, HOLD_LAST + 1)),
        "enter_exit_frames_distinct_from_hold": all(
            full_hash[i] != full_hash[HOLD_FIRST] for i in list(range(0, HOLD_FIRST)) + list(range(HOLD_LAST + 1, N))
        ),
    }


# ----------------------------------------------------------------------------- ffmpeg

# Frame 15 = frame diam pertama. tpad menambah 89 klon setelahnya: 16 + 89 = 105 frame (0..104),
# lalu concat dengan frame keluar 105..119 -> 120 frame.
RECON_FILTER = f"[0:v]tpad=stop_mode=clone:stop={HOLD_N - 1}[a];[a][1:v]concat=n=2:v=1:a=0[v]"


def recon_inputs(sub_dir: Path) -> list[str]:
    pat = str(sub_dir / "element-%03d.png")
    return [
        "-framerate", str(FPS), "-start_number", "0", "-i", pat,
        "-framerate", str(FPS), "-start_number", str(N - EXIT_F), "-i", pat,
    ]


def run_ffmpeg(args: list[str]) -> tuple[float, str, str]:
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", *args]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg gagal: {r.stderr[-400:]}")
    return wall, r.stdout, r.stderr


def frames_from_progress(stdout: str) -> int:
    nums = re.findall(r"^frame=(\d+)$", stdout, flags=re.M)
    return int(nums[-1]) if nums else -1


def time_recon_null(sub_dir: Path) -> tuple[float, int]:
    wall, out, _ = run_ffmpeg([*recon_inputs(sub_dir), "-filter_complex", RECON_FILTER, "-map", "[v]",
                               "-fps_mode", "passthrough", "-progress", "pipe:1", "-f", "null", "-"])
    return wall, frames_from_progress(out)


def time_recon_png(sub_dir: Path, out_dir: Path) -> tuple[float, int]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    wall, _, _ = run_ffmpeg([*recon_inputs(sub_dir), "-filter_complex", RECON_FILTER, "-map", "[v]",
                             "-fps_mode", "passthrough", "-start_number", "0", str(out_dir / "element-%03d.png")])
    return wall, len(list(out_dir.glob("element-*.png")))


def time_decode_full_null(full_dir: Path) -> tuple[float, int]:
    wall, out, _ = run_ffmpeg(["-framerate", str(FPS), "-start_number", "0", "-i", str(full_dir / "element-%03d.png"),
                               "-fps_mode", "passthrough", "-progress", "pipe:1", "-f", "null", "-"])
    return wall, frames_from_progress(out)


def time_hardlinks(sub_dir: Path, out_dir: Path) -> float:
    """Alternatif tanpa ffmpeg: 120 nama file, frame diam jadi hardlink. Kompositor lalu membaca 120 PNG."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    t0 = time.perf_counter()
    for i in range(N):
        src = i if i <= HOLD_FIRST or i >= N - EXIT_F else HOLD_FIRST
        os.link(frame_path(sub_dir, src), frame_path(out_dir, i))
    return time.perf_counter() - t0


def framemd5(args: list[str]) -> list[str]:
    _, out, _ = run_ffmpeg([*args, "-pix_fmt", "rgba", "-fps_mode", "passthrough", "-f", "framemd5", "-"])
    return [ln.rsplit(",", 1)[-1].strip() for ln in out.splitlines() if ln and not ln.startswith("#")]


def pixel_compare(a_dir: Path, b_dir: Path) -> dict[str, Any]:
    """Selisih piksel per frame antara dua deret 120 frame (RGBA, semua kanal termasuk alpha)."""
    identical, max_diff, hold_identical = 0, 0, 0
    for i in range(N):
        a = Image.open(frame_path(a_dir, i)).convert("RGBA")
        b = Image.open(frame_path(b_dir, i)).convert("RGBA")
        diff = ImageChops.difference(a, b)
        peak = max(hi for _, hi in diff.getextrema())
        max_diff = max(max_diff, peak)
        if peak == 0:
            identical += 1
            if HOLD_FIRST <= i <= HOLD_LAST:
                hold_identical += 1
    return {"frames_compared": N, "frames_identical": identical, "max_abs_channel_diff": max_diff,
            "hold_frames_compared": HOLD_N, "hold_frames_identical": hold_identical}


def verify_reconstruction(full_dir: Path, sub_dir: Path, work: Path) -> dict[str, Any]:
    """Bangun ulang 120 frame dari subset (render terpisah dari render penuh) lalu bandingkan."""
    t, n_png = time_recon_png(sub_dir, work / "recon_png")
    res: dict[str, Any] = {"frames_out": n_png, "frames_expected": N, "frame_count_ok": n_png == N}

    md5_recon = framemd5([*recon_inputs(sub_dir), "-filter_complex", RECON_FILTER, "-map", "[v]"])
    md5_full = framemd5(["-framerate", str(FPS), "-start_number", "0", "-i", str(full_dir / "element-%03d.png")])
    eq = sum(1 for x, y in zip(md5_recon, md5_full) if x == y)
    res["framemd5"] = {
        "frames_recon": len(md5_recon), "frames_full": len(md5_full),
        "frames_equal": eq,
        "hold_equal": sum(1 for i in range(HOLD_FIRST, HOLD_LAST + 1) if i < len(md5_recon) and md5_recon[i] == md5_full[i]),
        "note": "md5 byte RGBA hasil decode, filter tpad+concat langsung (tanpa menulis PNG)",
    }
    if Image is not None:
        res["pixel_png_roundtrip"] = {**pixel_compare(full_dir, work / "recon_png"),
                                      "note": "PNG hasil rekonstruksi ffmpeg dibaca ulang dan dibandingkan per piksel RGBA dengan render penuh"}
    return res


# ----------------------------------------------------------------------------- satu ukuran

def run_size(key: str, reps: int, browser: str) -> dict[str, Any]:
    cfg = SIZES[key]
    comp = cfg["id"]
    base = WORK / comp
    full_dir, sub_dir = base / "full", base / "sub"
    runs: dict[str, list[dict[str, Any]]] = {"full": [], "subset": []}
    pairs: list[dict[str, Any]] = []
    spec = {"full": FULL_SPEC, "subset": SUBSET_SPEC}
    dirs = {"full": full_dir, "subset": sub_dir}

    for rep in range(reps):
        # ABBA: ulangan genap penuh dulu, ganjil subset dulu.
        order = ["full", "subset"] if rep % 2 == 0 else ["subset", "full"]
        for mode in order:
            time.sleep(COOLDOWN_S)
            r = render(comp, spec[mode], dirs[mode], browser, base / f"log_{mode}_{rep + 1}")
            r["rep"] = rep + 1
            runs[mode].append(r)
            inner = r["inner"]
            print(f"  {comp:>10} {mode:>6} #{rep + 1}: wall {r['wall_s']:6.2f}s  files {r['files']:3d}  "
                  f"render {inner.get('render_ms', 0) / 1000:6.2f}s  avail_min {r['avail_min_mb']} MB  "
                  f"swapout {r['swapout_pages_delta']}  {'ABORT' if r['aborted_by_memory_watchdog'] else ''}", flush=True)
            if not r["ok"]:
                return {"id": comp, **{k: cfg[k] for k in ("width", "height")}, "measured": False,
                        "error": r["error"], "runs": runs}
        if runs["full"][-1]["files"] != N or runs["subset"][-1]["files"] != len(SUBSET):
            return {"id": comp, **{k: cfg[k] for k in ("width", "height")}, "measured": False,
                    "error": "jumlah file tidak sesuai", "runs": runs}
        pairs.append({"rep": rep + 1, **check_pair(full_dir, sub_dir)})

    # ffmpeg: pakai direktori dari ulangan terakhir (kedua render sudah selesai dan independen).
    print(f"  {comp:>10} ffmpeg: {FFMPEG_REPS}x tiap varian", flush=True)
    t_null, t_png, t_dec, t_link = [], [], [], []
    n_null = n_png = n_dec = -1
    for _ in range(FFMPEG_REPS):
        w, n_null = time_recon_null(sub_dir)
        t_null.append(w)
        w, n_png = time_recon_png(sub_dir, base / "recon_png_timed")
        t_png.append(w)
        w, n_dec = time_decode_full_null(full_dir)
        t_dec.append(w)
        t_link.append(time_hardlinks(sub_dir, base / "recon_links"))
    shutil.rmtree(base / "recon_png_timed", ignore_errors=True)
    shutil.rmtree(base / "recon_links", ignore_errors=True)

    equivalence = verify_reconstruction(full_dir, sub_dir, base)
    shutil.rmtree(base / "recon_png", ignore_errors=True)

    wall_full = [r["wall_s"] for r in runs["full"]]
    wall_sub = [r["wall_s"] for r in runs["subset"]]
    rend_full = [r["inner"]["render_ms"] / 1000 for r in runs["full"]]
    rend_sub = [r["inner"]["render_ms"] / 1000 for r in runs["subset"]]
    fixed_full = [(r["inner"]["total_ms"] - r["inner"]["render_ms"]) / 1000 for r in runs["full"]]
    fixed_sub = [(r["inner"]["total_ms"] - r["inner"]["render_ms"]) / 1000 for r in runs["subset"]]

    m = statistics.median
    sp_wall = m(wall_full) / m(wall_sub)
    sp_render = m(rend_full) / m(rend_sub)
    recon_null, recon_png, dec_full, link = m(t_null), m(t_png), m(t_dec), m(t_link)

    def paired(a: list[float], b: list[float]) -> list[float]:
        return [round(x / y, 2) for x, y in zip(a, b)]

    return {
        "id": comp,
        "width": cfg["width"], "height": cfg["height"],
        "measured": True,
        "reps": reps,
        "frames": {"full": N, "subset": len(SUBSET), "hold_skipped": N - len(SUBSET),
                   "frame_ratio_predicted_P": round(N / len(SUBSET), 2)},
        "wall_s": {"full": med_range(wall_full), "subset": med_range(wall_sub)},
        "render_phase_s_inprocess": {"full": med_range(rend_full), "subset": med_range(rend_sub),
                                     "note": "renderFrames saja, diukur timer Node; bundling/browser/select/close dikeluarkan"},
        "fixed_setup_s_inprocess": {"full": med_range(fixed_full), "subset": med_range(fixed_sub),
                                    "note": "bundle + buka browser + selectComposition + tutup; tidak berkurang oleh hold frame"},
        "fps": {
            "full_wall": round(N / m(wall_full), 2), "subset_wall": round(len(SUBSET) / m(wall_sub), 2),
            "full_render_phase": round(N / m(rend_full), 2), "subset_render_phase": round(len(SUBSET) / m(rend_sub), 2),
        },
        "speedup": {
            "render_wall_whole_process": {"value": round(sp_wall, 2), "paired_per_rep": paired(wall_full, wall_sub),
                                           "basis": "median(wall penuh)/median(wall subset)"},
            "render_phase_only": {"value": round(sp_render, 2), "paired_per_rep": paired(rend_full, rend_sub)},
        },
        "ffmpeg_s": {
            "reconstruct_tpad_null_sink": {**med_range(t_null, 3), "frames_out": n_null,
                                           "note": "decode 31 PNG + tpad + concat -> 120 frame, tanpa menulis; mirip dipakai kompositor"},
            "reconstruct_tpad_to_png": {**med_range(t_png, 3), "frames_out": n_png,
                                        "note": "batas atas: juga meng-encode 120 PNG ke disk"},
            "decode_full_120_null_sink": {**med_range(t_dec, 3), "frames_out": n_dec,
                                          "note": "pembanding jalur lama: ffmpeg membaca 120 PNG"},
            "hardlink_120_names": {**med_range(t_link, 5),
                                   "note": "alternatif tanpa ffmpeg; kompositor tetap membaca 120 PNG"},
        },
        "net_speedup": {
            "conservative_recon_to_png": round(m(wall_full) / (m(wall_sub) + recon_png), 2),
            "production_like_recon_null": round(m(wall_full) / (m(wall_sub) + recon_null), 2),
            "symmetric_both_pay_ffmpeg_read": round((m(wall_full) + dec_full) / (m(wall_sub) + recon_null), 2),
            "render_phase_only_plus_recon_null": round(m(rend_full) / (m(rend_sub) + recon_null), 2),
            "definition": "waktu_penuh / (waktu_subset + biaya_rekonstruksi); semua median dari waktu dinding",
        },
        "equivalence": {"per_rep_byte_checks": pairs, "reconstruction": equivalence},
        "memory": {
            "avail_min_mb_over_runs": min(r["avail_min_mb"] for ms in runs.values() for r in ms),
            "swapout_pages_total": sum(r["swapout_pages_delta"] for ms in runs.values() for r in ms),
        },
        "runs": runs,
    }


def main(argv: list[str]) -> int:
    sizes = ["600", "300", "1080"]
    reps = 3
    browser = DEFAULT_BROWSER
    keep = False
    for a in argv:
        if a.startswith("--sizes="):
            sizes = a.split("=", 1)[1].split(",")
        elif a.startswith("--reps="):
            reps = int(a.split("=", 1)[1])
        elif a.startswith("--browser="):
            browser = a.split("=", 1)[1]
        elif a == "--keep":
            keep = True
    if reps < 2 or any(s not in SIZES for s in sizes):
        print(__doc__)
        return 2
    if stray := stray_renderers():
        print("render lain sedang berjalan, dibatalkan (aturan: konkurensi 1):\n" + "\n".join(stray))
        return 3

    chk = subprocess.run(["node", "check_static.mjs"], cwd=REMOTION, capture_output=True, text=True)
    static = json.loads(chk.stdout.strip().splitlines()[-1])
    print(f"cek statis numerik fase hold: ok={static['ok']} (pose unik di hold = {static['hold_distinct_poses']})", flush=True)

    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu": next((ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text().splitlines() if ln.startswith("model name")), "?"),
        "nproc": os.cpu_count(),
        "mem_available_mb_start": round(mem_available_mb()),
        "loadavg_start": [round(x, 2) for x in os.getloadavg()],
        "node": sh(["node", "--version"]),
        "ffmpeg": sh(["ffmpeg", "-version"]).splitlines()[0],
        "browser": f"{browser} :: {sh([browser, '--version'])}",
        "remotion": json.loads((REMOTION / "node_modules/remotion/package.json").read_text())["version"],
        "python": platform.python_version(),
        "concurrency": 1,
        "cooldown_s": COOLDOWN_S,
        "note_node": "permintaan tugas menyebut Node 22; mesin ini hanya punya Node 24.15 (sama dengan baseline lama)",
    }
    WORK.mkdir(exist_ok=True)
    configs = []
    t_start = time.time()
    for key in sizes:
        print(f"== {SIZES[key]['id']} {SIZES[key]['width']}x{SIZES[key]['height']}  {reps} ulangan", flush=True)
        configs.append(run_size(key, reps, browser))

    not_measured = [f"{SIZES[k]['id']}" for k in SIZES if k not in sizes]
    payload = {
        "experiment": "hold-frame",
        "plan": {"frames": N, "fps": FPS, "enter_frames": IN_F, "exit_frames": EXIT_F, "hold_frames": HOLD_N,
                 "subset_frames": len(SUBSET), "subset_spec": SUBSET_SPEC,
                 "predicted_frame_ratio_P": round(N / len(SUBSET), 2), "alpha": "RGBA (latar transparan)"},
        "legend": {"T": "terukur oleh skrip ini", "P": "perkiraan, tidak diukur"},
        "meta": meta,
        "static_check_numeric_T": static,
        "configs": configs,
        "not_measured": {"sizes": not_measured, "reason": "tidak diminta pada pemanggilan ini" if not_measured else None},
        "total_runtime_s": round(time.time() - t_start, 1),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n")
    if not keep:
        shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n✓ {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
