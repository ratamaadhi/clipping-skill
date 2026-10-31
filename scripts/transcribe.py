"""Transkripsi word-level. Pluggable: Groq / OpenAI / Deepgram / faster-whisper lokal.

Semua engine dinormalisasi ke format yang sama (schema/transcript.schema.json).
Kalau API tidak mengembalikan word-level, waktu kata diestimasi dari segmen —
caption jadi kurang presisi tapi pipeline tidak berhenti.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .lib import jsonio

TIMEOUT = 900  # detik; file panjang butuh waktu

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

TRANSCRIPT = "transcript.json"


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
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("DEEPGRAM_API_KEY"):
        return "deepgram"
    return "local"


# ---------------------------------------------------------------------------
# HTTP helper (stdlib only)
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


def _post(
    url: str, body: bytes, content_type: str, headers: dict[str, str]
) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise TranscribeError(f"{url} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TranscribeError(f"tidak bisa menghubungi {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Normalisasi
# ---------------------------------------------------------------------------


def _estimate_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback: sebar waktu segmen ke kata secara proporsional panjang kata."""
    words: list[dict[str, Any]] = []
    idx = 0
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
        for tok, w in zip(toks, weights):
            dur = span * w / total
            words.append(
                {
                    "i": idx,
                    "w": tok,
                    "start": round(t, 3),
                    "end": round(t + dur, 3),
                    "speaker": seg.get("speaker"),
                    "conf": None,
                }
            )
            idx += 1
            t += dur
    return words


def _normalize(
    raw_words: list[dict[str, Any]] | None,
    segments: list[dict[str, Any]] | None,
    *,
    source: str,
    language: str | None,
    duration: float,
    engine: str,
) -> dict[str, Any]:
    words: list[dict[str, Any]] = []
    if raw_words:
        for i, w in enumerate(raw_words):
            text = str(w.get("word") or w.get("punctuated_word") or w.get("w") or "").strip()
            if not text:
                continue
            words.append(
                {
                    "i": len(words),
                    "w": text,
                    "start": round(float(w.get("start") or 0.0), 3),
                    "end": round(float(w.get("end") or 0.0), 3),
                    "speaker": w.get("speaker"),
                    "conf": w.get("confidence") if w.get("confidence") is not None else w.get("conf"),
                }
            )
    elif segments:
        words = _estimate_from_segments(segments)

    if not words:
        raise TranscribeError("tidak ada kata yang bisa diekstrak dari respons ASR")

    return {
        "version": "0.1.0",
        "source": source,
        "language": language or "unknown",
        "duration": round(float(duration), 3),
        "engine": engine,
        "words": words,
        "segments": segments or [],
    }


# ---------------------------------------------------------------------------
# Engine implementations
# ---------------------------------------------------------------------------


def _openai_compatible(
    audio: Path, key: str, url: str, model: str, language: str | None, engine: str
) -> dict[str, Any]:
    fields = {
        "model": model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    if language:
        fields["language"] = language

    body, ctype = _multipart(
        fields, {"file": (audio.name, audio.read_bytes(), "audio/wav")}
    )
    data = _post(url, body, ctype, {"Authorization": f"Bearer {key}"})

    segs = [
        {"start": s.get("start"), "end": s.get("end"), "text": s.get("text", "")}
        for s in data.get("segments", []) or []
    ]
    dur = float(segs[-1]["end"]) if segs and segs[-1].get("end") else 0.0
    return _normalize(
        data.get("words"),
        segs,
        source=str(audio),
        language=data.get("language") or language,
        duration=dur,
        engine=engine,
    )


def _deepgram(audio: Path, key: str, language: str | None) -> dict[str, Any]:
    params = "model=nova-3&smart_format=true&punctuate=true&diarize=true&utterances=true"
    if language:
        params += f"&language={language}"
    url = f"{DEEPGRAM_URL}?{params}"
    body = audio.read_bytes()
    data = _post(url, body, "audio/wav", {"Authorization": f"Token {key}"})

    try:
        alt = data["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError) as exc:
        raise TranscribeError("respons Deepgram tidak dikenali") from exc

    segs = [
        {"start": u.get("start"), "end": u.get("end"), "text": u.get("transcript", ""),
         "speaker": u.get("speaker")}
        for u in data.get("results", {}).get("utterances", []) or []
    ]
    dur = float(alt.get("words", [{}])[-1].get("end", 0.0)) if alt.get("words") else 0.0
    return _normalize(
        alt.get("words"),
        segs,
        source=str(audio),
        language=language,
        duration=dur,
        engine="deepgram",
    )


def _local(audio: Path, language: str | None) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise TranscribeError(
            "faster-whisper belum terpasang. Jalankan `pip install faster-whisper` "
            "di venv Python 3.11-3.12 (ctranslate2 belum ada wheel untuk 3.14), "
            "atau pakai engine API: GROQ_API_KEY / OPENAI_API_KEY / DEEPGRAM_API_KEY."
        ) from exc

    model = WhisperModel(os.environ.get("CLIP_WHISPER_MODEL", "small"), device="auto")
    segments_iter, info = model.transcribe(
        str(audio), language=language, word_timestamps=True, vad_filter=True
    )

    words: list[dict[str, Any]] = []
    segs: list[dict[str, Any]] = []
    for seg in segments_iter:
        segs.append({"start": seg.start, "end": seg.end, "text": seg.text})
        for w in seg.words or []:
            words.append(
                {"word": w.word, "start": w.start, "end": w.end, "confidence": w.probability}
            )

    dur = segs[-1]["end"] if segs else 0.0
    return _normalize(
        words,
        segs,
        source=str(audio),
        language=getattr(info, "language", language),
        duration=dur,
        engine="local",
    )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def run(
    work_dir: str | Path,
    engine: str | None = None,
    language: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    wd = Path(work_dir)
    meta = jsonio.read_json(wd / "meta.json")
    out_path = wd / TRANSCRIPT

    if out_path.exists() and not force:
        return jsonio.read_json(out_path)

    if not meta.get("has_audio"):
        raise TranscribeError("sumber tidak punya audio — tidak ada yang bisa ditranskripsi")

    audio16 = Path(meta.get("audio16") or "")
    if not audio16.exists():
        raise FileNotFoundError(f"audio 16k tidak ada: {audio16}")

    chosen = pick_engine(engine)
    lang = language or os.environ.get("CLIP_LANGUAGE") or None

    if chosen == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise TranscribeError("GROQ_API_KEY kosong")
        transcript = _openai_compatible(
            audio16, key, GROQ_URL, "whisper-large-v3-turbo", lang, "groq"
        )
    elif chosen == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise TranscribeError("OPENAI_API_KEY kosong")
        transcript = _openai_compatible(audio16, key, OPENAI_URL, "whisper-1", lang, "openai")
    elif chosen == "deepgram":
        key = os.environ.get("DEEPGRAM_API_KEY")
        if not key:
            raise TranscribeError("DEEPGRAM_API_KEY kosong")
        transcript = _deepgram(audio16, key, lang)
    elif chosen == "local":
        transcript = _local(audio16, lang)
    else:
        raise TranscribeError(
            f"engine {chosen!r} tidak dikenal. Pilih: groq, openai, deepgram, local"
        )

    transcript["source"] = meta.get("source", str(audio16))
    if not transcript.get("duration"):
        transcript["duration"] = meta.get("duration", 0.0)

    jsonio.write_json(out_path, transcript)
    meta["language"] = transcript.get("language")
    jsonio.write_json(wd / "meta.json", meta)
    return transcript
