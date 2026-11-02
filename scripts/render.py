"""Render: EDL -> mp4. Renderer TIDAK punya logika kreatif (docs/DECISIONS.md D-001).

Urutan filter:
  crop (reframe) -> scale 1080x1920 -> setsar -> subtitles (libass)
Audio: loudnorm sekali jalan ke -14 LUFS.

Caption ditulis oleh dua penulis ASS berbeda menurut `clip["caption_style"]`:
`"phrase"` (bawaan, tier-1) memakai `captions.write_ass`; `"kinetic"` (tier-2)
memakai `kinetic.build_ass`. Renderer hanya memilih dan menulis — posisi kata
sudah diputuskan saat EDL dibangun (D-001).

Pratinjau (`preview=True`) mengecilkan frame ke 540x960 @15 fps SETELAH overlay
dan SEBELUM subtitles, lalu meng-encode cepat. ASS tetap PlayRes 1080x1920:
libass menskalakan sendiri, jadi pratinjau menunjukkan tata letak yang sama.

Catatan seek: `-ss` diletakkan SEBELUM `-i`. Dengan re-encode ini akurat dan cepat.
Output dipaksa CFR (`-fps_mode cfr`) supaya durasi caption tidak melayang.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from . import captions as cap_mod
from . import faces
from . import kinetic as kinetic_mod
from . import motion
from . import presets
from . import pullback
from .lib import ffmpegbin
from .lib import jsonio

TARGET_W, TARGET_H = 1080, 1920
TARGET_AR = TARGET_W / TARGET_H

# Pratinjau: setengah resolusi target, 15 fps. Cukup untuk memeriksa timing
# dan tata letak, jauh lebih cepat di-encode dan ditransfer.
PREVIEW_W, PREVIEW_H = 540, 960
PREVIEW_FPS = 15
PREVIEW_PRESET = "ultrafast"
PREVIEW_CRF = 30
PREVIEW_SUFFIX = ".preview.mp4"

CAPTION_STYLES = ("phrase", "kinetic")

EDL = "edl.json"
OUT_DIR = "out"
CAP_DIR = "captions"

class RenderError(RuntimeError):
    pass

# Karakter khusus di dua lapis parser ffmpeg. Nilai opsi (`fontsdir=...`,
# jalur ASS) melewati KEDUANYA:
#   1. parser filtergraph memecah rantai pada `,` `;` `[` `]`, memproses
#      kuotasi `'` dan escape `\`;
#   2. parser opsi filter memecah `key=value:key=value` pada `:`.
# Satu lapis escape TIDAK cukup: `\:` di lapis-1 menjadi `:` di lapis-2 lalu
# dianggap pemisah opsi (terbukti: ffmpeg menolak "No option name near ...").
# Karena itu escape diterapkan dua kali, dari lapis-2 ke lapis-1.
_OPTION_SPECIAL = (":", "'")
_GRAPH_SPECIAL = ("'", ",", ";", "[", "]", ":", " ")

def _escape_level(value: str, special: tuple[str, ...]) -> str:
    """Escape satu lapis parser. Backslash DULU, kalau tidak hasilnya ter-escape lagi."""
    out = str(value).replace("\\", "\\\\")
    for ch in special:
        out = out.replace(ch, "\\" + ch)
    return out

def escape_filter_value(value: str) -> str:
    """Escape nilai opsi filtergraph (`fontsdir=...`) untuk DUA lapis parser.

    Hasilnya aman untuk jalur yang memuat spasi, titik dua, koma, tanda
    kurung siku, kutip tunggal, dan backslash. Backslash dilipatgandakan di
    tiap lapis, jadi satu backslash asli menjadi empat di string akhir —
    itu memang yang dibutuhkan ffmpeg, bukan bug.
    """
    return _escape_level(_escape_level(value, _OPTION_SPECIAL), _GRAPH_SPECIAL)

def _kinetic_fontsdir() -> str:
    """Direktori font bundel absolut (dari lokasi modul, bukan cwd)."""
    return str((Path(__file__).resolve().parent.parent / kinetic_mod.BUNDLED_FONT).parent)

def _presets_fontsdir() -> str:
    """Direktori font bundel absolut untuk preset (DM Serif Display Italic)."""
    return str((Path(__file__).resolve().parent.parent / presets.BUNDLED_FONT).parent)

def _warn(message: str) -> None:
    """Peringatan preset: renderer belum punya `report.md`, jadi tulis stderr.

    Kontrak Langkah 5b: preset yang dilewati (mis. font hilang) hanya
    menghasilkan satu baris peringatan, bukan exception. Awalan `PERINGATAN:`
    dipilih supaya mudah dicari di log CLI; `tests/test_presets_render.py`
    mengunci bentuk ini.
    """
    print(f"PERINGATAN: {message}", file=sys.stderr)

def _captions_fontsdir(fontsdir: str | None, style: str) -> str | None:
    """fontsdir efektif: eksplisit menang; kinetic jatuh ke font bundel.

    Klip frasa TIDAK berubah: tanpa `fontsdir` eksplisit, opsinya tidak dikirim
    sama sekali (perilaku tier-1 sejak awal). Klip kinetic WAJIB memakai font
    bundel — tanpa itu libass diam-diam memakai DejaVu dan layout kata meleset
    (risiko R4).
    """
    if fontsdir:
        return fontsdir
    if style == "kinetic":
        return _kinetic_fontsdir()
    return None

def write_caption_ass(
    clip: dict[str, Any],
    ass_path: str | Path,
    *,
    fps: float = 30.0,
) -> Path:
    """Tulis ASS menurut `caption_style`. Gagal keras bila data tidak lengkap.

    `kinetic` tanpa `words` pada salah satu caption adalah kesalahan EDL, bukan
    kondisi yang boleh menghasilkan nol caption: `build_ass` melewati frasa
    tanpa kata, sehingga klip akan tampil tanpa teks sama sekali. Karena itu
    diperiksa di sini dengan pesan yang menyebut klip dan indeks caption.
    """
    style = str(clip.get("caption_style", "phrase"))
    captions = clip.get("captions") or []

    if style == "phrase":
        return cap_mod.write_ass(captions, ass_path)
    if style == "kinetic":
        for i, cap in enumerate(captions):
            if not (cap.get("words") or []):
                raise RenderError(
                    f"{clip.get('id', '?')}: caption ke-{i} tidak punya `words` "
                    f"(text={cap.get('text')!r}); caption_style=\"kinetic\" "
                    f"butuh waktu per kata. Bangun ulang EDL dengan "
                    f"`build-edl --motion 2` atau ubah caption_style ke \"phrase\"."
                )
        text = kinetic_mod.build_ass(clip, fps=fps)
        p = Path(ass_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p
    raise RenderError(
        f"{clip.get('id', '?')}: caption_style tidak dikenal: {style!r} "
        f"(pakai salah satu dari {CAPTION_STYLES})"
    )


def crop_params(
    src_w: int,
    src_h: int,
    bias_x: float = 0.0,
    bias_y: float = 0.0,
    target_ar: float = TARGET_AR,
) -> tuple[int, int, int, int]:
    """Hitung crop 9:16. bias 0 = tengah, +1 = kanan/bawah, -1 = kiri/atas."""
    if src_w <= 0 or src_h <= 0:
        raise RenderError("dimensi sumber tidak valid")

    src_ar = src_w / src_h
    if src_ar > target_ar:
        ch = src_h
        cw = int(round(ch * target_ar / 2.0)) * 2
    else:
        cw = src_w
        ch = int(round(cw / target_ar / 2.0)) * 2

    cw = min(cw, src_w)
    ch = min(ch, src_h)

    free_x = src_w - cw
    free_y = src_h - ch
    x = int(round(free_x / 2.0 * (1.0 + max(-1.0, min(1.0, bias_x)))))
    y = int(round(free_y / 2.0 * (1.0 + max(-1.0, min(1.0, bias_y)))))
    x = max(0, min(x, free_x))
    y = max(0, min(y, free_y))
    return cw, ch, x, y


def _vf_chain(
    edl: dict[str, Any],
    clip: dict[str, Any],
    ass_rel: str | None = None,
    fontsdir: str | None = None,
    motion_filters: list[str] | None = None,
    fps: float = 30.0,
) -> str:
    src = edl["source"]
    reframe = clip.get("reframe", {}) or {}
    cw, ch, x, y = crop_params(
        int(src["width"]),
        int(src["height"]),
        float(reframe.get("bias_x", 0.0)),
        float(reframe.get("bias_y", 0.0)),
    )

    parts: list[str] = []
    if (cw, ch) != (int(src["width"]), int(src["height"])):
        track = reframe.get("bias_track") or []
        if track:
            # crop bergerak mengikuti wajah; x dievaluasi per frame oleh ffmpeg
            expr = faces.crop_expression(
                [(float(t), float(b)) for t, b in track],
                cw,
                int(src["width"]) - cw,
            )
            parts.append(f"crop={cw}:{ch}:x='{expr}':y={y}")
        else:
            parts.append(f"crop={cw}:{ch}:{x}:{y}")
    parts.append(f"scale={TARGET_W}:{TARGET_H}:flags=lanczos")
    parts.append("setsar=1")

    # Normalisasi fps SEBELUM motion. zoompan memakai d=1, jadi kalau input 25fps
    # dibiarkan, 25 frame masuk -> 25 frame keluar tapi ditimestamppi 30fps:
    # video jadi 0,83x lebih cepat dan audio desync.
    if motion_filters:
        parts.append(f"fps={fps:g}")

    # motion graphics SEBELUM caption, supaya caption selalu di lapisan teratas
    parts.extend(motion_filters or [])

    # PENGAMAN, bukan perbaikan bug. zoompan menulis timestamp sendiri
    # (indeks/fps) sehingga secara teori bisa melenceng dari grid fps dan
    # memicu pembuangan frame saat konversi CFR. Pada pengujian dengan tiga
    # klip nyata, keluaran tanpa baris ini juga bersih (0 celah, 0 duplikat),
    # jadi manfaatnya belum terbukti — biayanya nyaris nol, dijaga sebagai
    # jaring pengaman. Periksa dengan `python3 -m scripts.verify` sebelum
    # menyimpulkan ada frame hilang.
    if any(f.startswith("zoompan") for f in (motion_filters or [])):
        parts.append(f"setpts=N/({fps:g}*TB)")

    if ass_rel:
        sub = f"subtitles={ass_rel}"
        if fontsdir:
            sub += f":fontsdir={fontsdir}"
        parts.append(sub)
    return ",".join(parts)


def _preview_filter() -> str:
    """Fragmen pratinjau: setengah resolusi lalu 15 fps.

    Diletakkan SETELAH overlay dan SEBELUM `subtitles`, jadi overlay tetap
    dihitung di ruang 1080x1920 (koordinatnya tidak perlu diubah) dan libass
    menerima frame yang sudah kecil — lebih murah, dan ASS PlayRes tetap
    1080x1920 sehingga libass menskalakan sendiri.
    """
    return f"scale={PREVIEW_W}:{PREVIEW_H}:flags=bilinear,fps={PREVIEW_FPS:g}"

def render_clip(
    edl: dict[str, Any],
    clip: dict[str, Any],
    work_dir: str | Path,
    out_path: str | Path,
    crf: int = 20,
    preset: str = "veryfast",
    fontsdir: str | None = None,
    *,
    preview: bool = False,
    fx_fontsdir: str | None = None,
) -> Path:
    wd = Path(work_dir)
    src_path = Path(str(edl["source"]["path"])).expanduser()
    if not src_path.is_absolute():
        src_path = (wd / src_path).resolve()
    if not src_path.exists():
        raise RenderError(f"sumber tidak ada: {src_path}")

    segs = clip.get("segments") or []
    if not segs:
        raise RenderError(f"{clip['id']}: tidak punya segments")
    first_start = min(float(s["src_start"]) for s in segs)
    last_end = max(float(s["src_end"]) for s in segs)
    duration = sum(float(s["src_end"]) - float(s["src_start"]) for s in segs)
    if duration <= 0:
        raise RenderError(f"{clip['id']}: durasi <= 0")

    # Offset relatif terhadap titik seek (-ss), karena trim menghitung dari situ.
    rel: list[tuple[float, float]] = [
        (float(s["src_start"]) - first_start, float(s["src_end"]) - first_start)
        for s in segs
    ]

    cap_dir = wd / CAP_DIR
    cap_dir.mkdir(parents=True, exist_ok=True)
    ass_path = cap_dir / f"{clip['id']}.ass"
    fps = float(edl["output"].get("fps", 30.0))
    write_caption_ass(clip, ass_path, fps=fps)
    ass_rel = f"{CAP_DIR}/{clip['id']}.ass"
    style = str(clip.get("caption_style", "phrase"))
    eff_fontsdir = _captions_fontsdir(fontsdir, style)
    escaped_fontsdir = escape_filter_value(eff_fontsdir) if eff_fontsdir else None

    # Preset efek (tier-2) -> satu dokumen ASS + satu filter `subtitles`.
    # Klip tanpa overlay preset TIDAK menulis berkas dan TIDAK menambah filter.
    try:
        fx_ass, fx_warnings = presets.build_fx_ass(clip, fps=fps)
    except presets.PresetError as exc:
        raise RenderError(
            f"{clip.get('id', '?')}: preset overlay tidak valid: {exc}"
        ) from exc
    for warning in fx_warnings:
        _warn(warning)
    fx_rel: str | None = None
    if fx_ass is not None:
        fx_path = cap_dir / f"{clip['id']}.fx.ass"
        fx_path.write_text(fx_ass, encoding="utf-8")
        fx_rel = f"{CAP_DIR}/{clip['id']}.fx.ass"

    # Efek pullback (tier-2) -> scale+overlay video + dokumen ASS sendiri.
    # Klip tanpa overlay pullback TIDAK menulis berkas dan TIDAK menambah filter.
    try:
        pb_plan, pb_warnings = pullback.build(clip, fps=fps)
    except pullback.PullbackError as exc:
        raise RenderError(
            f"{clip.get('id', '?')}: pullback overlay tidak valid: {exc}"
        ) from exc
    for warning in pb_warnings:
        _warn(warning)
    pb_rel: str | None = None
    if pb_plan is not None:
        pb_ass, pb_ass_warnings = pullback.ass(pb_plan, fps=fps)
        for warning in pb_ass_warnings:
            _warn(warning)
        if pb_ass is not None:
            pb_path = cap_dir / f"{clip['id']}.pb.ass"
            pb_path.write_text(pb_ass, encoding="utf-8")
            pb_rel = f"{CAP_DIR}/{clip['id']}.pb.ass"

    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    show_progress = bool(clip.get("progress", True)) and duration > 0

    # --- motion graphics tier-1 ---
    zoom = motion.zoompan_filter(clip.get("punch") or [], fps, TARGET_W, TARGET_H)
    base_motion: list[str] = []
    if zoom:
        base_motion.append(zoom)
    if show_progress:
        base_motion.append(motion.progress_track_filter())

    base = _vf_chain(edl, clip, None, None, base_motion, fps)

    parts: list[str] = []
    if len(rel) == 1:
        parts.append(f"[0:v]{base}[vcat]")
    else:
        labels: list[str] = []
        for i, (a, b) in enumerate(rel):
            parts.append(
                f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[sv{i}]"
            )
            labels.append(f"[sv{i}]")
        parts.append("".join(labels) + f"concat=n={len(rel)}:v=1:a=0[svcat]")
        parts.append(f"[svcat]{base}[vcat]")

    last = "vcat"
    if show_progress:
        parts.append(motion.progress_fill_source(duration, fps, TARGET_W))
        parts.append(f"[{last}][bar]{motion.progress_fill_overlay(duration)}[v1]")
        last = "v1"
    panels = motion.overlay_filters(clip.get("overlays") or [])
    if panels:
        parts.append(f"[{last}]" + ",".join(panels) + "[v2]")
        last = "v2"
    if pb_plan is not None:
        # (1) Sisipkan potongan filter_graph SESUDAH panel overlay tier-1 dan
        #     SEBELUM preset fx subtitles / pratinjau.
        pb_graph = pullback.filter_graph(
            pb_plan, in_label=last, out_label="vpb", fps=fps
        )
        parts.extend(pb_graph)
        last = "vpb"
        # (2) Tambahkan subtitles SESUDAH komposit dan SEBELUM filter pratinjau.
        if pb_rel:
            pb_fonts = fx_fontsdir or _presets_fontsdir()
            pb_sub = (
                f"subtitles={pb_rel}"
                f":fontsdir={escape_filter_value(pb_fonts)}"
            )
            parts.append(f"[{last}]{pb_sub}[vpb_sub]")
            last = "vpb_sub"
    if fx_rel:
        # Setelah panel tier-1, SEBELUM pratinjau dan SEBELUM caption. Filter
        # `subtitles` caption tetap yang terakhir (lihat blok di bawah), jadi
        # caption selalu berada di lapisan atas preset.
        preset_fonts = fx_fontsdir or _presets_fontsdir()
        fx_sub = (
            f"subtitles={fx_rel}"
            f":fontsdir={escape_filter_value(preset_fonts)}"
        )
        parts.append(f"[{last}]{fx_sub}[vfx]")
        last = "vfx"
    if preview:
        # Setelah overlay (masih di ruang 1080x1920), sebelum subtitles.
        parts.append(f"[{last}]{_preview_filter()}[vprev]")
        last = "vprev"
    sub = f"subtitles={ass_rel}" + (f":fontsdir={escaped_fontsdir}" if escaped_fontsdir else "")
    parts.append(f"[{last}]{sub}[v]")

    punch = clip.get("punch") or []
    sfx_events = [
        {"t": float(p["t"]), "kind": "hit" if i % 2 else "whoosh"}
        for i, p in enumerate(punch)
        if i > 0
    ]
    sfx_path = (
        motion.write_sfx_wav(wd / "sfx" / f"{clip['id']}.wav", sfx_events, duration)
        if sfx_events
        else None
    )

    has_audio = bool(edl["source"].get("audio_rate"))
    target_i = float(edl["output"].get("loudness_lufs", -14.0))
    target_tp = float(edl["output"].get("true_peak_db", -1.0))

    if has_audio:
        if len(rel) == 1:
            parts.append(f"[0:a]loudnorm=I={target_i:g}:TP={target_tp:g}:LRA=11[a0]")
        else:
            alabels: list[str] = []
            for i, (a, b) in enumerate(rel):
                parts.append(
                    f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[sa{i}]"
                )
                alabels.append(f"[sa{i}]")
            parts.append(
                "".join(alabels) + f"concat=n={len(rel)}:v=0:a=1[acat]"
            )
            parts.append(f"[acat]loudnorm=I={target_i:g}:TP={target_tp:g}:LRA=11[a0]")
        if sfx_path:
            parts.append("[1:a]volume=1.0[s1]")
            parts.append(
                "[a0][s1]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.95[a]"
            )
        else:
            parts.append("[a0]anull[a]")

    cmd: list[str] = [
        # Biner dipilih SAAT PANGGILAN: tes mengubah env, dan deteksi memanggil
        # subprocess yang tidak boleh terjadi saat import.
        ffmpegbin.resolve(),
        "-hide_banner",
        "-nostats",
        "-y",
        "-ss",
        f"{first_start:.3f}",
        "-t",
        f"{last_end - first_start:.3f}",
        "-i",
        str(src_path),
    ]
    if sfx_path:
        cmd += ["-i", str(sfx_path)]

    cmd += ["-filter_complex", ";".join(p for p in parts if p)]
    cmd += ["-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]

    # Pratinjau: encoder cepat + 15 fps. Non-pratinjau: nilai parameter apa
    # adanya, sehingga perintah tier-1 identik dengan sebelum perubahan ini.
    out_preset = PREVIEW_PRESET if preview else preset
    out_crf = PREVIEW_CRF if preview else crf
    out_fps = PREVIEW_FPS if preview else fps

    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        out_preset,
        "-crf",
        str(out_crf),
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-fps_mode",
        "cfr",
        "-r",
        f"{out_fps:g}",
        "-movflags",
        "+faststart",
        str(out),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", cwd=str(wd))
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1200:]
        raise RenderError(f"ffmpeg gagal untuk {clip['id']}:\n{tail}")
    return out


def render_all(
    work_dir: str | Path,
    top: int | None = None,
    crf: int = 20,
    preset: str = "veryfast",
    fontsdir: str | None = None,
    *,
    preview: bool = False,
) -> list[Path]:
    """Render semua klip EDL. `preview=True` menulis `<id>.preview.mp4`.

    Berkas pratinjau memakai akhiran sendiri sehingga render final tidak pernah
    tertimpa (dan sebaliknya).
    """
    wd = Path(work_dir).expanduser().resolve()
    edl = jsonio.read_json(wd / EDL)
    clips = edl["clips"][: top] if top else edl["clips"]

    out_dir = wd / OUT_DIR
    results: list[Path] = []
    for clip in clips:
        name = f"{clip['id']}{PREVIEW_SUFFIX if preview else '.mp4'}"
        results.append(
            render_clip(
                edl,
                clip,
                wd,
                out_dir / name,
                crf=crf,
                preset=preset,
                fontsdir=fontsdir,
                preview=preview,
            )
        )
    return results
