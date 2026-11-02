# Font bundel — sumber, lisensi, dan alasan

## Pilihan: Archivo Black

Satu keluarga sans-serif grotesque sangat tebal untuk caption gaya reel, satu
bobot statis. Alasan teknis (bukan estetika):

1. **Family unik di satu bobot.** `fontmetrics.Font.load(...).family` membaca
   `"Archivo Black"` dan `full_name` membaca `"Archivo Black Regular"`. Karena
   hanya ada satu bobot dengan nama keluarga unik, `Fontname` di `Style` ASS
   tidak ambigu bagi libass: tidak ada peluang libass memilih bobot lain
   (risiko **R4**, font fallback senyap). Montserrat dan Poppins berbagi satu
   nama keluarga (`"Montserrat"`, `"Poppins"`) di seluruh 18 bobot statis,
   sehingga `Fontname: Montserrat` di `Style` bergantung pada pemilihan bobot
   libass — persis risiko yang ingin dihindari.
2. **`usWeightClass` 400** pada berkas ini. Karena berkasnya sudah sangat tebal
   secara desain, `Style` memakai `Bold: 0` supaya libass **tidak** menebalkan
   secara sintetik (bold sintetik merusak ketajaman huruf). Kalau `Bold: -1`
   dipakai, libass akan menambah stroke sintetik di atas bobot yang sudah 900-an
   secara visual.

Syarat wajib lain, semuanya dibuktikan `tests/test_fonts_assets.py`:

| Syarat | Nilai terukur |
|---|---|
| Lisensi SIL OFL 1.1 | `assets/fonts/OFL.txt`, memuat "SIL OPEN FONT LICENSE" + "Version 1.1" |
| TTF statis (tanpa `fvar`) | 18 tabel, **tidak ada** `fvar` (dibaca dengan `struct` di tes) |
| Bobot tebal | `usWeightClass` 400, desain Black (satu-satunya bobot keluarga) |
| Ukuran ≤ 1 MB | 90.988 byte (88,9 KiB) |
| Latin dasar + tanda baca Indonesia | 426 glyph, semua karakter wajib punya glyph |

## Berkas

| Berkas | Ukuran | sha256 |
|---|---|---|
| `ArchivoBlack-Regular.ttf` | 90.988 byte | `dd9a89a019b4849f66ab75455fe7bdf931311042cbb0f0f97acc061539703180` |
| `OFL.txt` | 4.492 byte | `3173acd82f8c6159b5b1037b539fcbd4edff68e65c2ea8b9412b5a5ca97b08ff` |

## URL persis dan commit

Diunduh **2026-11-02** dari repo `google/fonts`, pada commit
`94a7d81318e438525a5285e07ab72c050fdfeb44` (commit terakhir yang menyentuh
`ofl/archivoblack/`, tanggal 2026-02-26, pesan "Archivo Black: add source
block to METADATA.pb"). Commit dipin supaya berkas tidak bisa berubah di bawah
kita; URL `main` akan memberi isi yang sama hari ini tetapi tidak dijamin
besok.

- Font:
  `https://raw.githubusercontent.com/google/fonts/94a7d81318e438525a5285e07ab72c050fdfeb44/ofl/archivoblack/ArchivoBlack-Regular.ttf`
- Lisensi:
  `https://raw.githubusercontent.com/google/fonts/94a7d81318e438525a5285e07ab72c050fdfeb44/ofl/archivoblack/OFL.txt`

`OFL.txt` adalah salinan **apa adanya** dari URL lisensi di atas (byte
identik, sha256 di tabel). Berkas font tidak diubah sama sekali: tidak ada
subsetting, tidak ada konversi, tidak ada rename tabel.

## Nama keluarga seperti dibaca `fontmetrics`

```
family    = "Archivo Black"
full_name = "Archivo Black Regular"
unitsPerEm = 1000
numGlyphs  = 426
```

`Fontname` di `Style` ASS diisi **dari nilai `family` ini**, bukan dari nama
tebakan. `tests/test_fonts_assets.py` membandingkan keduanya langsung, jadi
kalau suatu saat berkas font diganti tanpa memperbarui template, tes merah.

## Asal dan lisensi

Archivo Black dibuat oleh Omnibus-Type (The Archivo Black Project Authors),
Copyright 2017, dirilis di bawah SIL Open Font License 1.1. Teks lisensi asli
ada di `OFL.txt` di direktori ini; ia mengizinkan penggunaan, modifikasi, dan
redistribusi font (termasuk bundling dalam produk), dengan syarat berkas font
tidak dijual sendiri dan nama reserved tidak dipakai untuk versi modifikasi.

---

## Font kedua: DM Serif Display Italic (untuk preset `zoom_through_text`)

Satu serif miring tebal untuk teks judul besar yang memuai (efek referensi #09).
Bukan font caption: caption tetap Archivo Black. Satu berkas statis, tanpa
`fvar`.

| Berkas | Ukuran | sha256 |
|---|---|---|
| `DMSerifDisplay-Italic.ttf` | 71.208 byte | `df74c0ac387baeaeb0fe4f2324e1668e6a3ed8c09cd9796fe162c71753e19e45` |
| `OFL-DMSerifDisplay.txt` | 4.605 byte | `a3e5cdd67d4571dd0a24fcc968de0efde7ae97ef752daf0906e4767619dd7231` |

Diunduh **2026-11-02** dari `google/fonts`, commit
`7efaaeb60f72588557a6605b48311611937304ba` (commit terakhir yang menyentuh
`ofl/dmserifdisplay/`, 2026-06-02, "DM Serif Display: fix wrong config_yaml, add
override config"). Ukuran berkas cocok dengan yang dilaporkan GitHub API (71208).

- Font:
  `https://raw.githubusercontent.com/google/fonts/7efaaeb60f72588557a6605b48311611937304ba/ofl/dmserifdisplay/DMSerifDisplay-Italic.ttf`
- Lisensi (disalin APA ADANYA, diberi nama `OFL-DMSerifDisplay.txt` supaya tidak
  menimpa `OFL.txt` milik Archivo Black):
  `https://raw.githubusercontent.com/google/fonts/7efaaeb60f72588557a6605b48311611937304ba/ofl/dmserifdisplay/OFL.txt`

Berkas font tidak diubah (tanpa subsetting/konversi/rename tabel).

Nama seperti dibaca `fontmetrics`: `family = "DM Serif Display"`,
`full_name = "DM Serif Display Italic"`, `unitsPerEm = 1000`,
`cell_height_ratio = 1,371`. **Perhatian:** nama keluarga ini juga dipakai berkas
Regular-nya (yang TIDAK kita bundel), jadi `Style` harus meminta `Italic: -1`
dan tes oracle harus membuktikan libass memakai berkas bundel, bukan font
sistem (pola kontrol fallback seperti Archivo Black).
