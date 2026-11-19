"""Voice gateway end-to-end over a real WebSocket (Starlette TestClient):
FakeSTT + FakeTTS + ScriptedAnthropic (no network), real Postgres.

The app runs in the TestClient's own event loop, so the orchestrator gets a NullPool
sessionmaker (no pooled asyncpg connection is ever shared across loops).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.sessions import get_orchestrator
from app.api.voice import VoiceConfig, get_voice_config
from app.core.config import get_settings
from app.core.llm import LLMClient
from app.counselor.orchestrator import CounselorOrchestrator
from app.db.models import ChatSession, Turn, TurnMetricRow
from app.main import create_app
from app.schemas import ExtractionResult, ProfileDelta, Update
from app.voice.stt import FakeSTT
from app.voice.tts import FakeTTS
from tests.counselor_fixtures import ScriptedAnthropic, ScriptedParse, ScriptedStream, to_wire

pytestmark = pytest.mark.usefixtures("loaded_db")

UTTERANCE = "I love coding and building games"
REPLY = ["That's awesome! ", "Building games is a great ", "way to learn. ", "Where do you live?"]
FRAME = b"\x00\x00" * 320  # 20 ms of 16 kHz PCM16 silence


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _new_session(sm: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with sm() as db:
        row = ChatSession(mode="voice")
        db.add(row)
        await db.commit()
        return row.id


def _extraction(quote: str = "I love coding") -> ScriptedParse:
    result = ExtractionResult(
        delta=ProfileDelta(interests=Update(value=["coding"], confidence=0.9, quote=quote)),
        next_topic="location",  # type: ignore[arg-type]
    )
    return ScriptedParse(output=to_wire(result))


@dataclass
class Harness:
    client: TestClient
    fake: ScriptedAnthropic
    stt: FakeSTT
    tts: FakeTTS


def _harness(
    sm: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    stt: FakeSTT | None = None,
    tts: FakeTTS | None = None,
    barge_in: bool = False,
    config: bool = True,
) -> Harness:
    fake = ScriptedAnthropic()
    llm = LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)
    orch = CounselorOrchestrator(llm=llm, sessionmaker=sm)
    stt = stt or FakeSTT(utterances=[UTTERANCE])
    tts = tts or FakeTTS(sample_rate=24000)
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orch
    cfg = VoiceConfig(stt=stt, tts=tts, provider="fake", barge_in=barge_in) if config else None
    app.dependency_overrides[get_voice_config] = lambda: cfg
    return Harness(TestClient(app), fake, stt, tts)


Frame = tuple[str, Any]  # ("json", dict) | ("bytes", bytes)


def _recv(ws: Any) -> Frame:
    msg = ws.receive()
    if msg["type"] == "websocket.close":
        raise WebSocketDisconnect(msg.get("code", 1000))
    if msg.get("bytes") is not None:
        return ("bytes", msg["bytes"])
    import json

    return ("json", json.loads(msg["text"]))


def _until(ws: Any, pred: Callable[[dict[str, Any]], bool], limit: int = 500) -> list[Frame]:
    frames: list[Frame] = []
    for _ in range(limit):
        f = _recv(ws)
        frames.append(f)
        if f[0] == "json" and pred(f[1]):
            return frames
    raise AssertionError(f"predicate never matched; got {[x[1] for x in frames if x[0] == 'json']}")


def _is(kind: str, **kw: Any) -> Callable[[dict[str, Any]], bool]:
    return lambda d: d.get("type") == kind and all(d.get(k) == v for k, v in kw.items())


def _types(frames: list[Frame]) -> list[str]:
    return [f[1]["type"] if f[0] == "json" else "<pcm>" for f in frames]


def _speak(ws: Any, frames: int = 3, t_ms: float = 1000.0) -> None:
    for _ in range(frames):
        ws.send_bytes(FRAME)
    ws.send_json({"type": "speech_end", "t_ms": t_ms, "sent_ms": t_ms})


async def _turns(sm: async_sessionmaker[AsyncSession], sid: uuid.UUID) -> list[Turn]:
    async with sm() as db:
        rows = await db.execute(select(Turn).where(Turn.session_id == sid).order_by(Turn.idx))
        return list(rows.scalars().all())


async def _stages(sm: async_sessionmaker[AsyncSession], sid: uuid.UUID) -> list[TurnMetricRow]:
    async with sm() as db:
        rows = await db.execute(select(TurnMetricRow).where(TurnMetricRow.session_id == sid))
        return list(rows.scalars().all())


# ------------------------------------------------------------------------ tests


async def test_happy_path_state_machine_audio_and_ttfa(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path)
    h.fake.add_stream(ScriptedStream(chunks=REPLY, delay_s=0.2))
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)

    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        hello = _recv(ws)[1]
        assert hello == {
            "type": "hello", "barge_in": False, "input_sample_rate": 16000,
            "output_sample_rate": 24000, "provider": "fake",
        }  # fmt: skip
        assert _recv(ws)[1] == {"type": "state", "state": "listening"}

        _speak(ws)
        frames = _until(ws, _is("state", state="listening"))
        types = _types(frames)

        interims = [
            f[1]["text"] for f in frames if f[0] == "json" and f[1]["type"] == "transcript_interim"
        ]
        assert interims == ["I", "I love", "I love coding"]
        final = next(f[1] for f in frames if f[0] == "json" and f[1]["type"] == "transcript_final")
        assert final == {"type": "transcript_final", "text": UTTERANCE, "turn": 1}

        # state machine: listening -> thinking -> speaking -> listening
        states = [f[1]["state"] for f in frames if f[0] == "json" and f[1]["type"] == "state"]
        assert states == ["thinking", "speaking", "listening"]

        # assistant text streams; sentences are spoken in order with audio between markers
        deltas = "".join(
            f[1]["delta"] for f in frames if f[0] == "json" and f[1]["type"] == "assistant_text"
        )
        assert deltas == "".join(REPLY)
        starts = [f[1] for f in frames if f[0] == "json" and f[1]["type"] == "audio_start"]
        assert [(s["sentence"], s["text"]) for s in starts] == [
            (0, "That's awesome!"),
            (1, "Building games is a great way to learn."),
            (2, "Where do you live?"),
        ]
        assert all(s["sample_rate"] == 24000 and s["turn"] == 1 for s in starts)
        i0 = types.index("audio_start")
        assert types[i0 + 1 : i0 + 3] == ["state", "<pcm>"] or types[i0 + 1] == "<pcm>"
        assert types.count("<pcm>") == 3 * h.tts.chunks_per_sentence
        assert types.count("audio_end") == 3
        assert h.tts.requests == [s["text"] for s in starts]

        tail = [t for t in types if t not in ("<pcm>", "audio_start", "audio_end", "state")]
        assert tail[-3:] == ["profile", "ready", "done"]
        done = next(f[1] for f in frames if f[0] == "json" and f[1]["type"] == "done")
        assert done["audio"] is True and done["assistant_text"] == "".join(REPLY)
        assert done["turn"] == 1 and done["turn_id"]

        # client reports first audio played 500 ms after end of speech (client clock)
        ws.send_json({"type": "playback_start", "turn": 1, "t_ms": 1500.0, "sent_ms": 1500.0})
        metrics = _until(ws, _is("metrics"))[-1][1]
        assert metrics["ttfa_total_ms"] == 500.0
        assert metrics["turn_id"] == done["turn_id"]
        for k in (
            "stt_final_ms",
            "llm_ttft_ms",
            "first_sentence_ms",
            "tts_first_chunk_ms",
            "playback_ms",
        ):
            assert metrics[k] is not None and metrics[k] >= 0, k
        assert metrics["llm_ttft_ms"] >= 40  # first scripted chunk arrives after ~50 ms
        ws.send_json({"type": "stop"})

    turns = await _turns(sm, sid)
    assert [(t.role, t.source, t.interrupted) for t in turns] == [
        ("user", "voice", False), ("assistant", "voice", False),
    ]  # fmt: skip
    assert turns[0].text == UTTERANCE and turns[1].text == "".join(REPLY)
    voice_stages = {m.stage: m for m in await _stages(sm, sid)}
    for name in ("stt_final", "llm_ttft", "tts_first_chunk", "ttfa_total"):
        assert name in voice_stages, name
    assert voice_stages["ttfa_total"].ms == 500.0
    assert str(voice_stages["ttfa_total"].turn_id) == done["turn_id"]
    assert "reply_total" in voice_stages and "extract" in voice_stages  # orchestrator rows


async def test_tts_failure_falls_back_to_text(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path, tts=FakeTTS(fail_on={0}))
    h.fake.add_stream(ScriptedStream(chunks=REPLY))
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)

    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        _until(ws, _is("state", state="listening"))
        _speak(ws)
        frames = _until(ws, _is("metrics"))
        types = _types(frames)
        assert "<pcm>" not in types and "audio_start" not in types
        err = next(f[1] for f in frames if f[0] == "json" and f[1]["type"] == "error")
        assert err["code"] == "tts_failed" and err["fatal"] is False
        done = next(f[1] for f in frames if f[0] == "json" and f[1]["type"] == "done")
        assert done["audio"] is False and done["assistant_text"] == "".join(REPLY)
        assert frames[-1][1]["ttfa_total_ms"] is None and frames[-1][1]["audio"] is False
        assert h.tts.requests == ["That's awesome!"]  # no more attempts this turn

        # next turn tries TTS again (fail_on only covers request #0)
        h.fake.add_stream(ScriptedStream(chunks=["Got it. ", "Thanks!"]))
        h.fake.add_parse("ExtractionWire", _extraction())
        _speak(ws)
        frames = _until(ws, _is("done"))
        assert "<pcm>" in _types(frames)
        assert frames[-1][1]["audio"] is True
        ws.send_json({"type": "stop"})

    turns = await _turns(sm, sid)
    assert turns[1].text == "".join(REPLY) and not turns[1].interrupted


async def test_stt_disconnect_reconnects_once(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    stt = FakeSTT(utterances=[UTTERANCE], fail_after_frames=2)
    h = _harness(sm, tmp_path, stt=stt)
    h.fake.add_stream(ScriptedStream(chunks=["Nice. "]))
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)

    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        _until(ws, _is("state", state="listening"))
        ws.send_bytes(FRAME)
        ws.send_bytes(FRAME)  # first stream dies here; gateway reconnects silently
        _until(ws, _is("transcript_interim", text="I"))
        import time

        deadline = time.monotonic() + 2
        while stt.connections < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert stt.connections == 2
        _speak(ws)
        frames = _until(ws, _is("done"))
        assert any(f[1].get("type") == "transcript_final" for f in frames if f[0] == "json")
        assert not any(f[1].get("type") == "error" for f in frames if f[0] == "json")
        ws.send_json({"type": "stop"})


async def test_stt_disconnect_fatal_when_reconnect_fails(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    stt = FakeSTT(utterances=[UTTERANCE], fail_after_frames=1, fail_connect_after=1)
    h = _harness(sm, tmp_path, stt=stt)
    sid = await _new_session(sm)

    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        _until(ws, _is("state", state="listening"))
        ws.send_bytes(FRAME)
        err = _until(ws, _is("error"))[-1][1]
        assert err["code"] == "stt_disconnected" and err["fatal"] is True
        with pytest.raises(WebSocketDisconnect):
            _recv(ws)


async def test_stt_connect_failure_is_fatal(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path, stt=FakeSTT(utterances=[UTTERANCE], fail_connect_after=0))
    sid = await _new_session(sm)
    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        assert _recv(ws)[1]["type"] == "hello"
        err = _recv(ws)[1]
        assert err["code"] == "stt_unavailable" and err["fatal"] is True
        with pytest.raises(WebSocketDisconnect):
            _recv(ws)


async def test_llm_failure_reports_error_and_returns_to_listening(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path)
    h.fake.add_stream(RuntimeError("upstream exploded"))
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)
    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        _until(ws, _is("state", state="listening"))
        _speak(ws)
        frames = _until(ws, _is("state", state="listening"))
        err = next(f[1] for f in frames if f[0] == "json" and f[1]["type"] == "error")
        assert err["code"] in {"llm_failed", "turn_failed"} and err["fatal"] is False
        assert "done" not in _types(frames)
        ws.send_json({"type": "stop"})


async def test_voice_unavailable_without_config(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path, config=False)
    sid = await _new_session(sm)
    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        err = _recv(ws)[1]
        assert err == {
            "type": "error", "code": "voice_unavailable",
            "message": "Voice isn't connected yet.", "fatal": True,
        }  # fmt: skip
        with pytest.raises(WebSocketDisconnect) as exc:
            _recv(ws)
        assert exc.value.code == 4503


async def test_unknown_session_closes_4404(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path)
    with h.client.websocket_connect(f"/api/sessions/{uuid.uuid4()}/voice") as ws:
        assert _recv(ws)[1]["code"] == "session_not_found"
        with pytest.raises(WebSocketDisconnect) as exc:
            _recv(ws)
        assert exc.value.code == 4404


# -------------------------------------------------------------------- barge-in

SLOW_REPLY = [
    "That's awesome! ",
    "Games teach ",
    "a lot. ",
    "What else ",
    "do you like? ",
    "Tell me.",
]


async def test_barge_in_cancels_and_truncates_to_played_sentences(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path, barge_in=True)
    h.fake.add_stream(ScriptedStream(chunks=SLOW_REPLY, delay_s=3.0))  # 0.5 s per chunk
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)

    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        assert _recv(ws)[1]["barge_in"] is True
        _until(ws, _is("state", state="listening"))
        _speak(ws)
        _until(ws, _is("audio_end", sentence=0))
        # student starts talking over the counselor after sentence 0 finished playing
        ws.send_json({"type": "interrupt", "turn": 1, "last_played": 0, "sent_ms": 0})
        frames = _until(ws, _is("state", state="listening"))
        intr = next(f[1] for f in frames if f[0] == "json" and f[1]["type"] == "interrupted")
        assert intr["played_through"] == 0
        assert intr["assistant_text"] == "That's awesome!"
        assert intr["turn_id"]
        assert "done" not in _types(frames)
        metrics = _until(ws, _is("metrics"))[-1][1]
        assert metrics["interrupted"] is True

        # the conversation continues; history carries only what was heard
        h.fake.add_stream(ScriptedStream(chunks=["Okay! ", "Where do you live?"]))
        h.fake.add_parse("ExtractionWire", _extraction())
        _speak(ws, t_ms=9000.0)
        done = _until(ws, _is("done"))[-1][1]
        assert done["turn"] == 2 and done["audio"] is True
        ws.send_json({"type": "stop"})

    turns = await _turns(sm, sid)
    assert [(t.role, t.interrupted) for t in turns] == [
        ("user", False), ("assistant", True), ("user", False), ("assistant", False),
    ]  # fmt: skip
    assert turns[1].text == "That's awesome!"
    assert str(turns[1].id) == intr["turn_id"]
    # the second reply request saw the truncated assistant turn in its history
    reply_calls = [
        kw for kind, kw in h.fake.calls if kind == "stream" and "format" not in kw["output_config"]
    ]
    second = reply_calls[1]["messages"]
    assert {"role": "assistant", "content": "That's awesome!"} in second


async def test_barge_in_after_llm_finished_still_truncates(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path, barge_in=True)
    h.fake.add_stream(ScriptedStream(chunks=REPLY))
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)
    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        _until(ws, _is("state", state="listening"))
        _speak(ws)
        done = _until(ws, _is("done"))[-1][1]
        _until(ws, _is("state", state="listening"))
        # all audio was sent faster than real time; the client had played nothing yet
        ws.send_json({"type": "interrupt", "turn": 1, "last_played": -1})
        intr = _until(ws, _is("interrupted"))[-1][1]
        assert intr["assistant_text"] == "…" and intr["turn_id"] == done["turn_id"]
        ws.send_json({"type": "stop"})
    turns = await _turns(sm, sid)
    assert turns[1].text == "…" and turns[1].interrupted is True


async def test_interrupt_ignored_without_flag(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path, barge_in=False)
    h.fake.add_stream(ScriptedStream(chunks=SLOW_REPLY, delay_s=0.6))
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)
    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        _until(ws, _is("state", state="listening"))
        _speak(ws)
        _until(ws, _is("audio_end", sentence=0))
        ws.send_json({"type": "interrupt", "turn": 1, "last_played": 0})
        frames = _until(ws, _is("done"))
        assert "interrupted" not in _types(frames)
        assert frames[-1][1]["assistant_text"] == "".join(SLOW_REPLY)
        ws.send_json({"type": "stop"})
    turns = await _turns(sm, sid)
    assert turns[1].text == "".join(SLOW_REPLY) and not turns[1].interrupted


async def test_client_disconnect_mid_turn_persists_partial(
    sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    h = _harness(sm, tmp_path)
    h.fake.add_stream(ScriptedStream(chunks=SLOW_REPLY, delay_s=3.0))
    h.fake.add_parse("ExtractionWire", _extraction())
    sid = await _new_session(sm)
    with h.client.websocket_connect(f"/api/sessions/{sid}/voice") as ws:
        _until(ws, _is("state", state="listening"))
        _speak(ws)
        _until(ws, _is("audio_end", sentence=0))
    # leaving the context closes the socket; the server cancels the turn and persists
    import time

    deadline = time.monotonic() + 3
    turns: list[Turn] = []
    while time.monotonic() < deadline:
        turns = await _turns(sm, sid)
        if len(turns) == 2:
            break
        time.sleep(0.05)
    assert [(t.role, t.interrupted) for t in turns] == [("user", False), ("assistant", True)]
    assert turns[1].text.startswith("That's awesome!")
