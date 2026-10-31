# PIPELINE — detail tiap tahap

Dokumen ini menjelaskan *kenapa* tiap tahap ada dan *angka* yang dipakai.
Semua konstanta di sini punya padanan di kode; kalau kamu mengubah satu, ubah keduanya.

---

## 0. Ringkasan alur

```
video.mp4
  ingest      → mezzanine.mp4 (CFR 30fps) + audio48.wav + audio16.wav + meta.json
  transcribe  → transcript.json   (word-level)
  segment     → atoms.json        (unit kalimat)
  candidates  → candidates.json   (top 15 + fitur)
  [AGENT]     → selection.json    (6 axis + evidence)
  score       → scored.json       (komposit + percentile)
  edl         → edl.json          (artefak pusat)
  render      → out/clip_NN.mp4
```

Yang deterministik: ingest, segment, candidates, features, score (komposit), edl, render.
Yang tidak: `selection.json` — karena itu dibuat agent, dan sengaja dipersempit ke satu langkah.

---

## 1. Ingest

| Keputusan | Nilai | Alasan |
|---|---|---|
| fps output | 30 CFR | VFR dari HP/screen recording merusak sinkronisasi caption |
| CRF mezzanine | 18 | cukup tinggi untuk generasi kedua tanpa artefak terlihat |
| GOP | 30 (1 detik) | seek cepat dan akurat untuk cut |
| audio | 48kHz PCM | hindari resample berulang; encoder AAC butuh 48k |
| audio ASR | 16kHz mono | input standar Whisper, ukuran upload kecil |
| loudness | diukur, bukan dinormalisasi di sini | normalisasi dilakukan saat render supaya bisa diubah tanpa re-ingest |

**Kenapa loudness diukur dengan limit 180s:** integrasi penuh untuk podcast 2 jam
memakan waktu lama tanpa manfaat. 180 detik pertama cukup representatif untuk laporan.

---

## 2. Transkripsi

Empat engine, satu format output. Yang penting: **word-level timestamp**.

| Engine | Model | Word-level | Diarization | Catatan |
|---|---|---|---|---|
| groq | whisper-large-v3-turbo | ✅ | ❌ | termurah, tercepat |
| openai | whisper-1 | ✅ | ❌ | paling stabil |
| deepgram | nova-3 | ✅ | ✅ | terbaik untuk wawancara |
| local | faster-whisper | ✅ | ❌ | offline, butuh py3.11–3.12 |

Kalau API tidak mengembalikan word-level, waktu kata **diestimasi** dari segmen
secara proporsional panjang kata. Pipeline tetap jalan, caption kurang presisi.
Ini fallback yang disengaja — bukan jalur utama.

**Batas akurasi yang harus diketahui:** timestamp Whisper bergeser puluhan sampai
ratusan milidetik pada audio panjang, dan berhalusinasi di keheningan atau musik.
Mitigasi produksi: VAD (silero) + chunk ≤30s + forced alignment (WhisperX).
Belum diimplementasikan di v0 — dicatat sebagai risiko.

---

## 3. Segmentasi atom

Boundary dipicu oleh tiga sinyal, berurutan prioritas:

1. **Tanda baca akhir** (`.` `!` `?` `…`) — presisi tertinggi
2. **Jeda ≥ 400ms** ke kata berikutnya
3. **Discourse marker** — presisi tinggi tanpa jeda, presisi rendah butuh jeda ≥150ms

Daftar marker ada di `scripts/lib/text.py`. Ini keunggulan lokal: tool global memakai
model generik yang tidak tahu bahwa "nah" dan "intinya" biasanya memulai poin baru.

**Post-processing:**
- atom < 3 kata digabung ke atom sebelumnya
- atom > 70 kata dipotong di jeda terbesar dalam 15 kata terakhir

**Kenapa atom, bukan detik:** LLM buruk dalam aritmetika waktu. Dengan atom, agent
hanya memilih indeks, dan mapping ke detik dilakukan deterministik (D-002).

---

## 4. Candidate generation

Lima strategi, dijalankan semua, lalu digabung dan di-dedupe:

| Strategi | Cara | Menangkap |
|---|---|---|
| `sliding` | jendela 3–8+ atom yang berakhir di batas kalimat | baseline recall |
| `qa` | atom pertanyaan + 4 atom sesudahnya | struktur tanya-jawab |
| `payoff` | atom berangka/klaim + 2 sebelum + 3 sesudah | insight |
| `topic_shift` | TF-IDF kosinus antar atom, ambil lembah | pergantian topik |
| `energy` | RMS per atom, ambil puncak | momen emosional |

**Hard filter (gugur, bukan skor):**
- durasi 20–60 detik
- minimal 30 kata
- minimal 72 wpm (bukan potongan sepi)
- tidak dimulai kata sambung menggantung ("Dan...", "Tapi...", "Karena...")

**Skor murah** untuk memilih 15 terbaik:

```
25 · max(0, 1 − |wpm − 160| / 160)      # puncak di 160 wpm
20 · max(0, 1 − filler_ratio / 0.10)    # disfluency
25 · max(0, 1 − hook_latency / 3.0)     # detik ke sinyal poin pertama
10 · min(number_density / 3, 1)         # angka spesifik
10 · (bukan kata sambung di awal)
10 · min(type_token_ratio / 0.55, 1)    # kekayaan kosakata
```

**Diversity:** kandidat yang tumpang tindih >60% (IoU temporal) dengan yang sudah
dipilih dibuang. Tanpa ini, 15 kandidat bisa berisi 3 poin yang sama.

---

## 5. Fitur deterministik

Dihitung per kandidat, tanpa numpy (`docs/DECISIONS.md` D-004).

**Teks:** `words`, `duration`, `wpm`, `filler_count`, `filler_ratio`, `particle_count`,
`question_count`, `number_count`, `number_density`, `hook_latency`,
`starts_with_conjunction`, `ends_mid_thought`, `type_token_ratio`,
`avg_atom_words`, `sentence_len_std`, `wpm_score`

**Audio** (butuh `rms.json`): `rms_mean_db`, `rms_std_db`, `silence_ratio`,
`prosody_score` = `min(rms_std / 6.0, 1.0)` — delivery datar dinilai rendah.

Fitur ini dipakai dua kali: prefilter (tahap 4) dan sebagai fitur tambahan saat
kalibrasi model nanti.

---

## 6. Scoring (agent)

Agent menilai **6 axis, skala 0–10**, masing-masing dengan `evidence` kutipan persis.

| Axis | Bobot | Yang diukur |
|---|---|---|
| hook | 0.30 | 1.5 detik pertama menciptakan ketegangan? |
| payoff | 0.20 | ada resolusi? hook dibayar? |
| self_contained | 0.20 | bisa dipahami tanpa konteks? |
| emotional | 0.15 | opini, kejutan, kontroversi, humor? |
| concrete | 0.10 | angka, contoh, cerita — atau abstrak? |
| loop | 0.05 | ending nyambung ke awal? mendorong rewatch? |

**Komposit:**

```
base    = Σ w_i · axis_i
penalty = 0.5  bila hook < 5
        × 0.7  bila self_contained < 4
final   = base · penalty · 10        # skala 0–100
```

Kenapa bukan rata-rata: klip dengan hook 2 dan payoff 10 tetap dapat 6 kalau dirata-rata,
padahal hook 2 berarti sudah di-swipe di detik pertama. Penalti non-linear menutup celah itu.

**Bobot ini heuristik.** Wajib diganti setelah ada data retention nyata. Sampai saat itu,
jangan klaim prediktif — sajikan sebagai persentil dalam library.

---

## 7. EDL dan timing

**Aturan yang tidak boleh dilanggar:**

- `segments[].src_start/src_end` → waktu **sumber** (absolut)
- `captions[].start/end` → waktu **output** (relatif awal klip)
- `captions[].src_start` → jejak balik, untuk debug drift

**v0 (satu segmen per klip):** mapping cukup `t_out = t_src − clip_start`.

**v1 (multi-segment):** wajib piecewise-linear. Untuk segmen ke-k dengan
`src_start_k`, `out_start_k`, `speed_k`:

```
t_out = out_start_k + (t_src − src_start_k) / speed_k
```

Aturan: hitung semua timestamp **setelah** EDL final, jangan pernah menjumlahkan
durasi yang sudah dibulatkan. Konversi ke frame **sekali** di akhir:
`frame = round(t_out · fps)`.

**Perapian caption:**
- durasi minimum 0.45s — di bawah itu tidak terbaca
- gap ≤0.55s diisi sampai `next.start − 0.04` — mencegah caption berkedip
- gap >0.55s dibiarkan — itu jeda bicara nyata, bukan flicker

---

## 8. Render

Rantai filter:

```
crop (9:16, bias opsional) → scale 1080x1920 lanczos → setsar=1 → subtitles (libass)
```

| Parameter | Nilai | Alasan |
|---|---|---|
| CRF | 20 | kualitas visual cukup untuk sosial media |
| preset | veryfast | rasio waktu/kualitas terbaik untuk batch |
| fps_mode | cfr, 30 | mencegah durasi caption melayang |
| audio | loudnorm −14 LUFS, TP −1 dBTP | standar platform |
| faststart | ya | streaming mulai sebelum unduh selesai |

**Seek:** `-ss` sebelum `-i`. Dengan re-encode ini akurat *dan* cepat.
Tanpa re-encode, `-ss` sebelum `-i` akan menempel ke keyframe dan meleset.

**Determinisme:** sudah diuji — EDL sama menghasilkan hash SHA-256 identik.

---

## 9. Yang belum ada (dan risikonya)

| Belum ada | Risiko | Fase |
|---|---|---|
| Face tracking | reframe center bisa memotong wajah di frame lebar | v1 |
| Forced alignment | drift caption pada audio panjang | v1 |
| Multi-segment | filler di tengah klip tidak bisa dibuang | v1 |
| Kalibrasi | bobot masih tebakan | v2 |
| Pitch tracking | prosody hanya dari RMS, bukan intonasi | v2 |
