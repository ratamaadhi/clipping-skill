"""Runner spike matte orang (docs/MOTION-TIER2-PLAN.md, Langkah 1b).

Satu pemanggilan = satu pengukuran (satu model x satu sumber). Tiap pengukuran
berjalan di proses sendiri karena `ru_maxrss` hanya naik sepanjang umur proses:
kalau dua model diukur di proses yang sama, yang kedua mewarisi puncak yang
pertama dan RSS-nya bohong. `--runs N` memanggil dirinya sendiri N kali.

Pipeline yang diukur sama dengan yang akan dipakai produk:
  ffmpeg decode -> crop 9:16 -> fps -> scale -> model -> alpha
  -> penghalusan temporal -> biner 0,5

Yang masuk jam: baca frame + pra-proses + inferensi + pasca-proses + penghalusan.
`lag` (putaran 2) mengukur berapa jauh tepi mask halus tertinggal dari tepi mask mentah.
Yang TIDAK masuk jam: metrik, deteksi wajah, dan pembuatan preview. Frame pertama
dibuang dari pengukuran waktu (inferensi pemanasan, ffmpeg start dingin).

Hasil ditambahkan ke benchmarks/matte.json; vonisnya dibaca matte_gate.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

from benchmarks import matte_metrics as mm  # noqa: E402

MODELS_DIR = REPO / "models"
PREVIEW_DIR = HERE / "matte_preview"
DEFAULT_OUT = HERE / "matte.json"

MODELS: dict[str, dict[str, Any]] = {
    "pphumanseg": {
        "file": "human_segmentation_pphumanseg_2023mar.onnx",
        "url": "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "human_segmentation_pphumanseg/human_segmentation_pphumanseg_2023mar.onnx",
        "input": (192, 192),  # (lebar, tinggi); model ini berukuran tetap
    },
    "modnet": {
        "file": "modnet.onnx",
        "url": "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx",
        "input": (320, 576),  # kelipatan 32, aspek ~9:16
    },
    "yunet": {  # hanya untuk metrik face_in_matte; sama dengan yang dipakai scripts/faces.py
        "file": "face_detection_yunet.onnx",
        "url": "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    },
}

MIN_RATIO_W = 9
MIN_RATIO_H = 16


# --------------------------------------------------------------------------- filter


def crop_filter(iw: int, ih: int, crop_x: float) -> str:
    """Filter ffmpeg `crop` ke 9:16. Kosong bila sumber sudah 9:16 atau lebih sempit.

    Lebar dibulatkan ke genap (608 untuk 1080 tinggi, sama dengan crop reframe produksi)."""
    if iw * MIN_RATIO_H <= ih * MIN_RATIO_W:
        return ""
    cw = int(round(ih * MIN_RATIO_W / MIN_RATIO_H / 2)) * 2
    cx = min(1.0, max(0.0, float(crop_x)))
    x = int(round(cx * (iw - cw) / 2)) * 2
    return f"crop={cw}:{ih}:{x}:0"


def build_vf(iw: int, ih: int, crop_x: float, fps: float, width: int, height: int) -> str:
    parts = []
    crop = crop_filter(iw, ih, crop_x)
    if crop:
        parts.append(crop)
    parts.append(f"fps={fps:g}")
    parts.append(f"scale={width}:{height}")
    return ",".join(parts)


# --------------------------------------------------------------------------- pasca-proses


def alpha_from_pphumanseg(logits: Any, out_hw: tuple[int, int]) -> Any:
    """Logit 2 kelas (latar, orang) -> alpha lembut 0..1 berukuran `out_hw` = (tinggi, lebar).

    Softmax, bukan argmax: argmax membuang kemiringan di tepi, yang justru dibutuhkan
    penghalusan temporal."""
    import cv2
    import numpy as np

    lg = np.asarray(logits, dtype=np.float32)[0]
    lg = lg - lg.max(axis=0, keepdims=True)
    e = np.exp(lg)
    p = e[1] / e.sum(axis=0)
    h, w = out_hw
    a = cv2.resize(p, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(a, 0.0, 1.0).astype(np.float32)


def alpha_from_modnet(out: Any, out_hw: tuple[int, int]) -> Any:
    import cv2
    import numpy as np

    a = np.asarray(out, dtype=np.float32)[0, 0]
    h, w = out_hw
    a = cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(a, 0.0, 1.0).astype(np.float32)


def smooth(prev: Any, cur: Any, w_new: float) -> Any:
    """Rata-rata bergerak eksponensial; `w_new` = bobot frame baru."""
    if prev is None:
        return cur
    return prev + w_new * (cur - prev)


# --------------------------------------------------------------------------- hasil


def build_record(
    *,
    model_kind: str,
    source: str,
    frames: int,
    wall_s: float,
    infer_s: float,
    rss_mb: float,
    load_ms: float,
    face_in_matte: float | None,
    flickers: Sequence[float],
    edge_shifts: Sequence[float],
    area_ok_ratio: float,
    n_faces: int,
    lags: Sequence[float] = (),
    **extra: Any,
) -> dict[str, Any]:
    """`frames` = jumlah frame yang masuk jam (tanpa frame pemanasan)."""
    rec: dict[str, Any] = {
        "id": f"{model_kind}@{Path(source).stem}",
        "model_kind": model_kind,
        "source": Path(source).name,
        "frames": frames,
        "fps_e2e": round(frames / wall_s, 3) if wall_s > 0 else 0.0,
        "fps_infer": round(frames / infer_s, 3) if infer_s > 0 else 0.0,
        "rss_mb": round(rss_mb, 1),
        "load_ms": round(load_ms, 1),
        "face_in_matte": None if face_in_matte is None else round(face_in_matte, 4),
        "n_face_frames": n_faces,
        # yang di-gate: piksel berkedip balik (A->B->A). None bila tidak ada data;
        # 0 akan lolos gate, jadi "tidak ada data" tidak boleh disamarkan jadi 0.
        "flicker_p50": round(mm.percentile(flickers, 50), 3) if flickers else None,
        "flicker_p95": round(mm.percentile(flickers, 95), 3) if flickers else None,
        # diagnostik saja: total pergeseran tepi, mencampur gerak asli dengan jitter
        "edge_shift_p50": round(mm.percentile(edge_shifts, 50), 3) if edge_shifts else None,
        "edge_shift_p95": round(mm.percentile(edge_shifts, 95), 3) if edge_shifts else None,
        # biaya penghalusan temporal: jarak tepi mask halus dari tepi mask mentah.
        # None (bukan 0) bila tidak ada frame yang dihaluskan: 0 akan lolos gate.
        "lag_p50": round(mm.percentile(lags, 50), 3) if lags else None,
        "lag_p95": round(mm.percentile(lags, 95), 3) if lags else None,
        "area_ok_ratio": round(area_ok_ratio, 4),
        "human_ok": None,  # hanya manusia yang boleh mengisi
    }
    rec.update(extra)
    return rec


def same_machine(existing_meta: dict[str, Any], current_meta: dict[str, Any]) -> bool:
    """Berkas hasil dinilai gate dengan SATU `meta.cpu`; jangan campur mesin."""
    old = existing_meta.get("cpu")
    return old is None or old == current_meta.get("cpu")


# --------------------------------------------------------------------------- lingkungan


def cpu_name() -> str:
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if out:
                return out
        else:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine()


def peak_rss_mb() -> float:
    """Puncak proses ini + puncak anak terbesar (ffmpeg), dijumlahkan: batas atas yang
    konservatif. macOS melaporkan byte, Linux kibibyte."""
    div = 1024 * 1024 if sys.platform == "darwin" else 1024
    own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    kids = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return (own + kids) / div


def collect_meta() -> dict[str, Any]:
    import cv2

    try:
        ff = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    except Exception:
        ff = "?"
    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cpu": cpu_name(),
        "nproc": os.cpu_count(),
        "platform": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "ffmpeg": ff,
    }


def probe_size(video: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def download(kind: str) -> None:
    spec = MODELS[kind]
    MODELS_DIR.mkdir(exist_ok=True)
    dest = MODELS_DIR / spec["file"]
    if dest.exists():
        print(f"{kind}: sudah ada")
    else:
        print(f"{kind}: unduh {spec['url']}")
        urllib.request.urlretrieve(spec["url"], dest)
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    print(f"{kind}: {dest.relative_to(REPO)}  {dest.stat().st_size} byte  sha256={sha}")


# --------------------------------------------------------------------------- model


def load_net(kind: str) -> Any:
    import cv2

    path = MODELS_DIR / MODELS[kind]["file"]
    if not path.exists():
        raise FileNotFoundError(f"{path} tidak ada; jalankan --download {kind}")
    return cv2.dnn.readNetFromONNX(str(path))


def preprocess(kind: str, frame: Any) -> Any:
    """BGR uint8 -> blob NCHW float32, RGB, (x/255 - 0,5) / 0,5.

    Normalisasi pphumanseg ditulis dari ingatan atas demo opencv_zoo; bila salah,
    face_in_matte yang menangkapnya."""
    import cv2
    import numpy as np

    w, h = MODELS[kind]["input"]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA)
    x = (rgb.astype(np.float32) / 255.0 - 0.5) / 0.5
    return cv2.dnn.blobFromImage(x)


def to_alpha(kind: str, out: Any, out_hw: tuple[int, int]) -> Any:
    if kind == "pphumanseg":
        return alpha_from_pphumanseg(out, out_hw)
    return alpha_from_modnet(out, out_hw)


def make_face_detector(width: int, height: int) -> Any:
    try:
        from scripts import faces

        if not faces.available():
            print("  (YuNet tidak ada: face_in_matte akan kosong; jalankan --download yunet)")
            return None
        return faces._detector(width, height)
    except Exception as exc:  # deteksi wajah hanya pembanding; jangan mematikan spike
        print(f"  (detektor wajah gagal: {exc})")
        return None


# --------------------------------------------------------------------------- preview


def text_layer(h: int, w: int, text: str = "EDIT") -> Any:
    """Teks besar di ~30% tinggi frame, tempat kepala biasanya berada."""
    import cv2
    import numpy as np

    font = cv2.FONT_HERSHEY_DUPLEX
    (tw, th), _ = cv2.getTextSize(text, font, 1.0, 2)
    scale = 0.92 * w / tw
    thick = max(3, int(scale * 3))
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    layer = np.zeros((h, w), np.uint8)
    cv2.putText(layer, text, ((w - tw) // 2, int(h * 0.30) + th // 2), font, scale, 255, thick, cv2.LINE_AA)
    return layer


def compose_behind(frame: Any, alpha: Any, layer: Any) -> Any:
    """Kasus pakai cover story: teks di BELAKANG orang. Memakai alpha lembut supaya
    kualitas tepi terlihat apa adanya."""
    import numpy as np

    t = (layer.astype(np.float32) / 255.0)[..., None]
    bg = frame.astype(np.float32) * 0.45
    bg = bg * (1.0 - t) + np.array([40, 215, 255], np.float32) * t
    a = alpha[..., None]
    return (frame.astype(np.float32) * a + bg * (1.0 - a)).astype(np.uint8)


def encode_preview(spool: Any, path: Path, width: int, height: int, fps: float) -> None:
    spool.seek(0)
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", str(path)],
        stdin=subprocess.PIPE,
    )
    assert enc.stdin is not None
    shutil.copyfileobj(spool, enc.stdin)
    enc.stdin.close()
    enc.wait()


def write_sheet(samples: list[tuple[Any, Any, Any]], path: Path) -> None:
    import cv2
    import numpy as np

    rows = []
    for frame, mask, comp in samples:
        m3 = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        row = np.hstack([cv2.resize(x, (270, 480)) for x in (frame, m3, comp)])
        rows.append(row)
    if rows:
        cv2.imwrite(str(path), np.vstack(rows[:2]) if len(rows) <= 2 else np.hstack([np.vstack(rows[:2]), np.vstack(rows[2:4])]))


# --------------------------------------------------------------------------- pengukuran


def measure(video: Path, kind: str, a: argparse.Namespace) -> dict[str, Any]:
    import cv2
    import numpy as np

    if a.threads:
        cv2.setNumThreads(a.threads)
    iw, ih = probe_size(video)
    vf = build_vf(iw, ih, a.crop_x, a.mask_fps, a.width, a.height)

    t0 = time.perf_counter()
    net = load_net(kind)
    load_ms = (time.perf_counter() - t0) * 1000.0
    detector = make_face_detector(a.width, a.height)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-ss", f"{a.start:.3f}", "-t", f"{a.seconds:.3f}", "-i", str(video),
           "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    assert proc.stdout is not None
    nbytes = a.width * a.height * 3

    expected = max(1, int(round(a.seconds * a.mask_fps)))
    sample_at = {int(expected * f) for f in (0.1, 0.35, 0.6, 0.85)}
    layer = text_layer(a.height, a.width) if a.preview else None
    spool = tempfile.TemporaryFile() if a.preview else None
    samples: list[tuple[Any, Any, Any]] = []

    prev_alpha = None
    prev_mask = None
    prev_thumb = None
    cuts = 0
    wall = infer = 0.0
    n = timed = 0
    shifts: list[float] = []
    flickers: list[float] = []
    lags: list[float] = []
    hist: list[Any] = []  # mask berurutan dalam shot yang sama (maks 2 terakhir)
    coverages: list[float] = []
    area_flags: list[bool] = []

    while True:
        ta = time.perf_counter()
        raw = proc.stdout.read(nbytes)
        if len(raw) < nbytes:
            break
        frame = np.frombuffer(raw, np.uint8).reshape(a.height, a.width, 3)
        # Cut shot: penghalusan harus mulai ulang (kalau tidak, mask orang A dicampur ke
        # orang B = hantu), dan pasangan frame yang melintasi cut bukan "tepi bergetar".
        thumb = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 18))
        if mm.is_cut(prev_thumb, thumb):
            prev_alpha = None
            prev_mask = None
            hist.clear()
            cuts += 1
        prev_thumb = thumb
        blob = preprocess(kind, frame)
        net.setInput(blob)
        tc = time.perf_counter()
        out = net.forward()
        td = time.perf_counter()
        alpha = to_alpha(kind, out, (a.height, a.width))
        # mask MENTAH diambil sebelum penghalusan: pembanding untuk `lag`. Hanya frame yang
        # benar-benar dihaluskan (prev_alpha ada) yang boleh dihitung; frame pertama shot
        # dan frame sesudah cut disalin apa adanya, jadi lag-nya 0 semu.
        raw_mask = alpha >= 0.5
        was_smoothed = prev_alpha is not None
        alpha_s = smooth(prev_alpha, alpha, a.smooth)
        mask = (alpha_s >= 0.5).astype(np.uint8) * 255
        te = time.perf_counter()

        if n > 0:  # frame 0 = pemanasan
            wall += te - ta
            infer += td - tc
            timed += 1

        # ---- di luar jam
        area_flags.append(mm.area_ok(mask))
        if was_smoothed:
            lags.append(mm.lag_px(mask, raw_mask))
        if prev_mask is not None:
            shifts.append(mm.edge_shift(prev_mask, mask))
        if len(hist) == 2:
            flickers.append(mm.flicker(hist[0], hist[1], mask))
        hist.append(mask)
        del hist[:-2]
        if detector is not None and n % a.face_every == 0:
            _, found = detector.detect(frame)
            if found is not None and len(found):
                best = max(found, key=lambda f: float(f[2]) * float(f[3]))
                coverages.append(mm.face_coverage(mask, best[:4]))
        if a.preview:
            comp = compose_behind(frame, alpha_s, layer)
            spool.write(comp.tobytes())
            if n in sample_at:
                samples.append((frame.copy(), mask.copy(), comp))

        prev_alpha, prev_mask = alpha_s, mask
        n += 1

    proc.stdout.close()
    proc.wait()
    rss = peak_rss_mb()  # sebelum encoder preview menambah puncak anak

    if n == 0:
        raise RuntimeError("ffmpeg tidak menghasilkan frame (cek --start / --video)")

    run_id = f"{kind}@{video.stem}"
    preview_rel = None
    if a.preview and spool is not None:
        PREVIEW_DIR.mkdir(exist_ok=True)
        safe = re.sub(r"[^\w.@-]+", "_", run_id)
        encode_preview(spool, PREVIEW_DIR / f"{safe}.mp4", a.width, a.height, a.mask_fps)
        write_sheet(samples, PREVIEW_DIR / f"{safe}.png")
        preview_rel = f"benchmarks/matte_preview/{safe}.mp4"
        spool.close()

    return build_record(
        model_kind=kind,
        source=video.name,
        frames=timed,
        wall_s=wall,
        infer_s=infer,
        rss_mb=rss,
        load_ms=load_ms,
        face_in_matte=mm.face_in_matte_ratio(coverages),
        flickers=flickers,
        edge_shifts=shifts,
        lags=lags,
        area_ok_ratio=sum(area_flags) / len(area_flags),
        n_faces=len(coverages),
        frames_total=n,
        cuts=cuts,
        start=a.start,
        seconds=a.seconds,
        mask_fps=a.mask_fps,
        size=[a.width, a.height],
        threads=cv2.getNumThreads(),
        smooth_w=a.smooth,
        crop_x=a.crop_x,
        preview=preview_rel,
        note=a.note,
    )


# --------------------------------------------------------------------------- CLI


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Spike matte orang (Langkah 1b)")
    p.add_argument("--download", choices=[*MODELS, "all"], help="unduh model ke models/ lalu keluar")
    p.add_argument("--video", type=Path)
    p.add_argument("--model-kind", choices=["pphumanseg", "modnet"], default="pphumanseg")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--seconds", type=float, default=6.0)
    p.add_argument("--mask-fps", type=float, default=15.0)
    p.add_argument("--width", type=int, default=540)
    p.add_argument("--height", type=int, default=960)
    p.add_argument("--crop-x", type=float, default=0.5, help="0..1, posisi crop 9:16 pada sumber lebar")
    p.add_argument("--smooth", type=float, default=0.6, help="bobot frame baru pada penghalusan temporal")
    p.add_argument("--threads", type=int, default=0, help="thread OpenCV; 0 = bawaan")
    p.add_argument("--face-every", type=int, default=3)
    p.add_argument("--runs", type=int, default=1, help="ulangi N kali, tiap kali di proses baru")
    p.add_argument("--no-preview", dest="preview", action="store_false")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--note", default="")
    p.add_argument("--dry-run", action="store_true", help="cetak hasil, jangan tulis berkas")
    return p.parse_args(argv)


def append_result(out: Path, meta: dict[str, Any], record: dict[str, Any]) -> None:
    data: dict[str, Any] = {"experiment": "matte", "meta": meta, "runs": []}
    if out.exists():
        data = json.loads(out.read_text())
        if not same_machine(data.get("meta", {}), meta):
            raise SystemExit(
                f"{out.name} berisi hasil dari CPU lain ({data['meta'].get('cpu')}). "
                f"Gate menilai satu mesin per berkas: pakai --out lain."
            )
    data.setdefault("runs", []).append(record)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    a = parse(argv)
    if a.download:
        for kind in (MODELS if a.download == "all" else [a.download]):
            download(kind)
        return 0
    if not a.video:
        print("pakai: python3 -m benchmarks.matte_bench --video <berkas> [--model-kind ...]")
        return 2
    if not a.video.exists():
        print(f"video tidak ada: {a.video}")
        return 2

    if a.runs > 1:
        base = [sys.executable, "-m", "benchmarks.matte_bench"] + [
            x for x in (argv if argv is not None else sys.argv[1:])
        ]
        # buang --runs N dari argumen anak; preview hanya di run pertama
        child: list[str] = []
        skip = False
        for tok in base[3:]:
            if skip:
                skip = False
                continue
            if tok == "--runs":
                skip = True
                continue
            if tok.startswith("--runs="):
                continue
            child.append(tok)
        for i in range(a.runs):
            extra = [] if (i == 0 or not a.preview) else ["--no-preview"]
            rc = subprocess.run(base[:3] + child + extra + ["--runs", "1"], cwd=REPO).returncode
            if rc != 0:
                return rc
        return 0

    meta = collect_meta()
    try:
        rec = measure(a.video, a.model_kind, a)
    except Exception as exc:
        rec = {"id": f"{a.model_kind}@{a.video.stem}", "model_kind": a.model_kind,
               "source": a.video.name, "error": f"{type(exc).__name__}: {exc}"}
        print(f"GAGAL {rec['id']}: {rec['error']}")
    else:
        print(
            f"{rec['id']}: {rec['fps_e2e']:.2f} fps e2e ({rec['fps_infer']:.2f} fps model) "
            f"RSS {rec['rss_mb']:.0f} MB, wajah-di-mask {rec['face_in_matte']} "
            f"({rec['n_face_frames']} frame), kedip p50/p95 {rec['flicker_p50']}/{rec['flicker_p95']} px "
            f"(geser total {rec['edge_shift_p50']}/{rec['edge_shift_p95']}), "
            f"lag p50/p95 {rec['lag_p50']}/{rec['lag_p95']} px, cut {rec['cuts']}"
        )
        if rec.get("preview"):
            print(f"  preview: {rec['preview']}")

    if a.dry_run:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
    else:
        append_result(a.out, meta, rec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
