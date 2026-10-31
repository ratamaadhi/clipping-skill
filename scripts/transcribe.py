"""Transkripsi word-level. Pluggable, gratis-first.

Urutan pilihan untuk pemakaian gratis:
  1. groq      whisper-large-v3-turbo, ~8 jam audio/hari gratis, WER ID ~7%
  2. deepgram  nova-3 (diarization), $200 kredit sekali pakai
  3. local     faster-whisper / whisper.cpp, offline, tanpa kuota

Yang didiskualifikasi dan alasannya (lihat docs/TRANSCRIPTION.md):
  * Gemini / Mistral Voxtral — tidak memberi word-level timestamp
  * Vosk — tidak ada model Bahasa Indonesia di daftar resmi

Upload TIDAK memakai WAV. WAV 16k mono = 32 KB/s, jadi batas 25MB hanya cukup
13 menit. MP3 32 kbps = 4 KB/s, cukup ~1,7 jam. File panjang tetap di-chunk
karena alasan keandalan, bukan cuma ukuran.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .lib import audio as A
from .lib import chunk as chunk_mod
from .lib import jsonio

TRANSCRIPT = "transcript.json"
SILENCES = "silences.json"

TIMEOUT = 900
MAX_RETRIES = 5
USER_AGENT = "clipping-skill/0.1"

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# Batas upload Groq free tier 25MB; sisakan margin.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
AUDIO_BITRATE = "32k"

# Glosarium untuk parameter `prompt` (maks 224 token).
# Tujuan: ejaan konsisten untuk istilah tech + partikel percakapan Indonesia.
GLOSSARY_ID = (
    "Transkrip Bahasa Indonesia informal. "
    "Istilah: Codex, Claude, ChatGPT, Gemini, prompt, token, API, endpoint, "
    "repository, commit, deploy, debugging, bug, framework, backend, frontend, "
    "startup, konten, kreator, algoritma, engagement, hook, caption, editing, "
    "motion graphics, rilis, update, fitur, performa, metrik, retensi, viral. "
    "Ejaan: gak, nggak, banget, udah, bikin, gimana, kayak, doang, aja."
)

# Frasa halusinasi khas Whisper di musik atau keheningan.
HALLUCINATION_PHRASES = (
    "terima kasih telah menonton",
    "terima kasih sudah menonton",
    "jangan lupa subscribe",
    "subtitle by",
    "subtitles by",
    "thanks for watching",
    "amara.org",
    "transkripsi oleh",
)

NO_SPEECH_MAX = 0.60
AVG_LOGPROB_MIN = -1.0
COMPRESSION_MAX = 2.4


class TranscribeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------


def pick_engine(engine: str | None = None) -> str:
    chosen = (engine or os.environ.get("CLIP_ENGINE") or "").strip().lower()
    if chosen and chosen != "auto":
        return chosen
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("DEEPGRAM_API_KEY"):
        return "deepgram"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "local"


# ---------------------------------------------------------------------------
# HTTP (stdlib only, dengan retry)
# ---------------------------------------------------------------------------


def _multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    boundary = "----clipping" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    for name, (filename, data, ctype) in files.items():
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        ).encode()
        body += f"Content-Type: {ctype}\r\n\r\n".encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _retry_after(header: str | None, attempt: int) -> float:
    if header:
        try:
            return min(max(float(header), 1.0), 120.0)
        except ValueError:
            pass
    return min(2.0 ** attempt * 2, 60.0)


def _post(
    url: str, body: bytes, content_type: str, headers: dict[str, str]
) -> dict[str, Any]:
    """POST dengan retry pada 429/5xx. Hormati header retry-after."""
    last = ""
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", content_type)
        # User-Agent default urllib kadang diblok Cloudflare (403)
        req.add_header("User-Agent", USER_AGENT)
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                time.sleep(_retry_after(exc.headers.get("retry-after"), attempt))
                continue
            raise TranscribeError(f"{url} -> {last}") from exc
        except urllib.error.URLError as exc:
            last = str(exc.reason)
            if attempt < MAX_RETRIES - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise TranscribeError(f"tidak bisa menghubungi {url}: {last}") from exc

    raise TranscribeError(f"gagal setelah {MAX_RETRIES} percobaan: {last}")


# ---------------------------------------------------------------------------
# Encoding untuk upload
# ---------------------------------------------------------------------------


def encode_upload(
    src_wav: str | Path, dst: str | Path, start: float, duration: float
) -> Path:
    """Potong dari WAV 16k lalu encode ke MP3 kecil.

    Potong dari WAV (bukan dari mp3/aac) supaya offset sampel eksak dan tidak ada
    encoder delay yang menggeser timestamp.
    """
    out = Path(dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        A.FFMPEG,
        "-hide_banner",
        "-nostats",
        "-y",
        "-ss",
        f"{max(0.0, start):.3f}",
        "-t",
        f"{max(0.05, duration):.3f}",
        "-i",
        str(src_wav),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        AUDIO_BITRATE,
        str(out),
    ]
    A._run(cmd)
    size = out.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise TranscribeError(
            f"chunk {out.name} {size / 1024 / 1024:.1f}MB melebihi batas upload; "
            "kecilkan --chunk-seconds"
        )
    return out


# ---------------------------------------------------------------------------
# Normalisasi + filter halusinasi
# ---------------------------------------------------------------------------


def _bad_ranges(segments: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Segmen yang kemungkinan halusinasi: musik, senyap, atau teks template."""
    bad: list[tuple[float, float]] = []
    for seg in segments:
        text = str(seg.get("text") or "").strip().lower()
        if not text:
            continue
        span = (float(seg.get("start") or 0.0), float(seg.get("end") or 0.0))
        if any(p in text for p in HALLUCINATION_PHRASES):
            bad.append(span)
            continue
        try:
            nsp = float(seg.get("no_speech_prob") or 0.0)
            alp = float(seg.get("avg_logprob") or 0.0)
            cr = float(seg.get("compression_ratio") or 0.0)
        except (TypeError, ValueError):
            continue
        if nsp > NO_SPEECH_MAX and alp < AVG_LOGPROB_MIN:
            bad.append(span)
        elif cr > COMPRESSION_MAX:
            bad.append(span)
    return bad


def _drop_bad(
    words: list[dict[str, Any]], bad: list[tuple[float, float]]
) -> list[dict[str, Any]]:
    if not bad:
        return words
    kept = []
    for w in words:
        mid = (float(w["start"]) + float(w["end"])) / 2.0
        if any(a <= mid <= b for a, b in bad):
            continue
        kept.append(w)
    return kept


def _parse_words(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in raw:
        text = str(w.get("word") or w.get("punctuated_word") or w.get("w") or "").strip()
        if not text:
            continue
        out.append(
            {
                "w": text,
                "start": round(float(w.get("start") or 0.0), 3),
                "end": round(float(w.get("end") or 0.0), 3),
                "speaker": w.get("speaker"),
                "conf": w.get("confidence")
                if w.get("confidence") is not None
                else w.get("conf"),
            }
        )
    return out


def _estimate_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback bila API tidak memberi word-level: sebar waktu proporsional."""
    words: list[dict[str, Any]] = []
    for seg in segments:
        toks = str(seg.get("text", "")).split()
        if not toks:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 0.4 * len(toks)))
        span = max(0.1, end - start)
        weights = [max(1, len(t)) for t in toks]
        total = sum(weights)
        t = start
        for tok, weight in zip(toks, weights):
            dur = span * weight / total
            words.append(
                {
                    "w": tok,
                    "start": round(t, 3),
                    "end": round(t + dur, 3),
                    "speaker": seg.get("speaker"),
                    "conf": None,
                }
            )
            t += dur
    return words


# ---------------------------------------------------------------------------
# Engine implementations — kata dikembalikan relatif terhadap file yang dikirim
# ---------------------------------------------------------------------------


def _openai_compatible(
    audio: Path, key: str, url: str, model: str, language: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fields = {
        "model": model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
        "temperature": "0",
    }
    if language:
        fields["language"] = language
    if language in (None, "id"):
        fields["prompt"] = GLOSSARY_ID

    body, ctype = _multipart(
        fields, {"file": (audio.name, audio.read_bytes(), "audio/mpeg")}
    )
    data = _post(url, body, ctype, {"Authorization": f"Bearer {key}"})

    segments = list(data.get("segments") or [])
    raw_words = data.get("words") or []
    words = _parse_words(raw_words) if raw_words else _estimate_from_segments(segments)
    return _drop_bad(words, _bad_ranges(segments)), segments


def _deepgram(
    audio: Path, key: str, language: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = "model=nova-3&smart_format=true&punctuate=true&diarize=true&utterances=true"
    if language:
        params += f"&language={language}"
    body = audio.read_bytes()
    data = _post(
        f"{DEEPGRAM_URL}?{params}", body, "audio/mpeg", {"Authorization": f"Token {key}"}
    )

    try:
        alt = data["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError) as exc:
        raise TranscribeError("respons Deepgram tidak dikenali") from exc

    segments = [
        {
            "start": u.get("start"),
            "end": u.get("end"),
            "text": u.get("transcript", ""),
            "speaker": u.get("speaker"),
        }
        for u in data.get("results", {}).get("utterances", []) or []
    ]
    return _parse_words(alt.get("words") or []), segments


def _local(
    audio: Path, language: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise TranscribeError(
            "faster-whisper belum terpasang. `pip install faster-whisper` di venv "
            "Python 3.11-3.12 (ctranslate2 belum ada wheel untuk 3.14), atau pakai "
            "GROQ_API_KEY (gratis ~8 jam audio/hari)."
        ) from exc

    model = WhisperModel(os.environ.get("CLIP_WHISPER_MODEL", "small"), device="auto")
    iterator, _info = model.transcribe(
        str(audio),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        initial_prompt=GLOSSARY_ID if language in (None, "id") else None,
    )

    words: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for seg in iterator:
        segments.append({"start": seg.start, "end": seg.end, "text": seg.text})
        for w in seg.words or []:
            words.append(
                {"w": w.word, "start": w.start, "end": w.end, "conf": w.probability}
            )
    return _parse_words(words), segments


# ---------------------------------------------------------------------------
# Orkestrasi
# ---------------------------------------------------------------------------


def _detect_silences(wd: Path, audio16: str) -> list[tuple[float, float]]:
    cache = wd / SILENCES
    if cache.exists():
        return [(float(a), float(b)) for a, b in jsonio.read_json(cache)]
    found = A.detect_silences(audio16)
    jsonio.write_json(cache, [[round(a, 3), round(b, 3)] for a, b in found])
    return found


def _transcribe_chunked(
    wd: Path,
    audio16: str,
    engine: str,
    language: str | None,
    chunk_seconds: float,
    overlap: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    meta = jsonio.read_json(wd / "meta.json")
    duration = float(meta.get("duration") or 0.0)
    if duration <= 0:
        duration = A.probe(audio16).duration

    chunks = chunk_mod.plan(
        duration,
        target=chunk_seconds,
        overlap=overlap,
        silences=_detect_silences(wd, audio16),
    )

    tmp = wd / "chunks"
    tmp.mkdir(parents=True, exist_ok=True)

    per_chunk: list[list[dict[str, Any]]] = []
    all_segments: list[dict[str, Any]] = []

    for ch in chunks:
        mp3 = encode_upload(
            audio16, tmp / f"chunk_{ch.index:03d}.mp3", ch.start, ch.duration
        )
        try:
            if engine == "groq":
                words, segments = _openai_compatible(
                    mp3,
                    os.environ["GROQ_API_KEY"],
                    GROQ_URL,
                    "whisper-large-v3-turbo",
                    language,
                )
            elif engine == "openai":
                words, segments = _openai_compatible(
                    mp3, os.environ["OPENAI_API_KEY"], OPENAI_URL, "whisper-1", language
                )
            else:
                words, segments = _deepgram(
                    mp3, os.environ["DEEPGRAM_API_KEY"], language
                )
        finally:
            mp3.unlink(missing_ok=True)

        per_chunk.append(words)
        for seg in segments:
            all_segments.append(
                {
                    **seg,
                    "start": round(ch.start + float(seg.get("start") or 0.0), 3),
                    "end": round(ch.start + float(seg.get("end") or 0.0), 3),
                }
            )

    return chunk_mod.merge(per_chunk, chunks), all_segments


def run(
    work_dir: str | Path,
    engine: str | None = None,
    language: str | None = None,
    force: bool = False,
    chunk_seconds: float = chunk_mod.DEFAULT_TARGET,
    overlap: float = chunk_mod.DEFAULT_OVERLAP,
) -> dict[str, Any]:
    wd = Path(work_dir).expanduser().resolve()
    meta = jsonio.read_json(wd / "meta.json")
    out_path = wd / TRANSCRIPT

    if out_path.exists() and not force:
        return jsonio.read_json(out_path)

    if not meta.get("has_audio"):
        raise TranscribeError("sumber tidak punya audio")

    audio16 = meta.get("audio16")
    if not audio16 or not Path(audio16).exists():
        raise FileNotFoundError(f"audio 16k tidak ada: {audio16}")

    chosen = pick_engine(engine)
    lang = language or os.environ.get("CLIP_LANGUAGE") or None

    if chosen in ("groq", "openai", "deepgram"):
        if not os.environ.get(f"{chosen.upper()}_API_KEY"):
            raise TranscribeError(
                f"{chosen.upper()}_API_KEY kosong — isi .env, atau pakai engine lokal"
            )
        words, segments = _transcribe_chunked(
            wd, str(audio16), chosen, lang, chunk_seconds, overlap
        )
    elif chosen == "local":
        words, segments = _local(Path(audio16), lang)
        for i, w in enumerate(words):
            w["i"] = i
    else:
        raise TranscribeError(
            f"engine {chosen!r} tidak dikenal. Pilih: groq, openai, deepgram, local"
        )

    if not words:
        raise TranscribeError(
            "tidak ada kata yang lolos filter — cek audio, atau longgarkan threshold"
        )

    transcript = {
        "version": "0.1.0",
        "source": meta.get("source", str(audio16)),
        "language": lang or "unknown",
        "duration": round(float(meta.get("duration") or 0.0), 3),
        "engine": chosen,
        "words": words,
        "segments": segments,
    }
    jsonio.write_json(out_path, transcript)

    meta["language"] = transcript["language"]
    jsonio.write_json(wd / "meta.json", meta)
    return transcript
