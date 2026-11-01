"""Pelacak wajah & pembicara untuk reframe 9:16.

Masalah yang diselesaikan: crop 9:16 hanya mengambil 31,7% lebar frame 16:9.
Kalau dua orang duduk berdampingan (wajah di ~27% dan ~65%), crop tengah jatuh
tepat di celah antar mereka — hasilnya cuma bahu, tanpa wajah.

Pendekatan:
  1. YuNet (OpenCV) mendeteksi wajah + 5 landmark per frame sampel
  2. wajah dikelompokkan jadi track berdasarkan posisi x
  3. "siapa yang bicara" diperkirakan dari gerak daerah mulut antar frame
     (pembicara membuka-tutup mulut, pendengar relatif diam)
  4. track dengan skor gerak tertinggi menang, dengan histeresis supaya
     crop tidak lompat-lompat saat keduanya diam
  5. hasilnya timeline (waktu, bias_x) yang dipakai renderer

Kenapa bukan face landmark mouth-open: YuNet hanya memberi sudut mulut, bukan
bibir atas/bawah. Gerak piksel di kotak mulut lebih sensitif dan tidak butuh
model tambahan.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

MODEL = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet.onnx"

SAMPLE_FPS = 5.0
SAMPLE_W = 640
SAMPLE_H = 360
MOUTH_TOP = 0.58      # mulai dari 58% tinggi kotak wajah
MOUTH_SIDE = 0.18     # buang 18% kiri-kanan (pipi)
MOUTH_SIZE = (32, 16)  # normalisasi ukuran sebelum dibandingkan
WINDOW = 1.2          # detik, jendela penghalusan skor bicara
SWITCH_MARGIN = 1.35  # track lain harus 35% lebih aktif untuk merebut crop
MIN_SCORE = 0.004     # di bawah ini dianggap tidak ada gerak mulut


def available() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:
        return False
    return MODEL.exists()


def _detector(w: int, h: int) -> Any:
    import cv2

    return cv2.FaceDetectorYN_create(str(MODEL), "", (w, h), 0.6, 0.3, 5000)


def _extract_frames(video: Path, start: float, end: float, out_dir: Path) -> list[Path]:
    dur = max(0.1, end - start)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
        "-vf", f"fps={SAMPLE_FPS:g},scale={SAMPLE_W}:{SAMPLE_H}",
        "-q:v", "3", str(out_dir / "f_%04d.jpg"),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(out_dir.glob("f_*.jpg"))


def _mouth_patch(frame: Any, box: tuple[float, float, float, float]) -> Any:
    import cv2

    x, y, w, h = box
    y0 = int(y + h * MOUTH_TOP)
    y1 = int(y + h)
    x0 = int(x + w * MOUTH_SIDE)
    x1 = int(x + w * (1.0 - MOUTH_SIDE))
    if y1 - y0 < 4 or x1 - x0 < 4:
        return None
    patch = frame[max(0, y0):y1, max(0, x0):x1]
    if patch.size == 0:
        return None
    return cv2.resize(patch, MOUTH_SIZE)


def sample(video: str | Path, start: float, end: float) -> list[dict[str, Any]]:
    """Ambil sampel wajah + skor gerak mulut sepanjang [start, end]."""
    import cv2
    import numpy as np

    if not available():
        return []

    video = Path(video)
    det = _detector(SAMPLE_W, SAMPLE_H)

    with tempfile.TemporaryDirectory() as td:
        frames = _extract_frames(video, start, end, Path(td))
        if not frames:
            return []

        out: list[dict[str, Any]] = []
        prev: dict[int, Any] = {}  # track_id -> patch mulut frame sebelumnya
        prev_small = None

        for idx, path in enumerate(frames):
            img = cv2.imread(str(path))
            if img is None:
                continue
            # deteksi ganti shot: kamera berpindah sudut, jadi posisi wajah
            # tidak boleh dirata-rata melintasi batas ini
            small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (32, 18))
            cut = (
                prev_small is not None
                and float(np.abs(small.astype(np.int16) - prev_small.astype(np.int16)).mean()) > 20.0
            )
            prev_small = small

            _, faces = det.detect(img)
            t = round(start + idx / SAMPLE_FPS, 3)
            row: list[dict[str, Any]] = []

            if faces is not None:
                for f in faces:
                    x, y, w, h = (float(f[0]), float(f[1]), float(f[2]), float(f[3]))
                    score = float(f[14])
                    if score < 0.6 or w < 20:
                        continue
                    cx = (x + w / 2.0) / SAMPLE_W
                    cy = (y + h / 2.0) / SAMPLE_H
                    patch = _mouth_patch(img, (x, y, w, h))
                    row.append(
                        {
                            "cx": round(cx, 4),
                            "cy": round(cy, 4),
                            "w": round(w / SAMPLE_W, 4),
                            "patch": patch,
                            "motion": 0.0,
                        }
                    )

            # cocokkan wajah dengan frame sebelumnya berdasarkan jarak x terdekat
            for face in row:
                best, best_d = None, 1e9
                for key, p in prev.items():
                    if p is None or face["patch"] is None:
                        continue
                    d = abs(face["cx"] - key)
                    if d < best_d:
                        best, best_d = key, d
                if best is not None and best_d < 0.15 and best in prev and prev[best] is not None:
                    a = face["patch"].astype(np.int16)
                    b = prev[best].astype(np.int16)
                    face["motion"] = float(np.abs(a - b).mean() / 255.0)
            prev = {f["cx"]: f["patch"] for f in row}

            row.sort(key=lambda f: f["cx"])
            out.append(
                {
                    "t": t,
                    "cut": bool(cut),
                    "faces": [{k: v for k, v in f.items() if k != "patch"} for f in row],
                }
            )
        return out


def _pick_face(
    faces: list[dict[str, Any]], target: float | None
) -> dict[str, Any] | None:
    """Pilih wajah yang paling masuk akal untuk diikuti pada frame ini.

    Bukan clustering global: kamera berpindah shot dan wajah muncul-hilang, jadi
    yang penting adalah kesinambungan terhadap pilihan frame sebelumnya.
    """
    if not faces:
        return None
    if target is None:
        return max(faces, key=lambda f: f["w"])

    def cost(f: dict[str, Any]) -> float:
        dist = abs(f["cx"] - target)
        return f["w"] * 2.0 + f["motion"] * 1.5 - dist * 3.0

    best = max(faces, key=cost)
    # lompatan jauh = kemungkinan ganti shot, bukan orang yang sama
    if abs(best["cx"] - target) > 0.25:
        return max(faces, key=lambda f: f["w"])
    return best


def bias_timeline(
    samples: list[dict[str, Any]],
    src_w: int,
    crop_w: int,
    clip_start: float,
) -> list[tuple[float, float]]:
    """Ubah sampel jadi [(detik_relatif, bias_x -1..1)]."""
    if not samples or src_w <= crop_w:
        return []

    free = src_w - crop_w
    if free <= 0:
        return []

    def to_bias(cx: float) -> float:
        x = cx * src_w - crop_w / 2.0
        x = max(0.0, min(float(free), x))
        return round((x / free) * 2.0 - 1.0, 4)

    # 1. pilih satu wajah per frame, jaga kesinambungan
    chosen: list[tuple[float, float]] = []
    target: float | None = None
    for s in samples:
        if s.get("cut"):
            target = None  # shot baru: jangan bawa pilihan dari shot sebelumnya
        faces = s["faces"]
        # kalau ada >=2 wajah dan gerak mulutnya beda jelas, ambil yang paling aktif
        if len(faces) >= 2:
            ranked = sorted(faces, key=lambda f: f["motion"], reverse=True)
            if ranked[0]["motion"] > ranked[1]["motion"] * 1.5 + 1e-6:
                target = ranked[0]["cx"]
                chosen.append((s["t"], target))
                continue
        face = _pick_face(faces, target)
        if face is None:
            continue
        target = face["cx"]
        chosen.append((s["t"], target))

    if not chosen:
        return []

    # 2. agregasi PER SHOT, bukan per frame.
    #    Mengikuti wajah tiap frame membuat kamera gemetar dan melompat antar
    #    orang. Editor manusia memilih satu subjek per shot lalu menahannya.
    shots: list[list[dict[str, Any]]] = []
    cur_shot: list[dict[str, Any]] = []
    for s in samples:
        if s.get("cut") and cur_shot:
            shots.append(cur_shot)
            cur_shot = []
        cur_shot.append(s)
    if cur_shot:
        shots.append(cur_shot)

    timeline: list[tuple[float, float]] = []
    for shot in shots:
        picks: list[float] = []
        for s in shot:
            faces = s["faces"]
            if not faces:
                continue
            if len(faces) >= 2:
                ranked = sorted(faces, key=lambda f: f["motion"], reverse=True)
                # hanya percaya sinyal gerak kalau bedanya jelas
                if ranked[0]["motion"] > ranked[1]["motion"] * 1.5 + 1e-6:
                    picks.append(ranked[0]["cx"])
                    continue
            picks.append(max(faces, key=lambda f: f["w"])["cx"])
        if not picks:
            continue
        picks.sort()
        median_cx = picks[len(picks) // 2]
        timeline.append((round(shot[0]["t"] - clip_start, 3), to_bias(median_cx)))

    return timeline


def _compress(timeline: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Buang titik yang biasnya sama dengan sebelumnya."""
    out: list[tuple[float, float]] = []
    for t, b in timeline:
        if not out or abs(b - out[-1][1]) > 0.02:
            out.append((t, b))
    return out


def analyze_edl(work_dir: str | Path) -> dict[str, Any]:
    """Hitung jalur crop per klip dan tulis ke edl.json.

    Dipisah dari build-edl karena butuh OpenCV: pipeline inti tetap tanpa
    dependency, dan langkah ini opsional. Kalau cv2 tidak ada, edl.json
    dibiarkan apa adanya (reframe tengah).
    """
    from .lib import jsonio
    from .edl import map_time

    wd = Path(work_dir)
    edl = jsonio.read_json(wd / "edl.json")
    meta = jsonio.read_json(wd / "meta.json")

    src = meta.get("mezzanine") or meta.get("source")
    src_w = int(meta["width"])
    src_h = int(meta["height"])
    crop_w = int(round(src_h * 9.0 / 16.0 / 2.0)) * 2
    crop_w = min(crop_w, src_w)

    if not available():
        return {"clips": 0, "reason": "opencv atau model tidak tersedia"}

    done = 0
    for clip in edl.get("clips", []):
        segs = clip.get("segments") or []
        if not segs:
            continue
        first = min(float(s["src_start"]) for s in segs)
        last = max(float(s["src_end"]) for s in segs)
        samples = sample(src, first, last)
        timeline = bias_timeline(samples, src_w, crop_w, first)
        if not timeline:
            continue
        # bias_timeline memakai waktu relatif terhadap awal klip; dengan
        # multi-segment waktu itu harus dipetakan ke timeline output.
        mapped: list[list[float]] = []
        for t_rel, b in timeline:
            out_t = map_time(segs, first + t_rel)
            if out_t is not None:
                mapped.append([out_t, b])
        if mapped:
            reframe = clip.setdefault("reframe", {})
            reframe["mode"] = "track"
            reframe["bias_track"] = mapped
            done += 1

    jsonio.write_json(wd / "edl.json", edl)
    return {"clips": done, "total": len(edl.get("clips", []))}


def crop_expression(timeline: list[tuple[float, float]], crop_w: int, free_x: int) -> str:
    """Ekspresi x untuk filter crop, berupa jumlah ramp yang di-clip.

    x(t) = x0 + Σ Δx_i * clip((t - (t_i - TRANS)) / TRANS, 0, 1)

    Bentuk ini jauh lebih pendek daripada if bersarang dan otomatis
    menghasilkan gerakan linear yang halus antar titik.
    """
    if not timeline:
        return str(free_x // 2)

    TRANS = 0.40

    def x_of(bias: float) -> int:
        return int(round((bias + 1.0) / 2.0 * free_x))

    points = [(t, x_of(b)) for t, b in timeline]
    expr = str(points[0][1])
    for i in range(1, len(points)):
        t_cur, x_cur = points[i]
        x_prev = points[i - 1][1]
        delta = x_cur - x_prev
        if delta == 0:
            continue
        start = max(0.0, t_cur - TRANS)
        expr += f"+({delta})*clip((t-{start:.3f})/{TRANS:g},0,1)"
    return expr
