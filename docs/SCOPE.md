# SCOPE — clipping-skill

Dokumen ini adalah **kontrak batas kerja**. Apa pun yang tidak tertulis di sini
dianggap out-of-scope sampai dipindahkan secara eksplisit.

Tujuan: mencegah scope creep yang membuat v0 tidak pernah selesai.

---

## Definisi produk

**Satu kalimat:** mengubah satu video panjang menjadi N short vertical 9:16 yang
layak dipublikasi, dengan pemilihan klip dan penilaian yang bisa dijelaskan.

**Pengguna utama:** kreator solo dan agency kecil yang produksi 5–20 video/minggu
dan tidak masalah menjalankan terminal.

**Bukan untuk:** user non-teknis, multi-tenant SaaS, tim yang butuh dashboard.

---

## v0 — IN SCOPE (target: 1–2 hari)

Tujuan v0: **membuktikan bahwa rubrik seleksi benar-benar memilih klip bagus**,
bukan membangun produk lengkap.

### Pipeline
- [x] `ingest` — normalisasi ke CFR 30fps, audio 48kHz, loudnorm 2-pass
- [x] `transcribe` — word-level via Groq / OpenAI / Deepgram / faster-whisper lokal
- [x] `segment` — atom segmentation: tanda baca + jeda >400ms + discourse marker ID
- [x] `candidates` — 5 strategi (sliding, qa, payoff, topic_shift, energy) → filter → top 15
- [x] `features` — 12+ fitur deterministik dari teks + audio (tanpa numpy)
- [x] `score` — agent menilai 6 axis; script validasi schema + hitung komposit
- [x] `edl` — EDL JSON sebagai artefak pusat
- [x] `render` — ffmpeg cut + center crop 9:16 + caption libass kinetic
- [x] **motion graphics tier-1** — punch-in (zoompan), progress bar, SFX
      disintesis, panel VS. Semua ffmpeg, tanpa dependency baru.
      Lihat [`MOTION.md`](MOTION.md).

### Kualitas
- [x] Caption sinkron: drift < 50ms pada ≥95% kata
- [x] Render deterministik: EDL sama → hash output sama
- [x] Tes offline dengan fixture sintetis, tanpa API key

### Definisi "v0 selesai"
Satu video 10–30 menit → ≥3 klip yang bisa ditonton tanpa rasa malu, caption benar,
audio seimbang, dan setiap klip punya alasan skor yang bisa dibaca manusia.

---

## v1 — NEXT (target: +1 minggu, setelah v0 divalidasi)

Hanya dikerjakan **setelah** v0 dipakai pada ≥5 video nyata dan rubriknya terbukti.

- [ ] **Reframe dengan face tracking** — YOLOv8/MediaPipe + ByteTrack, crop keyframe,
      smoothing one-euro. Gate: wajah tidak terpotong di >95% frame.
- [ ] **Multi-segment clip** — buang filler di tengah, gabung 2–3 potongan.
      Butuh piecewise-linear timestamp mapping (lihat `docs/PIPELINE.md`).
- [ ] **Template motion graphics tier-2 (Remotion)** — spring physics, layout
      sadar-bbox wajah, animasi per kata, komponen React. Punch-in, progress bar,
      SFX, dan panel VS sudah selesai di tier-1 dan tinggal dipindahkan.
- [ ] ~~**Person matte**~~ — **dibekukan** (D-012): spike Langkah 1b gagal kualitas pada dua
      putaran (flicker vs kelambanan mask). Teks/objek di belakang pembicara, outline siluet,
      dan latar pengganti tidak dikejar; 7 dari 17 efek referensi tetap lewat Langkah 2–5b.
- [ ] **Preset per-niche** — podcast, edukasi, tech review, interview.
- [ ] **Batch mode** — proses banyak video sekaligus dari folder/CSV.

---

## v2 — LATER (target: +4–6 minggu)

- [ ] Publish API (IG Graph, TikTok, YouTube) + scheduler
- [ ] Feedback loop: tarik retention/metrics → kalibrasi bobot per channel
- [ ] Style fingerprint extractor: ukur ritme referensi → preset pacing
- [ ] Thin web UI di atas scripts yang sama (queue + review + export)
- [ ] Multi-bahasa selain Indonesia

---

## OUT OF SCOPE — jangan dikerjakan di v0

Daftar ini sengaja eksplisit karena semuanya menggoda:

| Hal | Kenapa ditunda |
|---|---|
| Klaim "prediksi viral" | Tidak bisa diverifikasi. Ganti dengan percentile per channel. |
| Dashboard / web UI | Scripts dulu. UI hanya menambah permukaan bug. |
| Billing / kredit / auth | Butuh user nyata dulu. |
| Render farm / GPU cluster | Satu mesin cukup untuk puluhan video/hari. |
| Auto-publish ke sosmed | ToS platform + butuh review manusia. |
| Scraping Instagram/YouTube | ToS violation. Input = file milik user atau URL resmi. |
| B-roll generation / text-to-video | Produk berbeda. |
| Avatar / voice cloning | Produk berbeda. |
| Editor timeline drag-drop | v2, dan hanya setelah pipeline stabil. |
| Model ML training sendiri | Bobot heuristik dulu; ganti setelah ada data retention. |

---

## Quality gate per fase

| Fase | Gate terukur |
|---|---|
| v0 pipeline | 1 video → 3 klip, caption drift <50ms, render deterministik |
| v0 rubrik | Pada 5 video nyata, ≥3 dari 5 klip terpilih dinilai "layak posting" oleh manusia |
| v1 reframe | Wajah tidak terpotong di >95% frame; skor jerk halus |
| v1 multi-segment | Audio-video sync tetap <50ms setelah 3 cut |
| v2 kalibrasi | Korelasi skor vs completion-rate ≥0.6 pada ≥50 klip |

---

## Non-goals yang permanen

- Bukan pengganti editor manusia untuk konten brand-level.
- Bukan penjamin views. Skor adalah **ranker relatif dalam library user**, bukan ramalan.
- Bukan tool untuk mencuri konten orang lain.
