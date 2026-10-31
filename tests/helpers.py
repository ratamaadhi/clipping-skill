"""Helper bersama untuk tes: bangun work dir sintetis lengkap."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import candidates as cand_mod  # noqa: E402
from scripts import demo as demo_mod  # noqa: E402
from scripts import edl as edl_mod  # noqa: E402
from scripts import features as feat_mod  # noqa: E402
from scripts import score as score_mod  # noqa: E402
from scripts import segment  # noqa: E402
from scripts.lib import jsonio  # noqa: E402


def make_work(tmp: Path, top_n: int = 10, top: int = 3) -> Path:
    wd = tmp / "work"
    wd.mkdir(parents=True, exist_ok=True)

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

    cands = cand_mod.generate(atoms, top_n=top_n)
    feat_mod.attach(cands, atoms)
    jsonio.write_json(wd / "candidates.json", cands)

    jsonio.write_json(wd / "selection.json", demo_mod.synthetic_selection(cands))
    payload = score_mod.score(wd)
    edl = edl_mod.build(wd, top_n=top)
    edl_mod.write(wd, edl)
    edl_mod.write_report(wd, payload, edl)
    return wd


class TempWork:
    """Context manager: temp dir berisi work dir lengkap."""

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        return make_work(Path(self._tmp.name))

    def __exit__(self, *exc: object) -> None:
        self._tmp.cleanup()
