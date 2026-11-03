---
name: clipping-skill
description: Use when turning a long video into vertical shorts (Reels/TikTok/Shorts) — transcribes, segments, picks candidate clips, scores them on 6 explainable axes, builds an EDL, and renders 9:16 clips with kinetic captions. Deterministic except the scoring step, which the agent performs.
---

# clipping-skill

Mengubah video panjang menjadi short vertical 9:16 dengan pemilihan klip berbasis
transkrip dan skor 6-axis yang bisa dijelaskan.

## Kapan dipakai

- User punya video panjang (podcast, wawancara, webinar, screen recording) dan ingin
  beberapa potongan short.
- User ingin **alasan** kenapa sebuah potongan dipilih, bukan sekadar hasil.
- User ingin output yang bisa direproduksi (EDL tersimpan, render deterministik).

Jangan dipakai untuk: generate video dari teks, mencuri konten orang lain,
atau editing frame-by-frame manual.

## Prasyarat

```bash
ffmpeg -version    # >= 6.0
python3 --version  # >= 3.11
```

API key transkripsi di `.env` (`GROQ_API_KEY` / `OPENAI_API_KEY` / `DEEPGRAM_API_KEY`),
atau `CLIP_ENGINE=local` dengan `faster-whisper` terpasang.

## Prosedur

### Langkah 1 — jalankan bagian deterministik

```bash
python3 -m scripts.cli run <video> --out work/<nama>
```

Menghasilkan: `audio.wav`, `transcript.json`, `atoms.json`, `candidates.json`
(top 15 dengan fitur), dan `meta.json`.

Kalau transkripsi gagal, cek `.env` dan jalankan `python3 -m scripts.cli transcribe --help`.

### Langkah 2 — nilai kandidat (INI TUGAS AGENT)

```bash
python3 -m scripts.cli score-prompt work/<nama>
```

Perintah ini mencetak prompt berisi 15 kandidat. **Baca seluruh prompt**, lalu tulis
`work/<nama>/selection.json` berisi penilaian 6 axis untuk setiap kandidat.

Aturan wajib saat menilai:

1. **Nilai 6 axis secara independen**: `hook`, `payoff`, `self_contained`, `emotional`,
   `concrete`, `loop`. Skala 0–10.
2. **Wajib kutip `evidence`** — potongan teks persis dari transkrip kandidat.
   Kalau tidak bisa mengutip, turunkan skornya.
3. **Jangan menulis skor total.** Skor komposit dihitung oleh script, bukan oleh agent.
   Menulis total akan meng-anchor axis lain.
4. **Jangan mengubah `atom_start` / `atom_end`.** Kalau kandidat tidak layak, turunkan
   skornya — jangan potong ulang sendiri.
5. Isi `weakest_axis` dan `fix_suggestion` (satu kalimat, konkret dan bisa dieksekusi).

### Langkah 3 — validasi dan render

```bash
python3 -m scripts.cli score-validate work/<nama>
python3 -m scripts.cli build-edl work/<nama>
python3 -m scripts.cli render work/<nama> --top 3
```

Output: `work/<nama>/out/clip_01.mp4` dst, plus `report.md` berisi alasan tiap klip.

### Langkah 4 (opsional, tier-2) — usulkan efek overlay (mode `suggest`)

Hanya bila user meminta efek visual (kartu UI, checklist, grafik, ponsel, teks memuai, pull-back).
**Bawaannya TIDAK ada efek.** Agent hanya MENGUSULKAN; tidak ada yang ditulis ke `edl.json`
sebelum user menyetujui secara eksplisit.

Prasyarat: `build-edl --motion 2` (kata per kata) dan, untuk gerbang close-up,
`python3 -m scripts.cli faces work/<nama> --face-track` (butuh OpenCV).

```bash
python3 -m scripts.cli fx-catalog                      # baca katalog efek, batas props, anggaran
python3 -m scripts.cli fx-candidates work/<nama>       # → fx_candidates.json (fakta, bukan keputusan)
```

Baca `fx_candidates.json`: per klip ada `shots` (`close_up`/`medium`/`wide`) dan `moments` (pemicu
`number`, `trend`, `list`, `question`, `product`, `emphasis`, `reveal`) dengan `fits` per efek,
`available_window`, dan `suggested_window`. Lalu **tulis `work/<nama>/fx_plan.json`**:

```json
{"version": 1, "mode": "suggest",
 "clips": [{"clip_id": "clip_04", "items": [
   {"id": "p1", "type": "zoom_through_text", "start": 2.82, "end": 3.52,
    "props": {"text": "Nggak!"}, "reason": "kata kunci beraksen 'nggak' di punchline", "moment": "m001"}]}]}
```

Aturan wajib:

1. **Efek hanya bila isi klip mendukung.** Pakai pemetaan katalog: angka/punchline → `zoom_through_text`;
   tren → `chart_grow`; daftar/langkah → `checklist`; aplikasi/produk/layar → `ui_panel` atau
   `phone_frame`; pengungkapan sebelum→sesudah → `pullback`. Tidak ada pemicu = tidak ada efek.
   Klip tanpa overlay sama sekali adalah hasil yang sah.
2. **Hormati `fits`.** Usulkan hanya efek dengan `ok: true`, dan pakai `suggested_window`. Pada
   `close_up` kartu (`checklist`, `chart_grow`, `ui_panel`, `phone_frame`) tidak punya area bebas:
   pilih `zoom_through_text`/`pullback`, atau beri `rect` eksplisit yang tidak menutup mata/mulut.
3. **Anggaran:** paling banyak 3 overlay per klip, kartu tidak berimpit dan berjarak ≥ 10 s, tidak mulai
   di 2 detik pertama kecuali efek itu hook-nya (`"hook": true` dan jelaskan alasannya).
4. **Data harus berasal dari klip.** Label, nilai, dan tag grafik, butir checklist, serta angka
   `pullback` harus diambil dari yang DIUCAPKAN di klip. Jangan mengarang angka. Bila penutur tidak
   menyebut data, jangan buat grafik.
5. **Tulis `reason` konkret** (1 kalimat, merujuk isi klip). Item tanpa alasan ditolak.

```bash
python3 -m scripts.cli fx-validate work/<nama>         # → fx_plan.report.json + .md (diterima/ditolak + alasan)
python3 -m scripts.cli fx-preview work/<nama>          # pratinjau + lembar kontak di work/<nama>/fx_preview/
```

Baca `fx_plan.report.md`; perbaiki item yang ditolak (jangan memaksa lolos). Tunjukkan lembar kontak
`fx_preview/contact_sheet.png` ke user dan **tunggu persetujuan eksplisit**. Hanya setelah user
menyetujui:

```bash
python3 -m scripts.cli fx-apply work/<nama> --approve  # tulis overlays[] ke edl.json (cadangan otomatis)
python3 -m scripts.cli fx-undo work/<nama>             # batalkan bila user berubah pikiran
python3 -m scripts.cli render work/<nama> --top 3
```

Jangan: menerapkan tanpa persetujuan, menambah efek supaya "ramai", mengklaim efek menaikkan retensi,
atau menutupi wajah pada close-up tanpa sepengetahuan user (item `accepted_with_warnings` harus
disebutkan ke user beserta peringatannya).

## Format output agent

Tulis ke `work/<nama>/selection.json`:

```json
{
  "version": "0.1.0",
  "candidates": [
    {
      "id": 3,
      "atom_start": 12,
      "atom_end": 17,
      "axes": {
        "hook":            {"score": 8, "evidence": "Codex atau Claude? Mana yang lebih oke?"},
        "payoff":          {"score": 7, "evidence": "..."},
        "self_contained":  {"score": 9, "evidence": "..."},
        "emotional":       {"score": 6, "evidence": "..."},
        "concrete":        {"score": 7, "evidence": "..."},
        "loop":            {"score": 4, "evidence": "..."}
      },
      "weakest_axis": "loop",
      "fix_suggestion": "ulangi pertanyaan pembuka di 2 detik terakhir"
    }
  ]
}
```

## Cara membaca hasil

`score-validate` menolak selection yang:
- tidak lengkap 6 axis,
- `evidence` kosong,
- `atom_start`/`atom_end` berbeda dari kandidat asli,
- berisi field `total` / `final` / `score_total` (skor total bukan tugas agent).

Skor akhir disajikan sebagai **percentile dalam library**, bukan prediksi viral.
Sampaikan ke user dengan bahasa itu.

## Jangan

- Jangan klaim "video ini akan viral". Skor adalah ranker relatif.
- Jangan menilai dari ringkasan — baca teks kandidat lengkap.
- Jangan menilai lebih dari 15 kandidat; kalau perlu lebih, naikkan `--top-n` di
  langkah `candidates` dulu.
