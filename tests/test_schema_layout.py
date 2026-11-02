"""Drift skema `layout` (Langkah 4b-1) — aditif, tanpa `jsonschema`.

Keluaran `layout.compute_layout` (skenario sintetis nyata, bukan dokumen
tangan) harus lolos penjelajah skema yang sudah dipakai
`tests/test_schema_drift.py`. Penjelajah itu tidak mengenal `anyOf`, jadi
`rect` overlay yang boleh `null` diperiksa dengan memanggil `_walk` pada
`$defs/rect` secara eksplisit (masih penjelajah yang sama, tanpa dependensi).
"""

from __future__ import annotations

import copy
import unittest
from typing import Any

from tests.test_schema_drift import (
    _walk,
    load_schema,
    missing_required,
    undeclared_keys,
)

from scripts import layout

VERSION = "0.1.0"


def _clip_doc(layout_out: dict[str, Any]) -> dict[str, Any]:
    """Dokumen minimal yang memenuhi `required` clip, dengan layout asli."""
    return {
        "version": VERSION,
        "source": {
            "path": "synthetic://x", "duration": 10.0, "fps": 30.0,
            "width": 1920, "height": 1080,
        },
        "output": {"width": 1080, "height": 1920, "fps": 30.0},
        "clips": [{
            "id": "clip_00",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [{"start": 0.0, "end": 1.0, "text": "halo"}],
            "reframe": {"mode": "center"},
            "score": {
                "axes": {}, "base": 1.0, "penalty": 0.0,
                "final": 50.0, "percentile": 50.0,
            },
            "layout": layout_out,
        }],
    }


class SchemaLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema()
        cls.layout_schema = cls.schema["$defs"]["clip"]["properties"]["layout"]

    def test_version_unchanged(self) -> None:
        self.assertEqual(self.schema["properties"]["version"]["const"], VERSION)
        self.assertEqual(self.layout_schema["properties"]["version"]["minimum"], 1)

    def test_caption_keeps_old_keys_and_adds_scale_reason(self) -> None:
        props = self.layout_schema["properties"]["caption"]["items"]["properties"]
        for key in ("t", "an", "y", "x", "size"):
            self.assertIn(key, props, f"kunci lama {key!r} tidak boleh hilang")
        self.assertIn("scale", props)
        self.assertIn("reason", props)
        self.assertEqual(props["scale"]["type"], "number")
        self.assertEqual(props["scale"]["exclusiveMinimum"], 0)
        self.assertEqual(props["reason"]["type"], "string")
        self.assertFalse(
            self.layout_schema["properties"]["caption"]["items"]["additionalProperties"]
        )

    def test_overlays_declared_additively(self) -> None:
        overlays = self.layout_schema["properties"]["overlays"]
        self.assertEqual(overlays["type"], "array")
        item = overlays["items"]
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(sorted(item["required"]), ["index", "reason", "rect"])
        self.assertEqual(item["properties"]["index"]["type"], "integer")
        self.assertEqual(item["properties"]["index"]["minimum"], 0)
        self.assertEqual(item["properties"]["reason"]["type"], "string")
        self.assertIn("anyOf", item["properties"]["rect"])

    def test_real_compute_layout_output_matches_schema(self) -> None:
        face_track = [
            {"t": 0.0, "faces": [{"x": 120.0, "y": 900.0, "w": 400.0, "h": 420.0}]},
            {"t": 3.0, "faces": []},
        ]
        punch = [{"t": 0.0, "scale": 1.0}, {"t": 1.0, "scale": 1.2}]
        blocks = [
            {"start": 0.0, "end": 1.5, "w": 980.0, "h": 193.2},
            {"start": 1.6, "end": 2.9, "w": 700.0, "h": 193.2},
            {"start": 3.1, "end": 4.5, "w": 820.0, "h": 96.6},
        ]
        overlays = [
            {"type": "ui_panel", "start": 0.5, "end": 2.5,
             "size": (400.0, 200.0)},
            {"type": "pullback", "start": 4.0, "end": 5.0,
             "size": (600.0, 400.0)},
            {"type": "checklist", "start": 5.5, "end": 6.0,
             "size": (300.0, 240.0)},
        ]
        out = layout.compute_layout(
            face_track, punch, 6.0, caption_blocks=blocks, overlays=overlays
        )
        doc = _clip_doc(out)
        bad = undeclared_keys(self.schema, doc)
        self.assertEqual(bad, [], msg=f"kunci tak dideklarasikan: {bad}")
        self.assertEqual(missing_required(self.schema, doc), [])

        # Bukti keluaran benar-benar memakai kunci baru (bukan lolos karena kosong).
        self.assertTrue(out["caption"])
        self.assertTrue(all("scale" in e and "reason" in e for e in out["caption"]))
        self.assertTrue(out["overlays"])
        self.assertTrue(any(o["rect"] is not None for o in out["overlays"]))
        self.assertTrue(any(o["rect"] is None for o in out["overlays"]))

        rect_schema = self.schema["$defs"]["rect"]
        for i, item in enumerate(out["overlays"]):
            rect = item["rect"]
            if rect is None:
                continue
            self.assertEqual(
                _walk(rect_schema, self.schema, rect, f"overlays[{i}].rect"), []
            )
            self.assertEqual(
                missing_required(rect_schema, rect, f"overlays[{i}].rect"), []
            )

    def test_drift_checker_would_catch_missing_scale_reason(self) -> None:
        """Mutan yang menghapus scale/reason dari skema harus tertangkap."""
        out = layout.compute_layout(
            [{"t": 0.0, "faces": []}],
            [],
            2.0,
            caption_blocks=[{"start": 0.0, "end": 1.0, "w": 700.0, "h": 193.2}],
            overlays=[],
        )
        doc = _clip_doc(out)
        mutated = copy.deepcopy(self.schema)
        props = mutated["$defs"]["clip"]["properties"]["layout"]["properties"]["caption"]["items"]["properties"]
        props.pop("scale")
        props.pop("reason")
        bad = undeclared_keys(mutated, doc)
        self.assertTrue(any(p.endswith(".scale") for p in bad), msg=bad)
        self.assertTrue(any(p.endswith(".reason") for p in bad), msg=bad)


if __name__ == "__main__":
    unittest.main()
