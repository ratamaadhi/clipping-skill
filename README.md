# clipping-skill

Agent skill untuk mengubah video panjang (podcast, wawancara, screen recording, webinar)
menjadi short vertical 9:16 siap Reels / TikTok / Shorts — lengkap dengan pemilihan klip
berbasis transkrip, skor 6-axis yang explainable, dan caption kinetic.

> **Status: v0 — deterministic pipeline.** Bagian yang butuh penilaian (scoring 6 axis)
> dilakukan oleh agent, bukan oleh model terpisah. Semua sisanya deterministik dan bisa diuji.

---

## Kenapa skill, bukan web app

Skill ini adalah **Phase 1** dari produk yang lebih besar, bukan versi murahnya.

| | Web app | Skill ini |
|---|---|---|
| Waktu ke v1 jalan | 8–9 minggu | 1–2 hari |
| Biaya sebelum user pertama | infra + storage + queue | ~$0 |
| Biaya per video | render worker + API + egress | $0.02–0.13 (transkripsi saja) |
| Iterasi rubrik | deploy ulang | edit file, langsung coba |
| Layer LLM | bayar per call | **gratis** (agent sudah jalan) |

Script di `scripts/` **adalah** pipeline inti web app nanti. Lapisan queue + UI tinggal
ditambahkan di atasnya. Tidak ada kerja yang terbuang.

Baca [`docs/SCOPE.md`](docs/SCOPE.md) untuk batas kerja yang eksplisit, dan
[`docs/DECISIONS.md`](docs/DECISIONS.md) untuk alasan di balik keputusan arsitektur.

---

## Pipeline

```
video.mp4
   │
   ├─ 1. ingest      → CFR 30fps, 48kHz, audio mono 16k, loudnorm
   ├─ 2. transcribe  → word-level timestamps (+ diarization bila tersedia)
   ├─ 3. segment     → atoms (kalimat) via tanda baca + jeda + discourse marker ID
   ├─ 4. candidates  → 30–50 kandidat (5 strategi), lalu filter → 15
   ├─ 5. features    → fitur deterministik (WPM, filler, hook latency, prosodi)
   ├─ 6. score       → ⚠️ AGENT menilai 6 axis, script memvalidasi + menghitung komposit
   ├─ 7. edl         → EDL JSON (artefak pusat, sumber kebenaran render)
   └─ 8. render      → ffmpeg cut + reframe 9:16 + caption libass
```

Tahap 1–5 dan 7–8 deterministik (input sama → output sama).
Tahap 6 adalah satu-satunya langkah non-deterministik, dan sengaja dipersempit
ke konteks kecil (15 kandidat × ~150 kata).

---

## Instalasi

Tidak ada dependency Python eksternal. Hanya butuh:

```bash
ffmpeg -version      # >= 6.0
python3 --version    # >= 3.11 (diuji di 3.14)
```

Analisis audio memakai filter ffmpeg (`ebur128`, `astats`) — bukan numpy/librosa —
supaya tool ini portable dan tidak terikat wheel yang belum tersedia.

Transkripsi butuh salah satu API key (isi di `.env`):

```bash
cp .env.example .env
# GROQ_API_KEY=...        # ← rekomendasi: gratis ~8 jam audio/hari
# DEEPGRAM_API_KEY=...    # $200 kredit, diarization
# OPENAI_API_KEY=...
```

**Rekomendasi gratis: Groq.** `whisper-large-v3-turbo`, kuota 28.800 audio-detik/hari
(8 jam), WER Bahasa Indonesia ~7%, tanpa RAM lokal. Biaya $0.
Perbandingan lengkap + alasan opsi lain didiskualifikasi: [`docs/TRANSCRIPTION.md`](docs/TRANSCRIPTION.md).

Atau jalur lokal (butuh venv Python 3.11–3.12 karena `ctranslate2` belum ada wheel untuk 3.14):

```bash
pip install faster-whisper
export CLIP_ENGINE=local
export CLIP_WHISPER_MODEL=large-v3-turbo   # jangan di bawah "small" untuk Bahasa Indonesia
```

---

## Pemakaian

```bash
# 1. Tahap deterministik: ingest → transkrip → atom → kandidat → fitur
python3 -m scripts.cli run input.mp4 --out work/demo

# 2. Agent menilai 15 kandidat (langkah ini dilakukan agent, bukan CLI)
python3 -m scripts.cli score-prompt work/demo > work/demo/score_prompt.md
#    → agent membaca prompt, menulis work/demo/selection.json

# 3. Validasi skor + hitung komposit
python3 -m scripts.cli score-validate work/demo

# 4. Bangun EDL dan render
python3 -m scripts.cli build-edl work/demo
python3 -m scripts.cli render work/demo --top 3
```

Hasil ada di `work/demo/out/clip_01.mp4` dst.

### Subcommand

| Command | Fungsi |
|---|---|
| `ingest` | normalisasi video + ekstrak audio |
| `transcribe` | ASR word-level → `transcript.json` |
| `segment` | → `atoms.json` |
| `candidates` | → `candidates.json` (top 15) |
| `features` | → fitur deterministik per kandidat |
| `score-prompt` | cetak prompt penilaian untuk agent |
| `score-validate` | validasi `selection.json` + hitung skor komposit |
| `build-edl` | → `edl.json` |
| `render` | → `out/clip_NN.mp4` |
| `run` | jalankan 1–5 sekaligus |

---

## Struktur

```
clipping-skill/
├── SKILL.md                  # definisi skill untuk agent
├── docs/
│   ├── SCOPE.md              # batas kerja v0 / v1 / out-of-scope
│   ├── DECISIONS.md          # ADR: alasan keputusan arsitektur
│   └── PIPELINE.md           # detail tiap tahap + rumus skor
├── schema/
│   ├── transcript.schema.json
│   ├── selection.schema.json
│   └── edl.schema.json
├── scripts/
│   ├── cli.py                # entry point
│   ├── ingest.py
│   ├── transcribe.py
│   ├── segment.py
│   ├── candidates.py
│   ├── features.py
│   ├── score.py
│   ├── edl.py
│   ├── captions.py
│   ├── render.py
│   └── lib/
│       ├── text.py           # tokenisasi + marker Bahasa Indonesia
│       ├── audio.py          # probe + loudness + RMS via ffmpeg
│       └── jsonio.py
├── templates/
│   └── caption_default.ass.tmpl
├── fixtures/                 # data sintetis untuk tes offline
└── tests/
```

---

## Tes

```bash
make test        # pytest (atau unittest bila pytest tidak ada)
make lint        # py_compile semua modul
```

Tes berjalan **offline** memakai fixture sintetis — tidak butuh video, tidak butuh API key.

---

## Batas yang diketahui (v0)

- Reframe masih **center crop**. Face tracking belum ada (butuh `opencv` + `mediapipe`).
- Satu klip = satu segmen kontinu. Multi-cut per klip sudah ada di schema tapi belum dirender.
- Motion graphics masih caption kinetic. Template Remotion belum ada.
- Skor belum terkalibrasi ke data retention nyata (belum ada user).
- Tidak ada publish API / feedback loop.

Semua ini tercatat di `docs/SCOPE.md` dengan fase masing-masing.
