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

---

## Matte orang (Langkah 1b)

Spike untuk `docs/MOTION-TIER2-PLAN.md` Langkah 1b: apakah ada model segmentasi yang cukup
cepat, ringan, dan bersih di tepi untuk menaruh teks/objek **di belakang** pembicara.
Gate, definisi metrik, dan alasan tiap ambang ada di rencana; ambangnya dikunci sebelum
mengukur. Kode: [`matte_bench.py`](matte_bench.py) (runner), [`matte_metrics.py`](matte_metrics.py)
(metrik), [`matte_gate.py`](matte_gate.py) (vonis). Data mentah: [`matte.json`](matte.json).

### Unduh model

Butuh `opencv-python-headless` (opsional, sama dengan langkah `faces`). Model disimpan di
`models/` (di-gitignore).

```bash
python3 -m benchmarks.matte_bench --download all
```

| Model | Berkas | Ukuran | sha256 |
|---|---|---|---|
| pphumanseg (opencv_zoo, Apache-2.0) | `human_segmentation_pphumanseg_2023mar.onnx` | 6.163.938 B | `552d8a984054e59b5d773d24b9b12022b22046ceb2bbc4c9aaeaceb36a9ddf24` |
| modnet (HF `Xenova/modnet`, tag Apache-2.0) | `modnet.onnx` | 25.888.640 B | `07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9` |
| yunet (hanya untuk metrik `face_in_matte`) | `face_detection_yunet.onnx` | 232.589 B | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |

### Menjalankan

```bash
python3 -m benchmarks.matte_bench --video <sumber> --model-kind modnet \
    --start 120 --seconds 6 --crop-x 0.52 --runs 3
python3 -m benchmarks.matte_gate benchmarks/matte.json
```

Tiap run berjalan di proses sendiri (`ru_maxrss` hanya naik sepanjang umur proses). Run
pertama membuat `matte_preview/<id>.mp4` (teks "EDIT" di belakang orang) dan `.png`. Tonton,
lalu isi keputusan manusia di `matte.json`: `"reviews": {"modnet@0321-ilc": true}`.

### Hasil terukur (2026-11-02) — **Apple M1, BUKAN mesin target**

Mesin uji: Apple M1 (8 core), OpenCV 5.0.0, ffmpeg 9.0.2, `cv2.dnn` CPU. Target gate adalah
i5-7300U, jadi **kolom fps dan RSS di bawah tidak sah sebagai vonis kecepatan**; hanya kualitas
yang tidak bergantung CPU. 3 run per baris, jendela 6 s, 15 mask/detik, 540×960,
penghalusan 0,6. Kualitas identik di tiga run (pipeline deterministik); yang berubah hanya waktu.

| Model | Sumber | fps e2e | RSS MB | `face_in_matte` | flicker p50 / p95 px | geser total p50 / p95 (diagnostik) | cut |
|---|---|---|---|---|---|---|---|
| pphumanseg | wawancara ILC 16:9 → 9:16 | 60–65 | 300–326 | **0,70** | **0,56** / **2,40** | 4,17 / 13,2 | 1 |
| pphumanseg | vertikal, orang menari | 70–74 | 240–278 | **0,00** | **1,05** / **2,54** | 5,53 / 11,3 | 0 |
| modnet | wawancara ILC 16:9 → 9:16 | 8,1–8,6 | 491–520 | 1,00 | 0,17 / **4,91** | 2,45 / 13,6 | 1 |
| modnet | vertikal, orang menari | 7,8–8,2 | 444–478 | 1,00 | **0,89** / **2,77** | 5,66 / 12,1 | 0 |

Tebal = melanggar ambang (`face_in_matte` ≥ 0,95; flicker p50 ≤ 0,5, p95 ≤ 1,5). `area_ok_ratio`
= 1,00 di semua run.

**Vonis gate: `NO_GO` untuk kedua model** pada protokol yang dikunci. `human_ok` belum diisi
(hanya manusia yang boleh).

### Temuan

- **pphumanseg gugur dengan jelas.** Probabilitas orang di wajah rata-rata ≈ 0,45 (min 0,27),
  jatuh tepat di bawah 0,5, jadi wajah berlubang (cakupan elips 0,41–0,57 pada video_1).
  Masukan 192×192 dibentangkan ke 540×960; tepinya bergumpal dan "D" pada teks tembus ke wajah.
- **MODNet bersih secara visual** (sorban, kacamata, rambut, jari terpotong rapi; huruf
  tersembunyi di balik kepala) dan lolos `face_in_matte` 1,00 di kedua sumber. Ia gagal di
  flicker: p95 4,91 px pada ILC, dan p50 0,89 px pada video menari.
- **Flicker MODNet terkonsentrasi dan dipengaruhi penghalusan.** Pada ILC puncaknya menumpuk di
  frame 72–77 (tangan dan mikrofon bergerak). Dengan bobot frame baru 0,3 (bukan 0,6) p50 turun
  0,17 → 0,07 dan p95 4,91 → 1,00. Itu **pengamatan tunggal pada satu sumber**, bukan vonis:
  konfigurasi ini tidak dijalankan pada video menari, dan harga penghalusan lebih kuat (mask
  tertinggal di tepi benda yang bergerak) belum diukur. Mengubah konfigurasi lalu mengulang
  sampai lolos adalah penyetelan setelah melihat hasil; bila diambil, harus dideklarasikan
  sebagai konfigurasi baru di rencana **sebelum** dijalankan.
- **Kecepatan MODNet di M1 ≈ 8 fps** dengan `cv2.dnn` CPU, di dekat ambang `GO` 7,5. Mesin
  target 2 core / 4 thread hampir pasti lebih lambat; tidak ada angka untuk itu sebelum dijalankan di sana.
- **Dua cacat metrik ditemukan oleh dry-run pertama** (cakupan pada kotak wajah, dan cut shot
  yang membuat mask "hantu"), diperbaiki dengan tes; lihat rencana, "Tiga koreksi definisi".

### Putaran 2 — penghalusan 0,3 (2026-11-02, Apple M1)

Dideklarasikan di rencana sebelum dijalankan. MODNet saja, dua sumber, 3 run, ditambah kontrol 0,6
dengan metrik `lag` yang sama. Berkas: [`matte_s06_control.json`](matte_s06_control.json),
[`matte_s03.json`](matte_s03.json).

| Bobot | Sumber | flicker p50 / p95 | lag p50 / p95 | `face_in_matte` |
|---|---|---|---|---|
| 0,6 (kontrol) | ILC | 0,17 / 4,91 | 0,81 / 2,14 | 1,00 |
| 0,6 (kontrol) | video menari | 0,89 / 2,77 | 0,89 / 1,20 | 1,00 |
| 0,3 | ILC | 0,07 / 1,00 | **2,49 / 10,11** | 1,00 |
| 0,3 | video menari | **0,55 / 1,60** | **5,11 / 8,95** | 1,00 |

Ambang: flicker p50 ≤ 0,5 dan p95 ≤ 1,5; lag p50 ≤ 1,0 dan p95 ≤ 2,5. **Hipotesis ditolak:** lag
2,5–5× di atas batas, dan flicker video menari masih gagal tipis. Vonis: MODNet `NO_GO` final;
matte dibekukan (D-012). Penghalusan lebih kuat menukar flicker dengan kelambanan mask.
