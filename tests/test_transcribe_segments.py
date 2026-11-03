"""Filter halusinasi jalur Groq/OpenAI-kompatibel (Langkah G1).

Groq `whisper-large-v3-turbo` mengembalikan `segments: []` bila kode hanya
meminta granularitas `word`; akibatnya `_bad_ranges()` tidak pernah aktif di
jalur bawaan produk. Tes di sini memakai respons tiruan sepenuhnya: tanpa
jaringan, tanpa `.env`, tanpa ffmpeg.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.helpers import ROOT
from tests.test_schema_drift import missing_required, undeclared_keys

from scripts import transcribe as T

SCHEMA_PATH = ROOT / "schema" / "transcript.schema.json"


def _load_transcript_schema() -> dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _legacy_multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    """Salinan perilaku `_multipart` sebelum kunci berulang didukung."""
    boundary = "----clipping" + T.uuid.uuid4().hex
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


def _multipart_parts(ctype: str, body: bytes) -> list[tuple[str, bytes]]:
    """Kembalikan (nama field, payload) per bagian multipart."""
    boundary = ctype.split("boundary=", 1)[1].encode("ascii")
    parts: list[tuple[str, bytes]] = []
    for raw in body.split(b"--" + boundary):
        if not raw.startswith(b"\r\n"):
            continue
        raw = raw[2:]
        if raw.startswith(b"--"):
            continue
        head, _, payload = raw.partition(b"\r\n\r\n")
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        match = re.search(rb'name="([^"]+)"', head)
        if match:
            parts.append((match.group(1).decode("ascii"), payload))
    return parts


def _word(text: str, start: float, end: float) -> dict[str, Any]:
    return {"word": text, "start": start, "end": end}


def _segment(**overrides: Any) -> dict[str, Any]:
    seg: dict[str, Any] = {"start": 1.0, "end": 2.0, "text": "halo"}
    seg.update(overrides)
    return seg


class MultipartTest(unittest.TestCase):
    def test_repeated_key_emits_two_separate_parts(self) -> None:
        fields = [
            ("model", "whisper-large-v3-turbo"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        body, ctype = T._multipart(fields, {})
        parts = _multipart_parts(ctype, body)
        gran = [value for name, value in parts if name == "timestamp_granularities[]"]
        self.assertEqual(gran, [b"word", b"segment"])
        self.assertEqual(body.count(b'name="timestamp_granularities[]"'), 2)

    def test_dict_arguments_byte_identical_to_legacy(self) -> None:
        fields = {
            "model": "whisper-1",
            "response_format": "verbose_json",
            "temperature": "0",
            "language": "id",
        }
        files = {"file": ("chunk_000.mp3", b"ID3\x04\x00fake-audio", "audio/mpeg")}
        frozen = types.SimpleNamespace(hex="deadbeef" * 4)
        with patch.object(T.uuid, "uuid4", return_value=frozen):
            got = T._multipart(fields, files)
            old = _legacy_multipart(fields, files)
        self.assertEqual(got, old, msg="body multipart panggilan lama berubah byte")

    def test_pair_list_without_repeats_byte_identical_to_legacy(self) -> None:
        pairs = [("model", "whisper-1"), ("temperature", "0")]
        files = {"file": ("a.mp3", b"\x00\x01\x02binary", "audio/mpeg")}
        frozen = types.SimpleNamespace(hex="cafebabe" * 4)
        with patch.object(T.uuid, "uuid4", return_value=frozen):
            got = T._multipart(pairs, files)
            old = _legacy_multipart(dict(pairs), files)
        self.assertEqual(got, old, msg="daftar pasangan tanpa pengulangan harus identik")


class BadRangeThresholdTest(unittest.TestCase):
    """Ambang memakai konstanta kode apa adanya, bukan angka baru."""

    def test_no_speech_and_logprob_are_strict(self) -> None:
        at_nsp = _segment(
            no_speech_prob=T.NO_SPEECH_MAX,
            avg_logprob=T.AVG_LOGPROB_MIN - 0.5,
        )
        self.assertEqual(T._bad_ranges([at_nsp]), [])

        at_alp = _segment(
            no_speech_prob=T.NO_SPEECH_MAX + 0.01,
            avg_logprob=T.AVG_LOGPROB_MIN,
        )
        self.assertEqual(T._bad_ranges([at_alp]), [])

        over = _segment(
            no_speech_prob=T.NO_SPEECH_MAX + 0.01,
            avg_logprob=T.AVG_LOGPROB_MIN - 0.01,
        )
        self.assertEqual(T._bad_ranges([over]), [(1.0, 2.0)])

    def test_compression_ratio_is_strict(self) -> None:
        at_max = _segment(compression_ratio=T.COMPRESSION_MAX)
        self.assertEqual(T._bad_ranges([at_max]), [])
        over = _segment(compression_ratio=T.COMPRESSION_MAX + 0.01)
        self.assertEqual(T._bad_ranges([over]), [(1.0, 2.0)])

    def test_hallucination_phrase_dropped_regardless_of_stats(self) -> None:
        seg = _segment(
            text="Terima kasih telah menonton",
            no_speech_prob=0.0,
            avg_logprob=0.0,
            compression_ratio=1.0,
        )
        self.assertEqual(T._bad_ranges([seg]), [(1.0, 2.0)])
        self.assertEqual(T._bad_ranges([]), [])


class OpenAICompatibleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.audio = Path(self._tmp.name) / "chunk_000.mp3"
        self.audio.write_bytes(b"ID3fake")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _call(
        self, data: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], tuple[Any, ...]]:
        with patch.object(T, "_post", return_value=data) as post:
            words, segments = T._openai_compatible(
                self.audio, "kunci-tiruan", "http://tiruan", "model-tiruan", "id"
            )
        return words, segments, post.call_args.args

    def test_request_asks_word_and_segment_granularities(self) -> None:
        _, _, args = self._call({"words": [], "segments": []})
        _, body, ctype = args[:3]
        parts = _multipart_parts(ctype, body)
        gran = [value for name, value in parts if name == "timestamp_granularities[]"]
        self.assertEqual(gran, [b"word", b"segment"])
        fields = {name: value for name, value in parts if name != "file"}
        self.assertEqual(fields["response_format"], b"verbose_json")
        self.assertEqual(fields["model"], b"model-tiruan")

    def test_high_no_speech_segment_drops_only_words_inside_range(self) -> None:
        segments = [
            _segment(
                start=10.0,
                end=12.0,
                text="musik",
                no_speech_prob=0.95,
                avg_logprob=-1.5,
                compression_ratio=1.1,
            )
        ]
        words = [_word("dalam", 10.8, 11.2), _word("luar", 12.5, 12.9)]
        kept, returned_segments, _ = self._call({"words": words, "segments": segments})
        self.assertEqual([w["w"] for w in kept], ["luar"])
        self.assertEqual(returned_segments, segments)

    def test_healthy_segments_keep_every_word(self) -> None:
        segments = [
            _segment(
                start=0.0,
                end=20.0,
                text="halo dunia",
                no_speech_prob=0.10,
                avg_logprob=-0.25,
                compression_ratio=1.2,
            )
        ]
        words = [_word("halo", 0.4, 0.8), _word("dunia", 0.9, 1.4)]
        kept, _, _ = self._call({"words": words, "segments": segments})
        self.assertEqual([w["w"] for w in kept], ["halo", "dunia"])

    def test_empty_segments_keep_words_without_error(self) -> None:
        words = [_word("satu", 1.0, 1.4), _word("dua", 2.0, 2.4)]
        kept, segments, _ = self._call({"words": words, "segments": []})
        self.assertEqual([w["w"] for w in kept], ["satu", "dua"])
        self.assertEqual(segments, [])

    def test_missing_segments_keep_words_without_error(self) -> None:
        words = [_word("satu", 1.0, 1.4)]
        kept, segments, _ = self._call({"words": words})
        self.assertEqual([w["w"] for w in kept], ["satu"])
        self.assertEqual(segments, [])


class ChunkedSegmentsTest(unittest.TestCase):
    """Dua chunk tiruan: filter per chunk + offset absolut saat digabung."""

    def _run_chunked(
        self, responses: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[Any, ...]]]:
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            audio = wd / "audio16.wav"
            audio.write_bytes(b"RIFF-tiruan")
            (wd / "meta.json").write_text(
                json.dumps({"duration": 1195.0, "has_audio": True}), encoding="utf-8"
            )

            calls: list[tuple[Any, ...]] = []

            def fake_encode(src: Any, dst: Any, start: float, duration: float) -> Path:
                out = Path(dst)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"ID3")
                return out

            def fake_post(*args: Any, **kwargs: Any) -> dict[str, Any]:
                calls.append(args)
                return responses[len(calls) - 1]

            with patch.object(T, "encode_upload", side_effect=fake_encode):
                with patch.object(T, "_detect_silences", return_value=[]):
                    with patch.object(T, "_post", side_effect=fake_post):
                        with patch.dict(os.environ, {"GROQ_API_KEY": "kunci-tiruan"}):
                            words, segments = T._transcribe_chunked(
                                wd, str(audio), "groq", "id", 600.0, 5.0
                            )
            return words, segments, calls

    def test_bad_ranges_dropped_and_segments_made_absolute(self) -> None:
        responses = [
            {
                "words": [_word("alpha", 598.0, 598.4), _word("beta", 570.0, 570.4)],
                "segments": [
                    _segment(start=597.0, end=599.0, text="Terima kasih telah menonton"),
                    _segment(start=100.0, end=101.0, text="sehat", no_speech_prob=0.1),
                ],
            },
            {
                "words": [_word("gamma", 3.0, 3.4), _word("delta", 30.0, 30.4)],
                "segments": [
                    _segment(
                        start=2.0,
                        end=4.0,
                        text="musik",
                        no_speech_prob=0.95,
                        avg_logprob=-1.4,
                        compression_ratio=1.0,
                    ),
                    _segment(start=100.0, end=101.0, text="sehat", no_speech_prob=0.1),
                ],
            },
        ]
        words, segments, calls = self._run_chunked(responses)

        self.assertEqual(len(calls), 2)
        self.assertEqual([w["w"] for w in words], ["beta", "delta"])
        self.assertEqual([w["i"] for w in words], [0, 1])
        self.assertAlmostEqual(words[0]["start"], 570.0, places=3)
        self.assertAlmostEqual(words[1]["start"], 625.0, places=3)

        spans = [(seg["start"], seg["end"]) for seg in segments]
        self.assertEqual(
            spans,
            [(597.0, 599.0), (100.0, 101.0), (597.0, 599.0), (695.0, 696.0)],
            msg=f"segmen tidak dipetakan absolut: {spans}",
        )
        self.assertTrue(all(seg.get("text") for seg in segments))

        for _url, body, ctype, _headers in calls:
            gran = [
                value
                for name, value in _multipart_parts(ctype, body)
                if name == "timestamp_granularities[]"
            ]
            self.assertEqual(gran, [b"word", b"segment"])

    def test_empty_segments_keep_all_words_across_chunks(self) -> None:
        responses = [
            {"words": [_word("kiri", 10.0, 10.4)], "segments": []},
            {"words": [_word("kanan", 10.0, 10.4)], "segments": []},
        ]
        words, segments, _ = self._run_chunked(responses)
        self.assertEqual([w["w"] for w in words], ["kiri", "kanan"])
        self.assertEqual(segments, [])


class SchemaToleranceTest(unittest.TestCase):
    def test_groq_extra_segment_keys_are_schema_valid(self) -> None:
        """Segmen Groq membawa kunci diagnostik; skema harus tetap menerimanya."""
        schema = _load_transcript_schema()
        doc = {
            "version": "0.1.0",
            "language": "id",
            "duration": 10.0,
            "words": [
                {"i": 0, "w": "halo", "start": 0.0, "end": 0.4,
                 "speaker": None, "conf": None}
            ],
            "segments": [
                {
                    "id": 0,
                    "seek": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "halo",
                    "tokens": [1, 2],
                    "temperature": 0.0,
                    "avg_logprob": -0.2,
                    "compression_ratio": 1.0,
                    "no_speech_prob": 0.1,
                }
            ],
        }
        self.assertEqual(undeclared_keys(schema, doc), [])
        self.assertEqual(missing_required(schema, doc), [])


class RunSchemaTest(unittest.TestCase):
    def test_run_writes_filled_segments_valid_against_schema(self) -> None:
        schema = _load_transcript_schema()
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            audio = wd / "audio16.wav"
            audio.write_bytes(b"RIFF-tiruan")
            (wd / "meta.json").write_text(
                json.dumps(
                    {
                        "version": "0.1.0",
                        "source": "synthetic://uji",
                        "duration": 10.0,
                        "has_audio": True,
                        "audio16": str(audio),
                    }
                ),
                encoding="utf-8",
            )
            words = [
                {"i": 0, "w": "halo", "start": 0.0, "end": 0.4,
                 "speaker": None, "conf": None}
            ]
            segments = [{"start": 0.0, "end": 1.0, "text": "halo"}]

            with patch.object(T, "_transcribe_chunked", return_value=(words, segments)):
                with patch.dict(os.environ, {"GROQ_API_KEY": "kunci-tiruan"}):
                    out = T.run(wd, engine="groq", language="id")

            on_disk = json.loads((wd / "transcript.json").read_text(encoding="utf-8"))

        self.assertEqual(out["segments"], segments)
        self.assertEqual(on_disk, out)
        self.assertEqual(undeclared_keys(schema, out), [])
        self.assertEqual(missing_required(schema, out), [])


if __name__ == "__main__":
    unittest.main()
