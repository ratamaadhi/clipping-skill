"""Entry point CLI.

Semua subcommand idempoten: aman dijalankan ulang tanpa merusak state,
dan hasil antara disimpan sebagai JSON supaya bisa diperiksa manusia.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import candidates as cand_mod
from . import captions as cap_mod
from . import demo as demo_mod
from . import edl as edl_mod
from . import faces
from . import features as feat_mod
from . import fxapply, fxcatalog, fxfeatures, fxplan
from .fxapply import ApprovalRequired, FxApplyError, StaleReport
from . import ingest, render, score, segment, transcribe
from . import kinetic
from . import layout as layout_mod
from .lib import audio as audio_mod
from .lib import ffmpegbin
from .lib import jsonio
from .lib.text import clean as clean_text

# Em caption kinetic. Sama dengan nilai bawaan `kinetic.build_ass`, karena
# `layout` harus mengukur blok yang benar-benar digambar renderer.
CAPTION_EM = 84.0


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------


def _wd(path: str) -> Path:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _need(wd: Path, name: str, hint: str) -> Path:
    p = wd / name
    if not p.exists():
        raise FileNotFoundError(f"{p} belum ada — jalankan `{hint}` dulu")
    return p


def _rms_cache(wd: Path, meta: dict[str, Any]) -> list[tuple[float, float]] | None:
    cache = wd / "rms.json"
    if cache.exists():
        raw = jsonio.read_json(cache)
        return [(float(t), float(db)) for t, db in raw]
    audio48 = meta.get("audio48")
    if not audio48 or not Path(audio48).exists():
        return None
    series = audio_mod.rms_series(audio48, frame_ms=100)
    jsonio.write_json(cache, [[round(t, 3), round(db, 2)] for t, db in series])
    return series


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_ingest(args: argparse.Namespace) -> int:
    meta = ingest.run(args.src, args.out, fps=args.fps, force=args.force)
    print(f"✓ ingest  {meta['width']}x{meta['height']} @ {meta['fps']:.3f}fps  "
          f"{meta['duration']:.1f}s  LUFS={meta['loudness_lufs']}")
    return 0


def step_transcribe(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "meta.json", "ingest")
    tr = transcribe.run(
        wd,
        engine=args.engine,
        language=args.language,
        force=args.force,
        chunk_seconds=args.chunk_seconds,
    )
    print(f"✓ transkrip  {len(tr['words'])} kata  bahasa={tr['language']}  engine={tr['engine']}")
    return 0


def step_segment(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    tr = jsonio.read_json(_need(wd, "transcript.json", "transcribe"))
    atoms = segment.build_atoms(tr["words"])
    jsonio.write_json(wd / "atoms.json", atoms)
    print(f"✓ segment  {len(atoms)} atom  ({segment.total_words(atoms)} kata)")
    return 0


def step_candidates(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    atoms = jsonio.read_json(_need(wd, "atoms.json", "segment"))
    meta = jsonio.read_json(_need(wd, "meta.json", "ingest"))
    rms = _rms_cache(wd, meta)

    cands = cand_mod.generate(
        atoms, top_n=args.top_n, min_dur=args.min_dur, max_dur=args.max_dur, rms=rms
    )
    if not cands:
        raise ValueError(
            "tidak ada kandidat lolos filter. Video mungkin terlalu pendek, "
            "atau coba turunkan --min-dur."
        )
    feat_mod.attach(cands, atoms, rms)
    jsonio.write_json(wd / "candidates.json", cands)

    meta["clip_count"] = len(cands)
    jsonio.write_json(wd / "meta.json", meta)
    print(f"✓ kandidat  {len(cands)} dari {len(atoms)} atom")
    for c in cands:
        print(f"    [{c['id']:2d}] {c['start']:7.1f}s → {c['end']:7.1f}s "
              f"({c['duration']:5.1f}s)  cheap={c['cheap_score']:5.1f}  {c['strategy']}")
    return 0


def step_features(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    cands = jsonio.read_json(_need(wd, "candidates.json", "candidates"))
    atoms = jsonio.read_json(_need(wd, "atoms.json", "segment"))
    meta = jsonio.read_json(_need(wd, "meta.json", "ingest"))
    feat_mod.attach(cands, atoms, _rms_cache(wd, meta))
    jsonio.write_json(wd / "candidates.json", cands)
    print(f"✓ fitur  dihitung ulang untuk {len(cands)} kandidat")
    return 0


def step_score_prompt(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "candidates.json", "candidates")
    sys.stdout.write(score.build_prompt(wd))
    return 0


def step_score_validate(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "selection.json", "score-prompt")
    payload = score.score(wd)
    print(f"✓ skor  {len(payload['scored'])} kandidat dinilai\n")
    print(f"{'rank':>4} {'id':>3} {'final':>6} {'pct':>5} {'hook':>5} {'pay':>5} "
          f"{'self':>5} {'emo':>5} {'conc':>5} {'loop':>5}")
    for s in payload["scored"]:
        a = s["axes"]
        print(f"{s['rank']:>4} {s['id']:>3} {s['final']:>6.1f} {s['percentile']:>5.1f} "
              f"{a['hook']:>5.1f} {a['payoff']:>5.1f} {a['self_contained']:>5.1f} "
              f"{a['emotional']:>5.1f} {a['concrete']:>5.1f} {a['loop']:>5.1f}")
    return 0


def step_faces(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "edl.json", "build-edl")
    info = faces.analyze_edl(wd, face_track=args.face_track)
    if info.get("reason"):
        print(f"! {info['reason']} — crop tetap di tengah")
        return 0
    print(f"✓ wajah  {info['clips']}/{info['total']} klip punya jalur crop")
    for clip in jsonio.read_json(wd / "edl.json")["clips"]:
        tr = (clip.get("reframe") or {}).get("bias_track") or []
        if tr:
            lo = min(b for _, b in tr)
            hi = max(b for _, b in tr)
            print(f"    {clip['id']}  {len(tr):2d} titik  bias {lo:+.2f} … {hi:+.2f}")
    return 0


# ---------------------------------------------------------------------------
# Layout (tier-2): caption/overlay sadar wajah
# ---------------------------------------------------------------------------


def _kinetic_caption_blocks(clip: dict[str, Any]) -> list[dict[str, float]]:
    """Blok caption kinetic: jendela `display_window` + ukuran dari layout_phrase.

    Lebar blok = rentang x ± w/2 baris TERLEBAR (garis x tiap baris dipusatkan
    di 540 oleh `layout_phrase`). Tinggi blok = jumlah baris ×
    `LINE_HEIGHT_EM` × em — bukan tinggi tinta, karena `caption_rect` adalah
    kotak layout yang dipakai `place_caption`/`audit`.
    """
    captions = clip.get("captions") or []
    if not captions:
        return []

    font = kinetic._load_font(None)  # sumber font yang sama dengan build_ass
    center_y = float(layout_mod.CAPTION_CANDIDATES_Y[0])
    blocks: list[dict[str, float]] = []
    for i, cap in enumerate(captions):
        words = cap.get("words") or []
        if not words:
            continue
        start, end = kinetic.display_window(captions, i)

        emphasis = cap.get("emphasis")
        emphasis_clean = clean_text(str(emphasis)) if emphasis else ""
        targets: list[float] = []
        accented = False
        for w in words:
            if (
                emphasis_clean
                and not accented
                and clean_text(str(w["w"])) == emphasis_clean
            ):
                targets.append(kinetic.SCALE_EMPHASIS)
                accented = True
            else:
                targets.append(kinetic.SCALE_END)
        scales = [t / 100.0 for t in targets]

        positions = kinetic.layout_phrase(
            [{"w": str(w["w"])} for w in words],
            font,
            CAPTION_EM,
            center_y=center_y,
            scales=scales,
        )
        lines: dict[int, list[dict[str, Any]]] = {}
        for pos in positions:
            lines.setdefault(int(pos["line"]), []).append(pos)
        block_w = max(
            max(p["x"] + p["w"] / 2.0 for p in line)
            - min(p["x"] - p["w"] / 2.0 for p in line)
            for line in lines.values()
        )
        block_h = len(lines) * kinetic.LINE_HEIGHT_EM * CAPTION_EM
        blocks.append({
            "start": float(start),
            "end": float(end),
            "w": float(block_w),
            "h": float(block_h),
        })
    return blocks


def _layout_overlays(
    clip: dict[str, Any], notes: list[str]
) -> list[dict[str, Any]]:
    """Overlay untuk `compute_layout`: hanya yang punya `rect.w/h` eksplisit.

    `index` pada keluaran `layout.overlays` mengacu ke daftar overlay YANG
    DIPAKAI layout ini, bukan ke `clips[].overlays[]` asli. Overlay tanpa
    `rect` (mis. panel VS tier-1) dilewati dengan satu baris catatan; ukuran
    bawaannya per preset adalah pekerjaan 4b-2.
    """
    out: list[dict[str, Any]] = []
    for i, overlay in enumerate(clip.get("overlays") or []):
        if not isinstance(overlay, dict):
            continue
        rect = overlay.get("rect")
        w = rect.get("w") if isinstance(rect, dict) else None
        h = rect.get("h") if isinstance(rect, dict) else None
        if (
            not isinstance(w, (int, float))
            or isinstance(w, bool)
            or not isinstance(h, (int, float))
            or isinstance(h, bool)
            or w <= 0
            or h <= 0
        ):
            notes.append(
                f"overlay[{i}] {overlay.get('type', '?')} dilewati: rect.w/h "
                f"tidak eksplisit (ukuran bawaan preset = 4b-2)"
            )
            continue
        item: dict[str, Any] = {
            "type": str(overlay.get("type", "")),
            "size": (float(w), float(h)),
        }
        for key in ("start", "end"):
            if key in overlay:
                item[key] = float(overlay[key])
        out.append(item)
    return out


def step_layout(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    edl = jsonio.read_json(_need(wd, "edl.json", "build-edl"))
    fps = float(args.fps)

    for clip in edl.get("clips", []):
        cid = clip.get("id", "?")
        style = str(clip.get("caption_style", "phrase"))
        if style != "kinetic":
            print(f"    {cid}  dilewati: caption_style={style} (tier-1 tidak diubah)")
            continue

        notes: list[str] = []
        blocks = _kinetic_caption_blocks(clip)
        overlays = _layout_overlays(clip, notes)
        for note in notes:
            print(f"    {note}")

        segs = clip.get("segments") or []
        duration = sum(
            float(s["src_end"]) - float(s["src_start"]) for s in segs
        )
        if duration <= 0:
            raise ValueError(f"{cid}: durasi keluaran <= 0")

        reframe = clip.get("reframe") or {}
        track = reframe.get("face_track")
        punch = clip.get("punch") or []

        result = layout_mod.compute_layout(
            track, punch, duration,
            caption_blocks=blocks, overlays=overlays,
        )
        report = layout_mod.audit(
            result, track, punch, duration, blocks, overlays, fps,
        )
        if not args.no_write:
            clip["layout"] = result

        print(f"✓ layout  {cid}  {len(blocks)} frasa  "
              f"{len(result['caption'])} keputusan  {len(overlays)} overlay")
        for entry in result["caption"]:
            print(f"    caption t={entry['t']:.3f} y={entry['y']:.1f} "
                  f"scale={entry['scale']:.2f} {entry['reason']}")
        print(f"    caption∩wajah: {report['caption_face_frames']} frame, "
              f"overlay∩wajah: {report['overlay_face_frames']} frame, "
              f"caption∩overlay: {report['caption_overlay_frames']} frame")

    if not args.no_write:
        jsonio.write_json(wd / "edl.json", edl)
    return 0


def step_build_edl(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "scored.json", "score-validate")
    edl = edl_mod.build(wd, top_n=args.top, motion_tier=args.motion)
    edl_mod.write(wd, edl)
    scored = jsonio.read_json(wd / "scored.json")
    report_path = edl_mod.write_report(wd, scored, edl)
    print(f"✓ EDL  {len(edl['clips'])} klip → {wd / 'edl.json'}")
    print(f"✓ laporan → {report_path}")
    for clip in edl["clips"]:
        segs = clip["segments"]
        total = sum(s["src_end"] - s["src_start"] for s in segs)
        span = segs[-1]["src_end"] - segs[0]["src_start"]
        extra = f"  {len(segs)} potongan, buang {span - total:.1f}s" if len(segs) > 1 else ""
        print(f"    {clip['id']}  {segs[0]['src_start']:7.1f}s → {segs[-1]['src_end']:7.1f}s  "
              f"output {total:5.1f}s{extra}  "
              f"{len(clip['captions'])} caption  skor {clip['score']['final']}")
    return 0


def step_render(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "edl.json", "build-edl")
    try:
        outs = render.render_all(
            wd,
            top=args.top,
            crf=args.crf,
            preset=args.preset,
            fontsdir=args.fontsdir,
            preview=args.preview,
        )
    except (render.RenderError, ffmpegbin.FFmpegError) as exc:
        # Satu baris, kode keluar non-nol. Pesan FFmpegError sudah memuat
        # petunjuk pemasangan; jangan ditelan oleh handler generik di `main`.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for p in outs:
        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"✓ render  {p}  ({size_mb:.1f} MB)")
    return 0


def step_run(args: argparse.Namespace) -> int:
    wd = _wd(args.out)
    ingest.run(args.src, wd, fps=args.fps, force=args.force)
    transcribe.run(
        wd,
        engine=args.engine,
        language=args.language,
        force=args.force,
        chunk_seconds=args.chunk_seconds,
    )
    tr = jsonio.read_json(wd / "transcript.json")
    atoms = segment.build_atoms(tr["words"])
    jsonio.write_json(wd / "atoms.json", atoms)

    meta = jsonio.read_json(wd / "meta.json")
    rms = _rms_cache(wd, meta)
    cands = cand_mod.generate(atoms, top_n=args.top_n, rms=rms)
    if not cands:
        raise ValueError("tidak ada kandidat lolos filter — coba --min-dur yang lebih kecil")
    feat_mod.attach(cands, atoms, rms)
    jsonio.write_json(wd / "candidates.json", cands)

    print(f"✓ siap  {len(cands)} kandidat dari {len(atoms)} atom\n")
    print("Langkah berikutnya (dilakukan agent):")
    print(f"  1. python3 -m scripts.cli score-prompt {wd} > {wd}/score_prompt.md")
    print(f"  2. tulis {wd}/selection.json")
    print(f"  3. python3 -m scripts.cli score-validate {wd}")
    print(f"  4. python3 -m scripts.cli build-edl {wd}")
    print(f"  5. python3 -m scripts.cli render {wd}")
    return 0


def step_demo(args: argparse.Namespace) -> int:
    wd = _wd(args.out)
    tr = demo_mod.synthesize()
    jsonio.write_json(wd / "transcript.json", tr)
    jsonio.write_json(
        wd / "meta.json",
        {
            "version": "0.1.0",
            "source": "synthetic://demo",
            "source_sha256": "demo",
            "duration": tr["duration"],
            "fps": 30.0,
            "width": 1920,
            "height": 1080,
            "has_audio": False,
            "audio_rate": 48000,
            "loudness_lufs": -18.0,
            "mezzanine": "synthetic://demo",
            "language": "id",
        },
    )

    atoms = segment.build_atoms(tr["words"])
    jsonio.write_json(wd / "atoms.json", atoms)

    cands = cand_mod.generate(atoms, top_n=args.top_n)
    if not cands:
        raise ValueError("demo tidak menghasilkan kandidat — cek parameter filter")
    feat_mod.attach(cands, atoms)
    jsonio.write_json(wd / "candidates.json", cands)

    jsonio.write_json(wd / "selection.json", demo_mod.synthetic_selection(cands))
    payload = score.score(wd)
    edl = edl_mod.build(wd, top_n=args.top)
    edl_mod.write(wd, edl)
    edl_mod.write_report(wd, payload, edl)

    print(f"✓ demo  {len(atoms)} atom → {len(cands)} kandidat → {len(edl['clips'])} klip")
    print(f"  {'klip':<10} {'sumber':<22} {'caption':>8} {'skor':>6}")
    for clip in edl["clips"]:
        seg = clip["segments"][0]
        span = f"{seg['src_start']:.1f}s→{seg['src_end']:.1f}s"
        print(f"  {clip['id']:<10} {span:<22} {len(clip['captions']):>8} "
              f"{clip['score']['final']:>6.1f}")
    print(f"\n  laporan: {wd / 'report.md'}")
    print(f"  EDL    : {wd / 'edl.json'}")
    return 0


def step_fx_catalog(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        import json
        payload = {
            "budget": {
                "MAX_OVERLAYS_PER_CLIP": fxcatalog.MAX_OVERLAYS_PER_CLIP,
                "MIN_GAP_SECONDS": fxcatalog.MIN_GAP_SECONDS,
                "CARD_MIN_GAP_SECONDS": fxcatalog.CARD_MIN_GAP_SECONDS,
                "MAX_ACCENT_PER_CLIP": fxcatalog.MAX_ACCENT_PER_CLIP,
                "MAX_TRANSFORM_PER_CLIP": fxcatalog.MAX_TRANSFORM_PER_CLIP,
                "HOOK_WINDOW_SECONDS": fxcatalog.HOOK_WINDOW_SECONDS,
                "MIN_STABLE_SECONDS_PULLBACK": fxcatalog.MIN_STABLE_SECONDS_PULLBACK,
            },
            "effects": fxcatalog.EFFECTS,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(fxcatalog.catalog_markdown())
    return 0


def step_fx_candidates(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    edl_path = _need(wd, "edl.json", "build-edl")
    edl = jsonio.read_json(edl_path)
    if not isinstance(edl, dict):
        raise ValueError(f"{edl_path} harus dokumen JSON objek")

    clip_target = getattr(args, "clip", None)
    if clip_target:
        matching_clips = [
            c for c in edl.get("clips", [])
            if isinstance(c, dict) and c.get("id") == clip_target
        ]
        if not matching_clips:
            print(f"Peringatan: klip {clip_target!r} tidak ditemukan di {edl_path}", file=sys.stderr)
        edl = dict(edl)
        edl["clips"] = matching_clips

    fps = getattr(args, "fps", 30.0)
    candidates_doc = fxfeatures.extract(edl, fps=fps)

    out_path = wd / "fx_candidates.json"
    jsonio.write_json(out_path, candidates_doc)

    print(f"✓ fx-candidates  {out_path.name}  ({len(candidates_doc.get('clips', []))} klip)")
    from collections import Counter
    for c in candidates_doc.get("clips", []):
        cid = c.get("clip_id", "?")
        dur = c.get("duration", 0.0)
        shots = c.get("shots", [])
        shot_kinds = sorted(set(s.get("shot_kind", "unknown") for s in shots))
        shot_str = ", ".join(shot_kinds) if shot_kinds else "unknown"
        moments = c.get("moments", [])
        print(f"  Klip {cid}: durasi={dur:.1f}s, shots=[{shot_str}], total_momen={len(moments)}")

        counts = Counter(m.get("trigger", "unknown") for m in moments)
        for trig, count in sorted(counts.items()):
            print(f"    - {trig}: {count}")

    return 0


def step_fx_validate(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    edl_path = _need(wd, "edl.json", "build-edl")
    edl = jsonio.read_json(edl_path)
    if not isinstance(edl, dict):
        raise ValueError(f"{edl_path} harus dokumen JSON objek")

    plan_arg = getattr(args, "plan", None)
    if plan_arg:
        plan_path = Path(plan_arg)
        if not plan_path.is_absolute() and not plan_path.exists():
            plan_path = wd / plan_arg
    else:
        plan_path = wd / "fx_plan.json"

    plan = fxplan.load_plan(plan_path)

    cand_doc: dict[str, Any] | None = None
    cand_arg = getattr(args, "candidates", None)
    if cand_arg:
        cand_path = Path(cand_arg)
        if not cand_path.is_absolute() and not cand_path.exists():
            cand_path = wd / cand_arg
        if cand_path.is_file():
            cand_doc = jsonio.read_json(cand_path)
    else:
        default_cand = wd / "fx_candidates.json"
        if default_cand.is_file():
            try:
                cand_doc = jsonio.read_json(default_cand)
            except Exception:
                cand_doc = None

    fps = getattr(args, "fps", 30.0)
    report = fxplan.validate(edl, plan, candidates=cand_doc, fps=fps)

    rep_json_path = wd / "fx_plan.report.json"
    rep_md_path = wd / "fx_plan.report.md"

    jsonio.write_json(rep_json_path, report)
    rep_md_path.write_text(fxplan.report_markdown(report), encoding="utf-8")

    summary = report.get("summary", {})
    acc = summary.get("accepted", 0)
    warn = summary.get("accepted_with_warnings", 0)
    rej = summary.get("rejected", 0)

    print(f"✓ fx-validate  {rep_json_path.name}  ({acc} diterima, {warn} diterima+peringatan, {rej} ditolak)")
    for c in report.get("clips", []):
        cid = c.get("clip_id", "?")
        c_items = c.get("items", [])
        c_acc = sum(1 for it in c_items if it.get("status") == "accepted")
        c_warn = sum(1 for it in c_items if it.get("status") == "accepted_with_warnings")
        c_rej = sum(1 for it in c_items if it.get("status") == "rejected")
        print(f"  Klip {cid}: {c_acc} diterima, {c_warn} diterima+peringatan, {c_rej} ditolak")
        for it in c_items:
            it_id = it.get("id", "?")
            st = it.get("status", "?")
            if st == "rejected":
                for err in it.get("errors", []):
                    print(f"    - [DITOLAK] {it_id}: {err}")
            elif st == "accepted_with_warnings":
                for w in it.get("warnings", []):
                    print(f"    - [PERINGATAN] {it_id}: {w}")

    return 0


def step_fx_preview(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    rep_path = _need(wd, "fx_plan.report.json", "fx-validate")
    only = [x.strip() for x in args.only.split(",") if x.strip()] if getattr(args, "only", None) else None
    include_warnings = not getattr(args, "no_warnings", False)

    res = fxapply.preview(wd, rep_path, only=only, include_warnings=include_warnings)
    print("✓ fx-preview")
    for cid, clip_path in res.get("clips", {}).items():
        print(f"  Klip {cid}: {clip_path}")
    edl_preview_path = wd / "fx_preview" / "edl.fx_preview.json"
    print(f"  EDL pratinjau: {edl_preview_path}")
    print(f"  Lembar kontak: {res.get('contact_sheet')}")
    frames = res.get("frames", [])
    print(f"  Urutan frame ({len(frames)} frame):")
    for f in frames:
        print(f"    - {f['id']} ({f['type']}) @ {f['time']:.2f}s [{f.get('clip', '')}]")
    return 0


def step_fx_apply(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    rep_path = _need(wd, "fx_plan.report.json", "fx-validate")
    edl_path = _need(wd, "edl.json", "build-edl")
    only = [x.strip() for x in args.only.split(",") if x.strip()] if getattr(args, "only", None) else None
    include_warnings = not getattr(args, "no_warnings", False)
    approve = getattr(args, "approve", False)

    report = fxapply.load_report(rep_path)
    edl = jsonio.read_json(edl_path)
    fxapply.check_fresh(edl, report)

    selection = fxapply.select(report, only=only, include_warnings=include_warnings)
    total_selected = sum(len(v) for v in selection.values())
    if total_selected == 0:
        raise FxApplyError("Tidak ada item efek yang dipilih untuk diterapkan")

    if not approve:
        print("Rencana overlay yang AKAN diterapkan:")
        for cid, items in selection.items():
            print(f"  Klip {cid}:")
            clip_rep = next((c for c in report.get("clips", []) if str(c.get("clip_id")) == cid), None)
            rep_items_by_id = {str(it.get("id")): it for it in (clip_rep.get("items", []) if clip_rep else [])}
            for it in items:
                iid = it["id"]
                ov = it["overlay"]
                start = float(ov.get("start", 0.0))
                end = float(ov.get("end", 0.0))
                warns = rep_items_by_id.get(iid, {}).get("warnings", [])
                warn_str = f" (peringatan: {'; '.join(warns)})" if warns else ""
                print(f"    - [{iid}] {ov.get('type')} [{start:.2f}s - {end:.2f}s]{warn_str}")
        print("\nPERHATIAN: Penerapan efek ke edl.json memerlukan persetujuan pengguna.")
        print("Jalankan kembali dengan opsi `--approve` untuk menerapkan. edl.json tidak diubah.")
        return 2

    res = fxapply.apply(wd, report, only=only, include_warnings=include_warnings, approve=True)
    print(f"✓ fx-apply  {res.get('status')}")
    print(f"  Cadangan: {res.get('backup')}")
    print(f"  Ditambahkan ({len(res.get('added', []))}): {', '.join(res.get('added', [])) or '-'}")
    print(f"  Dilewati ({len(res.get('skipped', []))}): {', '.join(res.get('skipped', [])) or '-'}")
    return 0


def step_fx_undo(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    force = getattr(args, "force", False)
    res = fxapply.undo(wd, force=force)
    print("✓ fx-undo")
    print(f"  Dipulihkan dari: {res.get('restored_from')}")
    print(f"  Pesan: {res.get('message')}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipping-skill",
        description="Video panjang → short vertical 9:16 dengan skor explainable.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser, work_required: bool = True) -> None:
        if work_required:
            sp.add_argument("work", help="direktori kerja")
        sp.add_argument("--force", action="store_true", help="abaikan cache")

    sp = sub.add_parser("ingest", help="normalisasi video + ekstrak audio")
    sp.add_argument("src")
    sp.add_argument("--out", required=True)
    sp.add_argument("--fps", type=float, default=30.0)
    add_common(sp, work_required=False)
    sp.set_defaults(func=step_ingest)

    sp = sub.add_parser("transcribe", help="ASR word-level")
    add_common(sp)
    sp.add_argument("--engine", default=None, choices=["auto", "groq", "openai", "deepgram", "local"])
    sp.add_argument("--language", default=None)
    sp.add_argument("--chunk-seconds", type=float, default=600.0,
                    help="panjang chunk audio untuk API (default 600)")
    sp.set_defaults(func=step_transcribe)

    sp = sub.add_parser("segment", help="transkrip → atom")
    add_common(sp)
    sp.set_defaults(func=step_segment)

    sp = sub.add_parser("candidates", help="atom → kandidat klip")
    add_common(sp)
    sp.add_argument("--top-n", type=int, default=15)
    sp.add_argument("--min-dur", type=float, default=20.0)
    sp.add_argument("--max-dur", type=float, default=60.0)
    sp.set_defaults(func=step_candidates)

    sp = sub.add_parser("features", help="hitung ulang fitur kandidat")
    add_common(sp)
    sp.set_defaults(func=step_features)

    sp = sub.add_parser("score-prompt", help="cetak prompt penilaian untuk agent")
    add_common(sp)
    sp.set_defaults(func=step_score_prompt)

    sp = sub.add_parser("score-validate", help="validasi selection.json + hitung komposit")
    add_common(sp)
    sp.set_defaults(func=step_score_validate)

    sp = sub.add_parser("build-edl", help="bangun edl.json")
    add_common(sp)
    sp.add_argument("--top", type=int, default=5)
    sp.add_argument(
        "--motion",
        type=int,
        choices=[1, 2],
        default=1,
        help="1 = caption frasa (default), 2 = tambah words+caption_style kinetic",
    )
    sp.set_defaults(func=step_build_edl)

    sp = sub.add_parser("faces", help="lacak wajah & pembicara → jalur crop")
    add_common(sp)
    sp.add_argument(
        "--face-track",
        action="store_true",
        default=False,
        help="tulis juga reframe.face_track (kotak wajah per shot, px keluaran)",
    )
    sp.set_defaults(func=step_faces)

    sp = sub.add_parser(
        "layout", help="hitung caption/overlay sadar wajah + audit (tier-2)"
    )
    add_common(sp)
    sp.add_argument("--fps", type=float, default=30.0)
    sp.add_argument(
        "--no-write",
        action="store_true",
        default=False,
        help="hitung dan cetak audit saja; jangan tulis clips[].layout",
    )
    sp.set_defaults(func=step_layout)

    sp = sub.add_parser("render", help="render klip ke mp4")
    add_common(sp)
    sp.add_argument("--top", type=int, default=None)
    sp.add_argument("--crf", type=int, default=20)
    sp.add_argument("--preset", default="veryfast")
    sp.add_argument("--fontsdir", default=None)
    sp.add_argument(
        "--preview",
        action="store_true",
        default=False,
        help="render cepat 540x960 @15 fps ke <id>.preview.mp4 (tidak menimpa final)",
    )
    sp.set_defaults(func=step_render)

    sp = sub.add_parser("run", help="ingest → transkrip → atom → kandidat")
    sp.add_argument("src")
    sp.add_argument("--out", required=True)
    sp.add_argument("--fps", type=float, default=30.0)
    sp.add_argument("--engine", default=None)
    sp.add_argument("--language", default=None)
    sp.add_argument("--top-n", type=int, default=15)
    sp.add_argument("--chunk-seconds", type=float, default=600.0)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=step_run)

    sp = sub.add_parser("demo", help="jalankan pipeline pada transkrip sintetis")
    sp.add_argument("--out", default="work/demo")
    sp.add_argument("--top-n", type=int, default=10)
    sp.add_argument("--top", type=int, default=3)
    sp.set_defaults(func=step_demo)

    sp = sub.add_parser("fx-catalog", help="cetak katalog efek overlay untuk agen")
    sp.add_argument("--json", action="store_true", default=False, help="cetak dalam format JSON")
    sp.set_defaults(func=step_fx_catalog)

    sp = sub.add_parser("fx-candidates", help="ekstraksi momen kandidat efek video dari edl.json")
    add_common(sp)
    sp.add_argument("--clip", default=None, help="batasi ekstraksi ke klip tertentu (mis. clip_04)")
    sp.add_argument("--fps", type=float, default=30.0, help="frame rate timeline (default 30.0)")
    sp.set_defaults(func=step_fx_candidates)

    sp = sub.add_parser("fx-validate", help="pengesahan rencana efek video fx_plan.json terhadap edl.json")
    add_common(sp)
    sp.add_argument("--plan", default=None, help="jalur berkas fx_plan.json (bawaan <work>/fx_plan.json)")
    sp.add_argument("--candidates", default=None, help="jalur berkas fx_candidates.json")
    sp.add_argument("--fps", type=float, default=30.0, help="frame rate timeline (default 30.0)")
    sp.set_defaults(func=step_fx_validate)

    sp = sub.add_parser("fx-preview", help="render pratinjau efek video dan lembar kontak")
    add_common(sp)
    sp.add_argument("--only", default=None, help="batasi pratinjau ke item ID tertentu (dipisah koma, mis. p1,p3)")
    sp.add_argument("--no-warnings", action="store_true", default=False, help="abaikan item berstatus accepted_with_warnings")
    sp.set_defaults(func=step_fx_preview)

    sp = sub.add_parser("fx-apply", help="terapkan efek video yang disetujui ke edl.json")
    add_common(sp)
    sp.add_argument("--only", default=None, help="batasi penerapan ke item ID tertentu (dipisah koma)")
    sp.add_argument("--no-warnings", action="store_true", default=False, help="abaikan item berstatus accepted_with_warnings")
    sp.add_argument("--approve", action="store_true", default=False, help="setujui penerapan efek ke edl.json")
    sp.set_defaults(func=step_fx_apply)

    sp = sub.add_parser("fx-undo", help="pulihkan edl.json dari cadangan efek terakhir")
    add_common(sp)
    sp.set_defaults(func=step_fx_undo)

    return p


def main(argv: list[str] | None = None) -> int:
    jsonio.load_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ndibatalkan", file=sys.stderr)
        return 130
    except ApprovalRequired as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (FxApplyError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
