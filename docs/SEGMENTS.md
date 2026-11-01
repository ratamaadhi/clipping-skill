# MULTI-SEGMENT — membuang jeda mati

Masalah terukur: pada klip JKT48 22,6 detik, **26,8% durasinya adalah diam**
(4,10 s + 1,96 s). Di Reels/TikTok itu alasan orang scroll.

Solusi: klip tidak lagi satu potongan kontinu, tapi beberapa segmen yang
disambung — jeda di antaranya dibuang.

## Prinsip

**Yang dibuang hanya waktu, bukan kata.** Setiap segmen berisi bicara; tidak ada
satu pun frasa yang hilang. Yang hilang adalah ruang kosong di antaranya.

Ambang: jeda > **0,45 s** dibuang, segmen < **0,6 s** dibuang seluruhnya
(menampilkan 0,1 detik lebih buruk daripada melewatinya).

## Pemetaan waktu

Konsekuensi terbesar bukan di pemotongan, tapi di **pemetaan waktu**. Semua
timestamp di EDL (caption, punch, overlay, jalur crop wajah) dulu dihitung
`src - clip_start`. Dengan jeda yang dibuang, rumus itu salah.

```
map_time(segments, t):
    untuk setiap segmen:
        jika src_start <= t <= src_end:
            return out_start + (t - src_start)
    return None        # jatuh di jeda yang dibuang
```

`map_interval()` melakukan hal yang sama untuk rentang, dengan dua perilaku
penting:

| kasus | hasil |
|---|---|
| seluruh rentang di dalam jeda | `None` → caption dibuang |
| menyeberang akhir segmen | dipotong di batas segmen |
| menyeberang seluruh jeda | digabung, memakai sisi kiri dan kanan |

Contoh nyata (clip_01):

| rentang sumber | out |
|---|---|
| 1209,20 – 1214,02 | 0,00 – 4,82 |
| 1218,12 – 1221,16 | 4,82 – 7,86 |
| 1223,12 – 1231,70 | 7,86 – 16,44 |

Jeda 1214,02–1218,12 (4,10 s) dan 1221,16–1223,12 (1,96 s) hilang dari output.

## Renderer

Satu kali encode, bukan render-per-segmen lalu gabung:

```
[0:v]trim=start=A:end=B,setpts=PTS-STARTPTS[sv0];
[0:v]trim=start=C:end=D,setpts=PTS-STARTPTS[sv1];
[sv0][sv1]concat=n=2:v=1:a=0[svcat];
[svcat]crop,scale,setsar,fps,zoompan,progress,overlays,subtitles[v]
[0:a]atrim=...,asetpts=PTS-STARTPTS[sa0]; ... concat=v=0:a=1; loudnorm
```

Dua hal yang mudah salah:

1. **`trim` menghitung dari titik seek**, bukan dari awal file. Karena itu
   `-ss` diletakkan di `first_start` dan offset trim = `src_start - first_start`.
2. **Rantai crop/scale harus diterapkan SETELAH concat.** Kalau tidak, output
   kembali ke resolusi sumber — sempat kejadian, hasilnya 1920×1080 bukan
   1080×1920.

## Hasil pada 3 klip JKT48

| klip | span sumber | output | dibuang | segmen |
|---|---|---|---|---|
| clip_01 | 22,5 s | **16,4 s** | 6,1 s (27%) | 3 |
| clip_02 | 22,2 s | 20,5 s | 1,7 s (8%) | 3 |
| clip_03 | 23,5 s | 23,5 s | 0 | 1 |

Verifikasi: 492 frame untuk 16,4 s @ 30 fps (cocok), audio di titik sambung
tetap bicara (−11,9 dB, bukan senyap), caption bergeser tepat mengikuti segmen.

## Batas

- Sambungan tampak sebagai **jump cut**. Untuk gaya short-form ini justru
  diinginkan; kalau mau mulus perlu b-roll atau transisi.
- Yang dibuang hanya jeda di antara frasa. Diam panjang di tengah satu frasa
  (misal jeda dramatis sebelum jawaban) tetap dipertahankan.
- `MIN_SEG_DUR` yang terlalu besar bisa membuang kalimat pendek yang justru
  penting ("Iya."). Saat ini 0,6 s — masih aman.
