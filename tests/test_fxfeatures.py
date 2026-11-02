"""Tes ekstraktor fitur dan momen kandidat efek video (scripts/fxfeatures.py)."""

from __future__ import annotations

import copy
import unittest
from typing import Any

from scripts import fxcatalog
from scripts import fxfeatures
from tests.test_schema_drift import missing_required, undeclared_keys
from tests.test_schema_fx_candidates import load_fx_schema


class FxFeaturesTriggerLexiconTest(unittest.TestCase):
    """Pengujian positif dan negatif untuk setiap pemicu isi (Bahasa Indonesia)."""

    def _make_clip(self, captions: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        clip = {
            "id": "clip_test",
            "segments": [{"src_start": 0.0, "src_end": 20.0}],
            "captions": captions,
        }
        clip.update(kwargs)
        return clip

    def test_trigger_number_positive(self) -> None:
        # Kasus positif: 5%, 25 persen, 100 orang, 5 juta, 3 kali lipat
        sentences = [
            ("Keuntungan kita naik 5%", "persen"),
            ("Keuntungan kita naik 25 persen tahun ini", "persen"),
            ("Ada 100 orang yang hadir di acara", "digit>=2"),
            ("Omset mereka tembus 5 juta rupiah", "skala"),
            ("Kecepatannya meningkat 3 kali lipat", "skala"),
        ]
        for s, expected_evidence in sentences:
            clip = self._make_clip([{"start": 3.0, "end": 5.0, "text": s}])
            res = fxfeatures.extract_clip(clip)
            triggers = [m["trigger"] for m in res["moments"]]
            self.assertIn("number", triggers, f"Gagal mendeteksi 'number' pada: '{s}'")
            moment = next(m for m in res["moments"] if m["trigger"] == "number")
            self.assertEqual(moment["evidence"]["matched"], expected_evidence)

    def test_trigger_number_negative(self) -> None:
        # Kasus negatif: idiom angka, angka 1 digit tanpa satuan, tahun saja
        negatives = [
            "Dia adalah satu-satunya harapan kita",
            "Dua-duanya sama sekali tidak bersalah",
            "Ada seribu satu kisah di kota ini",
            "Hanya ada 5 orang yang datang",
            "Semua ini dimulai sejak tahun 2017",
        ]
        for s in negatives:
            clip = self._make_clip([{"start": 3.0, "end": 5.0, "text": s}])
            res = fxfeatures.extract_clip(clip)
            triggers = [m["trigger"] for m in res["moments"]]
            self.assertNotIn(
                "number",
                triggers,
                f"Pemicu 'number' tidak boleh mendeteksi kalimat negatif: '{s}'",
            )

    def test_trigger_trend_positive_and_negative(self) -> None:
        # Positif: perubahan dari-ke numerik
        pos_clip = self._make_clip(
            [{"start": 3.0, "end": 6.0, "text": "Penjualan melonjak dari 10% ke 50%"}]
        )
        res = fxfeatures.extract_clip(pos_clip)
        trend_moments = [m for m in res["moments"] if m["trigger"] == "trend"]
        self.assertTrue(trend_moments)
        ev = trend_moments[0]["evidence"]
        self.assertEqual(ev["kind"], "change")
        self.assertEqual(ev["from"], "10%")
        self.assertEqual(ev["to"], "50%")

        # Positif: deret >= 3 tahun berurutan
        years_clip = self._make_clip(
            [{"start": 3.0, "end": 7.0, "text": "Data kami dari 2021, 2022, hingga 2023"}]
        )
        res_years = fxfeatures.extract_clip(years_clip)
        trend_years = [m for m in res_years["moments"] if m["trigger"] == "trend"]
        self.assertTrue(trend_years)
        self.assertEqual(trend_years[0]["evidence"]["kind"], "years")

        # Negatif: dari-ke tanpa angka atau kata kerja tren
        neg_clip = self._make_clip(
            [{"start": 3.0, "end": 6.0, "text": "Saya berjalan dari kantor ke rumah"}]
        )
        res_neg = fxfeatures.extract_clip(neg_clip)
        trend_neg = [m for m in res_neg["moments"] if m["trigger"] == "trend"]
        self.assertEqual(trend_neg, [])

        # Negatif: kata kerja tren tanpa pola 'dari-ke' numerik
        neg_clip_2 = self._make_clip(
            [{"start": 3.0, "end": 6.0, "text": "Penjualan kita naik pesat bulan ini"}]
        )
        res_neg_2 = fxfeatures.extract_clip(neg_clip_2)
        trend_neg_2 = [m for m in res_neg_2["moments"] if m["trigger"] == "trend"]
        self.assertEqual(trend_neg_2, [], "Tren tanpa pola 'dari-ke' tidak boleh memicu pemicu trend")

    def test_trigger_list_positive_and_negative(self) -> None:
        # Positif: penanda urutan pertama ... kedua ...
        pos_clip = self._make_clip(
            [
                {
                    "start": 3.0,
                    "end": 6.0,
                    "text": "Pertama siapkan berkas lalu kedua lakukan verifikasi",
                    "words": [
                        {"w": "Pertama", "start": 3.0, "end": 3.5},
                        {"w": "siapkan", "start": 3.5, "end": 4.0},
                        {"w": "berkas", "start": 4.0, "end": 4.5},
                        {"w": "lalu", "start": 4.5, "end": 5.0},
                        {"w": "kedua", "start": 5.0, "end": 5.5},
                        {"w": "lakukan", "start": 5.5, "end": 5.8},
                        {"w": "verifikasi", "start": 5.8, "end": 6.0},
                    ],
                }
            ]
        )
        res = fxfeatures.extract_clip(pos_clip)
        list_moments = [m for m in res["moments"] if m["trigger"] == "list"]
        self.assertTrue(list_moments)
        items = list_moments[0]["evidence"]["items"]
        self.assertEqual(len(items), 2)
        # Verifikasi waktu done_at berasal dari waktu kata penanda!
        self.assertEqual(items[0]["done_at"], 3.0)
        self.assertEqual(items[1]["done_at"], 5.0)

        # Negatif: hanya 'pertama kali' (idiom, bukan daftar)
        neg_clip_1 = self._make_clip(
            [
                {
                    "start": 3.0,
                    "end": 5.0,
                    "text": "Ini pertama kali saya melihat kejadian seperti ini",
                    "words": [
                        {"w": "Ini", "start": 3.0, "end": 3.3},
                        {"w": "pertama", "start": 3.3, "end": 3.7},
                        {"w": "kali", "start": 3.7, "end": 4.0},
                    ],
                }
            ]
        )
        res_neg_1 = fxfeatures.extract_clip(neg_clip_1)
        self.assertEqual([m for m in res_neg_1["moments"] if m["trigger"] == "list"], [])

        # Negatif: hanya 1 penanda ('pertama') tanpa penanda kedua
        neg_clip_2 = self._make_clip(
            [
                {
                    "start": 3.0,
                    "end": 5.0,
                    "text": "Pertama kita harus tenang dan jangan panik",
                    "words": [
                        {"w": "Pertama", "start": 3.0, "end": 3.5},
                        {"w": "kita", "start": 3.5, "end": 3.8},
                    ],
                }
            ]
        )
        res_neg_2 = fxfeatures.extract_clip(neg_clip_2)
        self.assertEqual([m for m in res_neg_2["moments"] if m["trigger"] == "list"], [])

    def test_trigger_question_positive_and_negative(self) -> None:
        # Positif: penanda hook 'tahu nggak'
        pos_clip_1 = self._make_clip(
            [{"start": 5.0, "end": 7.0, "text": "Tahu nggak kenapa polisi jujur itu langka?"}]
        )
        res_1 = fxfeatures.extract_clip(pos_clip_1)
        q_moments = [m for m in res_1["moments"] if m["trigger"] == "question"]
        self.assertTrue(q_moments)

        # Positif: kalimat tanya di hook window
        pos_clip_2 = self._make_clip(
            [{"start": 0.5, "end": 1.8, "text": "Apa yang sebenarnya terjadi?"}]
        )
        res_2 = fxfeatures.extract_clip(pos_clip_2)
        self.assertTrue([m for m in res_2["moments"] if m["trigger"] == "question"])

        # Negatif: pernyataan biasa tanpa penanda di luar hook
        neg_clip = self._make_clip(
            [{"start": 5.0, "end": 7.0, "text": "Saya rasa semua orang sudah paham hal ini"}]
        )
        res_neg = fxfeatures.extract_clip(neg_clip)
        self.assertEqual([m for m in res_neg["moments"] if m["trigger"] == "question"], [])

    def test_trigger_product_positive_and_negative(self) -> None:
        # Positif: leksikon aplikasi
        clip_lex = self._make_clip(
            [{"start": 3.0, "end": 5.0, "text": "Langsung buka Instagram sekarang"}]
        )
        res_lex = fxfeatures.extract_clip(clip_lex)
        prod_moments = [m for m in res_lex["moments"] if m["trigger"] == "product"]
        self.assertTrue(prod_moments)
        self.assertEqual(prod_moments[0]["evidence"]["source"], "lexicon")

        # Positif: kata kerja layar + objek
        clip_action = self._make_clip(
            [{"start": 3.0, "end": 5.0, "text": "Silakan download aplikasinya sekarang"}]
        )
        res_action = fxfeatures.extract_clip(clip_action)
        prod_action = [m for m in res_action["moments"] if m["trigger"] == "product"]
        self.assertTrue(prod_action)
        self.assertEqual(prod_action[0]["evidence"]["source"], "action")

        # Negatif: kapital di awal kalimat biasa
        clip_cap = self._make_clip(
            [{"start": 3.0, "end": 5.0, "text": "Mereka semua sangat senang berkumpul"}]
        )
        res_cap = fxfeatures.extract_clip(clip_cap)
        self.assertEqual([m for m in res_cap["moments"] if m["trigger"] == "product"], [])

    def test_trigger_emphasis_and_confidence(self) -> None:
        # Positif: kata beraksen tier-1
        clip = self._make_clip(
            [
                {
                    "start": 4.0,
                    "end": 6.0,
                    "text": "Kita harus segera bertindak",
                    "emphasis": "harus",
                    "words": [
                        {"w": "Kita", "start": 4.0, "end": 4.3},
                        {"w": "harus", "start": 4.3, "end": 4.9},
                        {"w": "segera", "start": 4.9, "end": 5.4},
                        {"w": "bertindak", "start": 5.4, "end": 6.0},
                    ],
                }
            ],
            punch=[{"t": 4.5, "scale": 1.2}],
        )
        res = fxfeatures.extract_clip(clip)
        emp_moments = [m for m in res["moments"] if m["trigger"] == "emphasis"]
        self.assertTrue(emp_moments)
        m = emp_moments[0]
        self.assertEqual(m["text"], "harus")
        self.assertTrue(m["near_punch"])
        # Rumus confidence: base 0.60 + min(len(harus)/20, 0.20) [0.25 -> 0.20] + 0.15 (near punch) = 0.95
        self.assertAlmostEqual(m["confidence"], 0.95, places=2)

    def test_trigger_reveal_positive_and_negative(self) -> None:
        # Positif: kata pengungkapan diikuti angka dalam <= 3s
        pos_clip = self._make_clip(
            [
                {"start": 3.0, "end": 4.0, "text": "Ternyata hasilnya sangat mengejutkan"},
                {"start": 4.5, "end": 6.0, "text": "Ada 50 juta pengguna aktif baru"},
            ]
        )
        res = fxfeatures.extract_clip(pos_clip)
        reveal_moments = [m for m in res["moments"] if m["trigger"] == "reveal"]
        self.assertTrue(reveal_moments)
        self.assertEqual(reveal_moments[0]["evidence"]["reveal_word"], "ternyata")

        # Negatif: kata pengungkapan tanpa angka/tren dalam 3s
        neg_clip = self._make_clip(
            [
                {"start": 3.0, "end": 4.0, "text": "Ternyata kita semua sudah sangat lelah"},
                {"start": 4.5, "end": 6.0, "text": "Dan kita ingin segera beristirahat"},
            ]
        )
        res_neg = fxfeatures.extract_clip(neg_clip)
        self.assertEqual([m for m in res_neg["moments"] if m["trigger"] == "reveal"], [])

        # Negatif: kata penanda 'hasilnya' tanpa angka ("hasilnya aku lupa")
        neg_clip_lupa = self._make_clip(
            [{"start": 3.0, "end": 5.0, "text": "hasilnya aku lupa"}]
        )
        res_lupa = fxfeatures.extract_clip(neg_clip_lupa)
        self.assertEqual([m for m in res_lupa["moments"] if m["trigger"] == "reveal"], [])

    def test_trigger_reveal_same_sentence_across_captions(self) -> None:
        # Kasus positif recall 7b: penanda diikuti angka di kalimat yang sama walau jeda > 3s
        clip = self._make_clip(
            [
                {"start": 1.0, "end": 2.0, "text": "Ternyata hasilnya"},
                {"start": 5.0, "end": 6.5, "text": "3 kali lipat lebih besar dari tahun lalu"},
            ]
        )
        res = fxfeatures.extract_clip(clip)
        reveal_moments = [m for m in res["moments"] if m["trigger"] == "reveal"]
        self.assertTrue(reveal_moments, "Harus mendeteksi 'reveal' dalam kalimat yang sama walau jeda > 3s")
        self.assertIn("ternyata", reveal_moments[0]["evidence"]["reveal_word"])

        # Negatif bila beda kalimat (ada titik) dan jeda > 3s
        clip_diff_sent = self._make_clip(
            [
                {"start": 1.0, "end": 2.0, "text": "Ternyata hasilnya sudah keluar."},
                {"start": 5.5, "end": 7.0, "text": "Ada 3 orang pemenang baru"},
            ]
        )
        res_diff = fxfeatures.extract_clip(clip_diff_sent)
        self.assertEqual(
            [m for m in res_diff["moments"] if m["trigger"] == "reveal"],
            [],
            "Tidak boleh reveal jika kalimat berbeda dan jeda > 3 detik",
        )


class FxFeaturesVisualContextAndFitsTest(unittest.TestCase):
    """Pengujian shot_kind, in_hook_window, near_punch, dan evaluasi fits."""

    def test_shot_kind_exact_thresholds(self) -> None:
        # Ambang close_up: 0.35 * 1920 = 672.0 px
        track_cu = [{"t": 0.0, "faces": [{"x": 300, "y": 400, "w": 400, "h": 672.0}]}]
        res_cu = fxfeatures._analyze_shots(track_cu, 10.0)
        self.assertEqual(res_cu[0]["shot_kind"], "close_up")

        # Sedikit di bawah ambang close_up -> medium (h = 671.0 px)
        track_med1 = [{"t": 0.0, "faces": [{"x": 300, "y": 400, "w": 400, "h": 671.0}]}]
        res_med1 = fxfeatures._analyze_shots(track_med1, 10.0)
        self.assertEqual(res_med1[0]["shot_kind"], "medium")

        # Ambang medium: 0.20 * 1920 = 384.0 px
        track_med2 = [{"t": 0.0, "faces": [{"x": 300, "y": 400, "w": 400, "h": 384.0}]}]
        res_med2 = fxfeatures._analyze_shots(track_med2, 10.0)
        self.assertEqual(res_med2[0]["shot_kind"], "medium")

        # Sedikit di bawah ambang medium -> wide (h = 383.0 px)
        track_wide = [{"t": 0.0, "faces": [{"x": 300, "y": 400, "w": 400, "h": 383.0}]}]
        res_wide = fxfeatures._analyze_shots(track_wide, 10.0)
        self.assertEqual(res_wide[0]["shot_kind"], "wide")

        # Tanpa face_track -> unknown
        res_unk = fxfeatures._analyze_shots(None, 10.0)
        self.assertEqual(res_unk[0]["shot_kind"], "unknown")
        self.assertIsNone(res_unk[0]["face_height_ratio"])

    def test_in_hook_window_and_near_punch(self) -> None:
        clip = {
            "id": "clip_hook",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [
                {"start": 0.5, "end": 1.5, "text": "Ada 100 orang di hook"},
                {"start": 5.0, "end": 7.0, "text": "Ada 200 orang di tengah"},
            ],
            "punch": [{"t": 5.2, "scale": 1.2}],
        }
        res = fxfeatures.extract_clip(clip)
        moments = res["moments"]
        self.assertEqual(len(moments), 2)

        # Momen 1 di hook window
        self.assertTrue(moments[0]["in_hook_window"])
        self.assertFalse(moments[0]["near_punch"])

        # Momen 2 di luar hook window, dekat punch
        self.assertFalse(moments[1]["in_hook_window"])
        self.assertTrue(moments[1]["near_punch"])

    def test_fits_close_up_vs_wide_vs_no_face_track(self) -> None:
        # Close-up talking head: kartu ok=False, zoom_through_text & pullback ok=True
        clip_cu = {
            "id": "clip_cu",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [
                {"start": 3.0, "end": 7.0, "text": "Keuntungan melonjak 25 persen"}
            ],
            "reframe": {
                "face_track": [
                    {"t": 0.0, "faces": [{"x": 100.0, "y": 200.0, "w": 880.0, "h": 1200.0}]}
                ]
            },
        }
        res_cu = fxfeatures.extract_clip(clip_cu)
        m_cu = res_cu["moments"][0]
        fits_cu = m_cu["fits"]

        # Kartu ditolak karena close_up menutup slot
        for card_name in ("checklist", "chart_grow", "ui_panel", "phone_frame"):
            self.assertFalse(
                fits_cu[card_name]["ok"],
                f"{card_name} harus ok=False pada close-up",
            )
            self.assertIn("close_up: tidak ada slot bebas", fits_cu[card_name]["reason"])
            self.assertIsNone(fits_cu[card_name]["rect"])

        # Efek bebas wajah diterima
        self.assertTrue(fits_cu["zoom_through_text"]["ok"])
        self.assertTrue(fits_cu["pullback"]["ok"])

        # Shot lebar: kartu ok=True dengan rect
        clip_wide = {
            "id": "clip_wide",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [
                {"start": 3.0, "end": 7.0, "text": "Keuntungan melonjak 25 persen"}
            ],
            "reframe": {
                "face_track": [
                    {"t": 0.0, "faces": [{"x": 450.0, "y": 1500.0, "w": 180.0, "h": 250.0}]}
                ]
            },
        }
        res_wide = fxfeatures.extract_clip(clip_wide)
        m_wide = res_wide["moments"][0]
        fits_wide = m_wide["fits"]
        self.assertTrue(fits_wide["chart_grow"]["ok"])
        self.assertIsNotNone(fits_wide["chart_grow"]["rect"])
        self.assertIn("x", fits_wide["chart_grow"]["rect"])

        # Tanpa face_track: kartu ok=False dengan alasan 'tanpa face_track'
        clip_no_track = {
            "id": "clip_no_track",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [
                {"start": 3.0, "end": 7.0, "text": "Keuntungan melonjak 25 persen"}
            ],
        }
        res_nt = fxfeatures.extract_clip(clip_no_track)
        m_nt = res_nt["moments"][0]
        fits_nt = m_nt["fits"]
        self.assertFalse(fits_nt["checklist"]["ok"])
        self.assertIn("tanpa face_track", fits_nt["checklist"]["reason"])
        self.assertTrue(fits_nt["zoom_through_text"]["ok"])

    def test_fits_window_too_short(self) -> None:
        # Jendela tersedia sangat pendek: klip berakhir di 4.25s, END_MARGIN 0.4s -> available end = 3.85s <= t0 (4.0s)
        # Atau klip 4.45s -> available end = 4.05s -> avail_dur = 0.05s < min (0.40s)
        clip_short = {
            "id": "clip_short",
            "segments": [{"src_start": 0.0, "src_end": 4.45}],
            "captions": [
                {
                    "start": 4.0,
                    "end": 4.2,
                    "text": "harus",
                    "emphasis": "harus",
                    "words": [{"w": "harus", "start": 4.0, "end": 4.2}],
                }
            ],
        }
        res = fxfeatures.extract_clip(clip_short)
        m = res["moments"][0]
        fits = m["fits"]
        self.assertFalse(fits["zoom_through_text"]["ok"])
        self.assertIn("jendela (0.05s) < min", fits["zoom_through_text"]["reason"])

    def test_fits_available_window_emphasis_short_moment(self) -> None:
        # Kasus temuan 7a: kata beraksen 0.16s pada klip 10s
        # Sekarang zoom_through_text harus ok=True karena available_window 10 - 0.4 = 9.6s (avail_dur = 6.78s >= 0.4s)
        clip = {
            "id": "clip_emp_16",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [
                {
                    "start": 2.82,
                    "end": 2.98,
                    "text": "nggak",
                    "emphasis": "nggak",
                    "words": [{"w": "nggak", "start": 2.82, "end": 2.98}],
                }
            ],
            "reframe": {
                "face_track": [
                    {"t": 0.0, "faces": [{"x": 100.0, "y": 200.0, "w": 880.0, "h": 1200.0}]}
                ]
            },
        }
        res = fxfeatures.extract_clip(clip)
        m = res["moments"][0]
        self.assertAlmostEqual(m["trigger_duration"], 0.16, places=2)
        self.assertEqual(m["available_window"]["start"], 2.82)
        self.assertAlmostEqual(m["available_window"]["end"], 9.6, places=2)
        self.assertEqual(m["available_window"]["limited_by"], "clip_end")

        fits = m["fits"]
        # zoom_through_text ok=True dengan suggested_window ~ 0.7s
        self.assertTrue(fits["zoom_through_text"]["ok"])
        s_win = fits["zoom_through_text"]["suggested_window"]
        self.assertIsNotNone(s_win)
        self.assertAlmostEqual(s_win["end"] - s_win["start"], 0.70, places=2)

        # Kartu tetap ok=False karena close-up (bukan karena durasi jendela)
        self.assertFalse(fits["checklist"]["ok"])
        self.assertIn("close_up", fits["checklist"]["reason"])

    def test_available_window_limited_by_existing_overlay(self) -> None:
        clip = {
            "id": "clip_ov",
            "segments": [{"src_start": 0.0, "src_end": 20.0}],
            "captions": [
                {
                    "start": 3.0,
                    "end": 3.5,
                    "text": "100 persen berhasil",
                }
            ],
            "overlays": [
                {"type": "vs", "start": 8.0, "end": 11.0}
            ],
        }
        res = fxfeatures.extract_clip(clip)
        m = res["moments"][0]
        # Overlay berikutnya mulai 8.0. MIN_GAP_SECONDS = 4.0. Limit = 8.0 - 4.0 = 4.0s
        self.assertEqual(m["available_window"]["limited_by"], "existing_overlay")
        self.assertAlmostEqual(m["available_window"]["end"], 4.0, places=2)

    def test_suggested_window_for_list_extended_by_evidence(self) -> None:
        clip = {
            "id": "clip_list",
            "segments": [{"src_start": 0.0, "src_end": 20.0}],
            "captions": [
                {
                    "start": 3.0,
                    "end": 8.0,
                    "text": "Pertama siapkan berkas lalu kedua lakukan verifikasi",
                    "words": [
                        {"w": "Pertama", "start": 3.0, "end": 3.5},
                        {"w": "siapkan", "start": 3.5, "end": 4.0},
                        {"w": "berkas", "start": 4.0, "end": 4.5},
                        {"w": "lalu", "start": 4.5, "end": 5.0},
                        {"w": "kedua", "start": 7.5, "end": 8.0},
                    ],
                }
            ],
            "reframe": {
                "face_track": [
                    {"t": 0.0, "faces": [{"x": 450.0, "y": 1500.0, "w": 180.0, "h": 250.0}]}
                ]
            },
        }
        res = fxfeatures.extract_clip(clip)
        list_m = next(m for m in res["moments"] if m["trigger"] == "list")
        fits = list_m["fits"]
        self.assertTrue(fits["checklist"]["ok"])
        s_win = fits["checklist"]["suggested_window"]
        self.assertIsNotNone(s_win)
        # Butir terakhir ada di 7.5, diperpanjang hingga done_at + 1.0 = 8.5s
        self.assertGreaterEqual(s_win["end"], 8.5)


class FxFeaturesContractAndDeterminismTest(unittest.TestCase):
    """Pengujian kontrak EDL, determinisme, immutability, dan skema JSON."""

    def test_tier1_sets_time_precision_phrase(self) -> None:
        clip_t1 = {
            "id": "clip_t1",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [
                {"start": 3.0, "end": 5.0, "text": "Ada 50 juta orang"}
            ],
        }
        res = fxfeatures.extract_clip(clip_t1)
        self.assertEqual(res["time_precision"], "phrase")

    def test_tier2_sets_time_precision_word(self) -> None:
        clip_t2 = {
            "id": "clip_t2",
            "segments": [{"src_start": 0.0, "src_end": 10.0}],
            "captions": [
                {
                    "start": 3.0,
                    "end": 5.0,
                    "text": "Ada 50 juta orang",
                    "words": [{"w": "Ada", "start": 3.0, "end": 3.3}],
                }
            ],
        }
        res = fxfeatures.extract_clip(clip_t2)
        self.assertEqual(res["time_precision"], "word")

    def test_determinism_and_stable_ids(self) -> None:
        clip = {
            "id": "clip_det",
            "segments": [{"src_start": 0.0, "src_end": 15.0}],
            "captions": [
                {"start": 2.5, "end": 4.0, "text": "Tahu nggak kenapa?"},
                {"start": 5.0, "end": 7.0, "text": "Ada 100 orang mendaftar"},
                {"start": 8.0, "end": 10.0, "text": "Buka Instagram sekarang"},
            ],
        }
        res1 = fxfeatures.extract_clip(clip)
        res2 = fxfeatures.extract_clip(clip)

        self.assertEqual(res1, res2)
        ids = [m["id"] for m in res1["moments"]]
        self.assertEqual(ids, ["m001", "m002", "m003"])

    def test_input_immutability(self) -> None:
        edl = {
            "version": "0.1.0",
            "clips": [
                {
                    "id": "clip_immut",
                    "segments": [{"src_start": 0.0, "src_end": 10.0}],
                    "captions": [{"start": 3.0, "end": 5.0, "text": "Ada 25 persen"}],
                }
            ],
        }
        before = copy.deepcopy(edl)
        _ = fxfeatures.extract(edl)
        self.assertEqual(edl, before)

    def test_output_validates_against_schema(self) -> None:
        edl = {
            "version": "0.1.0",
            "clips": [
                {
                    "id": "clip_schema",
                    "segments": [{"src_start": 0.0, "src_end": 15.0}],
                    "captions": [
                        {"start": 0.5, "end": 1.8, "text": "Tahu nggak kenapa ini terjadi?"},
                        {"start": 3.0, "end": 6.0, "text": "Omset naik dari 10 ke 50 juta"},
                    ],
                    "reframe": {
                        "face_track": [
                            {"t": 0.0, "faces": [{"x": 200, "y": 300, "w": 400, "h": 500}]}
                        ]
                    },
                }
            ],
        }
        result = fxfeatures.extract(edl)
        schema = load_fx_schema()

        undeclared = undeclared_keys(schema, result)
        self.assertEqual(undeclared, [], f"Kunci tak terdaftar: {undeclared}")

        missing = missing_required(schema, result)
        self.assertEqual(missing, [], f"Field wajib kurang: {missing}")


if __name__ == "__main__":
    unittest.main()
