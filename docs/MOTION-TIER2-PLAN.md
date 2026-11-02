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

## 0. Keputusan dalam 8 baris

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

Total ≈ 9 hari-orang **[P]**: L1 0,5 · L2 0,5 · L3 2 · L4 1,5 · L5 1,5 · L6 3.
L1 boleh paralel dengan L2–L5; L6 menunggu L1 dan L4.
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

### Langkah 6 — Overlay Remotion sparse (**bersyarat** vonis Langkah 1 ≠ `NO_GO`)

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
```
