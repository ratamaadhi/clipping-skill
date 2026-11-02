# MOTION TIER-2 — rencana implementasi

> **Untuk pelaksana:** kerjakan per langkah (bagian 5), tes dulu baru kode. Disarankan
> `superpowers:subagent-driven-development` atau `superpowers:executing-plans`.
> Dokumen ini hanya rencana; belum ada kode yang diubah.

**Tujuan.** Kualitas visual setara reel populer (kinetic typography per kata, spring/easing,
elemen grafis masuk-keluar, transisi non-jump-cut, layout sadar wajah) di mesin i5-7300U
2 core, RAM tersedia 1,6–1,9 GiB, swap 97% penuh, tanpa GPU.

**Arsitektur.** *ASS-first, Remotion sparse-opsional.* libass tetap pemilik semua teks
caption (kini per kata, dengan spring yang disampel). Layout dihitung Python sekali saat
EDL dibangun. Remotion hanya merender overlay alpha untuk jendela waktu pendek yang
tidak bisa dilakukan ASS, dan hanya bila lolos gate pengukuran di mesin ini.

**Tech stack.** Python stdlib, ffmpeg + libass (sudah ada). Node 22 + Remotion 4.x
(opsional, folder `remotion/` terpisah). `pyproject.toml` tetap `dependencies = []`.

**Penanda angka.** **[T]** terukur (dari `docs/` repo) · **[P]** perkiraan saya, belum diukur
di mesin ini (saat menulis ini saya tidak punya akses shell) · **[?]** belum diverifikasi.
Semua **[P]** untuk Remotion diganti angka terukur oleh Langkah 1.

---

## 0. Keputusan dalam 9 baris

1. **Remotion merender frame penuh (opsi a): ditolak.** Perkiraan 130–320 s per klip 20 s
   (9–21× baseline) dan 1,2–1,8 GB RAM; menggandakan renderer; merusak D-001.
2. **Pilihan: (c).** Teks, bentuk datar, dan transisi dikerjakan ASS + ffmpeg (tanpa Node).
   Remotion (opsi b) dipersempit jadi overlay alpha **sparse** untuk efek yang ASS tidak
   punya (gradien, bayangan lembut, ikon, angka count-up).
3. **Pemilik caption: libass, satu-satunya.** Remotion tidak pernah menerima `captions[]`.
4. **Pemilik layout: `scripts/layout.py`** (Python, deterministik), hasilnya disimpan di EDL.
   Renderer dan React hanya mengeksekusi koordinat.
5. **Biaya render klip 20 s [P]:** tier-1 10–20 s → T2a (ASS) 11–23 s → T2b sparse
   35–80 s → overlay seluruh klip 90–230 s.
6. **Remotion dibuka hanya jika spike Langkah 1 lolos gate** (RSS pohon proses ≤ 1,0 GB,
   ≥ 2,5 fps pada 1080×1920 alpha, swap tidak bergerak). Jika gagal, Langkah 1–5 tetap
   memberi 5 dari 5 target visual tanpa Chromium.
7. **EDL hanya ditambah, tidak diubah.** `version` tetap `"0.1.0"`; tes lama mengunci ini.
8. **Lisensi Remotion harus dicek manusia** sebelum Langkah 6 (bagian 8).
9. **Person matte diukur dulu (Langkah 1b), baru dipakai.** Efek "teks/objek di belakang
   pembicara" (cover story, dinding kartu, outline siluet, latar pengganti) tidak bisa dibuat
   ASS maupun ffmpeg tanpa tahu piksel mana milik orang. Rencana awal hanya punya kotak wajah.
   Tidak ada kode produk matte sebelum spike memberi vonis di mesin target.

---

## 1. Temuan dari kode yang mengubah desain

| # | Temuan | Lokasi | Akibat |
|---|---|---|---|
| 1 | Timing per kata **dibuang** saat EDL dibentuk; `ph["words"]` hanya dipakai untuk `text` dan emphasis | `scripts/edl.py:167-186` | Kinetic per kata butuh field `captions[].words` |
| 2 | Schema **sudah ketinggalan**: `punch`, `progress`, `reframe.bias_track` dipakai kode tetapi tidak ada di schema yang `additionalProperties:false`; tidak ada tes yang memvalidasi schema | `edl.py:225-227`, `faces.py:320`, `schema/edl.schema.json:47,77,90` | Perlu tes drift schema sebelum menambah field |
| 3 | `faces.sample()` membuang tinggi kotak wajah; `analyze_edl` hanya menyimpan `bias_x` | `faces.py:129-137, 318-320` | Layout sadar wajah belum punya data |
| 4 | Panel VS tier-1 terpasang tetap di y=470–574 tanpa tahu posisi wajah | `motion.py:309-322` | Pada sumber 16:9 wajah pembicara biasanya di sepertiga atas–tengah frame [P]; panel kemungkinan menutup mata/dahi. Layout memperbaikinya |
| 5 | `-r 30` ditulis keras; `render_clip` sudah ±160 baris | `render.py:267-268` | Preview butuh parameter; logika tier-2 masuk modul baru, bukan menambah `render_clip` |
| 6 | Satu-satunya font sistem: DejaVu | `/usr/share/fonts/truetype/dejavu/` | Gaya reel butuh font tebal OFL yang dibundel + `fontsdir` |
| 7 | Resolusi waktu ASS = 10 ms (`{s:05.2f}`) | `captions.py:237-242` | Kuantisasi ≤ 10 ms < 1 frame (33 ms): aman untuk timing kata |
| 8 | Chromium = wrapper `~/.local/bin/chromium` → `/home/tama/.hermes/tools/chromium-1208/chrome-linux64/chrome --no-sandbox` | `~/.local/bin/chromium` | Remotion perlu `browserExecutable`; kecocokan versi CDP **[?]** |
| 9 | `test_version_and_structure` mengunci `version == "0.1.0"`; `test_reframe_mode` mengunci `mode == "center"` | `tests/test_edl.py:27-31,150-152` | Tidak boleh bump versi; field baru harus aditif dan muncul hanya bila diminta |
| 10 | `MAX_CAP_DUR=2.0` < `MAX_PHRASE_DUR=2.2`: caption bisa berakhir sebelum kata terakhir diucapkan | `edl.py:26`, `captions.py:17` | Jendela tampil kinetic ≠ jendela caption; aturan di Langkah 2 |
| 11 | D-003 menulis Remotion "≈1–3× realtime" tanpa pengukuran | `docs/DECISIONS.md` D-003 | Perkiraan saya untuk mesin ini lebih tinggi (3,75–10× realtime); Langkah 1 menentukan |

---

## 2. Arsitektur (jawaban pertanyaan 1)

### Pilihan: (c) ASS-first + overlay Remotion sparse opsional

```
edl.json (output timeline, D-001)
  │  build-edl --motion 2  → captions[].words, caption_style, transitions, overlays[]
  │  faces                 → reframe.face_track  (opsional, perlu OpenCV)
  │  layout                → layout.caption, overlays[].rect   (Python murni)
  ▼
render.py  (hanya mengeksekusi)
  ├─ ffmpeg: trim/concat → crop/scale → zoompan → track bar → fill bar
  │          → drawbox/flash (transisi) → [overlay PNG Remotion, jendela pendek]
  │          → subtitles (ASS kinetic)  ← SELALU terakhir
  └─ audio: loudnorm + SFX (tidak berubah)
remotion/ (opsional) ← props JSON saja → PNG RGBA per overlay → cache by hash
```

### Kenapa bukan (a) — Remotion frame penuh
- Menulis ulang seluruh rantai tier-1 di React (crop bergerak per shot, zoompan, trim/concat
  multi-segment, progress bar, loudnorm). Itu renderer kedua; D-001 melarang logika
  render yang tersebar.
- Skala zoom lewat CSS tidak sama dengan `scale=…:flags=lanczos`; kualitas turun.
- Determinisme (hash output identik, `docs/PIPELINE.md` §8) tidak terjamin.
- Biaya **[P]**: 130–320 s per klip 20 s dan RAM 1,2–1,8 GB, di atas RAM tersedia 1,6 GB
  terendah. Lihat bagian 3.

### Kenapa bukan (b) murni — overlay Remotion seluruh klip
- 600 frame × Chromium untuk teks yang libass gambar dengan biaya ≈ 0 **[T: tier-1 caption "~0"]**.
- Kalau Remotion juga menggarap caption: dua sumber kebenaran (teks, timing, emphasis,
  posisi), dua mesin metrik font (Chromium vs libass) sehingga layout wajah dihitung dua kali.
- Seluruh klip: perkiraan 90–230 s per klip (6–15× baseline).

### Kenapa (c) memenuhi lima target tanpa Chromium

| Target | Jalur | Catatan |
|---|---|---|
| Kinetic per kata | ASS: satu event per kata, posisi dari metrik font nyata | Langkah 3 |
| Spring/easing | Spring teredam dihitung Python, disampel per frame → rantai `\t(...)` | Skala/alpha/rotasi/blur. Translasi lewat event per-frame (≤ 10 event/kata) karena `\t` tidak bisa menganimasikan `\pos` |
| Elemen masuk-keluar | ASS vector drawing (`\p1`) + `\clip` wipe + `\fad` | Bentuk datar, garis, highlight bar |
| Transisi bukan jump cut | ffmpeg, **durasi dipertahankan**: flash, whip-zoom | Langkah 5 |
| Layout sadar wajah | `layout.py` + `reframe.face_track` | Langkah 4 |

Yang **tidak** terjangkau ASS dan karena itu butuh Remotion: gradien, bayangan lembut/blur
latar, kartu bersudut membulat dengan efek kaca, ikon/emoji berwarna (font sistem tidak
punya emoji), grafik/angka count-up. Itulah isi Langkah 6, dan hanya itu.

### Siapa memiliki apa setelah tier-2

| Data / keputusan | Pemilik (ditulis oleh) | Konsumen |
|---|---|---|
| Teks, timing, emphasis caption | `edl.py` → `captions[]` + `words` | `captions.py` / `kinetic.py` → libass |
| Posisi caption | `layout.py` → `layout.caption` | `kinetic.py` |
| Teks callout/stat/lower-third | `edl.py` → `overlays[].props` | Remotion |
| Posisi overlay | `layout.py` → `overlays[].rect` | ffmpeg drawbox / Remotion |
| Waktu | EDL output timeline | semua |

Aturan penegak (ada tesnya): **JSON yang dikirim ke Node tidak boleh berisi kunci `captions`**;
React tidak membaca EDL, tidak punya state selain `frame` dan props.

---

## 3. Kelayakan mesin (jawaban pertanyaan 2)

### Jawaban pendek
- Remotion frame penuh: **tidak realistis** di mesin ini.
- Remotion overlay seluruh klip: jalan, tetapi **bukan default** (6–15× baseline).
- Remotion overlay sparse (≤ 150 frame/klip): **borderline**, harus dibuktikan Langkah 1.
- ASS kinetic + shape + transisi: **realistis** (≈ 1,1–1,2×).

### Model biaya (klip 20 s = 600 frame)
`t_total = t_base + t_overhead + N_frame / fps_efektif`

- `t_base` = 10–20 s (diberikan; tier-1 41 s → 17,21 s **[T]**).
- `fps_efektif` Chromium **[P]**: komponen per frame pada 1080×1920 RGBA ≈ raster 10–25 ms
  + encode PNG 50–120 ms + CDP/Remotion 30–60 ms = 90–205 ms → 5–11 fps per tab. Dua core,
  konkurensi ≤ 2, throttling termal 13–20% **[T: benchmarks/README.md]**, dan RAM yang memaksa
  konkurensi 1 menurunkannya ke **3–8 fps** (konservatif). Ini lebih lambat dari angka
  D-003 (1–3× realtime) karena CPU 2 core dan PNG alpha.
- `t_overhead` = 5–12 s **[P]** (browser hangat, dekode PNG di ffmpeg, komposit). Bundle
  webpack sekali per perubahan template: 30–60 s **[P]**, di-cache.

| Jalur | N frame Chromium | Waktu / klip 20 s | × baseline (15 s) | RAM puncak | Per video 5 klip |
|---|---|---|---|---|---|
| Tier-1 sekarang | 0 | 10–20 s **[T]** | 1× | 544–579 MB **[T]** | 1–2 menit |
| **T2a** ASS kinetic + shape + transisi | 0 | **11–23 s** [P] | ≈ 1,1–1,2× | ≈ 600 MB [P] | 1–2 menit |
| **T2b sparse** (5 s overlay) | 150 | **35–80 s** [P] | 2–5× | Chromium+Node 0,65–1,0 GB [P] | 3–7 menit |
| Overlay seluruh klip | 600 | 90–230 s [P] | 6–15× | idem | 8–19 menit |
| (a) frame penuh | 600 + dekode video | 130–320 s [P] | 9–21× | 1,2–1,8 GB [P] | 11–27 menit |

Rincian T2a (+6–16% di atas tier-1, **[P]**): event kata ≈ 10× lebih banyak dari sekarang
(libass hanya merender event aktif, ≤ 8 serentak) +3–8%, vector shape + `\blur` +2–5%,
`drawbox enable` untuk flash +1–3%, layout 0 (dihitung sekali saat EDL, < 1 s).
**Anggaran keras: ≤ 1,3× tier-1** diukur 3 kali, median (variasi antar-run 13–20% **[T]**).

### Anggaran memori (tersedia 1,6–1,9 GiB, swap penuh = tidak ada jaring pengaman)
- Chromium per tab pada 1080×1920 **[P]** 300–500 MB; pohon proses (browser + GPU + renderer
  + Node host) konkurensi 1 ≈ 0,65–1,0 GB, konkurensi 2 ≈ 0,9–1,4 GB.
- Aturan: **konkurensi 1**, dan **tidak pernah** Chromium bersamaan dengan ffmpeg
  (ffmpeg ≈ 580 MB **[T]**). Urutan: overlay dulu → proses Node keluar → baru ffmpeg.
- Watchdog (stdlib, `scripts/lib/procmem.py`): menjumlahkan RSS seluruh pohon proses dari
  `/proc` tiap 0,5 s dan membunuh pohon di **1,2 GB**. Jangan pakai `/usr/bin/time -v` untuk
  Chromium: ia melaporkan RSS **satu proses terbesar**, bukan jumlah pohon.

### Gate Langkah 1 (ditetapkan sebelum mengukur)
| Metrik | NO_GO bila | GO bila |
|---|---|---|
| RSS pohon, konkurensi 1 | > 1000 MB | ≤ 1000 MB |
| Aktivitas swap (`pswpin+pswpout`) | > 25.000 halaman (≈ 100 MB) | ≤ itu |
| `MemAvailable` minimum saat render | < 250 MB | ≥ 250 MB |
| Alpha PNG valid (color type 6, piksel sudut α=0) | tidak | ya |
| fps efektif 1080×1920, 150 frame | < 1,5 | ≥ 2,5 → `GO`; 1,5–2,5 → `GO_SPARSE` (maks 90 frame/klip) |

### Strategi pratinjau vs final
| | Pratinjau | Final |
|---|---|---|
| Output | 540×960 @ 15 fps, `-preset ultrafast -crf 30` | 1080×1920 @ 30 fps, `veryfast -crf 20` |
| ASS | PlayRes tetap 1080×1920; libass menskalakan otomatis | idem |
| Biaya klip 20 s | ≈ 3–6 s [P] (batas bawahnya dekode sumber 1080p, bukan piksel keluaran) | tabel di atas |
| Overlay Remotion | `remotion still` di 3–6 timestamp, `--scale=0.5`, ≈ 1–3 s/still setelah hangat [P]; atau komposisi 15 fps skala 0,5 ≈ 0,3× waktu final [P] | PNG penuh, 30 fps |
| Cache | tidak dipakai | per overlay, kunci `sha256(props + versi template + versi remotion)` |
| Nama file | `clip_NN.preview.mp4` (tidak pernah menimpa final) | `clip_NN.mp4` |

Final dijalankan berurutan, di latar belakang, tanpa aplikasi lain yang memakai RAM.
Yang ditulis ulang saat iterasi hanya overlay yang hash-nya berubah.

---

## 4. Integrasi EDL (jawaban pertanyaan 3)

### Field baru — semuanya opsional, semuanya aditif

```jsonc
{
  "version": "0.1.0",                 // TIDAK dibump (tes lama mengunci)
  "clips": [{
    "caption_style": "kinetic",       // "phrase" (default bila absen) | "kinetic"
    "captions": [{
      "start": 0.0, "end": 1.76, "text": "Pertama, pasti nenekmu bangga.", "src_start": 1209.204,
      "words": [{"w": "Pertama,", "start": 0.00, "end": 0.38}]   // timeline OUTPUT
    }],
    "reframe": {
      "mode": "track", "bias_track": [[0.0, -0.2]],               // sudah ada
      "face_track": [                                              // BARU, dari faces.py
        {"t": 0.0, "faces": [{"x": 212, "y": 310, "w": 240, "h": 300}]}   // px 1080×1920, sebelum punch, per shot
      ]
    },
    "layout": {                                                    // BARU, dari layout.py
      "version": 1,
      "caption": [{"t": 0.0, "an": 2, "y": 1400}]                  // satu entri per shot
    },
    "transitions": [{"seg": 1, "kind": "flash", "dur": 0.10}],     // BARU; kunci = indeks segmen, bukan detik
    "overlays": [                                                   // sudah ada; ditambah:
      {"type": "callout", "renderer": "remotion", "start": 2.0, "end": 5.0,
       "slot": "auto", "rect": {"x": 60, "y": 260, "w": 960, "h": 300},
       "props": {"text": "3 dari 5", "variant": "stat"}}
    ]
  }]
}
```

Alasan bentuknya:
- `words` bersarang di `captions[]` supaya satu sumber teks; tidak ada daftar paralel.
- `transitions` memakai indeks segmen karena `out_start` bisa dihitung ulang; detik akan basi.
- `overlays[].renderer` default `"ffmpeg"` (perilaku tier-1: panel VS lewat drawbox).
  Tidak ada daftar `stage` baru; satu daftar, satu basis waktu.
- Semua waktu = timeline output, sesuai kontrak. Konversi ke frame **sekali**,
  `round(t·fps)`, di titik paling akhir (aturan `docs/PIPELINE.md` §7).

### Menjaga 183 tes lama lulus dan pipeline inti tanpa Node

1. **Muncul hanya bila diminta.** `build-edl --motion 2` (default 1). Tanpa flag, `edl.json`
   **byte-identik** dengan sekarang — dijaga tes golden (Langkah 2) dan `cmp` manual.
2. **Tanpa mengubah tanda tangan lama.** `render._vf_chain`, `render_clip`, `edl.build`
   hanya mendapat argumen *keyword* baru berdefault lama; tes `FilterChainTest` yang
   memanggil posisional tetap valid.
3. **Logika baru di modul baru:** `kinetic.py`, `layout.py`, `transitions.py`, `shapes.py`,
   `overlay_remotion.py`, `lib/spring.py`, `lib/fontmetrics.py`, `lib/procmem.py`.
   `render.py` hanya memanggil mereka bila field ada.
4. **Node tidak pernah diimpor atau dipanggil** kecuali ada ≥ 1 overlay `renderer:"remotion"`
   **dan** `overlay_remotion.available()` (cek `shutil.which("node")`, `remotion/node_modules`,
   browser, hasil gate). Jika tidak: panel VS jatuh ke drawbox tier-1, overlay lain dilewati
   dengan satu baris peringatan di `report.md`; **tidak ada exception**.
5. **Dependensi terisolasi:** `remotion/package.json` sendiri; `pyproject.toml` tidak berubah;
   `.gitignore` += `remotion/node_modules/`, `remotion/.bundle/`, `work/**/overlays/`.
6. **Tes yang butuh ffmpeg/Node memakai `skipUnless`** (pola `tests/test_chunk.py:168`), jadi
   `make test` tetap offline dan tanpa Node. Target baru `make test-tier2` menjalankan semuanya.
7. **Schema diperbaiki dulu** (Langkah 2): tambah `punch`, `progress`, `bias_track`, dan
   semua field baru; `version` tetap `const "0.1.0"`. Tes drift mencegah terulang.
8. **Jalur `faces` tetap opsional** (butuh OpenCV). Tanpa `face_track`, `layout` memakai zona
   bawaan; tidak ada error.

---

## 5. Milestone (jawaban pertanyaan 4)

Total ≈ 10 hari-orang **[P]**: L1 0,5 · L1b 1 · L2 0,5 · L3 2 · L4 1,5 · L5 1,5 · L6 3.
L1 dan L1b boleh paralel dengan L2–L5; L6 menunggu L1 dan L4. Langkah 7 (komposisi
"di belakang subjek", memakai matte) belum ditulis; ia hanya dibuka bila L1b memberi vonis.
Setiap langkah ditutup dengan: `make test` hijau (183 lama + baru), update
`docs/MOTION-TIER2.md`, satu commit atomik.

### Langkah 1 — Spike Remotion + gate (nol kode produk)

**File:** buat `benchmarks/remotion_bench.mjs`, `benchmarks/gate.py`, `benchmarks/remotion.json`,
`scripts/lib/procmem.py`; ubah `benchmarks/README.md` (bagian baru, format tabel yang sama).

**Tes dulu**
- `tests/test_bench_gate.py`: `gate.verdict(result)` — RSS 1200 → `NO_GO`; fps 3,1 + RSS 800 +
  swap 1000 → `GO`; fps 2,0 → `GO_SPARSE`; fps 1,0 → `NO_GO`; `alpha_ok=False` → `NO_GO`;
  swap 50.000 halaman → `NO_GO`.
- `tests/test_procmem.py`: anak Python mengalokasikan 150 MB → sampler pohon melaporkan ≥ 150 MB;
  watchdog dengan batas 100 MB membunuh anak tersebut dalam ≤ 2 s.

**Protokol.** Adegan kartu (rounded rect + bayangan + blur + dua teks + spring) pada tiga
ukuran: 1080×1920, 1080×600, 540×300; 150 frame; konkurensi 1 dan 2; 3 kali tiap konfigurasi,
laporkan median dan rentang. Catat `MemAvailable` awal, delta `/proc/vmstat`
(`pswpin`, `pswpout`), waktu bundle, waktu start dingin, validitas alpha. Uji
`browserExecutable` ke wrapper Chromium, dan apakah `calculateMetadata` bisa mengatur
`width/height` per props di versi Remotion yang dipin **[?]**. Ukuran kecil menentukan apakah
overlay boleh dirender sebesar bbox-nya (biaya PNG ∝ piksel).

**Selesai bila:** `python3 benchmarks/gate.py benchmarks/remotion.json` mencetak vonis;
README memuat tabel terukur; angka **[P]** di bagian 3 diganti angka terukur.
`NO_GO` → Langkah 6 dibekukan dan dokumen ini diperbarui; Langkah 2–5 jalan terus.

### Langkah 1b — Spike matte orang + gate (nol kode produk)

**Kenapa.** Dari video referensi "17 video effects" (analisis frame, 1–2 frame per efek, jadi
gerakannya disimpulkan): 7 dari 17 efek bisa dibuat dengan Langkah 2–5 (zoom, kartu UI, checklist,
chart, pull-back, mockup HP, tipografi). **10 efek menaruh sesuatu di belakang atau di sekeliling
orang** dan butuh mask per piksel: cover story (teks besar tertutup kepala), dinding kartu di
belakang pembicara, latar pengganti ("green screen"), potongan kertas, outline siluet "doodle
boil", frame break, orbit, vertigo, glass type. `faces.py` hanya memberi kotak wajah; kotak tidak
cukup untuk menyembunyikan teks di balik rambut dan tangan. Spike ini menjawab satu pertanyaan:
**apakah ada model segmentasi yang cukup cepat, cukup ringan, dan cukup bersih di tepi untuk
mesin ini?** Hasilnya vonis, bukan fitur.

**Jalur.** OpenCV DNN + ONNX, opsional, model di `models/` (di-gitignore), persis pola YuNet di
`faces.py`: tanpa model atau tanpa `cv2` fitur ini mati dengan tenang dan `dependencies = []`
tidak berubah. Dua kandidat diukur bersamaan supaya vonisnya membandingkan, bukan hanya
menyetujui:

| Kandidat | Sumber | Lisensi | Ukuran | Input | Keluaran | Dugaan |
|---|---|---|---|---|---|---|
| `pphumanseg` | opencv_zoo `human_segmentation_pphumanseg_2023mar.onnx` | Apache-2.0 (LICENSE repo) | 6,2 MB **[T]** | 192×192 | 2 kelas, softmax jadi alpha | cepat, tepi kasar **[P]** |
| `modnet` | Hugging Face `Xenova/modnet` `onnx/model.onnx` | tag HF `apache-2.0` (bobot asal MODNet belum diperiksa **[?]**) | 24,7 MB **[T]** | 320×576 (kelipatan 32, aspek 9:16; bukan 512×512 agar tidak membuang piksel) | alpha lembut | lebih halus, jauh lebih berat **[P]** |

Tidak diukur di spike ini dan alasannya: Apple Vision (hanya macOS; mesin target Linux),
MediaPipe (format tflite, bukan ONNX untuk `cv2.dnn`; dukungan wheel Python 3.14 **[?]**),
Robust Video Matting (dugaan lisensi GPL-3.0 **[?]**, periksa sebelum dipertimbangkan),
rembg/torch (dependensi berat, bertentangan dengan D-004).

**Protokol.**
- Dua jenis sumber: (i) wawancara 16:9 dipotong 9:16 di sekitar pembicara dengan tangan/kertas di
  frame (kasus tepi sulit), (ii) video vertikal dengan orang bergerak. Jendela 6 detik tiap sumber.
- Pipeline yang diukur sama dengan yang akan dipakai produk: ffmpeg decode → `crop` 9:16 →
  `fps=15` → `scale=540:960` → model → alpha → penghalusan temporal (rata-rata bergerak
  eksponensial, bobot frame baru 0,6) → biner pada 0,5.
- 3 run per (model × sumber); tiap run dinilai sendiri, vonis model = run terburuknya
  (variasi antar-run 13–20% **[T: benchmarks/README.md]**). Run pertama membuang inferensi
  pemanasan dari pengukuran waktu; waktu muat model dilaporkan terpisah.
- Metrik per run: `fps_e2e` (decode+inferensi+pasca-proses), `fps_infer` (hanya model),
  `rss_mb` (puncak proses + puncak anak ffmpeg, dijumlahkan), `load_ms`,
  `face_in_matte`, `flicker_p50/p95` (gate), `edge_shift_p50/p95` (diagnostik, tidak di-gate),
  `area_ok_ratio`, `cuts`, plus `meta` (CPU, OS, versi
  cv2/ffmpeg). Setiap pengukuran berjalan di proses sendiri: `ru_maxrss` hanya naik sepanjang
  umur proses, jadi model kedua di proses yang sama akan mewarisi puncak model pertama.
- Keluaran visual untuk mata manusia: `preview.mp4` yang menaruh kata "EDIT" besar **di belakang**
  orang (kasus pakai cover story yang sebenarnya) dan contact sheet PNG. Mask yang lolos angka tapi
  menggigit rambut atau memotong jari harus ketahuan di sini; angka tidak bisa melihatnya.

**Definisi metrik.**
- `face_in_matte`: dari frame yang YuNet temukan wajahnya (tiap frame ke-3; bila ada beberapa
  wajah, yang terbesar), proporsi yang ≥ 90% **elips terpancang di kotak wajah**-nya berada di
  dalam mask. Kurang dari 10 frame berwajah → metrik "tidak ada".
- `flicker` (**gate**): untuk tiap tiga mask berurutan A, B, C **dalam shot yang sama**, jumlah
  piksel yang `A == C` tetapi `B` berbeda (menyala lalu padam, atau sebaliknya), dibagi keliling B.
  Satuannya piksel amplitudo kedip. Gerak searah (tangan bergerak, kepala menoleh) menghasilkan
  0 karena piksel yang berubah tidak kembali; jitter menghasilkan nilai besar. Ini memisahkan
  kualitas model dari isi video.
- `edge_shift` (diagnostik, tidak di-gate): untuk tiap pasang mask berurutan **dalam shot yang sama**, `|XOR| / rata-rata
  keliling`. Satuannya piksel rata-rata pergeseran tepi per langkah mask (lebar 540, 15
  langkah/detik). Keliling = jumlah piksel depan yang bertetangga-4 dengan piksel bukan-depan;
  tepi frame tidak dihitung tepi. Cut shot (beda rata-rata thumbnail 32×18 > 20, sama dengan
  `faces.py`) membuang pasangan itu **dan me-reset penghalusan temporal**.
- `area_ok_ratio`: proporsi frame dengan luas mask 3–90% dari frame (menangkap mask kosong/penuh).

**Tiga koreksi definisi setelah dry-run pertama** (ILC 16:9, Mac; bukan data gate, tidak ada
ambang yang dilonggarkan). Dry-run itu memberi `face_in_matte = 0,0` dan `edge_shift_p95 = 14,6 px`;
kecurigaan atas angka itu mengungkap tiga cacat pada metrik, bukan pada model:
1. Definisi awal menghitung cakupan pada **kotak** wajah. Wajah oval tidak bisa mengisi kotak:
   kepala sempurna hanya 78,5% kotak (π/4), jadi ambang 90% mustahil dipenuhi mask sebaik apa pun
   (terukur: cakupan kotak 0,83–0,89 pada shot bersih). Diganti elips terpancang.
2. Jendela uji berisi cut antar-narasumber. Penghalusan yang melintasi cut menghasilkan mask
   "hantu" orang sebelumnya, dan XOR di cut meledakkan `edge_shift`. Cut kini me-reset
   penghalusan dan membuang pasangan frame itu. Ini juga perilaku yang harus dipakai produk.
3. `edge_shift` mencampur jitter model dengan gerak asli (kepala, tangan, kamera). Bukti: p95
   hampir sama (13,2 vs 13,6 px) pada dua model yang kualitas wajahnya jauh berbeda
   (0,70 vs 1,00). Dijadikan diagnostik; yang di-gate kini `flicker` (piksel berkedip balik),
   dengan ambang 0,5 / 1,5 px yang ditetapkan **sebelum** `flicker` pernah dihitung pada data nyata.
Pelajaran untuk protokol: lihat `contact sheet` sebelum mempercayai angka.

**Gate (ditetapkan sebelum mengukur; semua angka [P], diubah hanya sebelum ada hasil).**

| Metrik | NO_GO bila | Asal angka |
|---|---|---|
| `fps_e2e` | < 2,5 → NO_GO; 2,5–7,5 → `GO_SPARSE`; ≥ 7,5 → `GO` | klip 20 s × 15 langkah = 300 mask ≤ 40 s (+ ≈ T2b) → 7,5 fps; mode sparse ≤ 150 mask ≤ 60 s → 2,5 fps |
| `rss_mb` | > 1024 | sama dengan gate Remotion; ffmpeg (≈ 580 MB **[T]**) tidak berjalan bersamaan |
| `face_in_matte` | < 0,95 atau tidak ada | sama dengan gate reframe v1 (`SCOPE.md`: > 95% wajah utuh) |
| `flicker_p50` | > 0,5 px | piksel tepi yang berkedip balik (A→B→A) per piksel keliling; kedip ≥ 0,5 px di tiap langkah 15 fps terlihat sebagai tepi berkilau. Dikunci sebelum `flicker` pernah dihitung pada data nyata |
| `flicker_p95` | > 1,5 px | memberi ruang untuk momen gerak berbalik arah yang nyata (tangan berhenti, kepala mengangguk) |
| `area_ok_ratio` | < 0,95 | |
| `human_ok` | `false` → NO_GO; `null` → vonis `PENDING` | isi `reviews` di JSON (`{"<id>": true/false}`, berlaku untuk semua run ber-id sama) setelah menonton `preview.mp4` |

**Dua vonis yang tidak boleh dicampur.** Kualitas (`face_in_matte`, `edge_shift`, `area_ok_ratio`,
`human_ok`) tidak bergantung CPU. Kecepatan dan memori (`fps_e2e`, `rss_mb`) bergantung penuh
pada mesin. Gate mencetak keduanya terpisah, dan vonis akhir **hanya sah bila `meta.cpu` memuat
`i5-7300U`**. Run di mesin lain (mis. Mac pengembang) sah untuk menyaring model yang kualitasnya
buruk, tidak sah untuk menyatakan kecepatan; gate mencetak "BUKAN MESIN TARGET" dan tidak
mengeluarkan `GO`.

**File:** buat `benchmarks/matte_bench.py` (runner), `benchmarks/matte_metrics.py` (metrik murni),
`benchmarks/matte_gate.py` (vonis), `benchmarks/matte.json` (hasil); ubah `benchmarks/README.md`
(bagian baru: cara unduh model + sha256 + tabel terukur), `.gitignore` (`benchmarks/matte_preview/`),
`docs/SCOPE.md` (satu baris v1, belum dicentang).

**Tes dulu**
- `tests/test_matte_gate.py` (tanpa dependensi): semua baris tabel gate; `fps` 2,0 → NO_GO,
  5,0 → `GO_SPARSE`, 9,0 → `GO`; metrik hilang → NO_GO; `human_ok=None` dengan angka lolos →
  `PENDING`; `human_ok=False` → NO_GO; vonis model = run terburuk; `meta.cpu` bukan target →
  tidak pernah `GO`; CLI keluar 0 walau NO_GO.
- `tests/test_matte_metrics.py` (*skipUnless numpy*): persegi 40×40 yang mengembang 2 px ke
  segala arah → `edge_shift` ≈ 2; persegi yang bergeser 2 px horizontal → `4h / keliling` ≈ 1
  (hanya dua dari empat sisi yang bergerak; ini rata-rata sepanjang tepi, bukan pergeseran
  terbesar); dua mask identik → 0; dua mask kosong → 0 tanpa pembagian nol; keliling persegi
  `w×h` = `2(w+h)−4`; objek menempel tepi bawah frame = `w + 2(h−1)` (tepi frame bukan tepi
  objek); `face_coverage` 1,0 / 0,0 / 0,5 untuk kotak di dalam/luar/separuh; `area_ok` menolak
  mask kosong dan penuh; persentil dihitung tanpa numpy; `face_coverage` memberi ≥ 0,99 pada
  kepala elips sempurna sementara cakupan **kotak**-nya ≈ 0,785 (tes jebakan sudut), dan lubang
  di wajah menurunkannya di bawah 0,90; `is_cut` (ambang eksklusif, tanpa overflow uint8, frame
  pertama bukan cut); `flicker`: mask diam → 0, gerak searah (persegi bergeser 2 px per langkah)
  → 0, kedip 1 px (A→B→A) → 1,0, dua mask kosong → 0 tanpa pembagian nol.
- `tests/test_matte_bench.py`: pembangun filter crop (16:9 → 9:16 di `crop_x` 0,0 / 0,5 / 1,0 dan
  sumber yang sudah vertikal tidak di-crop); pasca-proses `pphumanseg` mengubah logit 2 kelas jadi
  alpha 0..1 (*skipUnless numpy*); keluaran bench memuat semua kunci yang dibaca gate.

**Selesai bila:** `python3 -m benchmarks.matte_gate benchmarks/matte.json` mencetak vonis kualitas
dan kecepatan per model; README memuat tabel terukur; `preview.mp4` sudah ditonton dan `human_ok`
diisi. **Vonis:**
- kualitas lolos **dan** kecepatan `GO`/`GO_SPARSE` di mesin target → tulis D-012 (model terpilih,
  sha256, mode penuh atau sparse) lalu buka Langkah 7;
- kualitas lolos tapi belum pernah dijalankan di mesin target → status "menunggu mesin target";
  Langkah 7 tetap tertutup;
- kualitas gagal pada kedua model → matte dibekukan; efek yang butuh mask tidak dikejar, dan
  Langkah 2–5 tetap memberi 7 dari 17 efek referensi.

**Status (2026-11-02).** Runner, metrik, gate, dan 80 tes selesai; pengukuran dijalankan di
**Apple M1, bukan mesin target**. Pada protokol yang dikunci kedua model `NO_GO` (kualitas):
pphumanseg gagal `face_in_matte` dan flicker; MODNet lolos `face_in_matte` 1,00 tetapi gagal
`flicker` (p95 4,91 px pada ILC). `human_ok` belum diisi. Tabel, temuan, dan sha256 model ada di
`benchmarks/README.md`. Langkah 7 tetap tertutup. Satu hipotesis untuk putaran berikutnya
(penghalusan 0,3 menurunkan p95 MODNet pada ILC ke 1,00) belum diuji pada sumber kedua dan tidak
boleh dijalankan sebagai ganti protokol ini tanpa dideklarasikan lebih dulu di sini.

#### Langkah 1b — Putaran 2: penghalusan 0,3 (dideklarasikan 2026-11-02, SEBELUM dijalankan)

Putaran 1 `NO_GO`. Satu pengamatan (MODNet, ILC, bobot 0,3: flicker p95 4,91 → 1,00) mengusulkan
bahwa penyebab kegagalan MODNet adalah penghalusan yang terlalu lemah, bukan modelnya. Ini
putaran **sekali jalan** untuk menguji dugaan itu secara jujur. Segala yang ditulis di sini
dikunci sebelum ada angka putaran 2.

**Hipotesis (bisa salah).** Pada MODNet, bobot frame baru **0,3** membuat `flicker_p50 ≤ 0,5` dan
`flicker_p95 ≤ 1,5` pada **kedua** sumber, tanpa kelambanan berlebih. Hipotesis ini sengaja diberi
peluang gagal yang nyata: pada video menari, p50 putaran 1 adalah 0,89 (jauh di atas 0,5) dan 0,3
belum pernah dicoba di sana.

**Berubah:** `--smooth 0.3`; model hanya `modnet` (pphumanseg gugur di `face_in_matte`, yang tidak
bergantung penghalusan: probabilitas ≈ 0,45 di wajah tidak naik di atas 0,5 oleh rata-rata
bergerak); satu metrik baru, `lag`. **Tidak berubah:** kedua sumber dan jendelanya, `crop_x`,
`mask_fps`, ukuran 540×960, semua ambang putaran 1.

**Metrik biaya `lag`.** Penghalusan lebih kuat menurunkan flicker tetapi membuat mask tertinggal di
tepi benda bergerak, dan gate putaran 1 tidak menghukum itu (mask lamban malah tampak "lebih
tenang"). Untuk tiap frame yang benar-benar dihaluskan (bukan frame pertama shot):
`|XOR(mask_halus, mask_mentah)| / keliling(mask_mentah)`, dengan `mask_mentah` = alpha mentah
model ≥ 0,5 **tanpa** penghalusan. Satuannya px jarak rata-rata tepi halus dari tepi mentah.
Mask mentah berderau, jadi nilainya tidak pernah 0; skalanya datang dari kontrol di bawah.

**Ambang `lag` [P], dikunci sekarang:** `lag_p50 ≤ 1,0 px`, `lag_p95 ≤ 2,5 px` (2,5 px di lebar 540
≈ 5 px di 1080: di atas itu tepi tangan yang bergerak terlihat meninggalkan teks di belakangnya).
Aturan gate: `lag` dinilai bila ada di record, dan **wajib ada** bila `smooth_w < 0,6`
(tanpa metrik → gagal).

**Kontrol.** MODNet pada bobot 0,6 dijalankan lagi dengan metrik `lag` yang sama, berkas terpisah.
Tanpa kontrol, angka `lag` pada 0,3 tidak punya skala.

**Aturan keputusan.** Lolos kualitas otomatis bila pada **kedua** sumber: `face_in_matte ≥ 0,95`,
`flicker_p50 ≤ 0,5`, `flicker_p95 ≤ 1,5`, `area_ok_ratio ≥ 0,95`, `lag_p50 ≤ 1,0`, `lag_p95 ≤ 2,5`;
lalu `human_ok` (preview ditonton khusus pada tepi tangan yang bergerak: ILC frame 72–77 dan video
menari). Gagal di salah satu sumber → **MODNet `NO_GO` final di L1b**. Tidak ada sweep lanjutan
(0,2 / 0,4 / ambang biner lain) di L1b; tuning tambahan butuh deklarasi baru dengan alasan baru.

**File:** `benchmarks/matte_metrics.py` (`lag_px`), `benchmarks/matte_bench.py` (catat `lag_p50/p95`,
`build_record(..., lags=)`), `benchmarks/matte_gate.py` (`LAG_P50_MAX`, `LAG_P95_MAX`, aturan
wajib-bila-`smooth_w<0,6`). Hasil: `benchmarks/matte_s03.json` (bobot 0,3) dan
`benchmarks/matte_s06_control.json` (kontrol).

**Tes dulu:** `lag_px` identik → 0; mask halus tertinggal 3 px (persegi 40×40 bergeser horizontal
3 px) → `6h / keliling mask mentah` = 240/156; mask float dibinarkan; dua mask kosong → 0; gate:
batas `lag` inklusif; `lag` absen dengan `smooth_w=0,6` → tidak dinilai; absen dengan
`smooth_w=0,3` → `FAIL` dengan alasan menyebut `lag`; hadir dan di atas ambang → `FAIL`; konstanta
terkunci `(LAG_P50_MAX, LAG_P95_MAX) == (1.0, 2.5)` dan konstanta flicker/wajah tidak berubah;
`build_record(lags=[])` → `lag_p50 is None` (bukan 0).

**Hasil putaran 2 (2026-11-02, Apple M1; kualitas tidak bergantung CPU).** Berkas:
`benchmarks/matte_s06_control.json` dan `benchmarks/matte_s03.json`, 3 run per baris, kualitas
identik antar run. Diverifikasi ulang oleh koordinator (gate dijalankan sendiri, bukan dari laporan pekerja).

| Bobot | Sumber | flicker p50 / p95 | lag p50 / p95 | `face_in_matte` |
|---|---|---|---|---|
| 0,6 (kontrol) | ILC | 0,17 / 4,91 | 0,81 / 2,14 | 1,00 |
| 0,6 (kontrol) | video menari | 0,89 / 2,77 | 0,89 / 1,20 | 1,00 |
| **0,3** | ILC | 0,07 / **1,00** ✓ | **2,49 / 10,11** ✗ | 1,00 |
| **0,3** | video menari | **0,55 / 1,60** ✗ | **5,11 / 8,95** ✗ | 1,00 |

Hipotesis **ditolak**. (a) Pada video menari flicker 0,3 masih di atas ambang (0,55 > 0,5; 1,60 > 1,5).
(b) `lag` melampaui ambang 2,5× (ILC p50) hingga 5,1× (video menari p50), dan 3,6–4,0× pada p95:
penghalusan 0,3 menurunkan flicker dengan membuat mask tertinggal. Hasil ILC saja (flicker 0,07 /
1,00) tanpa metrik `lag` akan tampak seperti kemenangan; metrik biaya yang dikunci lebih dulu
mencegah kesimpulan keliru itu. **Vonis menurut aturan keputusan: MODNet `NO_GO` final di L1b.**
`human_ok` tidak diperlukan (gagal otomatis). Matte **dibekukan**; lihat D-012. Membuka kembali
butuh model atau pendekatan yang berbeda (mis. penghalusan sadar-gerak) dengan deklarasi baru.

### Langkah 2 — Fondasi EDL + keputusan tertulis

**File:** ubah `docs/DECISIONS.md` (D-009 ASS-first tier-2; D-010 EDL aditif, versi tidak dibump;
D-011 Remotion hanya overlay sparse + gate) — *aturan repo: dokumen dulu, kode kemudian*;
`schema/edl.schema.json`, `scripts/edl.py`, `scripts/cli.py`, `docs/SCOPE.md` (baris v1 tier-2).

**Tes dulu (urutan ini)**
1. `tests/test_edl_golden.py` — karakterisasi: `sha256(json kanonik)` dari EDL hasil
   `make_work` sama dengan konstanta `GOLDEN`. Isi `GOLDEN` dengan menjalankan tes sekali
   **di HEAD sebelum mengubah apa pun**, jalankan dua kali untuk memastikan deterministik.
2. `tests/test_schema_drift.py` — penjelajah schema tanpa `jsonschema`: setiap kunci pada
   EDL hasil build (dan hasil `faces`) harus dideklarasikan. **Merah** sekarang
   (`punch`, `progress`, `bias_track`); hijau setelah schema diperbaiki.
3. `tests/test_edl_words.py` (dengan `motion_tier=2`): tiap caption punya `words`; monoton;
   `words[i].start == map_time(src)` ±1 ms; pada klip multi-segmen kata di jeda terbuang
   hilang; `captions[].start/end/text/emphasis` **identik** dengan build tier-1;
   `words[0].start ≥ start−1 ms`; kata terakhir mulai sebelum `end` caption berikutnya.
4. `tests/test_cli_flags.py`: default tanpa `words`/`caption_style`; `--motion 2` ada.

**Aturan jendela tampil** (temuan #10): `words` menyimpan waktu asli; kinetic menampilkan
frasa dari `words[0].start` sampai `max(cap.end, words[-1].end + 0.12)`, dibatasi
`next.start − 0.04`. Field `captions[].start/end` tidak disentuh.

**Selesai bila:** `make test` hijau; tes golden lulus; `edl.json` default `cmp`-identik dengan
sebelum perubahan; `build-edl --motion 2` memuat `words` dan `caption_style:"kinetic"`.

**Status Langkah 2 (2026-11-02): SELESAI.** Dikerjakan worker opencode lewat Orca dan diverifikasi
koordinator: EDL tier-1 identik byte dengan HEAD murni (`cmp`), tes golden + drift schema + `words`
+ flag CLI + validasi tier hijau, 371 tes (4 kegagalan `procmem` lama). Uji mutasi di salinan
menunjukkan batas tes seam di spesifikasi awal terlalu longgar; diganti nilai eksak (`end == 2.2`).
Langkah 3 dipecah: **3a** pustaka murni `spring` + `fontmetrics`; **3b** penulis ASS kinetic, font,
template, integrasi render, pratinjau.

**Status Langkah 3a (2026-11-02): SELESAI.** `scripts/lib/spring.py` + `scripts/lib/fontmetrics.py`,
69 tes, 440 tes total (4 `procmem` lama). Worker memetakan 31 mutan (30 tertangkap; satu ekuivalen
secara aljabar); koordinator menambah 4 mutan baru yang semuanya tertangkap. Angka spring bawaan
dihitung ulang: ζ 0,6047, overshoot 9,204%, puncak 0,149 s, settle 2% 0,224 s (rencana: ≈9%, 0,15 s,
0,25 s). Langkah 3b dipecah lagi: **3b-i** font OFL + `scripts/kinetic.py` + template (tanpa
menyentuh `render.py`); **3b-ii** integrasi render, pratinjau, tes oracle libass.

**Status Langkah 3b-i (2026-11-02): SELESAI, dengan satu cacat yang ditemukan koordinator.**
Font Archivo Black (OFL 1.1, TTF statik, sha256 dipin), `scripts/kinetic.py`, template, 81 tes,
521 tes total (4 `procmem` lama), 20/20 mutan tertangkap. Diverifikasi: berkas terlarang identik
HEAD, golden `captions.build_ass` lulus pada HEAD murni. Worker mengukur rantai spring dan menemukan
syarat awal (≤10 segmen, ±2%) gagal pada grid frame murni (3,3–4,1%); desain tiga tahap hasilnya
0,64–0,96% (≤1,32% untuk emphasis di 60 fps), tanpa melonggarkan toleransi.

**Cacat (R3 terbukti, ditemukan oleh render libass sungguhan, bukan tes murni).** libass
menafsirkan `Fontsize` sebagai tinggi sel `usWinAscent+usWinDescent` (kode `ass_face_set_size`,
gaya VSFilter), bukan em. Archivo Black: 1,347 em, jadi em efektif = Fontsize / 1,347. Terukur pada
`ffmpeg-full` + libass: lebar kata terrender = 0,707–0,724 × prediksi `fontmetrics` (0,742 ×
faktor jarak sisi glyph ≈ 0,97), jarak antar-kata 106 px vs rancangan 23,5 px. Pusat kata cocok
±1 px (`n5\pos` dan rantai `	` benar) dan kontrol `fontsdir` kosong memberi glyph berbeda, jadi
font bundel memang terpakai. Perbaikan: `Fontsize` ASS = `em × (winAscent+winDescent)/upem`
(**Langkah 3b-ii-a**). Catatan lingkungan: `ffmpeg` default Homebrew di mesin pengembang **tidak
punya libass** (filter `subtitles` tidak ada), sehingga `render` tier-1 pun tidak bisa membakar caption
di sana; yang berlibass: `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`.

**Status Langkah 3b-ii-a (2026-11-02): SELESAI.** Cacat `Fontsize` libass diperbaiki: `Style Fontsize =
em × (usWinAscent+usWinDescent)/upem` (`Font.cell_height_ratio`; Archivo Black 1,347 → 113,15 untuk em
84). Terukur ulang oleh koordinator dengan skrip sendiri pada libass nyata: rasio tinta/prediksi
**0,970 / 0,949 / 0,976 / 0,972** (sebelumnya 0,720 / 0,707 / 0,724 / 0,722), pusat kata ±0,7 px dari
`\pos`, dua klaster per baris pada ambang pemisah 16 px. Dua angka di spesifikasi awal koordinator
terbukti keliru dan dikoreksi atas permintaan worker (ambang pemisah kata 40 px → 16 px; jarak antar-tinta
harus memperhitungkan skala emphasis kedua kata). 542 tes, 4 `procmem` lama; oracle libass 9/9 JALAN
(bukan skip) di kedua Python berkat deteksi ffmpeg-full; 5/5 mutan worker + 4/4 mutan koordinator tertangkap.

**Status fixture klip nyata F1 (2026-11-02): SELESAI.** `work/clip04/` (gitignored): excerpt sumber
262–340 s, `transcript.json` Groq `whisper-large-v3-turbo` (171 kata, monoton, 0 halusinasi terbuang).
Waktu kata Groq vs YouTube auto-caption (153 pasangan, dihitung ulang koordinator): median Δ +26 ms,
p90 474 ms, ≤80 ms 64,1% — timing YouTube kasar di kata pertama tiap event. Temuan produk (belum
ditangani): Groq membalas `segments: []`, sehingga filter halusinasi `_bad_ranges()` tidak aktif di
jalur Groq (kode meminta timestamp kata saja).

**Status Langkah 3b-ii-b (2026-11-02): SELESAI, diverifikasi koordinator.** `scripts/lib/ffmpegbin.py`
(pemilihan ffmpeg ber-libass; `CLIP_FFMPEG` > PATH > `ffmpeg-full`; deteksi per kolom NAMA filter),
`render --preview` (540×960 @15 fps, `.preview.mp4`), penulis kinetic di `render_clip`, escape `fontsdir`
dua lapis (ditemukan empiris: satu lapis ditolak ffmpeg). 612 tes, 4 `procmem` lama, 17/17 mutan
tertangkap. Tier-1 terbukti identik: hash `cmd[1:]` dan ASS **sama persis** antara HEAD murni dan kode
sekarang pada harness koordinator (dua segmen, punch, progress, overlay VS, emphasis; dengan dan tanpa
`fontsdir`). Biaya (sintetis 3 s, indikatif): kinetic/tier-1 = 1,01×, pratinjau = 0,70×.

**Temuan visual pertama pada video nyata (cacat R3 lanjutan).** Render nyata dari excerpt klip_04
dengan transkrip Groq (14 s, 32 kata): spring pop **bekerja** (frame demi frame: kosong → 63% setengah
transparan → overshoot → settle) dan 414 frame tepat. Tetapi **kata di sebelah kata beremphasis menempel**:
celah tinta `apa|enggak` 7 px dan `apa|capeknya` 9 px, sama dengan celah antar-huruf (6–11 px), sehingga
terbaca "apaenggak"/"apacapeknya". Penyebab: (1) tata letak memakai advance pada skala 100% padahal kata
beremphasis dirender 112% (tepi tinta bergeser keluar `(s−1)/2 × lebar` ≈ 16 px untuk "enggak"); (2)
garis tepi hitam 7 px kata tetangga menimpa tinta kata sebelumnya karena tiap kata adalah event
terpisah di Layer yang sama; (3) bearing sisi glyph. Tes murni tidak bisa melihat ini; hanya render
libass. Diperbaiki di **Langkah 3b-iii**.

**Status Langkah 3b-iii (2026-11-02): SELESAI, diverifikasi koordinator.** Celah antar-kata kini
diturunkan dari celah TINTA yang diinginkan, bukan dari `gap_em`:
`celah_tinta = 2 × OUTLINE_PX + CLEARANCE_EM × size` (7 px × 2 + 0,10 em = 22,4 px pada em 84);
`celah_kotak = max(0, celah_tinta − rsb_i × s_i − lsb_j × s_j)` dengan lsb/rsb analitik dari `glyf`+`hmtx`
(bukan dikalibrasi dari render). Lebar kotak = `advance × skala akhir` (emphasis 1,12), dan pemotongan
baris memakai lebar berskala. `OUTLINE_PX`/`SHADOW_PX` kini SATU sumber (template `{{OUTLINE}}`/`{{SHADOW}}`);
`gap_em` dipertahankan tetapi DEPRECATED dan tidak lagi dipakai. Skala akhir ditentukan SEBELUM layout di
`build_ass`.
Terukur ulang koordinator pada render nyata klip_04 (libass, skrip sendiri, kolom tinta per baris aktif):
`apa|enggak` **7 → 23 px**, `apa|capeknya` **9 → 23 px**, semua celah antar-kata lain 22–24 px
(satu 27–29 px saat kata masih pop), sedangkan celah antar-huruf rata-rata ≤ 12 px. 647 tes, hanya 4
`procmem` lama gagal, di kedua Python; oracle spasi 6/6 dan oracle libass lama 9/9 JALAN (bukan skip).
Kontrol negatif `Outline=0` menurunkan celah ±14 px. 12/12 mutan koordinator tertangkap (lebar kata tanpa
skala di layout, suku outline, indeks skala bergeser, wrap tanpa skala, suku bearing, celah berlebih, lsb/rsb
tertukar, jepit ≥0, outline tak ditulis ke template, indeks celah, skala bearing, `build_ass` tanpa
`scales`), plus 11/11 mutan worker. Tier-1 byte-identik (golden `captions`/`render`/`edl` hijau;
`captions.py`, `render.py`, `edl.py`, `scripts/lib/*` tidak tersentuh).
Efek samping yang disengaja pada tes lama (bukan regresi): `test_exact_positions_four_words` dan
`test_gap_between_words…` (nama lama `…_is_gap_em_times_size`) mengunci posisi/celah lama;
`test_dialogue_positions_match_scaled_layout`, oracle libass `_layout()` dan `test_kinetic_render`
`_layout_and_widths()` membandingkan terhadap layout TANPA skala padahal render memakai skala; semuanya
dibawa ke rumus/skala yang sama dengan `build_ass` (skala diambil dari `kinetic.SCALE_EMPHASIS`, toleransi
±3 px tidak berubah). Ditambah asersi independen: pusat tinta vs `\pos` yang di-PARSE dari ASS keluaran.
Catatan teknis untuk nanti: `kinetic._GlyfReader` membaca atribut privat `fontmetrics.Font._advances`
karena `scripts/lib/*` terlarang pada tugas itu; pindahkan pembaca bearing ke `fontmetrics` saat modul itu
boleh disentuh. Kata biasa `dimusuhin|dia` dll. masih memakai celah 22–24 px seragam; frasa sebagian
yang tampil off-center tetap kompromi desain (posisi dihitung dari frasa lengkap).

**Koreksi 3b-iii (ditemukan koordinator saat memeriksa F2 pada resolusi penuh): `CLEARANCE_EM = 0.10`
terlalu rapat — kesalahan KOORDINATOR, bukan worker.** Target 22,4 px dibenarkan dengan "sama dengan celah
`Pertama,|pasti` pada oracle lama", padahal pasangan itu melibatkan kata beremphasis yang tintanya memakan
celah. Terukur pada `work/clip04`: spasi alami Archivo Black 27,97 px (0,333 em); celah tinta alami
(spasi + rsb + lsb) bermedian **35,3 px** (p10 30,9, p90 38,7). 3b-iii memperketat semua pasangan biasa dari
~35 px ke ~23 px (≈63%); gerbang [18, 40] tidak menangkapnya. Bukti visual: `setiap hari di posisi`
dan `lu ngerasain` sesak pada 0,10 em, natural pada 0,22 em (render pembanding koordinator, kanvas tetap
muat). Perbaikan: **Langkah 3b-iv** (`CLEARANCE_EM = 0.22` → 32,5 px ≈ 92% jarak alami; gerbang oracle
diperketat ke [28, 38] supaya kesalahan serupa tertangkap).

**Status Langkah 3b-iv (2026-11-02): SELESAI, diverifikasi koordinator.** `CLEARANCE_EM` 0,10 → **0,22**
(target celah tinta 22,4 → **32,48 px** ≈ 92% jarak alami Archivo Black); kode produk berubah HANYA pada
konstanta dan komentar/docstring (diff diperiksa baris demi baris; template tidak berubah). Gerbang oracle spasi
diperketat ke **[28, 38] px**. Terukur ulang koordinator pada render nyata klip_04: celah antar-kata
**32–34 px** pada semua pasangan settled (satu 39 px saat kata masih pop), celah antar-huruf ≤ 13 px.
647 tes, hanya 4 `procmem` lama gagal, di kedua Python; oracle jalan; golden tier-1 hijau. Mutan: 15/15
tertangkap pada harness koordinator (termasuk kesalahan 3b-iii: clearance 0,10, serta 0,18 dan 0,27 yang
hanya meleset ±0,05 em) + 11/11 + 2/2 milik worker. Audit dampak (diverifikasi independen) pada 42 frasa
nyata: 3 frasa berubah 1 → 2 baris (`Ditambah, dia keluar,`; `busuk, polisi sampah.`; `bilang kan
perubahan`), tinta+outline terkiri 50 px dan terkanan 1030 px (batas aman [40, 1040]).

**Status fixture klip nyata F2 (2026-11-02): SELESAI, diverifikasi koordinator.** `work/clip04_t2/`
(gitignored): EDL tier-1/tier-2 produk untuk atom 3→16 (5 segmen, 52,040 s, 42 caption, 124 kata, 12 punch;
atom 3 paling dekat dengan klip_04: awal beda 11 ms, atom 4 beda 2,75 s). Terbukti pada data nyata:
`edl_t2` tanpa `captions[].words`/`caption_style` **sama persis** dengan `edl_t1`; `git status` sebelum/sesudah
identik; tier-1 dan tier-2 final: 1562 frame, 1080×1920@30, audio ±0 byte sama. Render M1: tier-1 15,2 s,
tier-2 final 14,3 s (RSS 665/735 MB), pratinjau 6,7 s (318 MB) — bukan mesin target. Loudness −14,4 LUFS.
Audit celah kata (58 pasangan, 48 baris): 22–24 px pada baris yang settle penuh (konfirmasi koordinator
dengan skrip sendiri pada 7 waktu: 22–24 px). Lag audio render vs klip_04 tidak seragam (+16 ms → +60 ms →
+540 ms): klip_04 membuang 0,524 s lebih banyak (atomisasi video penuh berbeda), bukan cacat render.
Temuan produk (belum ditangani, backlog; bukan bagian 7-efek):
1. **Frasa pendek tak terlihat**: caption `Lu,` berjendela 40 ms (kata 80 ms di ASR, `DEFAULT_LEAD` 0,04 +
   `NEXT_GUARD` 0,04 memakan sisanya) → 0 frame terbaca. 1 dari 42 frasa; 7 baris terlalu singkat untuk
   diaudit. Opsi perbaikan (render-time, EDL tetap aditif/D-010): gabungkan frasa berjendela < ~0,25 s ke
   tetangganya bila muat ≤ 2 baris, atau pinjam waktu dari batas.
2. **Kata terakhir frasa masih pop saat jendela berakhir** pada 16 dari 48 baris (ucapan cepat: kata
   berikutnya mulai ≤ 0,1 s kemudian); inheren pada model "frasa diganti saat frasa berikut mulai".
3. **Jendela terakhir (#41) melewati durasi keluaran 0,12 s** (`TAIL_PAD`): tak berbahaya.
4. Selisih durasi audio-vs-video 26,7–33,3 ms pada klip nyata 52 s di tier-1 DAN tier-2 (pembulatan frame
   CFR + padding AAC). Kriteria "±1/48 s" dari Langkah 3b hanya berlaku untuk klip sintetis yang durasinya
   kelipatan frame; untuk klip nyata batas yang masuk akal = 1 frame video (1/30 s). Perilaku produk lama,
   bukan regresi tier-2.
5. Transkrip Groq tetap membalas `segments: []` → filter halusinasi tidak aktif (temuan F1).

**Status Langkah 5a (2026-11-02): SELESAI, diverifikasi koordinator.** `scripts/shapes.py` (585 baris, stdlib):
`rect`, `rounded_rect` (kappa 0,5522847498), `circle`, `line`, `polyline` (ruas + lingkaran sambungan),
`check_mark`, `colour`, `alpha`, `shape_event`, `wipe_tags`, `ass_document`. Tiga fakta libass yang DIUKUR
worker (bukan ditebak) dan dipakai 5b: (1) aturan isi **nonzero** → semua kontur dibuat berorientasi sama
(tumpang tindih = gabungan; kontur terbalik = lubang, dibuktikan oleh tes kontrol); (2) koordinat desimal
pada path dipakai subpiksel; (3) `\t(\clip)` **dianimasikan per frame** (linear sesuai `\t`, `accel` dipakai),
tetapi `\clip` membulatkan koordinat ke integer. 704 tes (57 baru: 44 murni + 13 oracle libass), hanya 4
`procmem` lama gagal, di kedua Python; oracle jalan di keduanya (jumlah skip tidak naik). Mutan: 9/9 worker
+ 12/12 koordinator tertangkap (kappa, orientasi lingkaran/line, lingkaran sambungan, alpha terbalik, RGB↔BGR,
detik vs ms, `\p0`, jepit radius, `accel`, `pos`, skala centang). Render koordinator sendiri (kartu krem
membulat + 3 thumbnail + tag kuning, checklist lingkaran+centang, polyline dengan wipe kiri→kanan, garis):
bersih, sudut membulat, sambungan tanpa celah, wipe tumbuh sesuai waktu. Hanya 3 berkas baru; tidak ada
berkas lama disentuh. Catatan kecil: `captions._ass_time` (tier-1, tidak diubah) menulis `0:00:60.00` untuk
t di [x9,995; x+1) detik; diduga tak berbahaya karena libass menjumlahkan field waktu, **belum diverifikasi**.

**Status Langkah 5b-1 (2026-11-02): SELESAI, diverifikasi koordinator.** `scripts/presets.py` (467 baris;
`REGISTRY`/`PRESET_TYPES`, `PresetError`, `build_fx_ass(clip, fps=…) → (ASS | None, peringatan)`) +
preset **`zoom_through_text`** (DM Serif Display Italic, skala 80% → 320% dengan `accel` 2, alfa 1 → 0 pada
40% terakhir, default `duration` 0,7 s) + integrasi **aditif** di `render.py` (+44 baris, 0 dihapus: satu
dokumen `captions/<id>.fx.ass`, satu filter `subtitles` SESUDAH panel tier-1 dan SEBELUM pratinjau/caption;
klip tanpa preset tidak menulis berkas dan tidak menambah filter). Tier-1 **byte-identik** terhadap HEAD
murni pada harness koordinator (`cmd[1:]` dan ASS, dengan dan tanpa `fontsdir`) dan golden hijau.
785 tes (81 baru), hanya 4 `procmem` lama gagal, di kedua Python; modul preset 92 OK di keduanya; oracle jalan.
Font bundel terbukti dipakai (lebar tinta 612 px vs 775 px pada font fallback). Mutan: 16/16 worker + 15/15
koordinator tertangkap. Biaya render +8,3% (median 3 run, M1; anggaran ≤ +10%). Render nyata klip_04
(dua overlay: "Polisi jujur?" di 6,6 s dan "2017" kuning di 20,9 s): teks tumbuh dari kecil ke besar dan
memudar sambil melintasi wajah, caption tetap di lapisan atas — sesuai maksud "zoom-through" (sengaja
melintasi wajah; preset ini dikecualikan dari aturan anti-tabrakan wajah Langkah 4). Catatan: teks putih
tipis pada latar terang di frame awal kurang kontras (bayangan lembut opsional belum dipakai); `{`, `}`, `\`
di `text` diganti `(`, `)`, `/` (bukan ditolak). Peringatan preset dicetak ke stderr berawalan `PERINGATAN:`
(renderer tidak punya `report.md`).

**Status Langkah 4a (2026-11-02): SELESAI, diverifikasi koordinator.** `scripts/layout.py` (1072 baris, stdlib,
murni) + `tests/test_layout.py` (65) + `tests/test_layout_properties.py` (10); hanya tiga berkas baru.
`Rect`, `shots`, `punch_scale_at`/`max_punch_scale`, `forbidden_zones` (inflasi 8% → skala punch terhadap
(540, 960) → potong kanvas), `place_caption` (prioritas: tidak memotong wajah > zona aman > kandidat
awal; semua terblokir → coba skala 0,85 → irisan minimal; **caption tidak pernah dibuang**), `place_overlay`
(`SLOT_ORDER` eksplisit), `compute_layout` (satu keputusan caption per shot; batas shot di tengah frasa
tidak mengubah frasa itu), `audit` (per frame, skala punch yang berlaku pada frame itu). 860 tes, hanya 4
`procmem` lama gagal, di kedua Python. Mutan: 12/12 worker + 8/10 koordinator tertangkap; dua yang lolos:
**T3 setara secara matematis** (inflasi dan penskalaan seragam saling komutatif → bukan celah tes) dan
**T5 celah tes nyata** (irisan-minimal diganti irisan-maksimal tidak tertangkap: belum ada tes yang
mewajibkan kandidat KEDUA yang lebih kecil irisannya menang) → ditutup di 4b-1.
Temuan yang mengubah rencana:
1. **`punch` tier-1 = loncatan keras, bukan ramp** (`motion.zoom_expression`: `if(lt(in,f),s0,…)`, perubahan
   pada frame `round(t·fps)`). Rencana lama yang menyiratkan ramp salah; layout memakai skala per frame.
2. **Konstanta `SAFE` [P] bertabrakan dengan desain caption sekarang**: caption kinetic 2 baris di `y=1400`
   berujung bawah 1496,6 px (> 1440) dan lebar 980 px berujung kanan 1030 (> 960); kandidat atas `y=330` berujung
   atas 233,4 (< 250); slot `top_safe`/`mid_low` berlebar 960 mulai x=60 melewati batas kanan 60 px. Worker
   memakai ANCHOR vertikal (bukan tepi kotak) supaya kandidat rencana tetap berlaku. **Angka zona aman belum
   diverifikasi ke spesifikasi platform** dan harus diukur ulang/diputuskan di 4b.
3. **Skema `layout` tidak cocok dengan keluaran**: `layout.caption[]` hanya mengizinkan `t/an/y/x/size`
   (`additionalProperties: false`) dan tidak ada `layout.overlays`; keluaran memuat `scale`, `reason`,
   `overlays`. Penyelarasan skema (aditif, dengan tes drift) = pekerjaan 4b-1.
4. Tanda tangan aditif: `punch_scale_at(..., fps=)` keyword-only; `place_overlay(caption_rect_=)` menerima
   daftar `Rect`.

**Status Langkah 5b-2 (2026-11-02): SELESAI, diverifikasi koordinator.** Preset **`checklist`** di
`scripts/presets.py` (467 → 1272 baris): kartu gelap semi-transparan (`#14161B`, opasitas 0,86), judul,
penghitung `n of N`, 2–6 butir; lingkaran cincin abu berubah menjadi hijau berisi centang (pop spring 0 → ~108% →
100%) tepat pada frame `round(done_at·fps)`; masuk kaku (semua elemen memakai `\move` identik 300 ms, alfa
ease-out), keluar fade 0,20 s; Archivo Black dari font bundel; maksimum 33 `Dialogue` untuk 6 butir. Fakta libass yang
diukur worker: **`\move` diabaikan bila `\pos` ada** (jadi event dirakit di `presets.py`, bukan lewat
`shapes.shape_event`) dan **geseran `\move` selalu linear** (ease-out hanya pada alfa). Waktu event penghitung
ditulis pada sentidetik pertama yang lebih besar dari timestamp frame sebelumnya (bukan `round`, yang bisa
menunda satu frame). 967 tes (+112), hanya 4 `procmem` lama gagal, di kedua Python; satu asersi tes lama
berubah (`PRESET_TYPES` kini memuat `checklist`); tier-1 byte-identik terhadap HEAD (harness koordinator).
Mutan: 12/12 worker + 14/15 koordinator tertangkap; **satu celah tes**: mutan C15 (waktu mulai event
penghitung diganti `round(frame/fps, 2)`) lolos karena tes hanya memakai frame 37 dan 60, tempat kedua rumus
kebetulan sama; frame seperti 38 atau 41 (di mana `round` membulat ke atas) tidak diuji → ditutup di 5b-3.
Biaya render: worker mengukur +26,5% (fixture 4 s) dan +15,6% (klip 20 s); pengukuran koordinator
(selang-seling, median 3 run, klip nyata 52 s, overlay 6 s, M1): **+2,1%** (`checklist`) dan **+1,0%**
(`zoom_through_text`). Biaya berbanding lurus dengan fraksi durasi klip yang overlay-nya aktif (ekstrapolasi
~+18% bila overlay menutupi seluruh klip) — anggaran ≤ +10% terpenuhi untuk pemakaian wajar (overlay 3–6 s).
Render nyata klip_04 (empat butir, `done_at` 9,5/10,8/12,2 s): penghitung naik 0→3 of 4, centang berurutan;
kartu di y=260 menutupi dahi dan sebagian mata pada close-up (lihat 4b-1 di bawah).

**Status Langkah 4b-1 (2026-11-02): SELESAI, diverifikasi koordinator.** `faces.crop_x_at` (satu sumber dengan
`crop_expression`; `crop_expression` identik byte-per-byte dengan HEAD pada 3000 kasus acak koordinator),
`faces.face_track` (amplop per wajah per shot; `analyze_edl(face_track=False)` bawaan byte-identik; flag
`cli faces --face-track`), skema `layout.caption[]` + `scale`/`reason` dan `layout.overlays[]` (aditif),
subperintah `cli layout` (0,10–0,12 s per klip, deterministik), tes penutup celah T5 4a. 967 tes, hanya 4
`procmem` lama gagal; mutan 14/14 worker. **Audit klip_04 nyata: 23 shot (1 wajah/shot), caption∩wajah 1293 dari
1561 frame; overlay tidak ada di klip itu.** Pemeriksaan visual koordinator (overlay_check): kotak YuNet
mencakup wajah (cakupan 0,955–1,000) tetapi **menjulur ke bawah dagu** dan, dihitung sebagai amplop satu shot
(hingga 15 s), makin besar karena kepala bergerak; caption di `y=1400` memang menimpa bagian bawah kotak
itu (dagu/leher) pada sebagian frame tetapi TIDAK menimpa mulut — sama seperti tier-1. Layout memilih
`min_overlap:y=1400` hampir di mana-mana, jadi hasilnya sama dengan tidak ada layout. Pelajaran: (1) zona
terlarang seharusnya zona INTI dari landmark (mata–hidung–mulut), bukan seluruh kotak wajah; (2) amplop
sebaiknya per jendela frasa, bukan per shot; (3) pada close-up talking-head (wajah mengisi ±60–70% frame) TIDAK
ADA slot bebas untuk overlay kartu: overlay yang tidak dikecualikan hanya `zoom_through_text` dan
`pullback`; sisanya harus diberi `rect` eksplisit oleh pemilih/agen sesuai jenis shot atau dilewati.
Tersisa (opsional, 4b-2): landmark → zona inti, amplop per frasa, `kinetic` membaca `layout.caption`,
ukuran bawaan overlay per preset. **Keputusan koordinator:** 4b-2 ditunda; preset berikutnya memakai `rect`
eksplisit/bawaan rencana dan tidak menunggu layout otomatis.

**Status G1 — filter halusinasi aktif di jalur Groq/OpenAI-kompatibel (2026-11-02): SELESAI, diverifikasi koordinator.**
`transcribe._openai_compatible` kini mengirim `timestamp_granularities[]` dua kali (`word` + `segment`);
`_multipart` menerima dict (perilaku lama, **byte-identik** terhadap HEAD pada pengujian koordinator) atau daftar
pasangan. Diff produk hanya 2 fungsi (`_multipart`, `_openai_compatible`). 15 tes baru (respons tiruan, tanpa
jaringan) hijau di kedua Python; mutan 6/6 worker + 3/3 koordinator tertangkap. **Verifikasi live koordinator**
(1 panggilan Groq, kunci dari `.env`, tidak dicetak): potongan 30 s klip_04 → 70 kata (transkrip lama pada
rentang yang sama 69), `segments` TERISI (sebelumnya `[]`), `no_speech_prob` 0,000, `avg_logprob` −0,077,
`compression_ratio` 1,77, `_bad_ranges` kosong (ucapan nyata tidak ada yang dibuang). **Keterbatasan jujur:** Groq
mengembalikan SATU segmen 30 s untuk potongan itu, jadi metrik per-segmen (`no_speech_prob`, dst.) kasar: filter
hanya menangkap potongan yang SELURUH jendelanya senyap/musik/berulang, bukan halusinasi pendek di tengah ucapan
nyata. Itu tetap lebih baik dari sebelumnya (filter sama sekali tidak aktif).

**Status Langkah 3b-v — frasa kinetic berjendela pendek digabung saat render (2026-11-02): SELESAI, diverifikasi
koordinator.** `kinetic.effective_captions` (murni; `MIN_VISIBLE` 0,25 s, `MAX_MERGED_WORDS` 6; gabung ke frasa
berikutnya, lalu ke sebelumnya, lalu biarkan; deep copy, EDL TIDAK berubah) dipanggil `build_ass`. Pada
`edl_t2.json` nyata: 42 → 41 frasa; satu-satunya yang berubah `Lu,` + `lu ngerasain nggak sih` → `Lu, lu ngerasain
nggak sih` (jendela 40 ms → 1,02 s); dari 124 baris `Dialogue` hanya 5 yang berbeda (kata-kata frasa itu), 119
identik byte-demi-byte. Render nyata: "Lu," tampil lalu kalimat tumbuh kumulatif. Koreksi spesifikasi koordinator
(dicatat worker): kriteria "kata pertama terlihat ≥ 6 frame SEBELUM kata kedua muncul" mustahil karena
penggabungan tidak mengubah waktu kata; kriteria yang benar = kata pertama tetap tampil bersama kata-kata
berikutnya. 1096 tes, hanya 4 `procmem` lama gagal, di kedua Python; tier-1 byte-identik; mutan 9/9 worker +
10/10 koordinator tertangkap. Catatan: `cli.py::_kinetic_caption_blocks` masih memanggil `display_window` pada
caption mentah (bagian dari 4b-2 yang ditunda); `_MAX_WIDTH`/`_DEFAULT_SIZE` di `kinetic.py` menduplikasi
nilai bawaan `layout_phrase`/`build_ass` (diberi komentar).

**Status Langkah 5b-3 — preset `chart_grow` + penutup celah checklist (2026-11-02): SELESAI, diverifikasi
koordinator.** Kartu grafik datar: garis kuning tumbuh kiri→kanan dengan ease kosinus 16 segmen (`\t(\clip)`
dan `\move` titik berwaktu sama; jarak titik–kepala garis terukur worker 0,5–1,3 px), titik ujung mengikuti
kepala garis, tag pil pop sesudah garis selesai, sumbu + 4 grid + label, maksimum 31 `Dialogue`. Penutup celah
C15 (frame 38/41/68 @30 fps) ditutup; koordinator memverifikasi 233 tes preset OK di kedua Python, 1096 tes
seluruh suite (hanya 4 `procmem` lama), tier-1 byte-identik. Biaya render (koordinator, interleaved, 4 putaran,
klip nyata 52 s, overlay 6 s, M1): **`chart_grow` +1,0%**, `checklist` +2,6% (satu set 3 putaran sebelumnya
menunjukkan +8,0% yang ternyata derau antar-run ±5%). Render nyata klip_04: garis tumbuh, titik mengikuti, tag
"+193%" muncul di ujung, kartu masuk/keluar kaku. Mutan: 11/11 worker + 12/14 koordinator; **dua celah tes
nyata**: `CHART_ENTRY_OFFSET = 0` (geser masuk) dan `CHART_GRID_LINES = 0` (grid) tidak digagalkan tes mana
pun → ditutup di 5b-4. Perubahan pada `presets.py` yang bukan aditif murni (4 baris diganti): asumsi
"font = checklist" digeneralisasi menjadi `font_kind` (hash dokumen 5b-1/5b-2 tetap hijau).

**Status Langkah 5b-4 — preset `ui_panel` + penutup celah `chart_grow` (2026-11-02): SELESAI, diverifikasi
koordinator.** `scripts/presets.py` kini 2532 baris, 4 preset terdaftar. `ui_panel`: kartu krem (`#F6EEDC`,
opasitas 0,96, radius 48) berjudul, 1–6 thumbnail pastel (3 per baris; kartu tumbuh ke bawah) yang pop satu per
satu dengan jeda 80 ms, tag pil kuning, bilah input; masuk/keluar kaku. Dua celah tes `chart_grow` (D6 geser masuk,
D12 jumlah grid) DITUTUP: koordinator mengonfirmasi keduanya kini tertangkap. 308 tes preset+golden OK di kedua
Python; tier-1 byte-identik; render nyata klip_04 (tiga dan enam thumbnail) benar: thumbnail ketiga terlihat
mid-pop, tag muncul sesudah thumbnail terakhir, tata letak enam thumbnail dua baris. Biaya render (koordinator,
interleaved, 4 putaran, klip nyata 52 s, overlay 6 s): **+3,2%**. Mutan: 12/12 worker; **koordinator 11/17: 6
lolos** — `UI_THUMB_STAGGER = 0,3` (spesifikasi: jeda 80 ms), `UI_CARD_Y = 300` dan `UI_CARD_W = 900`
(spesifikasi: bawaan `x=60, y=260, w=960`), serta `UI_THUMB_GAP_X`, `UI_INPUT_H`, `UI_CARD_RADIUS`. Penyebab:
tes menghitung ekspektasi dari konstanta modul yang sama sehingga mengubah konstanta ikut mengubah ekspektasi
(berbeda dengan `chart_grow` yang punya angka literal). **Celah tes yang perlu ditutup**: kunci literal untuk nilai
yang ditetapkan spesifikasi (rect bawaan, jeda 80 ms, radius ≈ 48) — dikerjakan bersama langkah integrasi
`phone_frame`.

**Status Langkah 5b-5 dan 5b-7 — `phone_frame` + integrasi + uji gabungan (2026-11-02): SELESAI, diverifikasi
koordinator.** `phone_frame` dibangun sebagai MODUL TERISOLASI (`scripts/presets_phone.py`, 683 baris; 51 tes) agar
bisa dikerjakan paralel dengan `ui_panel` tanpa menyunting `presets.py` bersamaan; lalu 5b-7 mengintegrasikannya
mekanis lewat 5 kait yang ditulis modul itu sendiri (`INTEGRATION`): `_build_phone_frame` (impor malas, bebas
siklus), entri `REGISTRY`/`PRESET_TYPES`, cabang event di `build_fx_ass`, tanpa duplikasi Style `Sans`. Ponsel datar:
badan hitam radius 56, layar inset 14, notch, judul + garis aksen, 2–4 baris bullet yang muncul berjeda 180 ms,
meluncur kaku 140 px dari sisi (`side` kanan/kiri) selama 0,35 s; tanpa pop skala (keterbatasan libass, tertulis).
Uji gabungan lewat `render_clip`: satu klip berisi kelima jenis overlay pada jendela terpisah menghasilkan SATU
dokumen fx dan SATU filter `subtitles` fx (koordinator: 72 `Dialogue`, 19,5 s render untuk klip_04 52 s). 370 tes preset
OK di kedua Python. Mutan: 11/11 + 10/10 worker; **koordinator 18/18** (enam mutan `ui_panel` yang dulu lolos kini
tertangkap lewat penguncian literal + hash dokumen, plus 12 mutan konstanta `phone_frame`). Render nyata klip_04
dengan kelima preset: semua tampil benar (zoom-through, checklist 3 of 3, chart + tag, ui_panel enam thumbnail,
ponsel di sisi kanan dengan empat baris). Pada close-up ponsel di slot kanan-atas menutupi mata/telinga kanan —
sama seperti kartu: pemilih harus memberi `rect` atau melewatinya (lihat `docs/TIER2-USAGE.md` §3).

**Status Langkah 5b-6 — efek `pullback` (2026-11-02): SELESAI, diverifikasi koordinator (poles menyusul di 5b-8).**
`scripts/pullback.py` (828 baris, modul terisolasi) + kait ADITIF di `render.py` (0 baris dihapus; urutan filter:
panel tier-1 → pullback → ASS pullback → fx subtitles → pratinjau → caption). Rancangan filter: `trim`+`concat`
per segmen sehingga hanya frame di dalam jendela yang melewati `scale eval=frame` + `overlay` (bukan gerbang
`enable`), latar krem, kurva smoothstep, count-up bertingkat (28 `Dialogue`), sudut membulat saat stabil. Tier-1
byte-identik terhadap HEAD (harness koordinator); 1267 tes seluruh suite, hanya 4 `procmem` lama gagal, di kedua
Python; 39 tes pullback. Render nyata klip_04 (overlay 30–38 s, 12 → 88%): jumlah frame (1562) dan durasi video/audio
IDENTIK dengan render tanpa efek; video menyusut ke jendela 9:16 dengan sudut membulat, angka menghitung, video
membesar kembali. Biaya render (koordinator, interleaved 4 putaran, overlay 6 s): **+2,7%** (angka worker −2,2%
adalah derau). Mutan: 13/13 worker; **koordinator 9/14**; lolos: `CORNER_RADIUS = 0`, `DEFAULT_GROW = 0,3`,
`NUMBER_AREA_BOTTOM = 400`, warna angka (tes menghitung ekspektasi dari konstanta yang sama) dan satu mutan
setara. **Cacat visual nyata**: elemen UI (label, judul) bertahan sepanjang jendela overlay sehingga tampak DI ATAS
video saat shrink/grow (t = 30,3 dan 37,7 s) → diperbaiki di 5b-8 (UI hanya pada fase stabil dengan fade) bersama
penguncian literal default.

**Status Langkah 5b-8 — poles `pullback` (2026-11-02): SELESAI, diverifikasi koordinator.** Semua elemen UI
(judul, angka, label, hiasan) kini hanya tampil pada fase STABIL dengan fade 120 ms (masuk sesudah shrink selesai,
keluar selesai tepat saat grow mulai); selama transisi tidak ada piksel teks di atas video. Render nyata klip_04
(30–38 s): frame t = 30,2 / 30,45 (shrink) dan 37,5 / 37,7 / 37,85 (grow) bersih; frame 31,0 dan 34,0 menampilkan
"53%" lalu "88%". Default dikunci literal (jendela `216/640/648/1152`, `shrink` 0,6, `grow` 0,5, `count` 1,2, radius
36, warna angka `#1B1B1F`, area angka 600). 47 tes pullback; koordinator memverifikasi 57 tes pullback+golden+gabungan
OK di kedua Python, tier-1 byte-identik. Mutan koordinator **13/14** (keempat yang dulu lolos kini tertangkap; satu
sisanya setara karena `pullback.ass(None)` memang mengembalikan `None`). **Ketujuh efek referensi kini lengkap dan
terverifikasi:** #05 zoom (tier-1 `punch`), #09 `zoom_through_text`, #07 `checklist`, #10 `chart_grow`, #03 `ui_panel`,
#06 `phone_frame`, #11 `pullback`.

### Langkah 3 — Kinetic captions per kata (ASS) + font + pratinjau

**File:** buat `scripts/lib/spring.py`, `scripts/lib/fontmetrics.py`, `scripts/kinetic.py`,
`templates/caption_kinetic.ass.tmpl`, `assets/fonts/<font OFL>.ttf` + `OFL.txt` + `SOURCES.md`
(sha256); ubah `render.py` (pilih penulis ASS menurut `caption_style`; `preview`; `-r` dari
parameter), `cli.py` (`render --preview`, `fontsdir` bawaan ke `assets/fonts`).

**Spring** (persamaan peredam massa-pegas, respons langkah dari 0 ke 1):
`ω0=√(k/m)`, `ζ=c/(2√(km))`, `ωd=ω0√(1−ζ²)`
`ζ<1: x(t)=1−e^(−ζω0t)(cos ωd t + (ζω0/ωd) sin ωd t)`
`ζ=1: x(t)=1−e^(−ω0t)(1+ω0t)`
`ζ>1: x(t)=1−(r2·e^(r1t) − r1·e^(r2t))/(r2−r1)`, `r1,2=−ω0(ζ∓√(ζ²−1))`.
Bawaan "pop kata": `m=1, k≈700, c≈32` → ζ≈0,60, overshoot ≈ 9%, settle 2% ≈ 0,25 s,
puncak ≈ 0,15 s. Skala kata `60% → 100%` mengikuti `x(t)`, alpha 0→1 dalam 2 frame.
Disampel tiap frame (33,3 ms) sampai settle (≤ 10 segmen) → `\t(t0,t1,\fscx..\fscy..)` berantai.

**Layout kata:** greedy line-break dengan `fontmetrics` (batas 90% × 1080, maks 2 baris),
posisi kata dihitung dari **frasa lengkap** supaya kata yang sudah tampil tidak bergeser
saat kata berikutnya muncul; tiap kata = satu `Dialogue` dengan `\an5\pos(x,y)`.
Kata emphasis: warna aksen permanen + skala 112% (sama dengan keputusan lama).
Keluar frasa: potongan keras (konsisten dengan keputusan "fade-out nol" di `captions.py`).
`fontmetrics` membaca `cmap` + `hmtx` TTF dengan `struct` (tanpa dependensi).

**Tes dulu**
- `tests/test_spring.py`: x(0)=0, x(∞)→1 (±0,5% pada 3 s); overshoot ≈ `exp(−πζ/√(1−ζ²))` (±1%);
  ζ ≥ 1 monoton; sampler mengembalikan tepat `ceil(dur·fps)+1` titik di waktu frame.
- `tests/test_fontmetrics.py`: `width("WW")==2·width("W")`; font monospace (DejaVuSansMono)
  → semua huruf sama; glyph hilang → advance `.notdef`; hasil deterministik.
- `tests/test_kinetic.py`: satu `Dialogue` per kata; `start` ASS = `word.start` ±10 ms
  (setelah `lead`); jumlah lebar kata + celah ≤ 0,9×1080; setiap baris `Dialogue` punya
  tepat 10 field (koma di teks aman); `{`, `}`, `\` di-escape; build tier-1 tidak berubah
  (`build_ass` identik byte pada input lama); `chain(\t)` pada waktu frame = spring analitik ±2%.
- `tests/test_fontmetrics_oracle.py` (*skipUnless ffmpeg+libass*): render "WWWW iiii" di latar
  hitam, ukur bbox dari frame mentah gray8 (stdlib), selisih dengan `fontmetrics` ≤ 3%.
  Ini juga mendeteksi **font fallback senyap** ke DejaVu.
- `tests/test_kinetic_render.py` (*skipUnless ffmpeg*): klip hitam 2 s; frame di
  `word.start−0,1 s` kosong di bbox kata, frame `word.start+2/fps` berisi piksel.

**`lead`:** tampilkan kata 40 ms lebih awal (default, dapat diubah). Teks yang telat terasa
lebih salah daripada yang sedikit mendahului; ASR Whisper melenceng puluhan–ratusan ms
**[T: docs/PIPELINE.md §2]**.

**Selesai bila:** semua tes hijau; `render --motion 2` pada `work/jkt48` `clip_01` memakai
waktu ≤ 1,3× tier-1 (median 3 run, sesi yang sama); spot-check 30 kata acak: ≥ 90% mulai dalam
±80 ms dari onset suara pada waveform; `render --preview` klip 20 s ≤ 6 s **[P]**.

### Langkah 4 — Layout sadar wajah (Python murni)

**File:** ubah `scripts/faces.py` (simpan `h`; tulis `reframe.face_track`; ekstrak
`crop_x_at(timeline, crop_w, free_x, t)` agar ramp 0,4 s tidak diduplikasi dengan
`crop_expression`), `scripts/cli.py` (subperintah `layout`), `scripts/motion.py`
(`overlay_filters` membaca `rect`), `scripts/kinetic.py` (baca `layout.caption`);
buat `scripts/layout.py`.

**Koordinat:** wajah YuNet di ruang sampel 640×360 → piksel sumber (×3) → keluar crop
(`x_out=(x−crop_x(t))·1080/608`, `y_out=y·1920/1080`) → inflasi untuk punch (zoom tengah
(540,960), skala maks pada jendela). `face_track` = amplop (min/max) tiap wajah **per shot**,
bukan per frame (alasan sama dengan `docs/REFRAME.md`: per frame gemetar).

**Aturan layout** (deterministik, diurutkan):
1. Zona terlarang = semua wajah pada shot di jendela itu, diperbesar 8% dan dikali skala punch maks.
2. Caption: kandidat berurutan `y=1400` (bawah-aman) → `y=330` (atas) → perkecil 15% di
   posisi pertama; **caption tidak pernah dibuang**. Berubah paling banyak sekali per shot,
   tidak pernah di tengah frasa.
3. Overlay: ambil slot bebas pertama menurut urutan per tipe (`top_safe=(60,260,960,300)`,
   `mid_low=(60,1000,960,240)`; nilai awal, diaudit); bila tak ada, overlay opsional
   dilewati. Tidak boleh menimpa caption maupun overlay lain.
4. Zona aman platform: atas 250 px, bawah 480 px, kanan 120 px **[P: panduan umum
   Reels/TikTok; verifikasi ke spesifikasi]** sebagai konstanta tunggal.
5. Tanpa `face_track`: zona bawaan (perilaku sekarang untuk caption).

**Tes dulu**
- `tests/test_crop_x_at.py`: `crop_x_at` = evaluasi `crop_expression` (konversi `clip(`→fungsi
  Python di dalam tes) pada 50 titik waktu acak.
- `tests/test_face_track.py`: sampel sintetis dua shot → amplop per wajah, koordinat keluaran
  sesuai rumus; wajah tak terdeteksi → entri dilewati.
- `tests/test_layout.py` (properti): untuk grid pusat wajah `cx, cy ∈ {0.2, 0.3, …, 0.8}`
  dan skala punch `{1.0, 1.14, 1.20}`: kotak caption (dari `fontmetrics`) tidak memotong wajah
  terinflasi; fallback atas dipakai bila wajah menutup zona bawah; satu wajah raksasa
  → caption diperkecil, tetap tidak memotong; keluaran identik pada dua panggilan.
- `tests/test_layout_real.py` (*skip bila `work/jkt48/edl.json` tak ada*): 3 klip nyata,
  nol frame dengan caption ∩ wajah.

**Selesai bila:** `python3 -m scripts.cli layout work/jkt48` mencetak audit "caption∩wajah: 0
frame, overlay∩wajah: 0 frame" pada 3 klip, plus angka pembanding **sebelum** untuk panel VS
tier-1 (membuktikan temuan #4 benar atau salah); waktu `layout` < 1 s per klip.

### Langkah 5 — Bentuk/garis/highlight ASS + transisi (durasi dipertahankan)

**Pemecahan (2026-11-02, keputusan koordinator):** **5a = `shapes.py` (SELESAI)**, dibutuhkan semua preset 5b.
**Transisi (`flash`/`whip`, `transitions.py`) DITUNDA**: tidak dibutuhkan satu pun dari 7 efek referensi;
dikerjakan setelah preset bila masih diinginkan. Preset pertama yang tidak butuh layout sadar wajah:
`zoom_through_text` dan `checklist`; `ui_panel`/`pullback`/`phone_frame` menunggu Langkah 4 (di klip_04 wajah
memenuhi ±60% atas frame sehingga zona atas pasti bertabrakan).

**File:** buat `scripts/shapes.py`, `scripts/transitions.py`; ubah `scripts/motion.py`
(`zoom_expression` mendukung ramp berbasis frame, fungsi lama utuh), `render.py`
(sisipkan fragmen transisi), `edl.py` (isi `transitions` di tier 2).

**Transisi: tidak boleh mengubah durasi.** `xfade`/`acrossfade` memendekkan timeline sebesar
overlap; itu menggeser `out_start`, semua caption/punch/overlay, dan memotong kata di
sambungan karena jeda sudah dibuang (`docs/SEGMENTS.md`). Jenis yang dipakai:
- `flash`: tiga `drawbox white@α enable='between(t,..)'` dengan α 0,9 / 0,6 / 0,3 (satu frame
  masing-masing) di sambungan. `drawbox`+`enable` sudah terbukti di panel VS.
- `whip`: ramp skala `zoompan` berbasis frame, 1,0→1,25 empat frame sebelum sambungan,
  kembali empat frame sesudahnya. Frame zoompan = frame output karena `fps=` dinormalisasi
  sebelum zoompan (`render.py:101-102`).
- SFX `whoosh` di sambungan hanya bila tidak ada punch dalam ±0,3 s.
- Dilewati bila segmen < 2×`dur` atau di t=0.

**Bentuk (ASS `\p1`):** `shapes.rect/rounded_rect/line/circle` mengeluarkan string path
(`m l b`) dalam koordinat PlayRes; animasi lewat `\t(\fscx)`, wipe lewat `\clip`; digambar di
Layer 0, teks di Layer 1. Pemakaian awal: highlight bar di belakang kata emphasis (sapuan
kiri→kanan 150 ms), garis bawah, sudut-sudut penanda.

**Tes dulu**
- `tests/test_shapes.py`: path dimulai `m`, semua koordinat dalam 0..PlayRes, bentuk tertutup,
  `\clip` wipe mulai/selesai tepat di waktu yang diminta.
- `tests/test_transitions.py`: fragmen filter per jenis (string); `join_time` = `out_start`
  segmen ke-`seg`; dilewati untuk segmen pendek; **(skipUnless ffmpeg)** jumlah frame dan durasi
  audio sama dengan render tanpa transisi (±1 frame AAC = 21 ms); luma frame sambungan
  > luma frame tetangga untuk `flash`.
- `tests/test_motion.py` tambahan: `zoom_expression` lama menghasilkan string identik (golden).

**Selesai bila:** tes hijau; biaya render ≤ +10% dibanding Langkah 3 (median 3 run);
tiga klip `jkt48` dirender, jumlah frame = `round(Σdurasi·30)`.

### Langkah 5b — Preset efek referensi: 7 dari 17 (ASS + ffmpeg, tanpa Chromium)

**Dasar.** Analisis video referensi "17 video effects" memberi 7 efek yang tidak butuh person matte.
Vonis gate Remotion di `benchmarks/remotion.json` adalah `NO_GO` (RSS 1,4–1,8 GB > 1,0 GB), jadi
Langkah 6 dibekukan dan **semua efek di bawah dibuat dengan ASS (`\p1`, `\t`, `\clip`) dan
ekspresi ffmpeg**. Pola tier-1 yang diteruskan: overlay = `drawbox`/`drawtext` dengan jendela
`enable` (lihat `motion.overlay_filters`, tipe `vs`). Tier-2 menambah tipe baru pada `overlays[]`
yang sama, satu daftar, satu basis waktu (output timeline), dikonversi ke frame sekali di akhir.

**Batas yang harus jujur.** Ini versi **datar** dari efek referensi: tanpa tilt 3D perangkat,
tanpa gradien lembut atau kaca buram, tanpa emoji/ikon berwarna, tanpa blur latar. Kemiripan
dinilai pada struktur gerak (masuk, tahan, keluar, urutan, easing) dan tata letak, bukan
pada kilau permukaan. Itu harus dikatakan kepada pengguna, bukan disembunyikan.

Kontrak umum tiap preset: `overlays[]` item `{"type", "start", "end", "props", "rect"?}`;
`rect` default dari zona layout (Langkah 4) dan boleh ditimpa; masuk 0,25–0,35 s dengan easing
ease-out kubik atau spring (`lib/spring.py`), keluar 0,20 s; **tidak mengubah durasi, jumlah
frame, maupun timing caption**; tidak menutup kotak wajah (`face_track`) bila ada; caption
(`subtitles`) tetap filter terakhir; tanpa font yang tersedia → preset dilewati dengan satu
baris peringatan di `report.md`, **bukan exception**; deterministik (EDL sama → hash frame sama).
Modul: `scripts/presets.py` (fungsi murni → daftar event ASS + fragmen filter), memakai
`scripts/shapes.py` (Langkah 5). Font: satu serif italic OFL tambahan di `assets/fonts` untuk
`zoom_through_text` (OFL.txt + sha256, aturan sama dengan Langkah 3).

| # | Efek referensi | Preset | Mekanisme | Props |
|---|---|---|---|---|
| 05 | digital zoom | — | sudah ada: `punch` tier-1; tidak ada pekerjaan baru | — |
| 03 | ui world | `ui_panel` | kartu putih krem membulat menutup zona atas; header, deretan kotak thumbnail, tag kuning, bilah input; masuk slide-turun | `title`, `tag`, `thumbs` (1–6) |
| 07 | checklist | `checklist` | kartu gelap semi-transparan; lingkaran per item yang terisi + centang (path ASS) pada `done_at` dengan pop spring; penghitung "n of N" | `title`, `items[{text, done_at}]` |
| 10 | chart grow | `chart_grow` | sumbu label + polyline yang tumbuh kiri→kanan lewat `\clip` wipe 1,2 s ease-in-out; titik ujung + tag mengikuti | `labels`, `values`, `tag` |
| 11 | pull-back reveal | `pullback` | video mengecil dari 1080×1920 ke jendela `rect` (`scale` ber-`eval=frame` + `overlay` ber-ekspresi) di atas latar krem + chrome UI datar; count-up angka | `from`, `to`, `suffix`, `window` |
| 06 | phone mockup | `phone_frame` | perangkat datar (rounded rect hitam, layar gelap, notch) di slot kanan-atas, masuk slide + pop; 3–4 baris teks; **tanpa tilt 3D** | `title`, `lines` |
| 09 | zoom-through | `zoom_through_text` | teks serif miring besar: skala 0,8→3,2 dalam 0,7 s, alpha 1→0 pada 40% terakhir; satu event ASS dengan rantai `\t` | `text` |

**Tes dulu (per preset, pola sama).**
- Murni (tanpa ffmpeg): struktur event ASS (jumlah `Dialogue`, 10 field tiap baris, `{` `}` `\` di-escape);
  geometri path (tertutup, semua koordinat dalam PlayRes, `rect` dihormati); fungsi waktu monoton
  (skala `zoom_through_text`, lebar tampak `chart_grow`, nilai `count-up` `pullback`);
  `start/end` di luar durasi klip dipotong; tanpa font → `[]` dan peringatan; keluaran identik
  pada dua panggilan; props tak valid (daftar kosong, `done_at` di luar `[start,end]`) ditolak dengan
  pesan jelas, bukan crash.
- *skipUnless ffmpeg+libass* pada klip hitam sintetis 3 s @30: piksel sebelum `start` identik
  dengan klip tanpa preset; piksel pusat elemen pada `start+entry+2 frame` = warna elemen (±4);
  sesudah `end+exit+2 frame` identik lagi dengan tanpa preset; jumlah frame dan durasi audio sama
  dengan tanpa preset (±1 frame AAC); khusus `checklist`: warna lingkaran berubah tepat pada frame
  `done_at` (±1 frame); `pullback`: bounding box video pada frame akhir transisi = `window` (±2 px).
- Tes lama: golden EDL, golden `zoom_expression`, golden `filter_complex` tier-1 tetap hijau (R8).

**Selesai bila:** tes hijau; satu **contact sheet** per preset dari klip uji (sumber nyata, bukan
hanya hitam) dihasilkan ke `work/**/presets/` dan saya memeriksanya secara visual terhadap
referensi; biaya render ≤ +10% per preset terhadap Langkah 3 (median 3 run, sesi sama); `make test`
tanpa ffmpeg tetap hijau.

### Langkah 7 — "Direktur efek": bagaimana agen memilih efek per klip (USULAN, belum dibangun; 2026-11-02)

**Masalah.** Efek sudah ada tetapi SATU-SATUNYA cara memakainya sekarang menulis `overlays[]` ke EDL dengan tangan.
Tier-1 hanya punya satu pemicu otomatis (`motion.detect_vs`: pola "A vs B" → panel VS). Tidak semua efek cocok untuk
semua klip, dan memakai semuanya adalah kesalahan (efek = bumbu; kartu yang menutupi wajah pada close-up merusak klip).

**Prinsip (sama dengan skor tier-1): kode mengekstrak fakta dan menegakkan batas; agen memutuskan; pengesah menolak
yang melanggar.** Tiga lapis:
1. **Fakta deterministik** (`scripts/fxfeatures.py`, murni, tanpa model): per klip, pada timeline OUTPUT dengan waktu kata:
   angka/persen/perbandingan "dari X ke Y"/"naik/turun N%", daftar berurutan ("pertama… kedua…", "tiga hal"),
   pertanyaan retoris/hook, kata beraksen (emphasis tier-1), nama produk/aplikasi/layar (kapital berulang), jeda/titik
   punchline; plus konteks visual: rasio tinggi wajah per segmen dari `face_track` (close-up ≥ ±0,5 / sedang / lebar),
   jadwal punch, kerapatan caption, jendela hook (2 s pertama) dan penutup. Keluaran `fx_candidates.json`: daftar
   MOMEN dengan `t0/t1`, jenis pemicu, kutipan, `confidence`, dan efek yang SECARA STRUKTUR memungkinkan.
2. **Katalog efek** (`presets.CATALOG`, mesin-baca): per jenis — kapan cocok, props wajib + batas, durasi tipikal,
   `needs_free_area` (kartu: ya; `zoom_through_text`/`pullback`: tidak), konflik, biaya render. Pemetaan awal:
   | Pemicu isi | Efek | Gerbang |
   |---|---|---|
   | satu angka/persen kunci atau punchline pendek | `zoom_through_text` (aksen, ≤ 2/klip) | jendela ≥ 0,7 s |
   | deret waktu/tren ("naik dari… ke…") | `chart_grow` | wajah bukan close-up atau `rect` eksplisit |
   | daftar/langkah/kriteria (≥ 2 butir) | `checklist` | idem; `done_at` dari waktu kata penutur |
   | menyebut aplikasi/produk/fitur/layar | `ui_panel` atau `phone_frame` | idem |
   | pengungkapan statistik besar sebelum→sesudah | `pullback` (≤ 1/klip) | fase stabil ≥ 1,5 s |
   Default = TIDAK ADA overlay; efek hanya bila momen memenuhi pemicu DAN gerbang.
3. **Pengesah + penerap** (`cli fx-apply`): agen menulis `fx_plan.json` (pilihan + props + waktu + alasan satu kalimat);
   pengesah menegakkan anggaran dan konflik (mis. ≤ 1 overlay kartu per 10 s dan ≤ 3 per klip, tidak tumpang tindih,
   jarak ≥ 4 s, tidak di jendela hook kecuali efek itu hook-nya, tidak menutup wajah pada close-up tanpa `rect`,
   tidak pada jeda yang dibuang), memakai `PresetError` yang sudah ada untuk props, lalu menulis `clips[].overlays`;
   pratinjau (`render --preview`) dan lembar kontak kecil dibuat untuk ditinjau agen/pengguna sebelum render final.
**Mode otonomi (keputusan pengguna):** (a) `off` — tidak ada overlay otomatis (bawaan yang aman), (b) `suggest` —
agen menulis `fx_plan.json` dan pengguna menyetujui, (c) `auto` — agen memilih dan pengesah menjaga batas.
**Kombinasi:** caption kinetic + `punch` selalu menyala; efek berat (kartu) tidak berimpit dengan `punch` kuat atau
dengan `zoom_through_text`; palet konsisten per klip (satu `accent`). **Yang tidak bisa dijamin kode:** apakah sebuah
momen "layak" secara editorial — itu penilaian agen; pengesah hanya mencegah yang jelas salah. Perkiraan: ±4–5 putaran
worker (ekstraktor + katalog, pengesah/CLI, uji pada klip_04 dan satu klip lebar, dokumentasi skill).

**Status Langkah 7a (2026-11-02): SELESAI dengan DUA temuan, diverifikasi koordinator.** `scripts/fxcatalog.py` (567 baris:
enam efek, batas props DIBACA dari konstanta preset, anggaran satu tempat), `scripts/fxfeatures.py` (1000 baris; pemicu
`number/trend/list/question/product/emphasis/reveal`; `shot_kind` dari `face_track`; `fits` per efek memakai `layout`),
`schema/fx_candidates.schema.json`, `cli fx-catalog` dan `cli fx-candidates` (aditif, 0 baris dihapus; `edl.json`
tidak berubah). 37 tes OK di kedua Python; worker 14/14 mutan. Pengujian koordinator pada kalimat Indonesia tulisan
tangan (12 kasus): 11/12 sesuai harapan — idiom ("satu-satunya"), "pertama kali", kalimat biasa TIDAK terpicu; angka, tren
dari-ke, tren tahun, daftar, hook, aplikasi, "download/install" terdeteksi. Klip_04 nyata: 23 shot semuanya `close_up`
(tinggi wajah 0,42–0,65 — cocok dengan pengamatan visual), 7 momen semuanya `emphasis` (isi klip memang tanpa angka/daftar).
**Temuan 1 (MAYOR, kesalahan spesifikasi koordinator): `fits` membandingkan durasi MOMEN dengan jendela minimum efek.**
Kata beraksen berdurasi 0,16 s membuat SEMUA efek ditolak ("jendela 0,16 s < min 0,40 s") padahal overlay lazimnya
berjalan melewati momen pemicunya (aksen 0,7 s mulai di kata itu; grafik 5 s mulai di frasa "naik dari…"). Yang benar =
JENDELA TERSEDIA (dari awal momen sampai batas berikut: akhir klip dikurangi margin / overlay lain / jendela terlarang),
bukan durasi pemicu. Tanpa perbaikan, mode `suggest` tidak akan pernah menawarkan efek. Diperbaiki di 7b.
**Temuan 2 (minor):** kalimat "Ternyata hasilnya 3 kali lipat lebih besar" hanya terdeteksi `number`, tidak `reveal`.

**Status Langkah 7b — `fits` jendela tersedia + pengesah rencana + `fx-validate` (2026-11-03): SELESAI, diverifikasi
koordinator.** Temuan 1 dan 2 dari 7a diperbaiki: momen punya `trigger_duration`, `available_window` (dibatasi akhir
klip/overlay berikutnya) dan `suggested_window` per efek; `fits` memakai jendela TERSEDIA. Pada klip_04 nyata kata
beraksen "nggak" (0,16 s) kini: `zoom_through_text` `ok=True` dengan `suggested_window` 2,82–3,52 s; kartu tetap `False`
karena close-up (alasan benar). `reveal` pulih untuk kalimat yang sama. `scripts/fxplan.py` (560 baris) +
`schema/fx_plan.schema.json` + `schema/fx_plan_report.schema.json` + `cli fx-validate` (menulis laporan JSON + MD;
tidak pernah menulis `edl.json`; keluar 0 saat ada penolakan). 1401 tes seluruh suite OK di kedua Python (hanya 4
`procmem` lama); tier-1 byte-identik. Mutan: 15/15 worker, **koordinator 12/12**. Uji nyata koordinator (rencana 8 item pada
klip_04, melalui CLI): `zoom_through_text` pada "nggak" DITERIMA; `checklist` tanpa `rect` pada close-up DITOLAK ("tidak
ada area bebas; beri rect eksplisit atau pilih zoom_through_text/pullback"); `checklist` dengan `rect` di area dahi
DITERIMA DENGAN PERINGATAN ("beririsan dengan zona wajah, 100%"); dua aksen terlalu dekat DITOLAK (jarak < 4 s); item
ke-4 DITOLAK (anggaran 3); kartu di jendela hook DITOLAK; aksen berimpit `punch` DITERIMA + peringatan.
**Status Langkah 7c — `fxapply` (2026-11-03): SELESAI, diverifikasi koordinator.** `scripts/fxapply.py` (623 baris):
`load_report`, `select`, `apply_to_edl` (murni, idempoten), `check_fresh` (laporan basi), `validate_edl_overlays`,
`preview` (render pratinjau dari SALINAN EDL + lembar kontak tanpa numpy/OpenCV; `edl.json` dan `out/` identik byte-per-byte),
`apply` (wajib `approve=True`; cadangan bernomor; tulis atomik; hanya `overlays[]` berubah; idempoten), `undo`. 49 tes OK;
uji end-to-end koordinator: preview 8,8 s, `apply` tanpa persetujuan ditolak dan `edl.json` utuh, `apply` dengan
persetujuan mengubah HANYA `overlays[]`, panggilan kedua menambah 0, `undo` memulihkan byte-per-byte. Mutan koordinator
6/8; lolos: kesamaan overlay yang mengabaikan `rect` atau `props` (dua overlay berbeda isi tetapi tipe/waktu sama bisa
dianggap duplikat) → ditutup di 7d. Temuan lembar kontak: `rect` kartu di zona caption (y≈1000–1520) bertumpuk dengan
caption; pengesah belum memperingatkan tabrakan dengan zona caption → ditambahkan di 7d.

**Status Langkah 7d — CLI `fx-preview`/`fx-apply`/`fx-undo`, zona caption, e2e `suggest` (2026-11-03): SELESAI,
diverifikasi koordinator. Mode `suggest` LENGKAP.** `cli.py` bertambah (hanya satu baris impor diubah);
`fx-apply` tanpa `--approve` mencetak ringkasan dan keluar dengan kode 2 (`edl.json` utuh); galat `FxApply*`
menjadi satu baris pesan. Aturan pengesah ke-10: `rect` kartu/ponsel yang beririsan dengan kotak caption pada
jendela overlay → `accepted_with_warnings` (menyebut persen irisan dan frasa). Celah tes `fxapply` (kesamaan overlay
dengan `rect`/`props` berbeda) ditutup. 1420 tes seluruh suite OK di kedua Python (hanya 4 `procmem` lama); tier-1
byte-identik; mutan worker 11/11, koordinator 6/7 (lolos: nilai persen di teks peringatan caption tidak dikunci).
**Uji ujung-ke-ujung koordinator memakai CLI asli pada klip_04 nyata** (`fx-candidates` → rencana 3 item → `fx-validate`
[2 diterima, 1 diterima+peringatan: `rect` di y=1100 menimpa wajah 100% dan empat frasa caption] → `fx-preview` [video
pratinjau + lembar kontak 3 frame; `edl.json` identik] → `fx-apply` tanpa persetujuan [kode 2; `edl.json` identik] →
`fx-apply --approve` [cadangan; 3 overlay] → `render` produk [1562 frame, audio identik, 14,6 s] → `fx-undo` [`edl.json`
identik byte-per-byte dengan awal]). Instruksi agen ditulis di `SKILL.md` Langkah 4 dan `docs/TIER2-USAGE.md` §7
(termasuk aturan: data grafik/checklist/pullback HARUS berasal dari ucapan di klip, tidak boleh dikarang).
Catatan teknis: aturan 10 membungkus perhitungan irisan dengan `except Exception: pass` (galat diam-diam menghilangkan
peringatan; layak dipersempit).

**Uji pada video pengguna (2026-11-03): "Nasib Youtube Saya di Tangan Mereka", 41:38, podcast beberapa pembicara.**
Alur skill penuh dijalankan di `work/rd_nasib/` (gitignored): `run` (718 atom → 15 kandidat), penilaian agen 15 kandidat
(`score-validate` lolos), `build-edl --motion 2 --top 3` (klip 27,7 / 34,7 / 50,6 s), `faces --face-track`,
`fx-candidates`, rencana efek, `fx-validate`, `fx-preview`, persetujuan pengguna, `fx-apply --approve`, `render` final
(27 s untuk tiga klip; 831/1041/1518 frame = durasi × 30, `scripts.verify` 0 bermasalah). Pengguna membuang `checklist` dan
meminta transisi `zoom_through_text` "5.000 view" diperlambat (0,7 → 1,2 s via `props.duration`); dua overlay diterapkan.
**Tiga temuan pada data nyata (DIPERBAIKI di Langkah 7e dan 7f, lihat di bawah):**
1. **Pengesah menyuntikkan `rect` yang menyusut** untuk kartu tanpa `rect` eksplisit (`layout.place_overlay` mengecilkan
   ukuran bawaan ke slot 240–300 px; tinggi `checklist` 3 butir = 328 px) sehingga `fx-validate` MENERIMA tetapi
   `fx-preview` gagal ("kartu tidak boleh disusutkan"). Perbaikan: jangan menyuntikkan `rect` menyusut; tolak bila tak ada
   slot yang memuat ukuran penuh, atau biarkan preset memakai posisi bawaannya setelah dicek terhadap zona wajah.
2. **Pemicu `product` salah deteksi** pada kapitalisasi hasil ASR ("Deal.", "Oke.", "Tidak", "Vue-nya"); semua momen
   `product` pada tiga klip ini palsu. Perbaikan: wajibkan leksikon aplikasi/produk atau kapital di tengah kalimat yang
   berulang DAN bukan awal kalimat hasil ASR.
3. **Pemicu `list` salah satu kali** pada potongan kacau "Tidak ke pertama".
**Status Langkah 7e/7f (perbaikan tiga temuan; diverifikasi independen).**
- **7e:** `fxcatalog.required_size(type, props)` menurunkan ukuran kartu dari geometri preset asli (bukan angka statis);
  `layout.scan_free_rect` menempatkan kartu berukuran PENUH tanpa menyusutkan (menghindari zona wajah, zona aman, caption, dan
  overlay lain); `fxplan.validate` menjalankan ulang pembuat preset pada overlay final sehingga item `accepted` dijamin lolos
  `fx-preview` (invarian diuji: sapuan 81 item nyata, 0 pelanggaran). Pemicu `product` hanya dari leksikon aplikasi, kata kerja
  layar + objek, atau kapital berulang non-awal-kalimat di luar daftar henti dan gelar orang; pemicu `list` butuh penanda
  urutan berbeda dan naik atau isyarat jumlah.
- **7f (cacat sisa dari verifikasi 7e):** `phone_frame` tanpa `rect` kini menghormati `side` (x=640 kanan/bawaan, x=60 kiri;
  di pengesah dan `fits`); kata kerja layar persis daftar spesifikasi (`cari` hanya sebagai `cari di`; `pasang`/`tekan`
  dihapus); objek kata kerja layar berhenti di batas kalimat; 9 tes baru menutup celah yang dibuktikan mutan koordinator.
- **Hasil:** 1453 tes (hanya 4 kegagalan `test_procmem` lama, butuh /proc Linux); tier-1 byte-identik dengan HEAD; momen `product`
  dan `list` palsu pada tiga klip pengguna dan tujuh klip kandidat lain: 0; momen `number` tetap.
- **Batas yang diketahui (belum ditangani):** (1) nama tempat/orang yang diucapkan berulang di tengah kalimat ("Jakarta")
  tetap lolos aturan kapital berulang dan menjadi `product` lemah (`evidence.source = repeated_capital`; agen wajib menimbang
  dan mengabaikannya bila bukan produk); (2) tes belum mengunci bahwa kata sebelum "di" selain `cari` bukan kata kerja layar
  (kode benar, hanya celah tes); (3) tinggi `phone_frame` 3 baris (660 px) hampir tak pernah muat pada bidikan sedang/lebar
  nyata, sehingga biasanya ditolak dengan alasan jelas (agen dapat memberi `rect` eksplisit).

Catatan kualitas: Groq menghasilkan transkrip kacau pada bagian obrolan tumpang tindih ("Yono Bakri", "Bihangkudman");
klip dipilih dari bagian yang relatif bersih, tetapi ejaan caption tetap perlu diperiksa pengguna.

### Langkah 6 — Overlay Remotion sparse (**bersyarat** vonis Langkah 1 ≠ `NO_GO`; vonis aktual: `NO_GO`, dibekukan)

**File:** buat `remotion/` (`package.json` dengan versi dipin, `src/Root.tsx`,
`src/compositions/{Callout,LowerThird,Stat}.tsx`, `render.mjs`), `scripts/overlay_remotion.py`;
ubah `render.py`, `cli.py` (`render --overlays {auto,off}`), `.gitignore`, `Makefile`.

**Jembatan:** Python menulis `props.json` (hanya `overlays[i].props` + `rect` + `fps`) →
`node remotion/render.mjs` (satu bundle, satu browser untuk semua overlay dalam sebatch,
konkurensi 1, `browserExecutable` dari wrapper Chromium) → `work/<x>/overlays/<hash>/%04d.png`.
Overlay dirender **sebesar `rect`-nya** bila spike membuktikan biaya ∝ piksel.

**Komposit ffmpeg** (per overlay, sebelum `subtitles`):
`[k:v]format=rgba,setpts=PTS-STARTPTS+{s}/TB[ov{i}];[{last}][ov{i}]overlay={x}:{y}:eof_action=pass:enable='between(t,{s},{e})'`
dengan input `-framerate 30 -start_number 0 -i overlays/<hash>/%04d.png`. `subtitles`
tetap filter terakhir. Detail `format`/alpha divalidasi pada tes ffmpeg di bawah **[?]**.

**Tes dulu**
- `tests/test_overlay_bridge.py`: tanpa Node (`shutil.which` di-patch) → `available()` False
  dan `render` jatuh ke fallback tanpa exception; hash stabil untuk props sama, berubah bila
  satu karakter props berubah; cache hit tidak memanggil `subprocess`; **props tidak memuat kunci
  `captions`**; watchdog membunuh pohon proses di atas batas.
- `tests/test_render_overlay_chain.py`: tanpa overlay Remotion, string `filter_complex`
  **identik** dengan sebelum perubahan (golden); dengan overlay, `subtitles` tetap terakhir
  dan jendela `enable` cocok.
- `remotion/test/props.test.mjs` (`node --test`, di-skip tanpa Node): validasi props tanpa
  dependensi tambahan.
- (*skipUnless ffmpeg*) komposit PNG sintetis 3 frame: piksel di jendela berubah, di luar
  jendela identik.

**Selesai bila:** klip 20 s dengan dua overlay (≈ 3 s) selesai ≤ 90 s, RSS pohon ≤ gate,
frame akhir = `round(durasi·30)`; render dua kali menghasilkan SHA-256 yang sama untuk PNG
overlay dan untuk 5 frame sampel mp4 (bila mp4 penuh berbeda karena thread, putuskan di
D-011 hash mana yang jadi acuan); `make test` tanpa Node tetap hijau; pratinjau overlay
(still + skala 0,5) ≤ 3 s per still setelah hangat **[P]**.

---

## 6. Risiko (jawaban pertanyaan 5)

| # | Risiko | Peluang [P] | Deteksi paling awal | Mitigasi |
|---|---|---|---|---|
| R1 | **OOM/swap thrash** dengan Chromium (RAM 1,6 GB, swap penuh) | Tinggi pada konkurensi 2, sedang pada 1 | Langkah 1: jumlah RSS pohon, `pswpin/pswpout`, `MemAvailable` minimum | Konkurensi 1, tidak bersamaan ffmpeg, watchdog 1,2 GB, gate `NO_GO` |
| R2 | Remotion lebih lambat dari perkiraan (< 1,5 fps) | Sedang | Langkah 1 | Vonis `NO_GO` membekukan L6; L1–L5 sudah memberi nilai penuh |
| R3 | Metrik font Python ≠ libass (kerning/HarfBuzz) → kata bertumpuk/berjarak | Sedang | Tes oracle bbox (L3), toleransi 3% | Celah antar kata 0,28 em; mode cadangan: satu-dua kata di tengah (tanpa metrik) |
| R4 | **Font fallback senyap** ke DejaVu (nama keluarga TTF statik beda dengan nama di `Style`) | Sedang | Tes oracle yang sama (lebar menyimpang) | Cetak nama keluarga dari tabel `name` TTF saat build; uji `fontsdir` |
| R5 | Kata terlambat/mendahului suara (drift ASR puluhan–ratusan ms) terlihat jelas pada tampilan per kata | **Tinggi** | Spot-check 30 kata di L3 | `lead` 40 ms; bila > 20% kata di luar ±80 ms, kembalikan default ke `phrase` dan catat |
| R6 | Dua sumber waktu: `words` vs `captions` (jendela, MAX_CAP_DUR) → kata hilang/tumpang tindih | Sedang | `test_edl_words`, `test_kinetic` pada klip multi-segmen | Aturan jendela tampil (L2); tes pada `work/jkt48` |
| R7 | Layout salah karena wajah tak terdeteksi / pembicara keliru | Sedang | Audit `layout` pada 3 klip nyata (L4) | Zona bawaan; caption tidak pernah dibuang; hasil audit dicetak |
| R8 | Regresi diam-diam tier-1 | Rendah | Tes golden EDL, golden string `zoom_expression`, golden `filter_complex` | Ketiganya ditulis **sebelum** mengubah kode |
| R9 | Chromium wrapper (`--no-sandbox`) / versi CDP tidak cocok dengan Remotion | Sedang | Langkah 1 (hello-alpha) | Pin versi Remotion yang cocok; `browserExecutable` eksplisit |
| R10 | **Lisensi Remotion** tidak cocok dengan penggunaan (organisasi, bukan individu) | **[?]** | Sebelum L6 (bagian 8) | Keputusan manusia; T2a tidak terdampak |
| R11 | Anggaran render T2a > 1,3× | Rendah–sedang | Ukur tiap langkah L3, L5 | Kurangi event per-frame (translasi), turunkan `\blur`, atur sampel spring |
| R12 | Thermal throttling membuat gate lolos di pagi hari, gagal sore hari | Sedang | Variasi 13–20% sudah terukur di `benchmarks/` | Gate memakai median 3 run dan margin; ulangi spike setelah 5 menit beban |
| R13 | **Mask lolos angka tapi jelek di mata** (rambut tergigit, jari hilang, halo) | Sedang | `preview.mp4` L1b, `human_ok` | Gate manusia wajib; model B (`modnet`) sebagai pembanding; penghalusan temporal diukur terpisah |
| R14 | **Spike L1b dijalankan di mesin yang bukan target** (Mac pengembang jauh lebih cepat) dan angkanya dibaca sebagai vonis | **Tinggi** | `meta.cpu` di JSON | Gate memisahkan vonis kualitas dari kecepatan dan menolak `GO` di luar `i5-7300U` |

---

## 7. Yang ditolak (jawaban pertanyaan 6)

| Pendekatan | Kenapa menarik | Kenapa tidak di sini |
|---|---|---|
| Remotion frame penuh (a) | Satu sistem, React untuk semuanya | Renderer kedua (melanggar D-001); 130–320 s/klip [P]; 1,2–1,8 GB; kualitas scale CSS ≠ lanczos; determinisme tak terjamin |
| Remotion menggarap caption | Spring "gratis", tipografi CSS kaya | Dua sumber kebenaran; 600 frame Chromium vs ≈ 0 libass; metrik font ganda |
| Remotion Lambda / Cloud Run | Render cepat paralel | Render farm masuk **OUT OF SCOPE** (`SCOPE.md`); butuh akun cloud |
| Alpha lewat ProRes 4444 | Satu file overlay | ≈ 40 MB/s → ≈ 800 MB sementara untuk 20 s [P]; membebani disk dan RAM |
| Alpha lewat WebM VP9 | File kecil | Dekoder VP9 native ffmpeg membuang alpha (perlu libvpx); encode VP9 lambat di 2 core [P] |
| `xfade` / `acrossfade` | Transisi mulus bawaan | Memendekkan timeline → `out_start` dan semua timestamp bergeser; memotong kata di sambungan |
| Caption mengejar wajah per frame | Selalu "menghindari" wajah | Jitter; `docs/REFRAME.md` sudah membuktikan per frame gemetar. Layout per shot |
| WebGL/Three.js/shader/partikel | Tampilan mewah | Tanpa GPU: SwiftShader 1–3 fps pada 1080×1920 [P]; tidak sebanding dengan nilainya |
| Lottie / template After Effects | Banyak aset | `lottie-web` jalan di Chromium (biaya sama dengan Remotion); ffmpeg tak mendekodenya |
| MoviePy / numpy per frame di Python | Fleksibel | Tidak ada wheel Python 3.14 (D-004); komposit per frame < 5 fps [P] |
| Pratinjau Remotion lewat `--every-nth-frame` | Hemat frame | Opsi itu untuk GIF **[?]**; pakai `still` + `--scale` + komposisi 15 fps |
| Konkurensi Chromium 2–4 | 1,4–2× lebih cepat | RAM: 0,9–1,4 GB [P] untuk 2 tab; swap penuh → risiko OOM lebih besar daripada untungnya |
| Emoji berwarna lewat libass | Murah | Tidak ada font emoji di sistem; bundel font emoji ±10 MB dan dukungan CBDT di libass **[?]** — masuk jalur Remotion |
| Merender overlay 4K lalu turunkan | Teks tajam | 4× piksel, 4× biaya PNG; tidak ada gunanya untuk keluaran 1080×1920 |

---

## 8. Belum diverifikasi / butuh keputusan manusia

1. **Lisensi Remotion.** Dugaan saya: gratis untuk individu dan organisasi kecil, berbayar di atas
   ambang tertentu. Saya tidak bisa memastikannya dari sini. Periksa `remotion.dev/license`
   dan status pemakai/organisasi **sebelum Langkah 6**. Tidak memengaruhi Langkah 1–5.
2. **Pilihan font OFL** (mis. keluarga sans sangat tebal) dan teks lisensinya. Saya tidak
   mengunduh apa pun; pelaksana memilih, mengunduh, mencatat sha256.
3. **Zona aman platform** (atas 250 / bawah 480 / kanan 120 px) berasal dari panduan umum,
   bukan spesifikasi resmi.
4. **Semua angka [P]** di bagian 3: diganti angka terukur oleh Langkah 1 dan pengukuran L3/L5.
5. **Jumlah tes 183** berasal dari brief; saya tidak menjalankannya. Langkah 2 dimulai dengan
   menjalankan `make test` dan mencatat hitungan sebenarnya sebagai garis dasar.
6. Perilaku `libass` atas `\t` berantai dan `\an5\pos` dengan skala per kata dianggap standar
   (teknik umum karaoke Aegisub) tetapi harus dikonfirmasi oleh `test_kinetic_render.py`
   pada build ffmpeg di mesin ini.
7. Apakah aturan **hash identik** (`PIPELINE.md` §8) berlaku untuk mp4 penuh dengan overlay
   Chromium; putusan acuan hash dicatat di D-011.
8. **Matte (L1b):** normalisasi input `pphumanseg` (mean/std 0,5, RGB) ditulis dari ingatan atas
   demo opencv_zoo, bukan dibaca dari kode; spike memverifikasinya lewat `face_in_matte`. Lisensi
   bobot asal MODNet (di balik konversi ONNX Xenova) dan lisensi RVM belum diperiksa. Semua
   ambang gate matte adalah **[P]** yang dikunci sebelum pengukuran. Efek "vertigo" pada
   referensi hanya terlihat sebagai caption, jadi kebutuhan mask-nya dugaan.

## 9. Perintah rujukan

```bash
make test                        # offline, tanpa ffmpeg khusus, tanpa Node
make test-tier2                  # + tes ffmpeg dan Node (di-skip otomatis bila tak ada)
python3 -m scripts.cli build-edl work/jkt48 --motion 2
python3 -m scripts.cli faces     work/jkt48
python3 -m scripts.cli layout    work/jkt48
python3 -m scripts.cli render    work/jkt48 --top 3 --preview
python3 -m scripts.cli render    work/jkt48 --top 3
python3 benchmarks/gate.py benchmarks/remotion.json
python3 -m benchmarks.matte_bench --video <sumber> --model-kind pphumanseg --start 120 --seconds 6
python3 -m benchmarks.matte_gate  benchmarks/matte.json
```
