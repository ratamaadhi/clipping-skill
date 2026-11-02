# Tier-2 — cara memakai (untuk agen dan pengguna)

Tier-2 menambah tiga hal di atas pipeline tier-1, **semuanya opsional dan aditif**; tanpa flag, keluaran tier-1
byte-identik dengan sebelumnya (D-010). Rencana dan bukti: `docs/MOTION-TIER2-PLAN.md`. Keputusan: D-009 s.d. D-012.

| Fitur | Perintah / field EDL | Butuh |
|---|---|---|
| Caption kinetic per kata (pop spring, kata beraksen) | `build-edl --motion 2` | ffmpeg ber-libass |
| Preset overlay datar (`zoom_through_text`, `checklist`, …) | `clips[].overlays[]` bertipe preset | ffmpeg ber-libass |
| Jalur wajah + audit layout (opsional) | `faces --face-track`, `layout` | OpenCV + model YuNet |

## 1. Alur dasar

```bash
python3 -m scripts.cli build-edl  <work> --motion 2      # EDL + words per kata + caption_style "kinetic"
python3 -m scripts.cli render     <work> --preview       # 540x960 @15 fps, <work>/out/clip_NN.preview.mp4
python3 -m scripts.cli render     <work>                 # final 1080x1920 @30 fps
```

`render` membaca `<work>/edl.json`. `--preview` tidak pernah menimpa file final (`*.preview.mp4`).
ffmpeg ber-libass dipilih otomatis: `CLIP_FFMPEG` > `ffmpeg` di PATH (bila punya filter `subtitles`) >
`ffmpeg-full` Homebrew. Tanpa libass render berhenti dengan `FFmpegError` yang menyebut `CLIP_FFMPEG`, bukan menghasilkan video tanpa teks.

Font bundel (`assets/fonts/`): Archivo Black (caption dan teks preset `checklist`) dan DM Serif Display Italic
(`zoom_through_text`); keduanya SIL OFL, hash di `assets/fonts/SOURCES.md`.

## 2. Menambah preset overlay ke EDL

Preset adalah item `overlays[]` pada klip. **Waktu = timeline OUTPUT** (detik sejak awal klip, sesudah jeda
dibuang), sama dengan caption. Menulis ke `edl.json` langsung (atau mengubah `edl_t2.json` lalu menyalinnya).
Preset yang tidak dikenal atau di luar durasi klip dilewati dengan satu baris `PERINGATAN:` di stderr, tidak
pernah menggagalkan render; props yang SALAH (tipe/rentang) → `RenderError` yang menyebut klip, indeks overlay,
dan nama props.

### `zoom_through_text` — teks serif miring memuai menembus kamera

```json
{"type": "zoom_through_text", "start": 6.6, "end": 7.6,
 "props": {"text": "Polisi jujur?", "colour": "#FFFFFF", "size_em": 160, "duration": 0.7}}
```

- `text` 1–24 karakter, tanpa newline (`{`, `}`, `\` diganti `(`, `)`, `/`). `colour` `#RRGGBB`, `size_em` 60–400,
  `duration` 0,4–1,5 s. Skala 80% → 320% (easing akselerasi), alfa memudar pada 40% terakhir.
- Pusat = tengah frame, atau pusat `rect` bila `rect` diberikan. Sengaja **melintasi wajah** (maksud efeknya).
- Berlangsung `[start, min(end, start + duration)]`.

### `checklist` — kartu butir yang dicentang berurutan

```json
{"type": "checklist", "start": 8.0, "end": 14.0,
 "props": {"title": "Polisi jujur itu...",
           "items": [{"text": "Tidak ambil uang rokok", "done_at": 9.5},
                     {"text": "Berani lapor atasan",    "done_at": 10.8},
                     {"text": "Tahan tekanan",          "done_at": 12.2},
                     {"text": "Tetap dikucilkan",       "done_at": null}]}}
```

- `title` ≤ 28 karakter; 2–6 `items`, tiap `text` ≤ 28 karakter; `done_at` = waktu OUTPUT absolut, harus dalam
  `[start + 0,30, end]` atau `null` (tidak pernah dicentang). Teks yang tak muat ditolak (bukan dipotong).
- `rect` opsional `{x, y, w, h}`; bawaan `x=60, y=260, w=960`, tinggi dari isi. `rect.h` terlalu pendek → error.
- Penghitung `n of N` berganti tepat pada frame `round(done_at · fps)`.

### `chart_grow` — grafik garis yang tumbuh dengan titik dan tag

```json
{"type": "chart_grow", "start": 20.0, "end": 26.0,
 "props": {"title": "Kepercayaan publik", "labels": ["2019", "2020", "2021", "2022", "2023"],
           "values": [30, 42, 38, 61, 88], "tag": "+193%", "grow": 1.2}}
```

- `labels` 3–8 string (≤ 10 karakter, label sumbu x), `values` angka berhingga dengan panjang sama dan tidak
  semuanya sama (dipetakan min–max ke tinggi plot), `tag` ≤ 16 karakter, `title` opsional ≤ 28 karakter,
  `grow` 0,6–2,5 s (bawaan 1,2). Bawaan kartu `x=60, y=260, w=960, h=520`; `rect` boleh menimpa, tetapi `rect.h` yang
  terlalu pendek ditolak.
- Urutan: kartu masuk 0,30 s → garis tumbuh kiri→kanan (ease kosinus) dengan titik ujung mengikuti kepala garis →
  tag pop di ujung sesudah garis selesai → fade keluar 0,20 s. `grow` harus selesai di dalam jendela overlay.

### `ui_panel` — kartu antarmuka krem dengan thumbnail berurutan

```json
{"type": "ui_panel", "start": 20.0, "end": 26.0,
 "props": {"title": "Kasus polisi jujur", "tag": "VIRAL", "thumbs": 6, "input": "Cari kasus"}}
```

- `title` ≤ 28 karakter, `tag` ≤ 16, `thumbs` 1–6 (bawaan 3; lebih dari 3 pecah dua baris), `input` opsional ≤ 28.
  Bawaan `x=60, y=260, w=960`, tinggi dihitung dari isi (maksimum 700 px); `rect.h` yang terlalu pendek ditolak.
- Urutan: kartu masuk 0,30 s → thumbnail pop satu per satu (jeda 80 ms) → tag pil pop → fade keluar 0,20 s.

### `phone_frame` — ponsel datar dengan judul dan baris bullet berurutan

```json
{"type": "phone_frame", "start": 28.0, "end": 34.0,
 "props": {"title": "Laporan hari ini",
           "lines": ["Tidak terima suap", "Lapor ke atasan", "Tetap bertahan", "Dikucilkan rekan"],
           "accent": "#FFD60A", "side": "right"}}
```

- `title` 1–22 karakter, `lines` 2–4 string (≤ 22 karakter), `accent` opsional `#RRGGBB`, `side` `"right"` (bawaan) atau
  `"left"`. Bawaan `x=640, y=250, w=380` (sisi kiri `x=60`), tinggi dari isi; `rect.h` terlalu pendek ditolak.
- Urutan: ponsel meluncur kaku 140 px dari sisi (0,35 s) → baris muncul satu per satu (jeda 180 ms) → fade keluar
  0,20 s. Tanpa pop skala dan tanpa tilt 3D.

### Caption pendek digabung otomatis (kinetic)

Frasa kinetic yang jendela tampilnya < 0,25 s digabung ke frasa tetangga **saat render** (EDL tidak berubah): kata
berumur sangat pendek tidak lagi "hilang". Contoh klip_04: `Lu,` + `lu ngerasain nggak sih` → satu frasa.

(Efek yang tersisa dari daftar 7 — `pullback` — dicatat di
`docs/MOTION-TIER2-PLAN.md` begitu selesai; bagian ini diperbarui di sana.)

## 3. Aturan praktis memilih overlay (penting)

1. **Cek jenis shot dulu.** Pada close-up talking-head (wajah mengisi ±60–70% tinggi frame, seperti klip_04)
   TIDAK ADA area bebas untuk kartu: `checklist` pada `y=260` menutupi dahi dan sebagian mata. Pilihan: (a) pakai
   `zoom_through_text` (sengaja menutupi), (b) beri `rect` kecil di area yang Anda pilih, (c) lewati overlay.
   Pada shot lebar (wajah < ±40% frame) kartu di zona atas aman.
2. **Satu overlay kartu pada satu waktu.** Preset tidak menghindari satu sama lain atau caption; caption tetap di
   lapisan paling atas (filter `subtitles` caption selalu yang terakhir).
3. **Jangan menutupi hook.** Hindari memulai kartu pada 1–2 detik pertama kecuali kartu itu sendiri hook-nya.
4. Overlay tidak mengubah durasi, jumlah frame, atau timing caption (diuji pada render libass nyata).

## 4. Layout sadar wajah (opsional, informatif)

```bash
python3 -m scripts.cli faces  <work> --face-track     # tulis reframe.face_track (OpenCV + models/)
python3 -m scripts.cli layout <work> [--no-write]     # hitung layout.caption/overlays + cetak audit
```

Status sebenarnya (jujur): `layout` mengukur tabrakan caption/overlay dengan kotak wajah dan menulis keputusan ke
`clips[].layout`, tetapi **belum ada yang membacanya**: `kinetic` belum memindahkan caption dan overlay belum
mengambil `rect` otomatis (Langkah 4b-2, ditunda). Kotak wajah YuNet menjulur di bawah dagu dan dihitung sebagai
amplop satu shot, sehingga angka "caption∩wajah" pada close-up terlalu pesimistis (klip_04: 1293/1561 frame,
padahal caption tidak menimpa mulut). Gunakan audit sebagai petunjuk, bukan vonis.

## 5. Batasan yang diketahui

- **Versi datar** dari efek referensi: tanpa tilt 3D, kaca buram, blur latar, atau emoji berwarna. Kemiripan pada
  struktur gerak dan tata letak.
- Efek yang butuh masker orang (teks di belakang kepala, dinding kartu, siluet, dll.) **tidak tersedia** (D-012:
  masker orang dibekukan). Remotion/Chromium tidak dipakai (D-011: RSS 1,4–1,8 GB melewati gerbang 1,0 GB).
- Biaya render sebanding dengan fraksi durasi klip yang overlay-nya aktif: pada klip nyata 52 s dengan overlay 6 s,
  `checklist` +2,1% dan `zoom_through_text` +1,0% (M1, indikatif; mesin target i5-7300U belum diukur).
- Zona aman platform (atas 250, bawah 480, kanan 120 px) di `scripts/layout.py` adalah **[P]**, belum diverifikasi
  ke spesifikasi platform; caption 2 baris di `y=1400` melewati batas bawah 1440 dan kanan 960 dengan angka itu.
- Transkrip Groq: filter halusinasi aktif sejak G1 (permintaan `word` + `segment`), tetapi Groq sering membalas satu
  segmen 30 s per potongan sehingga hanya potongan yang SELURUHNYA senyap/musik/berulang yang tertangkap.

## 6. Pemecahan masalah

| Gejala | Penyebab paling mungkin |
|---|---|
| `FFmpegError` soal libass / `CLIP_FFMPEG` | pasang `ffmpeg-full` atau set `CLIP_FFMPEG` ke biner ber-libass |
| Teks caption jatuh ke font lain | `--fontsdir` salah/hilang; kinetic dan preset memakai `assets/fonts` otomatis |
| `PERINGATAN: overlay[i] ... dilewati` | jendela overlay di luar durasi klip, atau font preset hilang |
| `RenderError ... preset overlay tidak valid` | props salah; pesan menyebut nama props dan rentangnya |
| `faces` mencetak "opencv atau model tidak tersedia" | pakai Python ber-OpenCV dan pastikan `models/face_detection_yunet.onnx` ada |

## 7. Mode `suggest`: agen mengusulkan, Anda menyetujui

Agen TIDAK menulis overlay ke `edl.json` sendiri. Alurnya (instruksi lengkap untuk agen ada di `SKILL.md`, Langkah 4):

```bash
python3 -m scripts.cli fx-catalog                       # katalog efek, batas props, anggaran
python3 -m scripts.cli fx-candidates <work>             # fakta per klip -> fx_candidates.json
# agen menulis <work>/fx_plan.json (usulan + alasan)
python3 -m scripts.cli fx-validate <work>               # fx_plan.report.json/.md (diterima / peringatan / ditolak)
python3 -m scripts.cli fx-preview <work> [--only p1,p3] # pratinjau + contact_sheet.png (edl.json & out/ tidak disentuh)
python3 -m scripts.cli fx-apply <work>                  # tanpa --approve: hanya ringkasan, kode keluar 2
python3 -m scripts.cli fx-apply <work> --approve        # tulis overlays[] (cadangan edl.json.bak_fx otomatis)
python3 -m scripts.cli fx-undo <work>                   # pulihkan dari cadangan
```

Yang ditegakkan pengesah (`fx-validate`): maksimum 3 overlay per klip (≤ 2 aksen, ≤ 1 pullback), jarak ≥ 4 s antar-overlay dan
≥ 10 s antar-kartu, tidak tumpang tindih (termasuk panel `vs` tier-1), tidak ada kartu/pullback di 2 s pertama kecuali
`hook: true`, kartu pada close-up WAJIB `rect` eksplisit (atau pilih `zoom_through_text`/`pullback`), `pullback` butuh fase stabil
≥ 1,5 s, props divalidasi oleh pembuat preset asli. Peringatan (status `accepted_with_warnings`, TETAP perlu disebut ke Anda):
`rect` beririsan dengan wajah atau dengan kotak caption, berimpit dengan `punch`, dekat awal/akhir klip.
