# MOTION — motion graphics tier-1

Empat lapisan yang membuat klip terasa seperti short asli, semuanya lewat ffmpeg.
Tanpa Node, tanpa Chromium, tanpa dependency Python baru.

| Lapisan | Fungsi | Biaya render |
|---|---|---|
| Punch-in | ganti framing wide/medium/tight tiap 2,5–4,5 s | ~0,5× realtime |
| Progress bar | indikator durasi di atas frame | ~0 |
| SFX | hit/whoosh di setiap punch, disintesis sendiri | ~0 |
| Panel VS | dua entitas dibandingkan, slide-in | ~0 |

**Prinsip yang dipegang:** semua lapisan hanya mengubah *tampilan*, tidak mengubah
*timing*. Karena durasi output identik dengan input, caption di EDL tetap valid
tanpa dihitung ulang.

---

## 1. Punch-in

Ganti framing seperti multi-cam. Skala bergantian `1.0 → 1.14 → 1.0 → 1.20`,
dipasang di batas atom (bukan acak) supaya terasa disengaja.

Aturan jadwal (`motion.punch_schedule`):

- mulai `t=0` dengan skala 1.0 (wide)
- punch hanya di batas atom yang berjarak ≥ 2,5 s dari punch sebelumnya
- dipaksa muncul sebelum 4,5 s kalau tidak ada batas atom yang cocok
- tidak boleh lebih dekat dari 0,4 s ke akhir klip

Implementasi: filter `zoompan` dengan ekspresi bersarang yang memilih skala
berdasarkan nomor frame input.

```
zoompan=z='if(lt(in,131),1.0000,if(lt(in,220),1.1400,1.0000))'
        :d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30
```

Kenapa `zoompan` dan bukan potong-lalu-concat: satu pass, tidak menambah generasi
encoding kedua, dan durasi output dijamin sama dengan input.

---

## 2. Progress bar — dan jebakan drawbox

**`drawbox` mengevaluasi `w`/`h` SEKALI saat init.** Jadi

```
drawbox=x=0:y=0:w='iw*t/41.2':h=8   ← SALAH
```

menghasilkan bar **selebar frame sejak detik nol**, bukan bar yang tumbuh.
Sudah diuji: pada t=1 s, t=20 s, t=40 s lebarnya tetap 1080 px.

Yang bekerja per-frame adalah **`overlay`** dengan ekspresi `x`:

```
color=c=0x00E5FF:s=1080x8:r=30:d=41.13[bar];
[base][bar]overlay=x='-w+w*t/41.13':y=0:shortest=1
```

Bar didorong dari luar kiri layar (`x=-w`) sampai menempel (`x=0`). Hasil uji:

| t | lebar bar | target |
|---|---|---|
| 1 s | 26 px | 26 px |
| 10 s | 262 px | 263 px |
| 20 s | 526 px | 525 px |
| 30 s | 788 px | 788 px |
| 40 s | 1050 px | 1050 px |

Track gelap (`black@0.35`) tetap pakai `drawbox` statis — itu memang tidak butuh waktu.

---

## 3. SFX

Disintesis langsung di Python (`wave` + `array` + `math`), jadi **bebas lisensi**
dan tidak perlu unduh aset.

- `hit` — 85 ms, sinus 132 Hz + harmonik 264 Hz, envelope `exp(-42t)`
- `whoosh` — 200 ms, white noise (seed tetap) lewat low-pass satu kutub, envelope sinus

Ditempel ke buffer sepanjang klip pada waktu punch, gain default **−19 dB**,
lalu di-clip ke 0,95 kalau ada penumpukan. Ditulis sebagai WAV mono 48 kHz,
di-mix dengan audio utama:

```
[0:a]loudnorm=I=-14:TP=-1:LRA=11[a0];
[1:a]volume=1.0[s1];
[a0][s1]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]
```

`normalize=0` penting — tanpa itu `amix` menurunkan volume kedua input.

Terverifikasi: puncak RMS di titik punch naik **+2 sampai +5 dB** di atas median
klip, cukup terasa tapi tidak menutupi suara.

---

## 4. Panel VS

Mendeteksi perbandingan dua entitas dari transkrip, lalu menampilkan panel dua
kolom dengan slide-in 0,25 detik.

**Deteksi sengaja case-sensitive.** Hanya nama diri berhuruf kapital yang dianggap
entitas:

```
Codex atau Claude   → ("Codex", "Claude")  ✅
Codex vs Claude     → ("Codex", "Claude")  ✅
ini atau itu        → None                 ✅ (bukan nama)
Jika Anda atau …    → None                 ✅ (stopword)
```

Pola longgar tanpa case membuat "ini atau itu" ikut terdeteksi — itu sebabnya
versi pertama dibuang. Ada daftar stopword untuk kata berkapital yang bukan nama
(Jika, Anda, Mereka, Pertama, …).

Panel muncul di `t=0.6–3.6 s` kalau klip ≥ 6 detik. Teks disanitasi
(`_safe_text`) karena `drawtext` mudah rusak oleh `:`, `,`, `'`.

**Batasannya:** ini hanya mendeteksi perbandingan yang disebut *eksplisit dengan
nama diri*. "Aplikasi A lebih cepat dari aplikasi B" tidak terdeteksi. Ekstraksi
atribut perbandingan (baris mana untuk entitas mana) butuh LLM — itu pekerjaan
tier-2.

---

## Urutan filter

Urutan menentukan siapa menutupi siapa:

```
crop → scale → setsar → zoompan → track bar → [overlay fill bar] → panel VS → subtitles
```

Caption **selalu terakhir**, supaya tidak pernah tertutup panel atau bar.

---

## Hasil terukur (klip 41,13 detik, 1234 frame)

### Biaya render

| Konfigurasi | Waktu | Peak RSS |
|---|---|---|
| Tanpa motion (baseline) | 15,06 s | 544 MB |
| + punch-in | 16,87 s | — |
| + punch + progress bar | **17,21 s** | 579 MB |

**Motion graphics menambah ~14% waktu render, bukan berkali-kali lipat.**
Karena baseline-nya memang sudah ~2,7× realtime, hasil akhirnya 2,4× realtime
(41 s klip → 17 s render). `zoompan` memang me-rescale tiap frame, tapi biayanya
kecil dibanding encode x264 itu sendiri.

Angka ini sempat salah ditulis sebagai "2,5 menit per klip" — itu keliru, hasil
dari menyimpulkan waktu dari jarak antar perintah, bukan dari pengukuran.

### Kualitas visual

| Metrik | Nilai |
|---|---|
| Durasi output | 41,20 s (input 41,13 s — selisih padding AAC) |
| Frame | 1234 @ 30 fps, 1080×1920 |
| Punch | 10 titik, jarak 3,0–4,5 s |
| Jarak grid wide | 284 px |
| Jarak grid zoom 1,14 | 324 px (= 284 × 1,141) ✓ |
| Lebar bar (t=1/10/20/30/40 s) | 26/262/526/788/1050 px ✓ |
| Puncak RMS di titik punch | +2 … +5 dB di atas median |

---

## Jalan ke tier-2 (Remotion)

Tier-1 sengaja dibatasi pada apa yang bisa dilakukan ffmpeg. Yang **tidak** bisa
dan butuh Remotion:

- spring physics / easing per elemen
- layout responsif terhadap bounding box wajah
- animasi teks per kata dengan stagger
- komponen React yang bisa di-compose
- shader / efek partikel

Yang **bisa dipindahkan apa adanya** ke Remotion nanti:

- jadwal punch (`punch_schedule`) → keyframe animasi kamera
- event SFX (`sfx_events`) → audio track di timeline
- panel VS (`overlays`) → komponen React
- EDL sebagai input — kontraknya sudah stabil

Jadi tier-1 bukan kerja buang. Dia membuktikan ritme dan aturan kontennya dulu
dengan biaya render yang murah, sebelum investasi ke Chromium.
