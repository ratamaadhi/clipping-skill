# TRANSCRIPTION — riset jalur transkripsi gratis

Dokumen ini mencatat hasil riset untuk pertanyaan: **jalur transkripsi mana yang
gratis, hemat RAM, hemat biaya, tapi tetap memberi word-level timestamp untuk
Bahasa Indonesia?**

Semua angka di bawah punya sumber, tapi free tier berubah kapan saja — verifikasi
ulang di console provider sebelum mengandalkan jangka panjang.

---

## Syarat yang tidak bisa ditawar

**Word-level timestamp wajib.** Caption kinetic butuh timing per kata. Ini langsung
mendiskualifikasi beberapa opsi yang sebenarnya paling murah:

| Opsi | Kenapa gugur |
|---|---|
| **Gemini API** (free tier besar) | Tidak mengembalikan word-level timestamp |
| **Mistral Voxtral** | Indonesia tidak ada di daftar bahasa; timestamp hanya di model tertentu dan tidak bisa digabung dengan parameter `language` |
| **Vosk** | Tidak ada model Bahasa Indonesia di daftar model resmi alphacephei |
| **Moonshine / Parakeet** | Inggris-only |

---

## Peringkat untuk kasus ini

### 1. Groq — pilihan utama ✅

| Item | Nilai |
|---|---|
| Model | `whisper-large-v3-turbo` |
| Biaya | **$0** (free tier) |
| Kuota gratis | 7.200 audio-detik/jam + **28.800 audio-detik/hari = 8 jam/hari** |
| Rate limit | 20 RPM, 2.000 RPD |
| Upload max (free) | 25 MB |
| Kalau bayar | $0.04/jam |
| RAM lokal | **0 MB** (cloud) |
| WER Indonesia | ~6,98% (rata-rata FLEURS/MLS/CommonVoice) |
| Word timestamp | ✅ |

**240 jam audio/bulan gratis.** Kalau dibayar, itu setara ~$9,6/bulan.
Untuk pemakaian 5–20 video/minggu, kuota ini praktis tidak akan habis.

Catatan penting:
- Limit berlaku **per organisasi**, bukan per API key. Bikin banyak key tidak membantu.
- Kuota per jam (7.200 detik) berarti video 2 jam menghabiskan seluruh budget satu jam.
  Ini alasan tambahan untuk chunking.
- **Jangan** bikin banyak akun untuk menembus limit — itu pelanggaran ToS.

### 2. Deepgram — fallback cloud terbaik

| Item | Nilai |
|---|---|
| Model | `nova-3`, bahasa Indonesia didukung |
| Kredit gratis | **$200 sekali** (bukan bulanan) |
| Harga batch | ~$0.26/jam |
| Setara | ~770 jam — **tapi** kredit untuk bahasa non-Inggris bisa lebih kecil |
| Kelebihan | **diarization** (siapa bicara) — penting untuk wawancara/podcast |

### 3. Lokal — offline, tanpa kuota

| Model | Disk | RAM | Catatan |
|---|---|---|---|
| whisper.cpp tiny | 75 MB | ~273 MB | terlalu kecil untuk Indonesia |
| whisper.cpp base | 142 MB | ~388 MB | masih kurang |
| whisper.cpp small q5_1 | 182 MB | **488 MB** (terukur) | batas bawah yang layak |
| **large-v3-turbo q5_0** | **548 MB** | **816 MB** (terukur) | akurasi terbaik |

**Jangan pilih `small` kalau RAM masih cukup.** `large-v3-turbo` terkuantisasi q5_0
makan RAM ~1,7× `small` tapi akurasinya jauh lebih baik untuk Bahasa Indonesia.
Tapi lihat bagian pengukuran di bawah — di CPU 2-core, `large-v3-turbo` sangat lambat.

---

## Pengukuran nyata di mesin ini

Server: **Intel i5-7300U** (2 core / 4 thread, 2,6 GHz, 2017), **7,1 GB RAM**
(1,6–1,9 GB tersedia), swap 4 GB **sudah 97% terpakai**, tanpa GPU.

Diukur dengan `whisper.cpp 1.9.5`, `-t 4`, audio 16 kHz mono, `-l id`:

| Model | Peak RSS | Waktu untuk audio 130 s | Real-time factor |
|---|---|---|---|
| **large-v3-turbo q5_0** | **816 MB** | **4 menit 40 detik** | **0,46×** (2,15× lebih lambat dari realtime) |
| small q5_1 | 488 MB | 1 menit 15 detik | 1,74× |

Pada audio 650 detik, `large-v3-turbo` naik ke **863 MB** (masih tumbuh saat dihentikan).
Kenaikan berasal dari PCM float32 + mel spectrogram yang di-load utuh.

**Ekstrapolasi `large-v3-turbo`:**

| Durasi video | Perkiraan waktu proses | Perkiraan RAM |
|---|---|---|
| 10 menit | ~21 menit | ~850 MB |
| 30 menit | ~64 menit | ~950 MB |
| 1 jam | ~2,2 jam | ~1,1 GB |
| 2 jam | ~4,4 jam | **~1,5 GB → tidak muat** |

Encode menyumbang **97% waktu** (54,6 detik per jendela 30 detik). Decoder turbo
memang sudah dipangkas, tapi encoder-nya tetap seukuran `large-v3` — jadi `turbo`
tidak banyak menolong di CPU.

**Kesimpulan: secara RAM bisa, secara praktis tidak.** Untuk video >10 menit,
mesin ini butuh waktu lebih lama daripada durasi videonya sendiri. Pakai Groq.

### Catatan kualitas

Saat diuji dengan audio sine tone (bukan suara), `large-v3-turbo` mengeluarkan
"Terima kasih." berulang-ulang — **demonstrasi langsung halusinasi Whisper di audio
non-ucapan**. Ini persis yang ditangani `_bad_ranges()` di `scripts/transcribe.py`.

### 4. Kredit sekali pakai (untuk evaluasi, bukan produksi)

| Provider | Gratis | Catatan |
|---|---|---|
| AssemblyAI | $50 kredit (~185–330 jam tergantung model) | word timestamp ada, ID perlu diverifikasi |
| Gladia | 10 jam/bulan, refresh | diarization termasuk |
| Speechmatics | 8 jam/bulan (ada sumber bilang 40 jam — konflik) | prioritas rendah |

---

## Yang berubah di kode karena riset ini

### Bug kritis: upload WAV

Kode v0 mengirim **WAV 16 kHz mono**. Itu 32 KB/detik, jadi batas 25 MB Groq
hanya cukup **13 menit** — podcast biasa langsung gagal.

| Format | Durasi per 25 MB |
|---|---|
| WAV 16k mono (lama) | **13,1 menit** ❌ |
| MP3 32 kbps (sekarang) | **104,9 menit** ✅ |
| Opus 24 kbps | 139,8 menit |

Sekarang `transcribe.encode_upload()` memotong dari WAV lalu encode ke MP3 32 kbps.
8× lebih banyak audio per upload.

### Chunking

Walau file muat, tetap di-chunk (default 600 detik):

- satu request gagal tidak membuang seluruh transkrip
- loop halusinasi Whisper menjalar di audio sangat panjang
- kuota per jam lebih baik dipakai bertahap

**Aturan anti-drift:**

1. Potong dari **WAV**, jangan dari mp3/aac — encoder delay memberi drift puluhan ms
2. Offset chunk = posisi sampel / 16000, eksak
3. Batas chunk digeser ke tengah jeda terdekat (`silencedetect`, cari dalam ±60 detik)
4. Overlap 5 detik sebagai jaring pengaman
5. **Kata diambil dari chunk yang memiliki titik tengahnya** — cut selalu ≥2,5 detik
   dari tepi, jadi kata yang terpotong tidak pernah terpilih dari dua sisi
6. Dedupe kata berurutan identik dengan |Δstart| < 0,3 detik
7. Paksa monoton: `end` tidak boleh melewati `start` kata berikutnya

### Filter halusinasi

Whisper mengarang teks di musik atau keheningan ("Terima kasih telah menonton",
"Subtitle by…", kata berulang). Filter yang dipasang:

- `no_speech_prob > 0.60` **dan** `avg_logprob < -1.0`
- `compression_ratio > 2.4`
- blacklist frasa template

### Glosarium Bahasa Indonesia

Parameter `prompt` (maks 224 token) diisi daftar istilah tech + ejaan partikel
(`gak`, `nggak`, `banget`, `udah`, `bikin`, `gimana`, `kayak`). Tujuannya
konsistensi ejaan, bukan akurasi. Prompt dari transkrip sebelumnya sengaja **tidak**
dipakai karena menyebarkan kesalahan.

### Retry

429/5xx di-retry sampai 5 kali dengan menghormati header `retry-after`.
`User-Agent` diset eksplisit — default `urllib` kadang diblok Cloudflare (403).

---

## Risiko yang sering diremehkan

| Risiko | Mitigasi |
|---|---|
| **Privasi klien** | Groq menyimpan data audio transcription hingga 30 hari untuk monitoring. Aktifkan Zero Data Retention di Data Controls, atau pakai jalur lokal untuk materi NDA. |
| **Halusinasi** | Filter di atas + review manusia pada klip terpilih |
| **Code-switching ID/EN** | Glosarium + peta replace pasca-proses. Whisper tidak konsisten antara "gak/nggak/enggak". |
| **WER 6,98% itu optimistis** | Itu bacaan bersih (FLEURS/CommonVoice). Podcast dengan slang dan bicara bertumpuk jauh lebih buruk. Jangan jadikan janji ke klien. |
| **Free tier berubah** | Arsitektur sudah multi-provider (`groq`/`deepgram`/`local`). Jangan terikat satu vendor. |
| **Timestamp tidak sempurna** | Error puluhan–ratusan ms itu normal. Pipeline sudah memaksa monoton dan durasi minimum. |

---

## Rekomendasi operasional

```
Harian, gratis     → Groq free tier, chunk 10 menit
Klien NDA          → whisper.cpp large-v3-turbo q5_0 (offline)
Butuh diarization  → Deepgram nova-3
Klip final 30-60s  → opsional: transkrip ulang dengan model lebih mahal
                     demi timing presisi (kuota kecil pun cukup)
```

**Jangan** mengandalkan satu provider. Interface di `scripts/transcribe.py` sudah
menghasilkan bentuk `{w, start, end}` yang sama untuk semua engine, jadi menambah
provider baru hanya perlu satu fungsi.

---

## Sumber

- Groq rate limits — https://console.groq.com/docs/rate-limits
- Groq speech-to-text — https://console.groq.com/docs/speech-to-text
- Groq data retention — https://console.groq.com/docs/your-data
- WER Indonesia (TheWhisper benchmark) — https://huggingface.co/TheStageAI/thewhisper-large-v3-turbo
- whisper.cpp memori — https://github.com/ggml-org/whisper.cpp
- Deepgram Nova-3 Indonesian — https://deepgram.com/learn/deepgram-expands-nova-3-with-italian-turkish-norwegian-and-indonesian-support
- Vosk model list — https://alphacephei.com/vosk/models
- Mistral file transcription — https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-files
