"""Drift schema: setiap kunci pada EDL hasil build harus dideklarasikan.

Tanpa `jsonschema` (D-004: stdlib saja). Penjelajah ini cukup untuk bentuk
schema repo ini: `properties`, `items`, `additionalProperties`, `$ref` lokal,
dan `required`.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import ROOT, make_work

from scripts import edl as edl_mod
from scripts.lib import jsonio

SCHEMA_PATH = ROOT / "schema" / "edl.schema.json"


def load_schema() -> dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Ikuti `$ref` lokal (#/$defs/...)."""
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema:
        ref = str(schema["$ref"])
        if not ref.startswith("#/"):
            raise ValueError(f"$ref non-lokal tidak didukung: {ref}")
        node: Any = root
        for part in ref[2:].split("/"):
            node = node[part]
        schema = node
        seen += 1
        if seen > 50:
            raise ValueError("$ref melingkar")
    return schema


def undeclared_keys(schema: dict[str, Any], doc: Any, path: str = "") -> list[str]:
    """Jalur kunci pada `doc` yang tidak dideklarasikan padahal AP bukan true.

    Kunci yang dilanggar dilaporkan sebagai `path.key`; item array memakai
    `path[i]`.
    """
    root = schema
    return _walk(schema, root, doc, path)


def _walk(schema: Any, root: dict[str, Any], doc: Any, path: str) -> list[str]:
    if not isinstance(schema, dict):
        return []
    schema = _resolve(schema, root)

    if isinstance(doc, dict):
        props = schema.get("properties") or {}
        ap = schema.get("additionalProperties", True)
        bad: list[str] = []
        for key, value in doc.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in props:
                bad.extend(_walk(props[key], root, value, child_path))
            elif ap is True:
                continue
            elif isinstance(ap, dict):
                # kunci bebas tapi bentuknya dibatasi schema
                bad.extend(_walk(ap, root, value, child_path))
            else:
                bad.append(child_path)
        return bad

    if isinstance(doc, list):
        items = schema.get("items")
        if isinstance(items, list):
            bad = []
            for i, value in enumerate(doc):
                sub = items[i] if i < len(items) else None
                if sub is None:
                    continue
                bad.extend(_walk(sub, root, value, f"{path}[{i}]"))
            return bad
        if isinstance(items, dict):
            bad = []
            for i, value in enumerate(doc):
                bad.extend(_walk(items, root, value, f"{path}[{i}]"))
            return bad
        return []

    return []


def missing_required(schema: dict[str, Any], doc: Any, path: str = "") -> list[str]:
    """Jalur field wajib yang tidak ada. Dipakai sebagai jaring kedua."""
    return _missing(schema, schema, doc, path)


def _missing(schema: Any, root: dict[str, Any], doc: Any, path: str) -> list[str]:
    if not isinstance(schema, dict):
        return []
    schema = _resolve(schema, root)
    out: list[str] = []

    if isinstance(doc, dict):
        for key in schema.get("required") or []:
            if key not in doc:
                out.append(f"{path}.{key}" if path else str(key))
        props = schema.get("properties") or {}
        ap = schema.get("additionalProperties", True)
        for key, value in doc.items():
            if key in props:
                out.extend(_missing(props[key], root, value, f"{path}.{key}" if path else key))
            elif isinstance(ap, dict):
                out.extend(_missing(ap, root, value, f"{path}.{key}" if path else key))
        return out

    if isinstance(doc, list) and isinstance(schema.get("items"), dict):
        for i, value in enumerate(doc):
            out.extend(_missing(schema["items"], root, value, f"{path}[{i}]"))
        return out

    return []


def _faces_style_edl(base: dict[str, Any]) -> dict[str, Any]:
    """Tiru keluaran `scripts.faces.analyze_edl` tanpa cv2/video.

    faces.py menulis `reframe.mode="track"`, `reframe.bias_track`
    ([[t_output, bias], ...]) dan diagnostik `reframe.face_top`.
    """
    doc = copy.deepcopy(base)
    clip = doc["clips"][0]
    clip["reframe"] = {
        "mode": "track",
        "bias_x": 0.0,
        "bias_y": 0.0,
        "face_top": 0.3125,
        "bias_track": [[0.0, -0.2], [1.5, 0.05], [3.0, 0.4]],
    }
    return doc


def _tier2_style_edl(base: dict[str, Any]) -> dict[str, Any]:
    """Bentuk tier-2 penuh menurut tabel bagian 4 rencana.

    `make_work` tidak menghasilkan overlay/transitions/layout, jadi kunci itu
    diisi sintetis supaya tes drift benar-benar menjelajahinya.
    """
    doc = copy.deepcopy(base)
    clip = doc["clips"][0]
    clip["caption_style"] = "kinetic"
    clip["captions"][0]["words"] = [
        {"w": "Kalau", "start": 0.0, "end": 0.385},
        {"w": "pakai", "start": 0.445, "end": 0.83},
    ]
    clip["reframe"] = {
        "mode": "track",
        "bias_x": 0.0,
        "bias_y": 0.0,
        "bias_track": [[0.0, -0.2], [1.5, 0.1]],
        "face_track": [
            {"t": 0.0, "faces": [{"x": 212, "y": 310, "w": 240, "h": 300}]},
            {"t": 1.5, "faces": []},
        ],
    }
    clip["transitions"] = [
        {"seg": 1, "kind": "flash", "dur": 0.10},
        {"seg": 2, "kind": "whip"},
    ]
    clip["layout"] = {
        "version": 1,
        "caption": [{"t": 0.0, "an": 2, "y": 1400}, {"t": 3.0, "an": 8, "y": 330}],
    }
    clip["overlays"] = [
        {
            "type": "callout",
            "renderer": "remotion",
            "start": 2.0,
            "end": 5.0,
            "slot": "auto",
            "rect": {"x": 60, "y": 260, "w": 960, "h": 300},
            "props": {"text": "3 dari 5", "variant": "stat"},
        },
        {"type": "vs", "start": 0.5, "end": 3.5, "left": "Codex", "right": "Claude"},
    ]
    return doc


class SchemaDriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.wd = make_work(Path(cls._tmp.name), top_n=10, top=3)
        cls.tier1 = jsonio.read_json(cls.wd / "edl.json")
        cls.schema = load_schema()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_schema_is_object_with_clips(self) -> None:
        self.assertEqual(self.schema["type"], "object")
        self.assertEqual(self.schema["properties"]["version"]["const"], "0.1.0")

    def _tier2(self) -> dict[str, Any]:
        return edl_mod.build(self.wd, top_n=3, motion_tier=2)

    def test_tier1_edl_has_no_undeclared_keys(self) -> None:
        bad = undeclared_keys(self.schema, self.tier1)
        self.assertEqual(bad, [], msg=f"kunci tak dideklarasikan: {bad}")

    def test_tier2_edl_has_no_undeclared_keys(self) -> None:
        bad = undeclared_keys(self.schema, self._tier2())
        self.assertEqual(bad, [], msg=f"kunci tak dideklarasikan: {bad}")

    def test_tier2_synthetic_full_shape_has_no_undeclared_keys(self) -> None:
        doc = _tier2_style_edl(self.tier1)
        bad = undeclared_keys(self.schema, doc)
        self.assertEqual(bad, [], msg=f"kunci tak dideklarasikan: {bad}")
        self.assertEqual(missing_required(self.schema, doc), [])

    def test_faces_style_reframe_has_no_undeclared_keys(self) -> None:
        doc = _faces_style_edl(self.tier1)
        bad = undeclared_keys(self.schema, doc)
        self.assertEqual(bad, [], msg=f"kunci tak dideklarasikan: {bad}")

    def test_required_keys_present(self) -> None:
        self.assertEqual(missing_required(self.schema, self.tier1), [])
        self.assertEqual(missing_required(self.schema, self._tier2()), [])

    def test_checker_catches_unknown_key(self) -> None:
        """Pemeriksa tidak boleh diam-diam lolos."""
        doc = copy.deepcopy(self.tier1)
        doc["clips"][0]["zzz"] = {"apa": "saja"}
        bad = undeclared_keys(self.schema, doc)
        self.assertIn("clips[0].zzz", bad)

    def test_checker_catches_unknown_root_key(self) -> None:
        doc = copy.deepcopy(self.tier1)
        doc["zzz"] = 1
        self.assertIn("zzz", undeclared_keys(self.schema, doc))

    def test_checker_catches_unknown_caption_key(self) -> None:
        doc = copy.deepcopy(self.tier1)
        doc["clips"][0]["captions"][0]["zzz"] = 1
        bad = undeclared_keys(self.schema, doc)
        self.assertTrue(any(p.endswith(".zzz") and "captions[0]" in p for p in bad), msg=bad)

    def test_checker_accepts_free_form_additional_properties(self) -> None:
        """score.axes memakai additionalProperties: {type:number} — bukan drift."""
        base = undeclared_keys(self.schema, self.tier1)
        doc = copy.deepcopy(self.tier1)
        doc["clips"][0]["score"]["axes"]["axis_baru"] = 1.0
        self.assertEqual(undeclared_keys(self.schema, doc), base)


if __name__ == "__main__":
    unittest.main()
