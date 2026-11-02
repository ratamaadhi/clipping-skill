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

---

## D-009 — Tier-2: ASS dulu, bukan Remotion frame penuh

**Konteks.** Gaya reel butuh kinetic typography per kata, spring/easing, elemen grafis
masuk-keluar, dan layout sadar wajah, di mesin 2 core dengan RAM tersedia 1,6–1,9 GiB
dan swap penuh. Remotion frame penuh berarti renderer kedua (React) yang menulis ulang rantai
crop/zoom/trim/loudnorm tier-1 dan melanggar D-001.

**Keputusan.** Teks, bentuk datar, dan transisi dikerjakan libass + ffmpeg. libass tetap satu-satunya
pemilik caption (kini per kata, spring disampel per frame). Layout dihitung Python sekali saat EDL
dibangun; renderer hanya mengeksekusi koordinat. Rencana lengkap: `docs/MOTION-TIER2-PLAN.md`.

**Konsekuensi.**
- (+) Tanpa Node/Chromium di jalur kritis; biaya render diperkirakan ≈ 1,1–1,2× tier-1.
- (−) Hanya bentuk datar: tanpa tilt 3D, gradien lembut, kaca buram, emoji berwarna.
- (−) Metrik font Python harus cocok dengan libass (diuji dengan tes oracle bbox).

---

## D-010 — EDL hanya bertambah, versi tidak dibump

**Konteks.** Tes lama mengunci `version == "0.1.0"` dan `reframe.mode == "center"`. Field yang
dipakai kode (`punch`, `progress`, `reframe.bias_track`) ternyata sudah tidak ada di
`schema/edl.schema.json` yang `additionalProperties:false`, dan tidak ada tes yang menangkapnya.

**Keputusan.** Field tier-2 (`captions[].words`, `caption_style`, `transitions`, `layout`,
`overlays[].renderer/rect/props`, `reframe.face_track`) bersifat opsional dan hanya muncul bila
diminta (`build-edl --motion 2`). Tanpa flag, `edl.json` byte-identik dengan sebelumnya (tes
golden). Schema diperbaiki dan dijaga oleh tes drift: setiap kunci pada EDL hasil build harus
dideklarasikan.

**Konsekuensi.**
- (+) 229+ tes lama tetap valid; regresi diam-diam tier-1 tertangkap.
- (−) Tidak ada penanda versi untuk membedakan EDL tier-2; pembeda satu-satunya adalah keberadaan field.

---

## D-011 — Remotion dibekukan oleh gate; D-003 dikoreksi

**Konteks.** D-003 memperkirakan Remotion "≈1–3× realtime". Spike terukur
(`benchmarks/remotion.json`, 3 run per konfigurasi, mesin target): 1080×1920 hanya 2,7–3,2 fps,
yaitu ≈ 10× durasi video untuk merender, dengan RSS pohon proses 1,4–1,8 GB dan penurunan
`MemAvailable` ≈ 800 MB. `python3 -m benchmarks.gate benchmarks/remotion.json` memberi `NO_GO`
untuk setiap konfigurasi.

**Keputusan.** Overlay Remotion (Langkah 6 di rencana) **dibekukan**. Tidak ada kode Node di jalur
produk. Efek yang tidak terjangkau ASS (gradien, kaca, emoji, 3D) tidak dikejar di tier-2; bila
suatu saat dibutuhkan, spike diulang di mesin dengan RAM lebih besar, bukan dipaksakan di sini.
Perkiraan D-003 diganti angka terukur di atas.

**Konsekuensi.**
- (+) Anggaran memori mesin target tidak pernah terancam OOM oleh Chromium.
- (−) Pratinjau kaya (still React) tidak tersedia; pratinjau memakai render ffmpeg resolusi rendah.

---

## D-012 — Person matte dibekukan

**Konteks.** Spike Langkah 1b (`docs/MOTION-TIER2-PLAN.md`) menguji apakah ada model segmentasi
yang cukup bersih untuk menaruh teks/objek di belakang pembicara. Putaran 1 (protokol terkunci,
dua model × dua sumber): pphumanseg gagal `face_in_matte` (0,70 dan 0,00; probabilitas orang di
wajah ≈ 0,45) dan flicker; MODNet lolos `face_in_matte` (1,00) tetapi gagal flicker
(p95 4,91 px pada wawancara, p50 0,89 px pada video menari). Putaran 2 (dideklarasikan sebelum
dijalankan): penghalusan 0,3 menurunkan flicker pada wawancara (p95 1,00) tetapi membuat mask
tertinggal 2,5–5× di atas batas (`lag` p50 2,49 / 5,11 px, p95 10,1 / 8,95 px) dan flicker video
menari masih gagal tipis (0,55 / 1,60 px).

**Keputusan.** Matte tidak masuk produk. Tidak ada langkah `matte` di pipeline, tidak ada Langkah 7.
Efek referensi yang butuh mask (cover story, dinding kartu, latar pengganti, potongan kertas,
outline siluet, frame break, orbit, vertigo, glass type) tidak dikejar. Kualitas tidak bergantung
CPU, jadi keputusan ini tidak menunggu run di mesin target.

**Konsekuensi.**
- (+) Tidak ada dependensi model/OpenCV tambahan di jalur produk; `dependencies = []` utuh.
- (+) Pengalaman metodologis tercatat: metrik biaya (`lag`) yang dikunci sebelum data mencegah
  kesimpulan "lolos" yang keliru pada satu sumber.
- (−) Efek yang paling dikenali dari referensi (teks di belakang kepala) tidak tersedia.
- Membuka kembali butuh model atau pendekatan yang berbeda dengan deklarasi baru di rencana.
