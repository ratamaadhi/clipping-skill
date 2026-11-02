"""Oracle celah tinta antar-kata pada render libass NYATA (Langkah 3b-iii).

Kenapa tes ini ada: seluruh tes `kinetic` lain mengukur dengan `fontmetrics`
Python, jadi mereka konsisten dengan dirinya sendiri walau jarak antar-kata
runtuh di layar. Cacat yang ditutup di sini terukur pada render sungguhan
(docs/MOTION-TIER2-PLAN.md, "Temuan visual pertama"): `apa` + `enggak`
terbaca "apaenggak" karena celah tinta hanya 7 px, sedangkan celah antar-huruf
di dalam kata 6-11 px, sehingga kata tak bisa dibedakan dari huruf.

Tiga penyebab yang DIVERIFIKASI di sini, bukan diterima buta:

1. `layout_phrase` dulu mengukur kata pada skala 100%, padahal kata emphasis
   digambar 112%: tepi tinta bergeser keluar `(s-1)/2 x lebar` (16 px untuk
   "enggak" selebar 336 px) dan memakan celah 23,5 px. Terukur: `apa|enggak`
   menyisakan 7 px, dan `apa|capeknya` 0 px karena kotak advance-nya
   BERTUMPUK (336 + 443 px pada dua kata yang seharusnya muat).
2. Garis tepi (Outline 7 px) kata yang digambar BELAKANGAN menutup sisa celah:
   tidak ada satu pun piksel latar di antara kata.
3. Bearing sisi glyph (lsb glyph pertama, rsb glyph terakhir) bukan bagian dari
   `gap_em x size`, sehingga celah yang dijanjikan rumus bukan celah terlihat.

Cara mengukur, sesuai spesifikasi tugas: tinta tiap kata ditentukan dengan
MENUGASKAN KOLOM ke kata yang pusat `\\pos`-nya TERDEKAT, bukan dengan ambang
celah piksel. Pada render CACAT celah antar-kata 7 px tidak bisa dipisahkan
dari celah antar-huruf 6-11 px dengan ambang apa pun; pembagian pada titik
tengah antar-`\\pos` selalu bisa, dan itulah yang membuat tes ini bisa MERAH
pada kode lama tanpa lebih dulu memakai API baru.

Tes SKIP bila tidak ada ffmpeg ber-libass; lihat `tests/ffmpeg_libass.py`.
"""

from __future__ import annotations

import inspect
import math
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

from tests.ffmpeg_libass import find_ffmpeg_with_libass

from scripts import kinetic
from scripts.lib import fontmetrics

FONT_DIR = ROOT / "assets" / "fonts"
FONT_FILE = FONT_DIR / "ArchivoBlack-Regular.ttf"

PLAY_W = 1080
PLAY_H = 1920
FPS = 30
SIZE = 84.0
CENTER_Y = 1400.0

# Pita ukur. Semua skenario di bawah muat SATU baris (dijaga
# `test_every_scenario_is_a_single_line`), jadi pita ini hanya berisi tinta
# baris itu; 1300-1500 menutup ascender/descender Archivo Black pada em 84.
BAND = (1300, 1500)

# Batas dari spesifikasi tugas 3b-iv: 28 px <= celah tinta <= 38 px setelah
# settle. Batas lama [18, 40] meloloskan clearance 0,10 em (celah 22-24 px,
# ~63% jarak alami Archivo Black) - kesalahan koordinator di 3b-iii yang
# diperbaiki di sini. Target 0,22 em = 32,48 px (~92% jarak alami).
GAP_MIN = 28.0
GAP_MAX = 38.0

# Toleransi pusat tinta terhadap `\\pos` yang diparse dari ASS. Sama dengan
# `tests/test_kinetic_libass_oracle.py`: pusat glyph vs `\\an5\\pos` di PlayRes
# yang sama; terukur maksimum 0,66 px pada kode sekarang.
CENTER_TOL_PX = 3.0

# Puncak overshoot spring: skala emphasis 116,36% pada frame ke-5 (t=1/6 s),
# bukan 112% akhirnya. Angka ini dihitung dari `kinetic.spring_chain` yang
# dipakai produk, bukan diketik manual, dan dipakai untuk memperbesar kotak
# ukur pada frame overshoot (tanpa itu tinta puncak keluar dari kotak akhir
# dan pengaman "tinta di luar kotak" akan gagal palsu).
OVERSHOOT_GAP_MIN = 4.0
OVERSHOOT_FRAMES = (2, 3, 4, 5)


def _scale_from_chain(chain: list[tuple[int, float]], t_ms: float) -> float:
    """Skala rantai `\\t` pada `t_ms`, interpolasi linear antar titik.

    Rantai inilah yang benar-benar dieksekusi libass, jadi mengukur kotak pada
    skala ini berarti mengukur kotak yang benar-benar digambar - bukan skala
    akhir dan bukan puncak. Diperlukan karena pada frame ke-2 skala emphasis
    baru 95,6% (di BAWAH 112%), dan memakai kotak 116% akan membuat kotak
    tetangga menelan tinta kata emphasis.
    """
    if t_ms <= chain[0][0]:
        return chain[0][1] / 100.0
    for (t0, v0), (t1, v1) in zip(chain, chain[1:]):
        if t0 <= t_ms <= t1:
            f = 0.0 if t1 == t0 else (t_ms - t0) / (t1 - t0)
            return (v0 + (v1 - v0) * f) / 100.0
    return chain[-1][1] / 100.0


def _peak_scale() -> float:
    """Skala maksimum yang dicapai rantai spring untuk target emphasis."""
    chain = kinetic.spring_chain(float(FPS), kinetic.SCALE_EMPHASIS)
    return max(v for _ms, v in chain) / 100.0


def _scales_at(event_start: float, t_abs: float) -> tuple[float, float]:
    """(skala kata biasa, skala kata emphasis) pada waktu absolut `t_abs`.

    Kata biasa sudah settle (mulai >= 0,35 s sebelumnya, settle 0,224 s), jadi
    skalanya 100%. Kata emphasis mengikuti rantai `\\t` produk, yang mulai
    berjalan pada `Start` EVENT-nya - yaitu `word.start - lead`, bukan
    `word.start`. Memakai `word.start` menggeser rantai 40 ms dan membuat kotak
    ukur tidak cocok dengan glyph yang benar-benar digambar.
    """
    chain = kinetic.spring_chain(float(FPS), kinetic.SCALE_EMPHASIS)
    t_ms = (t_abs - event_start) * 1000.0
    return 1.0, _scale_from_chain(chain, t_ms)

# Outline dari template (satu sumber: `kinetic.OUTLINE_PX`). Pada kode lama
# konstanta itu belum ada, jadi dibaca dengan getattr supaya tes ini tetap
# MENJALAN dan melaporkan angka celah, bukan gagal dengan AttributeError.
OUTLINE_PX = float(getattr(kinetic, "OUTLINE_PX", 7.0))
OUTLINE_DROP = 2.0 * OUTLINE_PX          # 14 px
OUTLINE_DROP_TOL = 3.0

_FFMPEG = find_ffmpeg_with_libass()

SKIP_REASON = (
    "tidak ada ffmpeg dengan filter 'subtitles' (libass). Pasang dengan "
    "`brew install ffmpeg-full` (Homebrew Apple Silicon: "
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg; Intel: "
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg) atau set env CLIP_FFMPEG ke path "
    "ffmpeg berlibass. Formula `ffmpeg` Homebrew biasa dibangun tanpa libass."
)

# ---------------------------------------------------------------------------
# Skenario
# ---------------------------------------------------------------------------

def _words(*items: str, start: float = 0.30) -> list[dict]:
    """Kata berurutan, masing-masing 0,25 s, mulai tiap 0,35 s."""
    return [
        {
            "w": w,
            "start": round(start + i * 0.35, 3),
            "end": round(start + i * 0.35 + 0.25, 3),
        }
        for i, w in enumerate(items)
    ]


# (nama, kata, kata beremphasis atau None)
#
# (i)   kata pendek di sebelah kata PANJANG beremphasis
# (ii)  kata panjang di sebelah kata PENDEK beremphasis
# (iii) emphasis pada kata pertama / tengah / terakhir sebuah baris
# (iv)  tanpa emphasis (baseline)
SCENARIOS = [
    ("i-pendek-lalu-panjang", ("apa", "enggak"), "enggak"),
    ("i-pendek-lalu-sangat-panjang", ("apa", "capeknya"), "capeknya"),
    ("ii-panjang-lalu-pendek", ("dimusuhin", "dia"), "dia"),
    ("ii-panjang-lalu-pendek-2", ("capeknya", "lu"), "lu"),
    ("iii-emphasis-pertama", ("enggak", "apa"), "enggak"),
    ("iii-emphasis-tengah", ("apa", "enggak", "dia"), "enggak"),
    ("iii-emphasis-terakhir", ("apa", "dia", "enggak"), "enggak"),
    ("iv-tanpa-emphasis-2-kata", ("apa", "enggak"), None),
    ("iv-tanpa-emphasis-3-kata", ("apa", "enggak", "dia"), None),
]


def _clip(words: list[dict], emphasis: str | None) -> dict:
    cap = {
        "start": words[0]["start"],
        "end": round(words[-1]["end"] + 0.6, 3),
        "text": " ".join(w["w"] for w in words),
        "words": words,
    }
    if emphasis:
        cap["emphasis"] = emphasis
    return {"caption_style": "kinetic", "captions": [cap]}


# ---------------------------------------------------------------------------
# Render + ukur
# ---------------------------------------------------------------------------

def _render_frame(ass_text: str, frame: int) -> bytes:
    """Render ASS ke frame ke-`frame` di atas hitam 1080x1920; balikkan rgb24."""
    assert _FFMPEG is not None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ass_file = tmp_path / "clip.ass"
        ass_file.write_text(ass_text, encoding="utf-8")
        out_file = tmp_path / "frame.raw"

        chain = (
            f"subtitles={ass_file.name}:fontsdir={FONT_DIR},"
            f"trim=start_frame={frame}:end_frame={frame + 1},"
            f"setpts=PTS-STARTPTS"
        )
        cmd = [
            _FFMPEG,
            "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c=black:s={PLAY_W}x{PLAY_H}:d=6:r={FPS}",
            "-vf", chain,
            "-frames:v", "1",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            str(out_file),
        ]
        proc = subprocess.run(
            cmd, cwd=tmp_path, capture_output=True, timeout=180, check=False
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"ffmpeg gagal ({proc.returncode}): {proc.stderr.decode()[:800]}"
            )
        data = out_file.read_bytes()

    expected = PLAY_W * PLAY_H * 3
    if len(data) != expected:
        raise AssertionError(f"ukuran frame {len(data)} != {expected} byte")
    return data


def _ink_columns(frame: bytes, y0: int, y1: int) -> list[int]:
    """Kolom berisi tinta (putih atau kuning aksen) di pita [y0, y1).

    Ambang sama dengan `tests/test_kinetic_libass_oracle.py`: inti glyph saja,
    bukan halo anti-alias gelap dan bukan garis tepi hitam.
    """
    cols: set[int] = set()
    stride = PLAY_W * 3
    for y in range(max(0, y0), min(PLAY_H, y1)):
        base = y * stride
        row = frame[base : base + stride]
        for x in range(PLAY_W):
            i = x * 3
            r = row[i]
            g = row[i + 1]
            b = row[i + 2]
            if r > 200 and g > 200 and (b > 200 or b < 90):
                cols.add(x)
    return sorted(cols)


def _dialogue_lines(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def _ass_seconds(stamp: str) -> float:
    h, m, sec = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def _pos_x(line: str) -> float:
    m = re.search(r"\\pos\(([-\d.]+),([-\d.]+)\)", line)
    if not m:
        raise AssertionError(f"tidak ada \\pos di baris: {line!r}")
    return float(m.group(1))


class _Spacing:
    """Pusat `\\pos` tiap kata + penugasan kolom tinta per BATAS KOTAK.

    Kenapa BUKAN "kolom -> kata yang pusat `\\pos`-nya terdekat" (metode yang
    ditulis di spesifikasi awal tugas): metode itu TERBUKTI SALAH pada kasus
    inti tugas ini. Terukur pada render nyata frasa `apa enggak` (emphasis
    `enggak`, frame settle): `\\pos` apa=342,4, `\\pos` enggak=633,3, titik
    tengah 487,9. Tinta kiri "enggak" mulai di kolom 448 - jaraknya 188,3 px
    ke pusat "enggak" tetapi hanya 102,6 px ke pusat "apa", sehingga metode
    nearest-centre menugaskan tinta "enggak" ke "apa" dan melaporkan celah 0 px
    untuk SEMUA pasangan. Penyebabnya: kata emphasis yang LEBAR menggeser tepi
    kirinya jauh ke kiri, melewati titik tengah antar-`\\pos`. Itu justru
    skenario (i) yang jadi inti tugas.

    Metode yang dipakai di sini adalah turunan GEOMETRI, bukan ambang piksel:
    kotak tiap kata = `\\pos +- advance x skala / 2` (persis kotak yang dipakai
    libass untuk menggambar glyph, karena `\\an5` memusatkan glyph di `\\pos`).
    Kolom tinta di dalam satu kotak milik kata itu; kolom di antara dua kotak
    dibelah di titik tengah antar-tepi kotak. Tidak ada ambang yang di-tuning,
    sehingga metode ini tetap bisa MERAH pada render cacat (celah 7 px) yang
    tidak bisa dipisahkan dengan ambang.

    Tiga pengaman (diminta koordinator) supaya pengukuran tidak bisa lolos
    diam-diam bila penugasan salah:

    1. **Partisi penuh**: setiap kolom tinta di pita baris dipetakan ke TEPAT
       satu kata; tidak ada kolom yatim atau kolom ganda.
    2. **Tinta di dalam kotak**: rentang tinta tiap kata harus berada di dalam
       kotaknya yang dikembangkan `outline_px + 2` px. Kalau tidak, tata letak
       atau pengukuran menyimpang dan tes gagal dengan pesan jelas.
    3. **Titik belah bebas tinta**: kolom belah dan satu kolom di kiri-kanannya
       tidak boleh berisi tinta; kalau berisi, penugasan ambigu dan tes gagal
       (BUKAN melaporkan celah 0).
    """

    __slots__ = (
        "texts", "centers", "starts", "scales", "advances", "boxes",
        "emphasis_index",
    )

    def __init__(self, words: list[dict], ass: str, emphasis: str | None) -> None:
        font = fontmetrics.Font.load(FONT_FILE)
        self.texts = [w["w"] for w in words]
        self.scales = [
            (kinetic.SCALE_EMPHASIS / 100.0) if (emphasis and t == emphasis) else 1.0
            for t in self.texts
        ]
        self.emphasis_index = next(
            (i for i, s in enumerate(self.scales) if s != 1.0), -1
        )
        lines = _dialogue_lines(ass)
        if len(lines) != len(words):
            raise AssertionError(
                f"{len(lines)} Dialogue untuk {len(words)} kata: {self.texts}"
            )
        self.centers = [_pos_x(ln) for ln in lines]
        self.starts = [_ass_seconds(ln.split(",", 9)[1]) for ln in lines]
        self.advances = [font.width(t, SIZE) for t in self.texts]
        self.boxes = [
            (c - a * s / 2.0, c + a * s / 2.0)
            for c, a, s in zip(self.centers, self.advances, self.scales)
        ]

    # -- penugasan ---------------------------------------------------------

    def columns_by_word(
        self,
        frame: bytes,
        scales: list[float] | None = None,
        visible: set[int] | None = None,
    ) -> list[list[int]]:
        """Kolom tinta per kata; partisi penuh + pengaman 2 dan 3.

        `visible` membatasi pengaman ke kata yang sudah tampil (dipakai pada
        frame awal, saat kata berikutnya belum muncul sama sekali). Default:
        semua kata.

        Raises:
            AssertionError: bila ada kolom yatim/ganda, tinta di luar kotak
                yang dikembangkan, atau titik belah yang menyentuh tinta.
        """
        if scales is None:
            scales = self.scales
        if visible is None:
            visible = set(range(len(self.texts)))
        boxes = [
            (c - a * s / 2.0, c + a * s / 2.0)
            for c, a, s in zip(self.centers, self.advances, scales)
        ]
        cols = _ink_columns(frame, *BAND)
        if not cols:
            raise AssertionError(
                f"tidak ada tinta di pita {BAND} untuk {self.texts}; "
                f"render kosong atau frasa sudah keluar"
            )
        groups: list[list[int]] = [[] for _ in self.centers]
        slack = OUTLINE_PX + 2.0

        # Pengaman 3: setiap titik belah harus bebas tinta.
        colset = set(cols)
        for i in range(len(boxes) - 1):
            if i not in visible or i + 1 not in visible:
                continue
            boundary = (boxes[i][1] + boxes[i + 1][0]) / 2.0
            for probe in (math.floor(boundary), math.ceil(boundary)):
                for x in (probe - 1, probe, probe + 1):
                    if x in colset:
                        raise AssertionError(
                            f"penugasan ambigu: titik belah {boundary:.1f} antara "
                            f"{self.texts[i]!r} dan {self.texts[i + 1]!r} menyentuh "
                            f"tinta di kolom {x} (kotak "
                            f"{boxes[i][1]:.1f}/{boxes[i + 1][0]:.1f}). "
                            f"Jangan melaporkan celah 0; periksa tata letak."
                        )

        # Penugasan: kolom di dalam kotak -> kata itu; di antara kotak ->
        # dibelah di titik tengah antar-tepi kotak.
        for x in cols:
            owner = None
            for k, (lo, hi) in enumerate(boxes):
                if lo <= x <= hi:
                    owner = k
                    break
            if owner is None:
                for k in range(len(boxes) - 1):
                    if boxes[k][1] < x < boxes[k + 1][0]:
                        boundary = (boxes[k][1] + boxes[k + 1][0]) / 2.0
                        owner = k if x <= boundary else k + 1
                        break
            if owner is None:
                raise AssertionError(
                    f"kolom tinta {x} tidak masuk kotak kata mana pun: "
                    f"{[(round(a, 1), round(b, 1)) for a, b in boxes]}"
                )
            groups[owner].append(x)

        # Pengaman 1: partisi penuh, tanpa kolom yatim atau ganda.
        total = sum(len(g) for g in groups)
        if total != len(cols):
            raise AssertionError(
                f"partisi tidak penuh: {len(cols)} kolom tinta tetapi {total} "
                f"ditugaskan ({[len(g) for g in groups]})"
            )
        for k, g in enumerate(groups):
            if not g:
                if k not in visible:
                    continue  # kata ini belum tampil; tidak ada tinta memang
                raise AssertionError(
                    f"kata {self.texts[k]!r} tidak mendapat kolom tinta; "
                    f"penugasan salah (kotak {boxes[k]})"
                )

        # Pengaman 2: tinta tiap kata di dalam kotaknya + (outline + 2) px.
        for k, g in enumerate(groups):
            if not g:
                continue
            lo, hi = boxes[k]
            if g[0] < lo - slack or g[-1] > hi + slack:
                raise AssertionError(
                    f"tinta di luar kotak untuk {self.texts[k]!r}: tinta "
                    f"[{g[0]}, {g[-1]}] vs kotak [{lo:.1f}, {hi:.1f}] "
                    f"(toleransi {slack:.1f} px)"
                )
        return groups

    def ink_gap(
        self,
        frame: bytes,
        i: int,
        j: int,
        scales: list[float] | None = None,
        visible: set[int] | None = None,
    ) -> float:
        """Celah tinta (px) antara kata `i` (kiri) dan `j` (kanan).

        `scales` default skala AKHIR (settle). Untuk frame overshoot, kirim
        `self.peak_scales` supaya kotak ukur mengikuti skala sesaat.

        Negatif bila kotak advance BERSKALA kedua kata bertumpuk: pada kasus
        itu tinta kata kanan sudah masuk ke dalam kotak kata kiri, jadi tidak
        ada celah yang bisa diukur dan angkanya dilaporkan apa adanya.
        """
        if scales is None:
            scales = self.scales
        if visible is None:
            visible = set(range(len(self.texts)))
        overlap = (
            self.centers[i] + self.advances[i] * scales[i] / 2.0
            - (self.centers[j] - self.advances[j] * scales[j] / 2.0)
        )
        if overlap > 0:
            return -overlap
        groups = self.columns_by_word(frame, scales, visible)
        return float(groups[j][0] - groups[i][-1] - 1)


def _settle_frame(words: list[dict]) -> int:
    """Frame setelah kata TERAKHIR settle (0,60 s > settle 0,224 s)."""
    return int(round((words[-1]["start"] + 0.60) * FPS))


def _row_of_words(words: list[dict]) -> list[int]:
    font = fontmetrics.Font.load(FONT_FILE)
    pos = kinetic.layout_phrase(
        [{"w": w["w"]} for w in words], font, SIZE, center_y=CENTER_Y
    )
    return [p["line"] for p in pos]


# ---------------------------------------------------------------------------
# Tes
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class InkSpacingTest(unittest.TestCase):
    """Celah tinta antar-kata pada render libass sungguhan."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ass: dict[str, str] = {}
        cls.spacing: dict[str, _Spacing] = {}
        cls.words: dict[str, list[dict]] = {}
        cls._frames: dict[tuple[str, int], bytes] = {}
        for name, items, emphasis in SCENARIOS:
            words = _words(*items)
            cls.words[name] = words
            ass = kinetic.build_ass(_clip(words, emphasis), fps=FPS)
            cls.ass[name] = ass
            cls.spacing[name] = _Spacing(words, ass, emphasis)

    def _frame(self, name: str, frame: int) -> bytes:
        key = (name, frame)
        if key not in self._frames:
            self._frames[key] = _render_frame(self.ass[name], frame)
        return self._frames[key]

    def _report(self) -> str:
        lines = []
        for name, _, _ in SCENARIOS:
            words = self.words[name]
            sp = self.spacing[name]
            frame = self._frame(name, _settle_frame(words))
            for i in range(len(words) - 1):
                lines.append(
                    f"  {name:30s} {sp.texts[i]}|{sp.texts[i + 1]:12s}"
                    f" {sp.ink_gap(frame, i, i + 1):7.0f} px"
                )
        return "\n".join(lines)

    def test_every_scenario_is_a_single_line(self) -> None:
        """Pengaman: skenario harus satu baris, kalau tidak pita BAND salah.

        Tanpa ini, skenario yang tanpa sengaja membungkus dua baris akan
        mengukur tinta baris lain dan angkanya tidak bisa dipercaya.
        """
        for name, _, _ in SCENARIOS:
            rows = _row_of_words(self.words[name])
            self.assertEqual(set(rows), {0}, msg=f"{name}: baris {rows}")

    def test_settled_ink_gap_within_band_for_every_adjacent_pair(self) -> None:
        """28 <= celah tinta <= 38 px untuk SEMUA pasangan berdekatan.

        Pada kode SEBELUM perbaikan 3b-iii tes ini MERAH dengan 7 px
        (`apa|enggak`) dan 0 px (`apa|capeknya`, kotak advance bertumpuk) -
        angka yang sama dengan celah antar-huruf di dalam kata (6-11 px).
        Pada kode 3b-iii (clearance 0,10 em) celahnya 22-24 px: masih di luar
        pita ini, karena 22-24 px hanya ~63% jarak tinta alami Archivo Black
        (median 35,3 px pada transkrip nyata). Pita [28, 38] ditetapkan di
        3b-iv supaya kesalahan "terlalu rapat" itu tertangkap.
        """
        failures: list[str] = []
        for name, _, _ in SCENARIOS:
            words = self.words[name]
            sp = self.spacing[name]
            frame = self._frame(name, _settle_frame(words))
            for i in range(len(words) - 1):
                gap = sp.ink_gap(frame, i, i + 1)
                if not (GAP_MIN <= gap <= GAP_MAX):
                    failures.append(
                        f"  {name:30s} {sp.texts[i]}|{sp.texts[i + 1]:12s}"
                        f" {gap:7.0f} px (skala {sp.scales[i]:g}/{sp.scales[i + 1]:g})"
                    )
        self.assertEqual(
            failures, [],
            f"celah tinta di luar [{GAP_MIN:g}, {GAP_MAX:g}] px:\n"
            + "\n".join(failures)
            + "\nSemua celah terukur:\n"
            + self._report(),
        )

    def test_ink_centres_match_pos_parsed_from_the_ass(self) -> None:
        """Pusat tinta tiap kata = `\\pos` x yang di-PARSE dari ASS keluaran.

        Bebas-layout: tidak memanggil `layout_phrase` sama sekali, hanya membaca
        `\\pos` dari ASS yang benar-benar dikirim ke libass, lalu membandingkan
        dengan pusat tinta hasil render (+-3 px). Ini mengunci kesesuaian libass
        terhadap apa yang dikirim ke renderer, terlepas dari bagaimana Python
        menghitung tata letaknya - jadi kalau `build_ass` suatu saat menulis
        `\\pos` yang berbeda dari yang ia hitung sendiri, tes ini menangkapnya.

        Angka acuan pada kode sekarang (frame settle, 1080x1920): selisih
        maksimum 0,66 px pada keempat kata frasa oracle lama.
        """
        for name, _, _ in SCENARIOS:
            words = self.words[name]
            sp = self.spacing[name]
            frame = self._frame(name, _settle_frame(words))
            groups = sp.columns_by_word(frame)
            for k, g in enumerate(groups):
                ink_center = (g[0] + g[-1]) / 2.0
                self.assertAlmostEqual(
                    ink_center, sp.centers[k], delta=CENTER_TOL_PX,
                    msg=(
                        f"{name}: {sp.texts[k]!r} pusat tinta {ink_center:.2f} vs "
                        f"\\pos x {sp.centers[k]:.2f} (dibaca dari ASS)"
                    ),
                )

    def test_overshoot_peak_never_overlaps_neighbour(self) -> None:
        """Pada frame ke-2..5 sejak kata emphasis mulai, celah tinta >= 4 px.

        Skala puncak spring ~116%, yaitu 4 poin persen di atas 112%; untuk kata
        selebar 443 px itu 8,9 px per sisi. Celah target 32,48 px (3b-iv)
        menyisakan ~23 px, jadi >= 4 px harus bertahan dengan margin jauh.
        """
        checked = 0
        failures: list[str] = []
        for name, _, emphasis in SCENARIOS:
            if not emphasis:
                continue
            words = self.words[name]
            sp = self.spacing[name]
            k = sp.emphasis_index
            self.assertGreaterEqual(k, 0, msg=name)
            neighbours = [i for i in (k - 1, k + 1) if 0 <= i < len(words)]
            self.assertTrue(neighbours, msg=f"{name}: emphasis tanpa tetangga")
            for offset in OVERSHOOT_FRAMES:
                frame_idx = int(round((words[k]["start"] + offset / FPS) * FPS))
                t_abs = frame_idx / FPS
                frame = self._frame(name, frame_idx)
                for i in neighbours:
                    lo, hi = min(i, k), max(i, k)
                    # Celah ke kata yang belum tampil tidak bisa diukur. Alpha
                    # butuh 2 frame untuk penuh (`_alpha_tag`), jadi kata
                    # tetangga wajib sudah mulai >= 2 frame sebelum frame ini.
                    if t_abs + 1e-9 < max(sp.starts[lo], sp.starts[hi]) + 2.0 / FPS:
                        continue
                    plain, emph = _scales_at(sp.starts[k], t_abs)
                    scales = [
                        (emph if q == sp.emphasis_index else plain)
                        for q in range(len(words))
                    ]
                    visible = {
                        q for q in range(len(words))
                        if t_abs + 1e-9 >= sp.starts[q] + 2.0 / FPS
                    }
                    gap = sp.ink_gap(frame, lo, hi, scales, visible)
                    checked += 1
                    if gap < OVERSHOOT_GAP_MIN:
                        failures.append(
                            f"  {name:30s} +{offset} frame "
                            f"{sp.texts[lo]}|{sp.texts[hi]} = {gap:.0f} px"
                        )
        self.assertGreater(checked, 0, msg="tidak ada frame overshoot diukur")
        self.assertEqual(
            failures, [],
            f"celah tinta < {OVERSHOOT_GAP_MIN:g} px di puncak overshoot:\n"
            + "\n".join(failures),
        )


def _force_style_outline_zero(ass: str) -> str:
    """Ganti kolom Outline pada `Style: Kinetic` menjadi 0 (kode lama tanpa kwarg)."""
    out = []
    for line in ass.splitlines():
        if line.startswith("Style: Kinetic,"):
            fields = line[len("Style: "):].split(",")
            # Outline = kolom ke-16 (BorderStyle 15, Outline 16, Shadow 17).
            fields[16] = "0"
            line = "Style: " + ",".join(fields)
        out.append(line)
    return "\n".join(out)


def _supports_outline_kwarg() -> bool:
    """True bila `build_ass` sudah menerima `outline_px` (kode sesudah fix)."""
    return "outline_px" in inspect.signature(kinetic.build_ass).parameters


@unittest.skipUnless(_FFMPEG is not None, SKIP_REASON)
class OutlineSensitivityTest(unittest.TestCase):
    """Kontrol negatif: tes ini harus PEKA terhadap Outline dari template.

    Rumus celah yang dipakai: `celah_tinta = 2 x outline_px + clearance x size`.
    Kalau Outline dipaksa 0, celah tinta harus turun ~2 x Outline = 14 px,
    karena (a) template tidak lagi menggambar garis tepi dan (b) tata letak
    menghitung ulang celah kotak dari outline 0. Tanpa kontrol ini, tes bisa
    lulus karena kebetulan angka, bukan karena rumusnya benar.
    """

    NAMES = ("i-pendek-lalu-panjang", "iii-emphasis-tengah")

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases: dict[str, tuple[float, float]] = {}
        cls.zero_ass: dict[str, str] = {}
        for name, items, emphasis in SCENARIOS:
            if name not in cls.NAMES:
                continue
            words = _words(*items)
            clip = _clip(words, emphasis)
            frame = _settle_frame(words)

            normal_ass = kinetic.build_ass(clip, fps=FPS)
            if _supports_outline_kwarg():
                zero_ass = kinetic.build_ass(clip, fps=FPS, outline_px=0.0)
            else:
                # Kode lama: kwarg belum ada; paksa hanya kolom Style-nya.
                zero_ass = _force_style_outline_zero(normal_ass)

            normal = _render_frame(normal_ass, frame)
            zero = _render_frame(zero_ass, frame)
            sp_n = _Spacing(words, normal_ass, emphasis)
            sp_z = _Spacing(words, zero_ass, emphasis)
            cls.cases[name] = (
                sp_n.ink_gap(normal, 0, 1),
                sp_z.ink_gap(zero, 0, 1),
            )
            cls.zero_ass[name] = zero_ass

    def test_outline_zero_is_written_to_style(self) -> None:
        """Kolom Outline pada `Style: Kinetic` benar-benar 0 pada render kontrol."""
        for name, ass in self.zero_ass.items():
            style = [
                ln for ln in ass.splitlines() if ln.startswith("Style: Kinetic,")
            ][0]
            fields = style[len("Style: "):].split(",")
            self.assertEqual(fields[16], "0", msg=f"{name}: {style}")

    def test_outline_zero_shrinks_ink_gap_by_two_outline(self) -> None:
        """Celah tinta turun 2 x Outline (14 px) +-3 saat Outline dipaksa 0."""
        for name, (gap_normal, gap_zero) in self.cases.items():
            drop = gap_normal - gap_zero
            self.assertAlmostEqual(
                drop, OUTLINE_DROP, delta=OUTLINE_DROP_TOL,
                msg=(
                    f"{name}: celah {gap_normal:.0f} px (Outline {OUTLINE_PX:g}) "
                    f"-> {gap_zero:.0f} px (Outline 0), turun {drop:.0f} px; "
                    f"diharapkan {OUTLINE_DROP:.0f} +-{OUTLINE_DROP_TOL:g}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
