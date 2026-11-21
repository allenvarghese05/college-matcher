"""TTFA math, client-clock mapping, Deepgram utterance assembly, TTS byte framing."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.voice.metrics import (
    TurnTiming,
    map_client_time,
    persisted_rows,
    ttfa_breakdown,
    voice_turn_record,
)
from app.voice.stt import STTEvent, UtteranceAssembler, deepgram_listen_url
from app.voice.tts import FakeTTS, TTSError, _even_chunks, _strip_wav_header


def test_accept_t0_window() -> None:
    from app.voice.metrics import accept_t0

    assert accept_t0(9.5, 10.0)
    assert accept_t0(7.0, 10.0)  # exactly 3 s old
    assert not accept_t0(6.9, 10.0)  # stale: cough / missed turn
    assert not accept_t0(10.1, 10.0)  # after the final: belongs to a later utterance


def test_assembler_utterance_end_appends_interim_tail() -> None:
    a = UtteranceAssembler()
    a.feed(_results("I live in Ohio", is_final=True))
    a.feed(_results("and like math", is_final=False))
    assert a.feed({"type": "UtteranceEnd"}) == [STTEvent("final", "I live in Ohio and like math")]


async def _collect(chunks: list[bytes]) -> bytes:
    async def src() -> AsyncIterator[bytes]:
        for c in chunks:
            yield c

    return b"".join([c async for c in _strip_wav_header(src())])


async def test_strip_wav_header_only_when_riff() -> None:
    header = b"RIFF" + b"\x00" * 40
    assert (
        await _collect([header[:10], header[10:] + b"\x01\x02", b"\x03\x04"]) == b"\x01\x02\x03\x04"
    )
    assert await _collect([b"\x05\x06", b"\x07\x08"]) == b"\x05\x06\x07\x08"
    assert await _collect([b"\x01"]) == b"\x01"  # short body, no header


def test_map_client_time_subtracts_report_delay() -> None:
    # VAD saw silence start 600 ms before the message was sent; received at server t=10 s
    assert map_client_time(10.0, t_ms=4000.0, sent_ms=4600.0) == pytest.approx(9.4)
    # a clock that reports "sent before event" is clamped, never moves t0 forward
    assert map_client_time(10.0, t_ms=5000.0, sent_ms=4000.0) == 10.0


def test_breakdown_stages_sum_to_total() -> None:
    t = TurnTiming(turn=1, t0=100.0, t1=100.35, t2=100.95, t3=101.30, t4=101.52, t5=101.60)
    b = ttfa_breakdown(t)
    assert b == {
        "stt_final": 350.0,
        "llm_ttft": 600.0,
        "first_sentence": 350.0,
        "tts_first_chunk": 220.0,
        "playback": 80.0,
        "ttfa_total": 1600.0,
    }
    parts = [b[k] for k in ("stt_final", "llm_ttft", "first_sentence", "tts_first_chunk")]
    assert sum(p for p in parts if p is not None) + (b["playback"] or 0) == b["ttfa_total"]


def test_total_prefers_exact_client_clock() -> None:
    t = TurnTiming(turn=1, t0=100.0, t5=101.6, t0_client_ms=5000.0, t5_client_ms=6612.5)
    assert ttfa_breakdown(t)["ttfa_total"] == 1612.5


def test_missing_marks_are_none_and_not_persisted() -> None:
    t = TurnTiming(turn=2, t1=1.0, t2=1.5, t3=1.7, t4=1.9)  # no client marks
    b = ttfa_breakdown(t)
    assert b["stt_final"] is None and b["ttfa_total"] is None and b["playback"] is None
    assert persisted_rows(t) == [
        {"stage": "llm_ttft", "ms": 500.0},
        {"stage": "tts_first_chunk", "ms": 200.0},
    ]
    rec = voice_turn_record(t)
    assert rec["t0_source"] == "missing" and rec["t5_source"] == "missing"
    assert rec["llm_ttft_ms"] == 500.0


def test_full_turn_persists_four_stages() -> None:
    t = TurnTiming(turn=1, t0=0.0, t1=0.2, t2=0.6, t3=0.8, t4=0.9, t5=1.0)
    assert [r["stage"] for r in persisted_rows(t)] == [
        "stt_final", "llm_ttft", "tts_first_chunk", "ttfa_total",
    ]  # fmt: skip


# --------------------------------------------------------------- Deepgram assembly


def _results(text: str, *, is_final: bool, speech_final: bool = False, **extra: bool) -> dict:  # type: ignore[type-arg]
    return {
        "type": "Results",
        "is_final": is_final,
        "speech_final": speech_final,
        "channel": {"alternatives": [{"transcript": text, "confidence": 0.9}]},
        **extra,
    }


def test_assembler_concatenates_final_segments_until_speech_final() -> None:
    a = UtteranceAssembler()
    assert a.feed(_results("I love", is_final=False)) == [STTEvent("interim", "I love")]
    assert a.feed(_results("I love coding", is_final=True)) == [
        STTEvent("interim", "I love coding")
    ]
    assert a.feed(_results("and games", is_final=False)) == [
        STTEvent("interim", "I love coding and games")
    ]
    out = a.feed(_results("and games.", is_final=True, speech_final=True))
    assert out == [STTEvent("final", "I love coding and games.")]
    # the UtteranceEnd that follows a speech_final is ignored
    assert a.feed({"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": 2.1}) == []


def test_assembler_utterance_end_without_speech_final() -> None:
    a = UtteranceAssembler()
    a.feed(_results("I live in Ohio", is_final=True))
    out = a.feed({"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": 1.4})
    assert out == [STTEvent("final", "I live in Ohio")]
    # interim-only utterance is also completed by UtteranceEnd
    a.feed(_results("maybe nursing", is_final=False))
    assert a.feed({"type": "UtteranceEnd"}) == [STTEvent("final", "maybe nursing")]


def test_assembler_finalize_response_completes() -> None:
    a = UtteranceAssembler()
    a.feed(_results("so yeah", is_final=False))
    out = a.feed(_results("so yeah", is_final=True, from_finalize=True))
    assert out == [STTEvent("final", "so yeah")]


def test_assembler_ignores_metadata_and_empty() -> None:
    a = UtteranceAssembler()
    assert a.feed({"type": "Metadata", "request_id": "x"}) == []
    assert a.feed(_results("", is_final=True, speech_final=True)) == []
    assert a.feed({"type": "SpeechStarted", "channel": [0], "timestamp": 0.5}) == [
        STTEvent("speech_started")
    ]


def test_listen_url_params() -> None:
    url = deepgram_listen_url(
        model="nova-3", language="en-US", sample_rate=16000, endpointing_ms=300,
        utterance_end_ms=1000,
    )  # fmt: skip
    assert url.startswith("wss://api.deepgram.com/v1/listen?")
    for p in (
        "model=nova-3", "encoding=linear16", "sample_rate=16000", "channels=1",
        "interim_results=true", "endpointing=300", "utterance_end_ms=1000", "vad_events=true",
    ):  # fmt: skip
        assert p in url


# ------------------------------------------------------------------------ TTS


async def test_even_chunks_never_split_samples() -> None:
    async def src() -> AsyncIterator[bytes]:
        for c in (b"\x01", b"\x02\x03", b"\x04\x05\x06", b"\x07"):
            yield c

    out = [c async for c in _even_chunks(src())]
    assert all(len(c) % 2 == 0 for c in out)
    assert b"".join(out) == b"\x01\x02\x03\x04\x05\x06"  # trailing odd byte dropped


async def test_fake_tts_chunks_and_failure() -> None:
    tts = FakeTTS(sample_rate=16000, chunks_per_sentence=3, chunk_ms=20, fail_on={1})
    chunks = [c async for c in tts.synthesize("Hello.")]
    assert len(chunks) == 3 and all(len(c) == 16000 * 20 // 1000 * 2 for c in chunks)
    with pytest.raises(TTSError):
        _ = [c async for c in tts.synthesize("World.")]
    assert tts.requests == ["Hello.", "World."]
