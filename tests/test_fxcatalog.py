"""Tes konsistensi dan validasi scripts/fxcatalog.py."""

from __future__ import annotations

import unittest
from typing import Any

from scripts import fxcatalog
from scripts import presets
from scripts import presets_phone
from scripts import pullback


class FxCatalogNamesAndStructureTest(unittest.TestCase):
    """Pengujian nama efek, struktur entri, dan API modul."""

    def test_names_match_presets_plus_pullback(self) -> None:
        expected = tuple(presets.PRESET_TYPES) + ("pullback",)
        self.assertEqual(fxcatalog.names(), expected)

    def test_all_names_present_in_effects(self) -> None:
        self.assertEqual(set(fxcatalog.names()), set(fxcatalog.EFFECTS.keys()))

    def test_get_valid_and_invalid(self) -> None:
        entry = fxcatalog.get("zoom_through_text")
        self.assertIsInstance(entry, dict)
        self.assertEqual(entry["budget_class"], "accent")

        with self.assertRaises(KeyError):
            fxcatalog.get("efek_palsu_tidak_ada")

    def test_entry_required_keys(self) -> None:
        required_keys = {
            "summary",
            "use_when",
            "avoid_when",
            "budget_class",
            "needs_free_area",
            "default_size",
            "window",
            "props",
            "example",
            "conflicts",
        }
        for name in fxcatalog.names():
            entry = fxcatalog.get(name)
            missing = required_keys - set(entry.keys())
            self.assertFalse(missing, f"Efek {name} tidak memuat kunci: {missing}")

            self.assertIsInstance(entry["summary"], str)
            self.assertTrue(entry["summary"])

            self.assertIsInstance(entry["use_when"], list)
            self.assertTrue(entry["use_when"])

            self.assertIsInstance(entry["avoid_when"], list)
            self.assertTrue(entry["avoid_when"])

            self.assertIn(entry["budget_class"], ("accent", "card", "transform"))
            self.assertIsInstance(entry["needs_free_area"], bool)

            if entry["needs_free_area"]:
                self.assertIsInstance(entry["default_size"], tuple)
                self.assertEqual(len(entry["default_size"]), 2)
                self.assertGreater(entry["default_size"][0], 0.0)
                self.assertGreater(entry["default_size"][1], 0.0)
            else:
                self.assertIsNone(entry["default_size"])

            w = entry["window"]
            self.assertIn("min", w)
            self.assertIn("typical", w)
            self.assertIn("max", w)
            self.assertLessEqual(w["min"], w["typical"])
            self.assertLessEqual(w["typical"], w["max"])


class FxCatalogConsistencyTest(unittest.TestCase):
    """Pengujian batas props terikat konstanta modul preset (bukan salinan)."""

    def test_zoom_through_text_props_bounds(self) -> None:
        props = fxcatalog.get("zoom_through_text")["props"]
        self.assertEqual(props["text"]["min"], presets.MIN_TEXT)
        self.assertEqual(props["text"]["max"], presets.MAX_TEXT)
        self.assertEqual(props["size_em"]["min"], presets.MIN_SIZE_EM)
        self.assertEqual(props["size_em"]["max"], presets.MAX_SIZE_EM)
        self.assertEqual(props["duration"]["min"], presets.MIN_DURATION)
        self.assertEqual(props["duration"]["max"], presets.MAX_DURATION)
        self.assertEqual(props["colour"]["default"], presets.DEFAULT_COLOUR)

    def test_checklist_props_bounds(self) -> None:
        props = fxcatalog.get("checklist")["props"]
        self.assertEqual(props["title"]["max"], presets.CHECK_MAX_TITLE)
        self.assertEqual(props["items"]["min"], presets.CHECK_MIN_ITEMS)
        self.assertEqual(props["items"]["max"], presets.CHECK_MAX_ITEMS)

    def test_chart_grow_props_bounds(self) -> None:
        props = fxcatalog.get("chart_grow")["props"]
        self.assertEqual(props["title"]["max"], presets.CHART_MAX_TITLE)
        self.assertEqual(props["labels"]["min"], presets.CHART_MIN_LABELS)
        self.assertEqual(props["labels"]["max"], presets.CHART_MAX_LABELS)
        self.assertEqual(props["tag"]["max"], presets.CHART_MAX_TAG_CHARS)
        self.assertEqual(props["grow"]["min"], presets.CHART_GROW_MIN)
        self.assertEqual(props["grow"]["max"], presets.CHART_GROW_MAX)

    def test_ui_panel_props_bounds(self) -> None:
        props = fxcatalog.get("ui_panel")["props"]
        self.assertEqual(props["title"]["min"], presets.UI_MIN_TITLE_CHARS)
        self.assertEqual(props["title"]["max"], presets.UI_MAX_TITLE_CHARS)
        self.assertEqual(props["tag"]["min"], presets.UI_MIN_TAG_CHARS)
        self.assertEqual(props["tag"]["max"], presets.UI_MAX_TAG_CHARS)
        self.assertEqual(props["thumbs"]["min"], presets.UI_MIN_THUMBS)
        self.assertEqual(props["thumbs"]["max"], presets.UI_MAX_THUMBS)
        self.assertEqual(props["input"]["max"], presets.UI_MAX_INPUT_CHARS)

    def test_phone_frame_props_bounds(self) -> None:
        props = fxcatalog.get("phone_frame")["props"]
        self.assertEqual(props["title"]["min"], presets_phone.PHONE_MIN_TITLE_CHARS)
        self.assertEqual(props["title"]["max"], presets_phone.PHONE_MAX_TITLE_CHARS)
        self.assertEqual(props["lines"]["min"], presets_phone.PHONE_MIN_LINES)
        self.assertEqual(props["lines"]["max"], presets_phone.PHONE_MAX_LINES)

    def test_pullback_props_bounds(self) -> None:
        props = fxcatalog.get("pullback")["props"]
        self.assertEqual(props["shrink"]["min"], pullback.MIN_SHRINK)
        self.assertEqual(props["shrink"]["max"], pullback.MAX_SHRINK)
        self.assertEqual(props["grow"]["min"], pullback.MIN_GROW)
        self.assertEqual(props["grow"]["max"], pullback.MAX_GROW)
        self.assertEqual(props["count"]["min"], pullback.MIN_COUNT)
        self.assertEqual(props["count"]["max"], pullback.MAX_COUNT)


class FxCatalogExampleValidationTest(unittest.TestCase):
    """Pengujian bahwa setiap `example` lolos pengesah preset nyata."""

    def test_examples_pass_real_preset_validators(self) -> None:
        # Jendela sintetis dipilih start=1.0, end=7.0 (durasi 6.0s) pada klip 20.0s.
        # Waktu ini dipilih agar fase masuk (0.35s), jeda butir checklist/telepon,
        # dan fase keluar (0.2s) memiliki margin yang cukup luas dan aman.
        clip_duration = 20.0
        fps = 30.0

        for name in fxcatalog.names():
            entry = fxcatalog.get(name)
            example_props = entry["example"]

            if name == "pullback":
                clip = {
                    "segments": [{"src_start": 0.0, "src_end": clip_duration}],
                    "overlays": [
                        {
                            "type": "pullback",
                            "start": 2.5,
                            "end": 8.0,
                            "props": example_props,
                        }
                    ],
                }
                plan, warnings = pullback.build(clip, fps=fps)
                self.assertIsNotNone(
                    plan,
                    f"Contoh pullback gagal divalidasi oleh pullback.build: {warnings}",
                )
            else:
                clip: dict[str, Any] = {
                    "id": "clip_test",
                    "segments": [{"src_start": 0.0, "src_end": clip_duration}],
                    "overlays": [
                        {
                            "type": name,
                            "start": 1.0,
                            "end": 7.0,
                            "props": example_props,
                        }
                    ],
                }
                # build_fx_ass memvalidasi props dan menghasilkan dokumen ASS
                ass_doc, warnings = presets.build_fx_ass(clip, fps=fps)
                self.assertIsNotNone(
                    ass_doc,
                    f"Contoh {name} menghasilkan None: {warnings}",
                )
                self.assertTrue(
                    len(ass_doc) > 0,
                    f"Contoh {name} menghasilkan ASS kosong: {warnings}",
                )


class FxCatalogMarkdownTest(unittest.TestCase):
    """Pengujian keluaran markdown katalog."""

    def test_catalog_markdown_contains_all_names_and_budget(self) -> None:
        md = fxcatalog.catalog_markdown()
        self.assertIn("Katalog Efek Video (Tier-2)", md)

        # Semua nama efek muncul
        for name in fxcatalog.names():
            self.assertIn(f"`{name}`", md)

        # Semua konstanta anggaran muncul
        self.assertIn(str(fxcatalog.MAX_OVERLAYS_PER_CLIP), md)
        self.assertIn(f"{fxcatalog.MIN_GAP_SECONDS:.1f}", md)
        self.assertIn(f"{fxcatalog.CARD_MIN_GAP_SECONDS:.1f}", md)
        self.assertIn(str(fxcatalog.MAX_ACCENT_PER_CLIP), md)
        self.assertIn(str(fxcatalog.MAX_TRANSFORM_PER_CLIP), md)
        self.assertIn(f"{fxcatalog.HOOK_WINDOW_SECONDS:.1f}", md)
        self.assertIn(f"{fxcatalog.MIN_STABLE_SECONDS_PULLBACK:.1f}", md)


if __name__ == "__main__":
    unittest.main()
