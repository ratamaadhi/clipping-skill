# benchmarks

Data pengukuran performa ASR lokal. Tujuannya: keputusan "model mana yang layak
di mesin ini" bisa dijawab dengan angka, bukan perkiraan.

**Data mentah:** [`results.json`](results.json) — mesin, model, waktu, RAM, RTF.
**Runner:** [`bench.py`](bench.py) — satu perintah untuk mengukur ulang.

---

## Hasil terukur

Mesin uji: **Intel i5-7300U** (2 core / 4 thread, 2,6 GHz), RAM 7,1 GiB
(1,6–1,9 GiB tersedia), swap 4 GiB **97% terpakai**, tanpa GPU.
whisper.cpp **1.9.5**, `-t 4`, `-l id`, audio 130 detik 16 kHz mono.

| Model | Disk | Peak RSS | Waktu | RTF | Encode / 30 s |
|---|---|---|---|---|---|
| `ggml-large-v3-turbo-q5_0` | 547 MB | **816 MB** | **315,7 s** | **0,41×** | 62,0 s |
| `ggml-small-q5_1` | 181 MB | 487 MB | 89,8 s | 1,45× | 10,4 s |

**RTF** (real-time factor) = durasi audio ÷ waktu proses.
RTF < 1 berarti lebih lambat daripada realtime. 0,41× artinya audio 1 jam butuh
~2,4 jam proses.

### Variasi antar run

Dua run pertama pada sesi yang sama memberi angka berbeda:

| Model | Run 1 | Run 2 (results.json) |
|---|---|---|
| large-v3-turbo | 280,0 s (0,46×) | 315,7 s (0,41×) |
| small | 74,9 s (1,74×) | 89,8 s (1,45×) |

Selisih ~13–20%, khas CPU laptop tanpa pendinginan aktif — thermal throttling.
**Peak RSS stabil** (816 MB dan 487 MB di kedua run), jadi angka memori bisa dipercaya;
angka waktu sebaiknya dibaca sebagai rentang, bukan satu nilai.

### Ekstrapolasi large-v3-turbo

Linear terhadap durasi audio, karena encode mendominasi (97% waktu):

| Durasi video | Waktu proses | Perkiraan RAM |
|---|---|---|
| 10 menit | ~24 menit | ~850 MB |
| 30 menit | ~73 menit | ~950 MB |
| 1 jam | ~2,4 jam | ~1,1 GB |
| 2 jam | ~4,9 jam | **~1,5 GB → tidak muat** |

RAM naik karena whisper.cpp memuat seluruh audio sebagai PCM float32
(16 kHz × 4 byte = 64 KB/detik) plus mel spectrogram, di samping bobot model.

---

## Cara mengukur ulang

### 1. Build whisper.cpp

```bash
# cmake tanpa sudo (kalau belum ada)
/usr/bin/python3 -m pip install --user --break-system-packages cmake
export PATH="$HOME/.local/bin:$PATH"

git clone --depth 1 https://github.com/ggml-org/whisper.cpp ~/tama-proj/whisper.cpp
cd ~/tama-proj/whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF
cmake --build build -j2 --target whisper-cli     # ~1m42s di mesin uji
```

### 2. Unduh model

```bash
mkdir -p ~/models && cd ~/models
curl -L -O https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
curl -L -O https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin
```

### 3. Siapkan audio uji

```bash
ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le ~/bench/a130.wav
```

### 4. Jalankan

```bash
export WHISPER_CLI=~/tama-proj/whisper.cpp/build/bin/whisper-cli

python3 benchmarks/bench.py \
  --model ~/models/ggml-large-v3-turbo-q5_0.bin \
  --audio ~/bench/a130.wav \
  --threads 4 --language id \
  --note "catatan bebas"
```

Hasil ditambahkan ke `benchmarks/results.json`. Pakai `--dry-run` untuk melihat
tanpa menulis.

---

## Cara membaca angka

| Field | Arti | Catatan |
|---|---|---|
| `peak_rss_mb` | RAM puncak proses | Dari `/usr/bin/time -v`; ini yang menentukan OOM |
| `rtf` | durasi audio ÷ waktu | <1 = lebih lambat dari realtime |
| `encode_ms_per_run` | waktu encoder per jendela 30 s | Biasanya 95%+ total waktu |
| `cpu_percent` | utilisasi CPU | 330% di mesin 4-thread = semua terpakai |
| `load_ms` | waktu muat model | Sekali per proses |

**Kenapa `encode` penting:** Whisper memproses audio dalam jendela 30 detik, dan
encoder-nya berjalan di setiap jendela. Model `turbo` hanya memangkas *decoder*
jadi 4 layer — encoder tetap seukuran `large-v3`. Jadi di CPU, `turbo` tidak
secepat namanya. Ini terlihat jelas di `encode_ms_per_run`: 62 s untuk turbo
vs 10,4 s untuk small, padahal parameter modelnya cuma 3× lebih besar.

---

## Kesimpulan yang sudah diambil dari data ini

- **Produksi harian:** Groq free tier (0 MB RAM, hitungan detik, gratis 8 jam/hari).
  Lihat [`../docs/TRANSCRIPTION.md`](../docs/TRANSCRIPTION.md).
- **Offline di mesin ini:** hanya layak untuk klip <10 menit, dan itu pun ~2,4×
  lebih lambat dari realtime.
- **Kalau harus offline untuk video panjang:** pakai `small q5_1` (1,45× realtime,
  487 MB) dan terima penurunan akurasi Bahasa Indonesia — atau jalankan di mesin lain.

Model `.bin` **tidak** disimpan di repo (547 MB + 181 MB). Unduh ulang dengan
perintah di atas kalau perlu.
