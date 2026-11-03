"""Tes ekstraktor fitur dan momen kandidat efek video (scripts/fxfeatures.py)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest import mock
from typing import Any

from scripts import fxcatalog
from scripts import fxfeatures
from scripts import presets_phone
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
        self.assertEqual(prod_action[0]["evidence"]["source"], "screen_action")

    def test_product_negative_real_cases(self) -> None:
        # Tujuh kasus nyata dari podcast video pengguna yang sebelumnya memicu product palsu
        real_negatives = [
            "sekali, Cukup Sekali, sekali.",
            "Deal, Tidak ya.",
            "ada Deal.",
            "Deal Oke.",
            "Ini Vue-nya cuma 5.000",
            "Sebelum Bangunan ditinggal",
            "Atau mau Om Pimpa dulu?",
        ]
        for sentence in real_negatives:
            with self.subTest(sentence=sentence):
                clip = self._make_clip([{"start": 3.0, "end": 6.0, "text": sentence}])
                res = fxfeatures.extract_clip(clip)
                prod = [m for m in res["moments"] if m["trigger"] == "product"]
                self.assertEqual(prod, [], f"Kalimat nyata '{sentence}' memicu product palsu: {prod}")

    def test_product_positive_cases(self) -> None:
        positives = [
            "Buka Instagram lalu klik profil",
            "Aku download Notion",
            "Di Tokopedia harganya murah",
            "Kamu bisa pakai ChatGPT untuk ini",
        ]
        for sentence in positives:
            with self.subTest(sentence=sentence):
                clip = self._make_clip([{"start": 3.0, "end": 6.0, "text": sentence}])
                res = fxfeatures.extract_clip(clip)
                prod = [m for m in res["moments"] if m["trigger"] == "product"]
                self.assertTrue(prod, f"Kalimat '{sentence}' harus memicu product")
                self.assertIn(prod[0]["evidence"]["source"], ("lexicon", "screen_action"))

    def test_product_mutants_checks(self) -> None:
        # Mutan (i): kapital tunggal tidak boleh memicu
        clip_single_cap = self._make_clip([{"start": 1.0, "end": 4.0, "text": "Ada Rumah di sana"}])
        res_sc = fxfeatures.extract_clip(clip_single_cap)
        self.assertEqual([m for m in res_sc["moments"] if m["trigger"] == "product"], [])

        # Mutan (j): stop words tidak boleh memicu walau berulang di tengah kalimat
        clip_stop = self._make_clip([{"start": 1.0, "end": 4.0, "text": "kami Oke dan sangat Oke"}])
        res_stop = fxfeatures.extract_clip(clip_stop)
        self.assertEqual([m for m in res_stop["moments"] if m["trigger"] == "product"], [])

        # Mutan (k): nama orang dengan gelar tidak boleh memicu
        clip_honorific = self._make_clip([{"start": 1.0, "end": 4.0, "text": "tanya Pak Pimpa dan Pak Pimpa"}])
        res_hon = fxfeatures.extract_clip(clip_honorific)
        self.assertEqual([m for m in res_hon["moments"] if m["trigger"] == "product"], [])

        # Mutan (l): leksikon aplikasi harus memicu
        clip_lex = self._make_clip([{"start": 1.0, "end": 4.0, "text": "putar di Spotify sekarang"}])
        res_lex = fxfeatures.extract_clip(clip_lex)
        prod_lex = [m for m in res_lex["moments"] if m["trigger"] == "product"]
        self.assertTrue(prod_lex)
        self.assertEqual(prod_lex[0]["evidence"]["source"], "lexicon")

        # Syarat (c): token berkapital berulang >= 2 kali di tengah kalimat tanpa gelar/stop
        clip_repeat = self._make_clip([{"start": 1.0, "end": 5.0, "text": "saya suka Kodingan lalu bikin Kodingan lagi"}])
        res_rep = fxfeatures.extract_clip(clip_repeat)
        prod_rep = [m for m in res_rep["moments"] if m["trigger"] == "product"]
        self.assertTrue(prod_rep)
        self.assertEqual(prod_rep[0]["evidence"]["source"], "repeated_capital")

    def test_screen_action_verbs_and_sentence_boundaries_7f(self) -> None:
        """Cacat 2 & 3: kata kerja layar spesifikasi 7e dan batas kalimat."""
        # 1. 'cari' polos bukan kata kerja layar; harus berupa 'cari di'
        cari_negatives = [
            "Gua mau cari Orang yang bisa.",
            "Gua mau cari Cara Baru buat ini.",
        ]
        for s in cari_negatives:
            with self.subTest(sentence=s):
                clip = self._make_clip([{"start": 1.0, "end": 4.0, "text": s}])
                prod = [m for m in fxfeatures.extract_clip(clip)["moments"] if m["trigger"] == "product"]
                self.assertEqual(prod, [], f"Cari polos tidak boleh memicu product: '{s}'")

        # 2. 'pasang' dan 'tekan' bukan kata kerja layar
        other_negatives = [
            "Dia pasang Spanduk besar.",
            "Tekan Tombol itu.",
        ]
        for s in other_negatives:
            with self.subTest(sentence=s):
                clip = self._make_clip([{"start": 1.0, "end": 4.0, "text": s}])
                prod = [m for m in fxfeatures.extract_clip(clip)["moments"] if m["trigger"] == "product"]
                self.assertEqual(prod, [], f"Bukan kata kerja layar: '{s}'")

        # 3. Batas kalimat setelah kata kerja atau token di jendela objek
        boundary_negatives = [
            "Pintunya gua buka. Rudi masuk duluan.",
            "Dia langsung klik. Sekarang Rudi nunggu.",
            "Buka pintu. Rudi masuk.",
        ]
        for s in boundary_negatives:
            with self.subTest(sentence=s):
                clip = self._make_clip([{"start": 1.0, "end": 4.0, "text": s}])
                prod = [m for m in fxfeatures.extract_clip(clip)["moments"] if m["trigger"] == "product"]
                self.assertEqual(prod, [], f"Batas kalimat harus menghentikan jendela objek: '{s}'")

        # 4. Batas kalimat menghentikan pemindaian kata berikutnya
        clip_stop_next = self._make_clip([{"start": 1.0, "end": 4.0, "text": "Kamu klik cepat. Lalu checkout."}])
        prod_stop = [m for m in fxfeatures.extract_clip(clip_stop_next)["moments"] if m["trigger"] == "product"]
        self.assertEqual(prod_stop, [], "Token 'cepat.' bertitik harus menghentikan pemindaian sebelum 'checkout'")

        # 5. Kasus positif: leksikon, screen_action UI, dan 'cari di'
        positives = [
            ("Coba cari di Google dulu.", "lexicon"),
            ("Coba buka TikTok terus cari akun itu.", "lexicon"),
            ("Kamu klik Shopee. Lalu checkout.", "lexicon"),
            ("Habis itu buka profil dia.", "screen_action"),
            ("Aku download Notion tiap hari.", "lexicon"),
            ("Silakan klik menu.", "screen_action"),
            ("Coba cari di Toko itu.", "screen_action"),
        ]
        for s, src in positives:
            with self.subTest(sentence=s):
                clip = self._make_clip([{"start": 1.0, "end": 4.0, "text": s}])
                prod = [m for m in fxfeatures.extract_clip(clip)["moments"] if m["trigger"] == "product"]
                self.assertTrue(prod, f"Kalimat positif harus memicu product: '{s}'")
                self.assertEqual(prod[0]["evidence"]["source"], src)

    def test_mutant_a_screen_action_window_3_words_limit(self) -> None:
        """Mutan A: jendela objek kata kerja layar maksimal 3 kata, bukan 6."""
        # 'Rudi' adalah kata ke-4 setelah kata kerja 'buka'
        clip = self._make_clip([{"start": 1.0, "end": 4.0, "text": "Gua buka pelan pelan banget Rudi."}])
        prod = [m for m in fxfeatures.extract_clip(clip)["moments"] if m["trigger"] == "product"]
        self.assertEqual(prod, [], "Objek di kata ke-4 tidak boleh memicu product")

    def test_mutant_b_repeated_capital_sentence_boundary_within_caption(self) -> None:
        """Mutan B: aturan batas kalimat pada repeated_capital di dalam satu caption."""
        clip = self._make_clip([{"start": 1.0, "end": 4.0, "text": "Gua oke. Pokoknya jalan. Pokoknya beres."}])
        prod = [m for m in fxfeatures.extract_clip(clip)["moments"] if m["trigger"] == "product"]
        self.assertEqual(prod, [], "Awal kalimat berulang setelah titik dalam satu caption bukan product")

    def test_mutant_k_screen_action_honorific_title_rejection(self) -> None:
        """Mutan K: nama orang yang diawali gelar (honorific) tidak boleh jadi objek kata kerja layar."""
        clip = self._make_clip([{"start": 1.0, "end": 4.0, "text": "Gua buka Om Pimpa dulu."}])
        prod = [m for m in fxfeatures.extract_clip(clip)["moments"] if m["trigger"] == "product"]
        self.assertEqual(prod, [], "Objek didahului gelar orang tidak boleh memicu product")

    def test_fits_phone_frame_default_side_rect(self) -> None:
        """Cacat 1: _evaluate_fits phone_frame harus menghasilkan rect.x == 640.0 (side kanan)."""
        from scripts.layout import Rect
        fits = fxfeatures._evaluate_fits(
            moment_t0=5.0,
            moment_t1=7.0,
            trigger="number",
            shot={"shot_kind": "medium"},
            in_hook=False,
            raw_faces=[Rect(450.0, 1500.0, 100.0, 100.0)],
            punch=[],
            caption_rects=[],
            taken_rects=[],
            available_window={"start": 0.0, "end": 20.0},
        )
        self.assertTrue(fits["phone_frame"]["ok"])
        self.assertEqual(
            fits["phone_frame"]["rect"]["x"],
            float(presets_phone.PHONE_DEFAULT_X_RIGHT),
            f"phone_frame rect.x harus {presets_phone.PHONE_DEFAULT_X_RIGHT}, dapat {fits['phone_frame']['rect']['x']}",
        )

    def test_list_negative_real_and_mutants(self) -> None:
        # Mutan (m): penanda identik berulang ("pertama" 2x) tidak boleh dihitung 2 butir
        clip_rep_m = self._make_clip([
            {"start": 1.0, "end": 3.0, "text": "Tidak ke pertama.", "words": [{"w": "Tidak", "start": 1.0, "end": 1.5}, {"w": "ke", "start": 1.5, "end": 1.8}, {"w": "pertama.", "start": 1.8, "end": 2.2}]},
            {"start": 3.0, "end": 5.0, "text": "Tidak ke pertama.", "words": [{"w": "Tidak", "start": 3.0, "end": 3.5}, {"w": "ke", "start": 3.5, "end": 3.8}, {"w": "pertama.", "start": 3.8, "end": 4.2}]},
        ])
        res_rep_m = fxfeatures.extract_clip(clip_rep_m)
        self.assertEqual([m for m in res_rep_m["moments"] if m["trigger"] == "list"], [], "Penanda 'pertama' berulang 2x tidak boleh memicu list")

        # Idiom negatif
        idiom_negatives = [
            ("pertama kali aku coba", "pertama kali"),
            ("pertama-tama kita sambut", "pertama-tama"),
            ("yang pertama dan yang pertama lagi", "pertama berulang"),
            ("kedua kakinya sakit", "kedua anggota tubuh"),
        ]
        for text, desc in idiom_negatives:
            with self.subTest(desc=desc):
                words = [{"w": w, "start": 1.0 + i * 0.4, "end": 1.4 + i * 0.4} for i, w in enumerate(text.split())]
                clip = self._make_clip([{"start": 1.0, "end": 5.0, "text": text, "words": words}])
                res = fxfeatures.extract_clip(clip)
                self.assertEqual([m for m in res["moments"] if m["trigger"] == "list"], [])

        # Mutan (n): urutan naik harus dicek ("kedua" lalu "pertama" -> bukan list)
        clip_non_asc = self._make_clip([
            {"start": 1.0, "end": 5.0, "text": "kedua modal pertama waktu", "words": [
                {"w": "kedua", "start": 1.0, "end": 1.5},
                {"w": "modal", "start": 1.5, "end": 2.0},
                {"w": "pertama", "start": 2.5, "end": 3.0},
                {"w": "waktu", "start": 3.0, "end": 3.5},
            ]}
        ])
        res_non_asc = fxfeatures.extract_clip(clip_non_asc)
        self.assertEqual([m for m in res_non_asc["moments"] if m["trigger"] == "list"], [], "Urutan menurun tidak boleh memicu list")

    def test_list_positive_cases(self) -> None:
        # Urutan naik pertama < kedua < ketiga
        clip_asc = self._make_clip([
            {"start": 1.0, "end": 6.0, "text": "pertama modal kedua tim ketiga waktu", "words": [
                {"w": "pertama", "start": 1.0, "end": 1.5},
                {"w": "modal", "start": 1.5, "end": 2.0},
                {"w": "kedua", "start": 2.5, "end": 3.0},
                {"w": "tim", "start": 3.0, "end": 3.5},
                {"w": "ketiga", "start": 4.0, "end": 4.5},
                {"w": "waktu", "start": 4.5, "end": 5.0},
            ]}
        ])
        res_asc = fxfeatures.extract_clip(clip_asc)
        moments_asc = [m for m in res_asc["moments"] if m["trigger"] == "list"]
        self.assertTrue(moments_asc)
        self.assertEqual(len(moments_asc[0]["evidence"]["items"]), 3)

        # Frasa 'yang pertama ... yang kedua'
        clip_yang = self._make_clip([
            {"start": 1.0, "end": 5.0, "text": "yang pertama kita mulai yang kedua kita evaluasi", "words": [
                {"w": "yang", "start": 1.0, "end": 1.2},
                {"w": "pertama", "start": 1.2, "end": 1.6},
                {"w": "kita", "start": 1.6, "end": 1.9},
                {"w": "mulai", "start": 1.9, "end": 2.3},
                {"w": "yang", "start": 2.5, "end": 2.7},
                {"w": "kedua", "start": 2.7, "end": 3.1},
                {"w": "kita", "start": 3.1, "end": 3.4},
                {"w": "evaluasi", "start": 3.4, "end": 4.0},
            ]}
        ])
        res_yang = fxfeatures.extract_clip(clip_yang)
        moments_yang = [m for m in res_yang["moments"] if m["trigger"] == "list"]
        self.assertTrue(moments_yang)

        # Isyarat jumlah + urutan
        clip_cue = self._make_clip([
            {"start": 1.0, "end": 6.0, "text": "ada tiga hal: satu modal dua tim tiga waktu", "words": [
                {"w": "ada", "start": 1.0, "end": 1.2},
                {"w": "tiga", "start": 1.2, "end": 1.4},
                {"w": "hal:", "start": 1.4, "end": 1.8},
                {"w": "satu", "start": 2.0, "end": 2.3},
                {"w": "modal", "start": 2.3, "end": 2.6},
                {"w": "dua", "start": 2.8, "end": 3.1},
                {"w": "tim", "start": 3.1, "end": 3.4},
                {"w": "tiga", "start": 3.6, "end": 3.9},
                {"w": "waktu", "start": 3.9, "end": 4.3},
            ]}
        ])
        res_cue = fxfeatures.extract_clip(clip_cue)
        moments_cue = [m for m in res_cue["moments"] if m["trigger"] == "list"]
        self.assertTrue(moments_cue)

    def test_fits_uses_dynamic_required_size_and_scan_free_rect(self) -> None:
        # Mutan (o): fits harus memakai required_size contoh katalog dan scan_free_rect
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

        # Contoh checklist 4 butir: required_size dinamis = 392.0 vs default_size statis = 328.0
        example_4_items = {
            "title": "Empat Butir",
            "items": [{"text": f"Langkah {i+1}", "done_at": float(i+1)} for i in range(4)],
        }
        with mock.patch.dict(fxcatalog.EFFECTS["checklist"], {"example": example_4_items}):
            res_dyn = fxfeatures.extract_clip(clip_wide)
            fits_dyn = res_dyn["moments"][0]["fits"]
            self.assertTrue(fits_dyn["checklist"]["ok"])
            rect_cl_dyn = fits_dyn["checklist"]["rect"]
            self.assertIsNotNone(rect_cl_dyn)
            self.assertEqual(rect_cl_dyn["w"], 960.0)
            self.assertEqual(rect_cl_dyn["h"], 392.0)

        res_wide = fxfeatures.extract_clip(clip_wide)
        m = res_wide["moments"][0]
        fits = m["fits"]

        # Checklist contoh memiliki 3 butir -> required_size h = 328.0 (bukan slot 300 / 240)
        self.assertTrue(fits["checklist"]["ok"])
        rect_cl = fits["checklist"]["rect"]
        self.assertIsNotNone(rect_cl)
        self.assertEqual(rect_cl["w"], 960.0)
        self.assertEqual(rect_cl["h"], 328.0)

        # Phone frame contoh memiliki 3 baris -> required_size h = 660.0, w = 380.0
        self.assertTrue(fits["phone_frame"]["ok"])
        rect_pf = fits["phone_frame"]["rect"]
        self.assertIsNotNone(rect_pf)
        self.assertEqual(rect_pf["w"], 380.0)
        self.assertEqual(rect_pf["h"], 660.0)

        # Chart grow contoh -> required_size h = 520.0, w = 960.0
        self.assertTrue(fits["chart_grow"]["ok"])
        rect_cg = fits["chart_grow"]["rect"]
        self.assertIsNotNone(rect_cg)
        self.assertEqual(rect_cg["w"], 960.0)
        self.assertEqual(rect_cg["h"], 520.0)

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


RD_NASIB_EDL = Path("work/rd_nasib/edl.json")


@unittest.skipUnless(RD_NASIB_EDL.is_file(), "work/rd_nasib/edl.json tidak ada")
class RealDataRdNasibRegressionTest(unittest.TestCase):
    """Regresi pada data nyata work/rd_nasib/edl.json."""

    def test_rd_nasib_extracted_moments_regression(self) -> None:
        with open(RD_NASIB_EDL, "r", encoding="utf-8") as f:
            edl = json.load(f)

        cands = fxfeatures.extract(edl)
        clips = cands["clips"]
        self.assertEqual(len(clips), 3)

        # Momen product = 0 dan list = 0 pada ketiga klip
        for c in clips:
            cid = c["clip_id"]
            moments = c["moments"]
            triggers = [m["trigger"] for m in moments]
            self.assertEqual(triggers.count("product"), 0, f"Klip {cid} memuat momen product: {moments}")
            self.assertEqual(triggers.count("list"), 0, f"Klip {cid} memuat momen list: {moments}")

        # Momen number untuk 'viewersnya 5.000' (clip_01) dan 'cuma 5.000, 3.000' (clip_03) TETAP ada
        c1_nums = [m["text"] for m in clips[0]["moments"] if m["trigger"] == "number"]
        self.assertTrue(any("5.000" in t for t in c1_nums), f"clip_01 missing number moment: {c1_nums}")

        c3_nums = [m["text"] for m in clips[2]["moments"] if m["trigger"] == "number"]
        self.assertTrue(any("5.000" in t for t in c3_nums), f"clip_03 missing number moment: {c3_nums}")

        # Jumlah momen emphasis tidak berubah (8, 10, 18)
        self.assertEqual(sum(1 for m in clips[0]["moments"] if m["trigger"] == "emphasis"), 8)
        self.assertEqual(sum(1 for m in clips[1]["moments"] if m["trigger"] == "emphasis"), 10)
        self.assertEqual(sum(1 for m in clips[2]["moments"] if m["trigger"] == "emphasis"), 18)


if __name__ == "__main__":
    unittest.main()
