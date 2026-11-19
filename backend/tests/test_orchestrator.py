from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.llm import LLMClient
from app.counselor.context import HistoryTurn
from app.counselor.orchestrator import (
    REFUSAL_FALLBACK,
    CounselorOrchestrator,
    SessionNotFound,
    TurnEvent,
    build_reply_messages,
)
from app.db.models import ChatSession, ProfileSnapshot, Turn, TurnMetricRow
from app.db.session import get_sessionmaker
from app.schemas import ExtractionResult, ProfileDelta, StudentProfile, Update
from tests.counselor_fixtures import ScriptedAnthropic, ScriptedParse, ScriptedStream

pytestmark = pytest.mark.usefixtures("requires_db")


async def _new_session() -> uuid.UUID:
    async with get_sessionmaker()() as db:
        row = ChatSession(mode="text")
        db.add(row)
        await db.commit()
        return row.id


def _orch(fake: ScriptedAnthropic, tmp_path: Path) -> CounselorOrchestrator:
    llm = LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)
    return CounselorOrchestrator(llm=llm, sessionmaker=get_sessionmaker())


async def _collect(orch: CounselorOrchestrator, sid: uuid.UUID, text: str) -> list[TurnEvent]:
    return [ev async for ev in orch.handle_turn(sid, text)]


def _extraction(**updates: Update) -> ScriptedParse:  # type: ignore[type-arg]
    return ScriptedParse(
        output=ExtractionResult(delta=ProfileDelta(**updates), next_topic="money")  # type: ignore[arg-type]
    )


async def test_reply_and_extraction_run_concurrently(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["Hi ", "there, ", "where do you live?"], delay_s=0.4))
    p = _extraction(interests=Update(value=["coding"], confidence=0.9, quote="I love coding"))
    p.delay_s = 0.4
    fake.add_parse("ExtractionResult", p)
    sid = await _new_session()

    t0 = time.perf_counter()
    events = await _collect(_orch(fake, tmp_path), sid, "I love coding")
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.7, f"reply and extraction ran sequentially ({elapsed:.2f}s)"
    marks = dict(fake.timeline)
    assert marks["parse_start:ExtractionResult"] < marks["stream_end"]
    assert marks["stream_start"] < marks["parse_end:ExtractionResult"]
    assert [e.event for e in events][-3:] == ["profile", "ready", "done"]


async def test_event_order_persistence_and_metrics(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["That's ", "awesome! ", "Where do you live?"]))
    fake.add_parse(
        "ExtractionResult",
        _extraction(interests=Update(value=["coding"], confidence=0.9, quote="I love coding")),
    )
    sid = await _new_session()
    events = await _collect(_orch(fake, tmp_path), sid, "I love coding")

    names = [e.event for e in events]
    assert names == ["token", "token", "token", "profile", "ready", "done"]
    assert "".join(e.data["text"] for e in events if e.event == "token") == (
        "That's awesome! Where do you live?"
    )
    profile = StudentProfile.model_validate(events[3].data["profile"])
    assert profile.interests.value == ["coding"]
    assert profile.interests.evidence[0].quote == "I love coding"
    assert profile.interests.evidence[0].turn_idx == 0
    assert events[4].data == {"ready": False, "missing": ["home_state", "income_bracket"]}
    done = events[5].data
    assert done["assistant_text"] == "That's awesome! Where do you live?"

    async with get_sessionmaker()() as db:
        turns = (
            (await db.execute(select(Turn).where(Turn.session_id == sid).order_by(Turn.idx)))
            .scalars()
            .all()
        )
        assert [(t.idx, t.role) for t in turns] == [(0, "user"), (1, "assistant")]
        assert str(turns[1].id) == done["turn_id"]
        snaps = (
            (await db.execute(select(ProfileSnapshot).where(ProfileSnapshot.session_id == sid)))
            .scalars()
            .all()
        )
        assert len(snaps) == 1 and snaps[0].after_turn == 0
        metrics = {
            m.stage: m
            for m in (
                await db.execute(select(TurnMetricRow).where(TurnMetricRow.session_id == sid))
            )
            .scalars()
            .all()
        }
    assert set(metrics) == {"extract", "reply_total", "reply_ttft"}
    assert all(m.turn_id == turns[0].id for m in metrics.values())
    assert metrics["extract"].model == "claude-sonnet-5-5"
    assert metrics["extract"].input_tokens == 1200 and metrics["extract"].cost_usd > 0
    assert metrics["reply_total"].output_tokens == 60
    assert metrics["reply_total"].cache_read_tokens == 1500
    assert 0 <= metrics["reply_ttft"].ms <= metrics["reply_total"].ms


async def test_profile_merges_across_turns_and_corrections_win(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    for _ in range(2):
        fake.add_stream(ScriptedStream(chunks=["Got it."]))
    fake.add_parse(
        "ExtractionResult",
        _extraction(home_state=Update(value="OH", confidence=0.95, quote="I live in Ohio")),
    )
    fake.add_parse(
        "ExtractionResult",
        _extraction(
            home_state=Update(value="MI", confidence=0.85, quote="actually I live in Michigan"),
            interests=Update(value=["robotics"], confidence=0.8, quote="I build robots"),
        ),
    )
    orch = _orch(fake, tmp_path)
    sid = await _new_session()
    await _collect(orch, sid, "I live in Ohio")
    events = await _collect(orch, sid, "Sorry, actually I live in Michigan. I build robots.")
    profile = StudentProfile.model_validate(
        next(e for e in events if e.event == "profile").data["profile"]
    )
    assert profile.home_state.value == "MI"
    assert [ev.turn_idx for ev in profile.home_state.evidence] == [0, 2]
    assert profile.interests.value == ["robotics"]

    # second reply prompt saw history + previous profile, ended with the system note
    _, kw = [c for c in fake.calls if c[0] == "stream"][1]
    msgs = kw["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "system"]
    assert msgs[0]["content"] == "I live in Ohio" and msgs[1]["content"] == "Got it."
    assert '"home_state": {"confidence": 0.95, "value": "OH"}' in msgs[-1]["content"]
    assert "Suggested next topic:" in msgs[-1]["content"]
    assert kw["model"] == "claude-sonnet-5-5" and kw["output_config"] == {"effort": "low"}


async def test_extraction_failure_keeps_reply_and_profile(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["Tell me more!"]))
    fake.add_parse("ExtractionResult", ScriptedParse(output="", stop_reason="refusal"))
    sid = await _new_session()
    events = await _collect(_orch(fake, tmp_path), sid, "hello")
    assert [e.event for e in events] == ["token", "profile", "ready", "done"]
    assert events[1].data["profile"] == StudentProfile().model_dump(mode="json")
    async with get_sessionmaker()() as db:
        snaps = (
            await db.execute(select(ProfileSnapshot).where(ProfileSnapshot.session_id == sid))
        ).all()
        assert snaps == []


async def test_reply_refusal_uses_safe_fallback(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=[], stop_reason="refusal"))
    fake.add_parse("ExtractionResult", _extraction())
    sid = await _new_session()
    events = await _collect(_orch(fake, tmp_path), sid, "something off topic")
    assert events[0] == TurnEvent("token", {"text": REFUSAL_FALLBACK})
    assert events[-1].event == "done"


async def test_reply_failure_emits_error_and_no_assistant_turn(tmp_path: Path) -> None:
    llm = LLMClient(mode="replay", cassette_dir=tmp_path)  # empty dir -> replay miss
    orch = CounselorOrchestrator(llm=llm, sessionmaker=get_sessionmaker())
    sid = await _new_session()
    events = [ev async for ev in orch.handle_turn(sid, "hello")]
    assert [e.event for e in events] == ["error"]
    async with get_sessionmaker()() as db:
        roles = (await db.execute(select(Turn.role).where(Turn.session_id == sid))).scalars().all()
    assert roles == ["user"]


async def test_unknown_session_raises(tmp_path: Path) -> None:
    orch = _orch(ScriptedAnthropic(), tmp_path)
    with pytest.raises(SessionNotFound):
        await _collect(orch, uuid.uuid4(), "hi")


def test_reply_messages_window_starts_with_user_and_ends_with_note() -> None:
    history = [
        HistoryTurn(3, "assistant", "orphan reply"),
        HistoryTurn(4, "user", "q"),
        HistoryTurn(5, "assistant", "a"),
    ]
    msgs = build_reply_messages(history, "new", StudentProfile())
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "system"]
    assert (
        "Still needed before recommendations: home_state, income_bracket, interests"
        in (msgs[-1]["content"])
    )
