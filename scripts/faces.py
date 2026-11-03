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

# Ramp linier perpindahan crop. Dipakai `crop_expression` (string ffmpeg) dan
# `crop_x_at` (evaluasi Python) supaya hanya ada SATU definisi gerakan.
CROP_RAMP = 0.40

# Pengelompokan wajah per shot: dua deteksi dianggap wajah yang sama bila
# pusat-x-nya berjarak kurang dari fraksi ini dari lebar frame (sama dengan
# ambang pencocokan di `sample()`).
FACE_MATCH_X = 0.15
MAX_TRACK_FACES = 4


def available() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:
        return False
    return MODEL.exists()


def _detector(w: int, h: int) -> Any:
    import cv2

    return cv2.FaceDetectorYN_create(str(MODEL), "", (w, h), 0.6, 0.3, 5000)


def _extract_frames(
    video: Path,
    start: float,
    end: float,
    out_dir: Path,
    size: tuple[int, int] | None = None,
) -> list[Path]:
    sw, sh = size or (SAMPLE_W, SAMPLE_H)
    dur = max(0.1, end - start)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
        "-vf", f"fps={SAMPLE_FPS:g},scale={sw}:{sh}",
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


def sample(
    video: str | Path,
    start: float,
    end: float,
    size: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Ambil sampel wajah + skor gerak mulut sepanjang [start, end].

    `size` harus mengikuti aspek video: frame 9:16 yang dipaksa ke 640x360
    terjepit 3,2x vertikal dan deteksi wajahnya jadi tidak bisa dipercaya.
    """
    import cv2
    import numpy as np

    if not available():
        return []

    video = Path(video)
    sw, sh = size or (SAMPLE_W, SAMPLE_H)
    det = _detector(sw, sh)

    with tempfile.TemporaryDirectory() as td:
        frames = _extract_frames(video, start, end, Path(td), size=(sw, sh))
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
                    cx = (x + w / 2.0) / sw
                    cy = (y + h / 2.0) / sh
                    patch = _mouth_patch(img, (x, y, w, h))
                    row.append(
                        {
                            "cx": round(cx, 4),
                            "cy": round(cy, 4),
                            "w": round(w / sw, 4),
                            "h": round(h / sh, 4),
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


def face_top_margin(samples: list[dict[str, Any]]) -> float | None:
    """Jarak dari tepi atas frame ke ubun-ubun, sebagai fraksi tinggi frame.

    Dipakai untuk membatasi punch-in: zoom memotong (1 - 1/s)/2 dari tinggi
    frame di sisi atas, jadi kalau margin lebih kecil dari itu, kepala terpotong.
    """
    tops: list[float] = []
    for s in samples:
        faces = s.get("faces") or []
        if not faces:
            continue
        # wajah terbesar = subjek utama
        f = max(faces, key=lambda x: x.get("w", 0.0))
        h = float(f.get("h") or f.get("w", 0.0))
        cy = float(f.get("cy", 0.5))
        tops.append(cy - h / 2.0)
    if not tops:
        return None
    tops.sort()
    return round(tops[len(tops) // 2], 4)


def _compress(timeline: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Buang titik yang biasnya sama dengan sebelumnya."""
    out: list[tuple[float, float]] = []
    for t, b in timeline:
        if not out or abs(b - out[-1][1]) > 0.02:
            out.append((t, b))
    return out


def _segment_index(segments: list[dict[str, Any]], t: float) -> int | None:
    """Indeks segmen EDL yang memuat waktu sumber `t` (None = jeda dibuang)."""
    for i, seg in enumerate(segments):
        s = float(seg["src_start"])
        e = float(seg["src_end"])
        if s - 1e-6 <= t <= e + 1e-6:
            return i
    return None


def _sample_face_box(
    face: dict[str, Any],
    sample_size: tuple[float, float],
    src_w: int,
    src_h: int,
    crop_x: float,
    crop_y: float,
    crop_w: int,
    crop_h: float,
    out_w: int,
    out_h: int,
) -> dict[str, float]:
    """Kotak wajah sampel (ternormalisasi) -> px keluaran 1080x1920.

    Rantainya: px sampel -> px sumber -> px keluaran setelah crop bergerak.
    Semua skala diturunkan dari ukuran (bukan angka ajaib): lebar sumber /
    lebar sampel, lalu `out_w / crop_w`; tinggi `out_h / crop_h`.
    """
    sw, sh = sample_size
    cx = float(face["cx"])
    cy = float(face["cy"])
    fw = float(face["w"])
    fh = float(face["h"])

    x_src = (cx * sw - fw * sw / 2.0) * (src_w / sw)
    y_src = (cy * sh - fh * sh / 2.0) * (src_h / sh)
    w_src = fw * src_w
    h_src = fh * src_h

    sx = out_w / crop_w
    sy = out_h / crop_h
    return {
        "x": (x_src - crop_x) * sx,
        "y": (y_src - crop_y) * sy,
        "w": w_src * sx,
        "h": h_src * sy,
    }


def face_track(
    samples: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    src_w: int,
    src_h: int,
    crop_w: int,
    free_x: int,
    timeline: list[tuple[float, float]],
    *,
    sample_size: tuple[int, int],
) -> list[dict[str, Any]]:
    """Kotak wajah per shot untuk `reframe.face_track` (px 1080x1920, pra-punch).

    Kontrak (Langkah 4b-1):

    * **Waktu = OUTPUT**, bukan waktu sumber. Tiap sampel dipetakan lewat
      `edl.map_time`; sampel yang jatuh di jeda yang dibuang dilewati.
    * **Shot** dimulai pada sampel `cut=True` dan pada sambungan segmen EDL
      (indeks segmen berubah). Satu entri per shot, `t` = waktu output sampel
      pertama shot itu.
    * **Satu wajah = satu amplop** (min/max gabungan) atas semua sampel shot.
      Deteksi dikelompokkan per `cx` terdekat dengan ambang `FACE_MATCH_X`
      (0,15 lebar frame, sama seperti `sample()`); maksimum
      `MAX_TRACK_FACES` wajah per shot (yang luas amplopnya terbesar),
      diurutkan `x` menaik.
    * Shot tanpa wajah tetap punya entri `faces: []`.
    * `crop_x` dievaluasi dengan `crop_x_at` pada waktu output tiap sampel;
      `crop_h`/`crop_y` diturunkan dari `render.crop_params` supaya sama
      dengan crop yang benar-benar dipakai renderer (bias_y = 0).

    Fungsi ini murni (tanpa OpenCV). Pemanggil yang memutuskan apakah data
    detektor tersedia; lihat `analyze_edl(face_track=True)`.
    """
    from .edl import map_time
    from .render import TARGET_H, TARGET_W, crop_params

    if not samples:
        return []

    src_w = int(src_w)
    src_h = int(src_h)
    crop_w = int(crop_w)
    free_x = int(free_x)
    sw, sh = float(sample_size[0]), float(sample_size[1])
    if min(src_w, src_h, crop_w, sw, sh) <= 0:
        raise ValueError("dimensi sumber/sampel/crop harus > 0")

    _cw, crop_h, _center_x, crop_y = crop_params(src_w, src_h)

    shots: list[dict[str, Any]] = []
    prev_seg: int | None = None
    for s in samples:
        t_src = float(s["t"])
        out_t = map_time(segments, t_src)
        if out_t is None:
            continue
        seg_idx = _segment_index(segments, t_src)
        if not shots or bool(s.get("cut")) or seg_idx != prev_seg:
            shots.append({"t": round(float(out_t), 3), "clusters": []})
        prev_seg = seg_idx
        clusters: list[dict[str, Any]] = shots[-1]["clusters"]

        crop_x = crop_x_at(timeline, crop_w, free_x, out_t)
        for face in s.get("faces") or []:
            fw = float(face.get("w", 0.0))
            fh = float(face.get("h") or 0.0)
            if fw <= 0.0 or fh <= 0.0:
                continue
            cx = float(face["cx"])
            box = _sample_face_box(
                face, (sw, sh), src_w, src_h, crop_x, crop_y,
                crop_w, crop_h, TARGET_W, TARGET_H,
            )
            best: dict[str, Any] | None = None
            best_d = FACE_MATCH_X
            for cluster in clusters:
                d = abs(cx - cluster["last_cx"])
                if d < best_d:
                    best, best_d = cluster, d
            if best is None:
                best = {"last_cx": cx, "boxes": []}
                clusters.append(best)
            best["boxes"].append(box)
            best["last_cx"] = cx

    out: list[dict[str, Any]] = []
    for shot in shots:
        faces_out: list[dict[str, float]] = []
        for cluster in shot["clusters"]:
            boxes = cluster["boxes"]
            x0 = min(b["x"] for b in boxes)
            y0 = min(b["y"] for b in boxes)
            x1 = max(b["x"] + b["w"] for b in boxes)
            y1 = max(b["y"] + b["h"] for b in boxes)
            faces_out.append({
                "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                "area": (x1 - x0) * (y1 - y0),
            })
        faces_out.sort(key=lambda f: (-f["area"], f["x"]))
        faces_out = faces_out[:MAX_TRACK_FACES]
        faces_out.sort(key=lambda f: f["x"])
        out.append({
            "t": shot["t"],
            "faces": [
                {
                    "x": round(f["x"], 3),
                    "y": round(f["y"], 3),
                    "w": round(f["w"], 3),
                    "h": round(f["h"], 3),
                }
                for f in faces_out
            ],
        })
    return out


# Alias supaya `analyze_edl(..., face_track=...)` (parameter bernama sama)
# masih bisa memanggil fungsi modul ini.
_FACE_TRACK = face_track


def analyze_edl(work_dir: str | Path, *, face_track: bool = False) -> dict[str, Any]:
    """Hitung jalur crop per klip dan tulis ke edl.json.

    Dipisah dari build-edl karena butuh OpenCV: pipeline inti tetap tanpa
    dependency, dan langkah ini opsional. Kalau cv2 tidak ada, edl.json
    dibiarkan apa adanya (reframe tengah).

    `face_track=True` (keyword-only) menambah `reframe.face_track`: kotak
    wajah per shot dalam px keluaran 1080x1920 SEBELUM punch, waktu OUTPUT.
    Nilai bawaan `False` tidak menulis apa pun yang baru dan menghasilkan
    EDL yang byte-identik dengan versi sebelumnya — ini jalur tier-1.
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

        # Margin headroom per sampel, dipetakan ke waktu output. Punch dibatasi
        # per event, bukan per klip: satu klip bisa memuat shot lebar dan
        # close-up sekaligus, dan rata-ratanya menyembunyikan close-up.
        timed: list[tuple[float, float]] = []
        for s in samples:
            fs = s.get("faces") or []
            if not fs:
                continue
            f = max(fs, key=lambda x: x.get("w", 0.0))
            hh = float(f.get("h") or f.get("w", 0.0))
            m = float(f.get("cy", 0.5)) - hh / 2.0
            out_t = map_time(segs, float(s["t"]))
            if out_t is not None:
                timed.append((out_t, round(m, 4)))
        if timed:
            # Disimpan sebagai diagnostik saja. Pembatasan punch berdasarkan
            # margin ini sempat dicoba dan dicabut: A/B pada klip close-up
            # menghasilkan 39 vs 40 frame terpotong, jadi tidak ada manfaatnya.
            clip.setdefault("reframe", {})["face_top"] = round(
                sorted(m for _, m in timed)[len(timed) // 2], 4
            )

        timeline = bias_timeline(samples, src_w, crop_w, first)
        # bias_timeline memakai waktu relatif terhadap awal klip; dengan
        # multi-segment waktu itu harus dipetakan ke timeline output.
        mapped: list[list[float]] = []
        for t_rel, b in timeline:
            out_t = map_time(segs, first + t_rel)
            if out_t is not None:
                mapped.append([out_t, b])

        if face_track and samples:
            reframe = clip.setdefault("reframe", {})
            reframe.setdefault("mode", "center")
            reframe["face_track"] = _FACE_TRACK(
                samples,
                segs,
                src_w,
                src_h,
                crop_w,
                src_w - crop_w,
                [(float(t), float(b)) for t, b in mapped],
                sample_size=(SAMPLE_W, SAMPLE_H),
            )

        if not timeline:
            continue
        if mapped:
            reframe = clip.setdefault("reframe", {})
            reframe["mode"] = "track"
            reframe["bias_track"] = mapped
            done += 1

    jsonio.write_json(wd / "edl.json", edl)
    return {"clips": done, "total": len(edl.get("clips", []))}


def crop_x_at(
    timeline: list[tuple[float, float]],
    crop_w: int,
    free_x: int,
    t: float,
) -> float:
    """Nilai `x` crop pada waktu keluaran `t` (piksel sumber).

    Ini adalah evaluasi Python dari ekspresi yang dibangun
    `crop_expression`, bukan rumus kedua: keduanya memakai `_crop_points` dan
    `CROP_RAMP` yang sama. Perpindahan antar titik linear selama
    `CROP_RAMP` detik dan datar di luar ramp.

    `crop_w` diterima demi keseragaman tanda tangan dengan `crop_expression`
    (di sana pun hanya `free_x` yang menentukan posisi); nilainya tidak dipakai.
    """
    if not timeline:
        return float(free_x // 2)

    points = _crop_points(timeline, free_x)
    x = float(points[0][1])
    for i in range(1, len(points)):
        t_cur, x_cur = points[i]
        delta = x_cur - points[i - 1][1]
        if delta == 0:
            continue
        start = max(0.0, t_cur - CROP_RAMP)
        frac = min(1.0, max(0.0, (float(t) - start) / CROP_RAMP))
        x += delta * frac
    return x


def _crop_points(
    timeline: list[tuple[float, float]], free_x: int
) -> list[tuple[float, int]]:
    """Titik (t, x piksel) dari timeline bias; dipakai kedua evaluator."""

    def x_of(bias: float) -> int:
        return int(round((bias + 1.0) / 2.0 * free_x))

    return [(float(t), x_of(float(b))) for t, b in timeline]


def crop_expression(timeline: list[tuple[float, float]], crop_w: int, free_x: int) -> str:
    """Ekspresi x untuk filter crop, berupa jumlah ramp yang di-clip.

    x(t) = x0 + Σ Δx_i * clip((t - (t_i - TRANS)) / TRANS, 0, 1)

    Bentuk ini jauh lebih pendek daripada if bersarang dan otomatis
    menghasilkan gerakan linear yang halus antar titik.
    """
    if not timeline:
        return str(free_x // 2)

    points = _crop_points(timeline, free_x)
    expr = str(points[0][1])
    for i in range(1, len(points)):
        t_cur, x_cur = points[i]
        x_prev = points[i - 1][1]
        delta = x_cur - x_prev
        if delta == 0:
            continue
        start = max(0.0, t_cur - CROP_RAMP)
        expr += f"+({delta})*clip((t-{start:.3f})/{CROP_RAMP:g},0,1)"
    return expr
