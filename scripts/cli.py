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
from . import features as feat_mod
from . import ingest, render, score, segment, transcribe
from .lib import audio as audio_mod
from .lib import jsonio


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
    tr = transcribe.run(wd, engine=args.engine, language=args.language, force=args.force)
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


def step_build_edl(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "scored.json", "score-validate")
    edl = edl_mod.build(wd, top_n=args.top)
    edl_mod.write(wd, edl)
    scored = jsonio.read_json(wd / "scored.json")
    report_path = edl_mod.write_report(wd, scored, edl)
    print(f"✓ EDL  {len(edl['clips'])} klip → {wd / 'edl.json'}")
    print(f"✓ laporan → {report_path}")
    for clip in edl["clips"]:
        seg = clip["segments"][0]
        print(f"    {clip['id']}  {seg['src_start']:7.1f}s → {seg['src_end']:7.1f}s  "
              f"{len(clip['captions'])} caption  skor {clip['score']['final']}")
    return 0


def step_render(args: argparse.Namespace) -> int:
    wd = _wd(args.work)
    _need(wd, "edl.json", "build-edl")
    outs = render.render_all(
        wd, top=args.top, crf=args.crf, preset=args.preset, fontsdir=args.fontsdir
    )
    for p in outs:
        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"✓ render  {p}  ({size_mb:.1f} MB)")
    return 0


def step_run(args: argparse.Namespace) -> int:
    wd = _wd(args.out)
    ingest.run(args.src, wd, fps=args.fps, force=args.force)
    transcribe.run(wd, engine=args.engine, language=args.language, force=args.force)
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
    sp.set_defaults(func=step_build_edl)

    sp = sub.add_parser("render", help="render klip ke mp4")
    add_common(sp)
    sp.add_argument("--top", type=int, default=None)
    sp.add_argument("--crf", type=int, default=20)
    sp.add_argument("--preset", default="veryfast")
    sp.add_argument("--fontsdir", default=None)
    sp.set_defaults(func=step_render)

    sp = sub.add_parser("run", help="ingest → transkrip → atom → kandidat")
    sp.add_argument("src")
    sp.add_argument("--out", required=True)
    sp.add_argument("--fps", type=float, default=30.0)
    sp.add_argument("--engine", default=None)
    sp.add_argument("--language", default=None)
    sp.add_argument("--top-n", type=int, default=15)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=step_run)

    sp = sub.add_parser("demo", help="jalankan pipeline pada transkrip sintetis")
    sp.add_argument("--out", default="work/demo")
    sp.add_argument("--top-n", type=int, default=10)
    sp.add_argument("--top", type=int, default=3)
    sp.set_defaults(func=step_demo)

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
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
