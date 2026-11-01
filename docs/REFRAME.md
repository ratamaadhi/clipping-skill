# REFRAME — mengikuti wajah

Masalah: crop 9:16 dari sumber 16:9 hanya mengambil **31,7% lebar frame**
(608 dari 1920 px). Kalau dua orang duduk berdampingan — wajah di ~27% dan
~65% — crop tengah jatuh tepat di celah antar mereka. Hasilnya bahu, tanpa
wajah sama sekali.

Solusi: deteksi wajah, pilih satu subjek **per shot**, geser crop ke sana.

## Kenapa per shot, bukan per frame

Percobaan pertama mengikuti wajah tiap frame (5 fps). Hasilnya kamera gemetar:
deteksi bergoyang beberapa piksel dan subjek berganti-ganti, sehingga crop
melompat ratusan piksel setiap 0,6 detik.

Percobaan kedua: rata-rata bergerak ±1 detik. Lebih halus, tapi **lebih buruk** —
kamera berpindah shot, dan rata-rata yang melintasi batas shot menghasilkan
posisi di antara dua orang, persis yang mau dihindari.

Yang bekerja: deteksi pergantian shot, lalu **satu posisi kamera per shot**.
Itu juga yang dilakukan editor manusia.

## Alur

```
1. sampel 5 fps, 640x360            (ffmpeg, cepat)
2. YuNet deteksi wajah + skor        (OpenCV FaceDetectorYN)
3. gerak mulut antar frame           → siapa yang bicara
4. deteksi cut dari beda frame       → batas shot
5. satu bias_x per shot (median)     → timeline
6. ekspresi crop bergerak            → ffmpeg crop x='...'
```

### Siapa yang bicara

YuNet hanya memberi **sudut** mulut, bukan bibir atas/bawah, jadi bukaan mulut
tidak bisa dihitung langsung. Yang dipakai: **gerak piksel di kotak mulut**
antara dua frame berurutan, setelah kotak dinormalisasi ke 32×16 px supaya
tidak terpengaruh skala wajah.

Sinyalnya cukup tajam saat dua wajah terlihat bersamaan. Contoh nyata:

| waktu | wajah kiri | wajah kanan | kesimpulan |
|---|---|---|---|
| 1227.2 s | 0,170 | 0,045 | kiri bicara |
| 1229.6 s | 0,021 | 0,084 | kanan bicara |

Aturannya: ambil yang paling aktif **hanya kalau** geraknya >1,5× lawannya.
Selisih kecil dianggap noise → jatuh ke wajah terbesar.

### Deteksi pergantian shot

frame di-downscale ke 32×18 grayscale, dibandingkan dengan frame sebelumnya.
Beda rata-rata >20 (skala 0–255) dianggap cut. Pada klip 22 detik,
6 cut terdeteksi → 7 shot.

## Ekspresi crop

ffmpeg mengevaluasi `crop` x **per frame** (berbeda dari `drawbox` yang
mengevaluasi `w` sekali saat init — lihat `docs/MOTION.md`).

Ekspresinya bukan `if` bersarang, tapi jumlah ramp yang di-clip:

```
x(t) = x0 + Σ Δx_i · clip((t − (t_i − 0.4)) / 0.4, 0, 1)
```

40 titik → ~760 karakter, jauh di bawah batas filtergraph. Transisi 0,4 detik
membuat kamera terlihat menggeser, bukan melompat.

## Hasil pada klip JKT48

| | sebelum | sesudah |
|---|---|---|
| crop | tengah, wajah di 27% & 65% dua-duanya terpotong | per shot |
| pusat crop | 50% | 34% / 46% / 52% / 61% / 62% |
| wajah terlihat | tidak (hanya bahu) | ya, utuh, tidak terpotong |
| posisi kamera | 1 (statis) | 7 (satu per shot) |

## Batas yang diketahui

- Butuh OpenCV (`opencv-python-headless`) + model YuNet 232 KB. Pipeline inti
  tetap tanpa dependency: langkah `faces` terpisah dan opsional, kalau cv2 tidak
  ada maka crop kembali ke tengah tanpa error.
- Kalau dua orang bicara bersamaan, gerak mulut tidak bisa memisahkan siapa
  yang dominan — dipilih yang terbesar di frame.
- Kalau wajah tidak terdeteksi sama sekali (membelakangi kamera, gelap), shot
  itu dilewati dan crop memakai posisi shot sebelumnya.
- Deteksi cut berbasis beda piksel bisa salah kalau ada transisi halus
  (fade/dissolve): dianggap satu shot panjang.
