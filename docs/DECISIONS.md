# DECISIONS — catatan keputusan arsitektur

Format ringkas ADR. Setiap entri: konteks → keputusan → konsekuensi.
Kalau kamu mau mengubah salah satu, ubah dokumen ini dulu, baru kodenya.

---

## D-001 — EDL JSON sebagai artefak pusat

**Konteks.** Render video punya banyak parameter (cut, caption, overlay, audio, reframe).
Kalau parameter tersebar di kode, render tidak reproducible dan tidak bisa di-A/B.

**Keputusan.** Semua keputusan render dinyatakan dalam satu dokumen deklaratif `edl.json`.
Renderer tidak boleh punya logika kreatif — ia hanya mengeksekusi EDL.

**Konsekuensi.**
- (+) Render deterministik: EDL sama → output sama. Bisa di-hash untuk tes regresi.
- (+) A/B test per pola jadi mungkin: ubah satu field, bandingkan.
- (+) EDL + metrik retensi = dataset untuk kalibrasi nanti (moat).
- (−) Schema harus di-version. Perubahan breaking wajib bump + migration.

---

## D-002 — Agent memilih `atom_id`, bukan timestamp

**Konteks.** LLM sangat buruk dalam aritmetika waktu. Meminta "klip dari 00:12.4 sampai
00:41.8" menghasilkan output yang meleset dan tidak konsisten antar-run.

**Keputusan.** LLM hanya boleh mengembalikan `{start_atom, end_atom}`. Mapping ke detik
dilakukan secara deterministik oleh `edl.py`.

**Konsekuensi.**
- (+) Menghilangkan seluruh kelas bug "timestamp meleset".
- (+) Output LLM bisa divalidasi terhadap rentang atom yang valid.
- (−) Atom segmentation jadi bagian kritis; kalau atomnya buruk, kandidatnya buruk.

---

## D-003 — Caption tier murah pakai libass, bukan Chromium

**Konteks.** Remotion merender lewat Chromium per frame. Untuk caption saja, itu
overkill dan mahal (≈1–3× realtime di CPU).

**Keputusan.** Caption dirender sebagai file `.ass` dan dibakar dengan filter `subtitles`
ffmpeg. Remotion hanya dipakai nanti untuk motion graphics premium.

**Konsekuensi.**
- (+) Render caption ~10× lebih cepat, tanpa Node/Chromium di jalur kritis.
- (+) Karaoke per kata (`\k`) didukung native.
- (−) Layout terbatas pada kemampuan ASS (tidak ada spring physics, tidak ada shader).
- (−) Font harus tersedia di sistem; perlu `fontsdir` yang benar di container.

---

## D-004 — Analisis audio lewat ffmpeg, bukan numpy/librosa

**Konteks.** Python 3.14 belum punya wheel untuk numpy/torch/ctranslate2. Menambah
dependency berat membuat tool rapuh dan susah dipasang.

**Keputusan.** Loudness, RMS per frame, dan silence ratio diambil dari filter ffmpeg
(`ebur128`, `astats`), di-parse dari stderr.

**Konsekuensi.**
- (+) Zero dependency Python. Jalan di mana pun ffmpeg ada.
- (+) Satu pass per file, cepat.
- (−) Pitch/prosody detail terbatas (belum ada pitch tracking). Ditandai TODO.
- (−) Parsing stderr ffmpeg rapuh terhadap perubahan format antar versi → ada tes.

---

## D-005 — Hanya satu langkah non-deterministik

**Konteks.** Agent LLM tidak deterministik. Kalau seluruh pipeline bergantung pada
penilaian agent, hasilnya tidak bisa direproduksi dan susah di-debug.

**Keputusan.** Persempit non-determinisme ke satu langkah: scoring 6 axis pada 15
kandidat. Semua langkah lain deterministik dan punya tes.

**Konsekuensi.**
- (+) Bug bisa dilokalisasi: kalau output aneh, cek `selection.json` dulu.
- (+) Konteks agent kecil (15 × ~150 kata) → cepat dan murah.
- (−) Skor bisa berubah antar-run. Mitigasi: cache `selection.json`, review manusia.

---

## D-006 — Skor komposit pakai penalti non-linear, bukan rata-rata

**Konteks.** Rata-rata sederhana menyembunyikan axis yang fatal. Klip dengan hook 2
dan payoff 10 tetap dapat 6 — padahal hook 2 berarti sudah di-swipe di detik pertama.

**Keputusan.**

```
base    = 0.30·hook + 0.20·payoff + 0.20·self_contained
        + 0.15·emotional + 0.10·concrete + 0.05·loop
penalty = 0.5 bila hook < 5;  ×0.7 bila self_contained < 4
final   = base · penalty
```

**Konsekuensi.**
- (+) Axis kritis mendominasi secara benar.
- (−) Bobot ini **heuristik**, bukan hasil kalibrasi. Wajib diganti setelah ada data.
      Sampai saat itu, jangan klaim prediktif.

---

## D-007 — Presentasi skor sebagai percentile, bukan persentase viral

**Konteks.** "Skor viral 87%" adalah klaim yang tidak bisa dipertahankan dan gampang
dibongkar user.

**Keputusan.** Tampilkan "klip ini di atas 78% klip lain di channel kamu" — rank relatif
dalam library user, bukan prediksi absolut.

**Konsekuensi.**
- (+) Klaim secara statistik bisa dipertahankan.
- (−) Butuh ≥20 klip dalam library sebelum percentile bermakna; di bawah itu
      tampilkan skor mentah + alasan.

---

## D-008 — Input hanya file milik user atau URL resmi

**Konteks.** Scraping Instagram/YouTube melanggar ToS dan membahayakan bisnis.

**Keputusan.** Tidak ada downloader. Input = path file lokal, atau URL yang diunduh
lewat API resmi (YouTube Data API tidak menyediakan download; jadi praktisnya file lokal).

**Konsekuensi.**
- (−) Friction onboarding lebih tinggi.
- (+) Model bisnis tidak bergantung pada asumsi yang bisa dicabut sepihak.
