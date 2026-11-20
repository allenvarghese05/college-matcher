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
from tests.counselor_fixtures import ScriptedAnthropic, ScriptedParse, ScriptedStream, to_wire

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


def _reply_calls(fake: ScriptedAnthropic) -> list[dict]:  # type: ignore[type-arg]
    """Text-reply requests (streams without a structured-output format)."""
    return [
        kw for kind, kw in fake.calls if kind == "stream" and "format" not in kw["output_config"]
    ]


async def _collect(orch: CounselorOrchestrator, sid: uuid.UUID, text: str) -> list[TurnEvent]:
    return [ev async for ev in orch.handle_turn(sid, text)]


def _extraction(next_topic: str = "money", **updates: Update) -> ScriptedParse:  # type: ignore[type-arg]
    result = ExtractionResult(delta=ProfileDelta(**updates), next_topic=next_topic)  # type: ignore[arg-type]
    return ScriptedParse(output=to_wire(result))


async def test_reply_and_extraction_run_concurrently(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["Hi ", "there, ", "where do you live?"], delay_s=0.4))
    p = _extraction(interests=Update(value=["coding"], confidence=0.9, quote="I love coding"))
    p.delay_s = 0.4
    fake.add_parse("ExtractionWire", p)
    sid = await _new_session()

    t0 = time.perf_counter()
    events = await _collect(_orch(fake, tmp_path), sid, "I love coding")
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.7, f"reply and extraction ran sequentially ({elapsed:.2f}s)"
    marks = dict(fake.timeline)
    assert marks["parse_start:ExtractionWire"] < marks["stream_end"]
    assert marks["stream_start"] < marks["parse_end:ExtractionWire"]
    assert [e.event for e in events][-3:] == ["profile", "ready", "done"]


async def test_event_order_persistence_and_metrics(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["That's ", "awesome! ", "Where do you live?"]))
    fake.add_parse(
        "ExtractionWire",
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
    assert metrics["reply_total"].cost_usd > 0
    assert snaps[0].next_topic == "dream_without_money"  # planned for this turn's reply
    assert 0 <= metrics["reply_ttft"].ms <= metrics["reply_total"].ms


async def test_profile_merges_across_turns_and_corrections_win(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    for _ in range(2):
        fake.add_stream(ScriptedStream(chunks=["Got it."]))
    fake.add_parse(
        "ExtractionWire",
        _extraction(home_state=Update(value="OH", confidence=0.95, quote="I live in Ohio")),
    )
    fake.add_parse(
        "ExtractionWire",
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
    kw = _reply_calls(fake)[1]
    msgs = kw["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "system"]
    assert msgs[0]["content"] == "I live in Ohio" and msgs[1]["content"] == "Got it."
    assert '"home_state": {"confidence": 0.95, "value": "OH"}' in msgs[-1]["content"]
    assert "Suggested next topic:" in msgs[-1]["content"]
    assert kw["model"] == "claude-sonnet-5-5" and kw["output_config"] == {"effort": "low"}


async def test_extraction_failure_keeps_reply_and_profile(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["Tell me more!"]))
    fake.add_parse("ExtractionWire", ScriptedParse(output="", stop_reason="refusal"))
    sid = await _new_session()
    events = await _collect(_orch(fake, tmp_path), sid, "hello")
    assert [e.event for e in events] == ["token", "profile", "ready", "done"]
    assert events[1].data["profile"] == StudentProfile().model_dump(mode="json")
    async with get_sessionmaker()() as db:
        snaps = (
            (await db.execute(select(ProfileSnapshot).where(ProfileSnapshot.session_id == sid)))
            .scalars()
            .all()
        )
    # profile unchanged, but the planned topic is recorded so it is not asked twice
    assert len(snaps) == 1 and snaps[0].profile == StudentProfile().model_dump(mode="json")
    assert snaps[0].next_topic == "dream_without_money"


async def test_reply_refusal_uses_safe_fallback(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=[], stop_reason="refusal"))
    fake.add_parse("ExtractionWire", _extraction())
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


async def test_account_limit_error_has_its_own_message(tmp_path: Path) -> None:
    import anthropic
    import httpx

    from app.core.llm import ACCOUNT_ERROR_MESSAGE

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.BadRequestError(
        "You have reached your specified API usage limits.",
        response=httpx.Response(400, request=req),
        body=None,
    )
    fake = ScriptedAnthropic()
    fake.add_stream(exc)
    fake.add_parse("ExtractionWire", exc)
    sid = await _new_session()
    events = await _collect(_orch(fake, tmp_path), sid, "hello")
    assert [e.event for e in events] == ["error"]
    assert events[0].data["message"] == ACCOUNT_ERROR_MESSAGE
    assert ACCOUNT_ERROR_MESSAGE == (
        "The counselor is unavailable right now (API account limit). Please try again later."
    )


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


def _upd(value: object, quote: str) -> Update:  # type: ignore[type-arg]
    return Update(value=value, confidence=0.9, quote=quote)


def _notes(fake: ScriptedAnthropic) -> list[str]:
    return [kw["messages"][-1]["content"] for kw in _reply_calls(fake)]


async def _play(
    script: list[tuple[str, dict[str, Update]]],  # type: ignore[type-arg]
    tmp_path: Path,
) -> tuple[ScriptedAnthropic, uuid.UUID]:
    fake = ScriptedAnthropic()
    for _text, updates in script:
        fake.add_stream(ScriptedStream(chunks=["Okay."]))
        # the extractor's own next_topic is logged only; the planner drives the reply
        fake.add_parse("ExtractionWire", _extraction(next_topic="ready_to_recommend", **updates))
    orch = _orch(fake, tmp_path)
    sid = await _new_session()
    for text, _ in script:
        await _collect(orch, sid, text)
    return fake, sid


async def test_counselor_asks_location_size_and_priorities_before_offering_matches(
    tmp_path: Path,
) -> None:
    """Readiness (state + income + interests) is not enough to offer matches: location
    preference, size/setting and priorities are asked first, once each, and "no
    preference" answers are accepted (never re-asked)."""
    script = [
        ("hi! I love coding", {"interests": _upd(["coding"], "I love coding")}),
        ("I'd make video games all day", {"dream_without_money": _upd("make video games",
                                                                     "make video games")}),
        ("I live in Ohio", {"home_state": _upd("OH", "I live in Ohio")}),
        ("no preference really", {}),
        ("anywhere is fine", {}),
        ("cost matters most", {"priorities": _upd(["cost"], "cost matters most")}),
        ("my parents make about 60k", {"income_bracket": _upd("48-75k", "60k")}),
        ("cool", {}),
    ]  # fmt: skip
    fake, sid = await _play(script, tmp_path)
    notes = _notes(fake)
    topics = [n.split("Suggested next topic: ")[1].split("\n")[0] for n in notes]
    assert [t.split(" (")[0] for t in topics] == [
        "dream_without_money",
        "location",  # home state
        "size_setting",  # state just asked (lag): move on instead of re-asking
        "location",  # now how far from home / regions
        "priorities",
        "money",
        "academics",  # money just asked; readiness completes this turn
        "ready_to_recommend",
    ]
    assert "which state they live in" in topics[1] and "how far from home" in topics[3]
    offer = ["Offer matches now: yes" in n for n in notes]
    assert offer == [False] * 7 + [True]
    assert "Ready for recommendations: no" in notes[6]
    async with get_sessionmaker()() as db:
        persisted = (
            (
                await db.execute(
                    select(ProfileSnapshot.next_topic)
                    .where(ProfileSnapshot.session_id == sid)
                    .order_by(ProfileSnapshot.after_turn)
                )
            )
            .scalars()
            .all()
        )
    assert persisted == [t.split(" (")[0] for t in topics]


async def test_student_asking_for_schools_short_circuits_the_checklist(tmp_path: Path) -> None:
    script = [
        (
            "I live in Ohio, my family makes 60k and I love coding",
            {
                "home_state": _upd("OH", "I live in Ohio"),
                "income_bracket": _upd("48-75k", "my family makes 60k"),
                "interests": _upd(["coding"], "I love coding"),
            },
        ),
        ("just show me schools", {}),
        ("ok thanks", {}),
    ]
    fake, _sid = await _play(script, tmp_path)
    notes = _notes(fake)
    assert "Suggested next topic: ready_to_recommend" in notes[1]
    assert "Offer matches now: yes" in notes[1]
    # the checklist stays waived afterwards; the counselor keeps learning instead
    assert "Suggested next topic: location" not in notes[2]
    assert "Offer matches now: no" in notes[2]


async def test_asking_for_schools_before_ready_asks_for_what_is_missing(tmp_path: Path) -> None:
    script = [
        ("I love art", {"interests": _upd(["art"], "I love art")}),
        ("can I see my matches?", {}),
    ]
    fake, _sid = await _play(script, tmp_path)
    note = _notes(fake)[1]
    assert "Suggested next topic: location (which state they live in)" in note
    assert "Offer matches now: no" in note


@pytest.mark.parametrize(
    "bad",
    [
        ScriptedParse(output='{"updates": 5, "next_topic": "money"}'),  # schema-invalid JSON
        ScriptedParse(output="", stop_reason="max_tokens"),
        RuntimeError("unexpected bug in extraction"),
    ],
)
async def test_any_extraction_failure_still_persists_reply(
    tmp_path: Path, bad: ScriptedParse | Exception
) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["Tell me more!"]))
    fake.add_parse("ExtractionWire", bad)
    sid = await _new_session()
    events = await _collect(_orch(fake, tmp_path), sid, "hello")
    assert [e.event for e in events] == ["token", "profile", "ready", "done"]
    async with get_sessionmaker()() as db:
        turns = (await db.execute(select(Turn).where(Turn.session_id == sid))).scalars().all()
        stages = (
            (await db.execute(select(TurnMetricRow.stage).where(TurnMetricRow.session_id == sid)))
            .scalars()
            .all()
        )
    assert sorted(t.role for t in turns) == ["assistant", "user"]
    assert "extract" in stages  # failure still recorded as a metric row


async def test_client_disconnect_persists_partial_reply_as_interrupted(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(
        ScriptedStream(chunks=["Partial ", "reply ", "never ", "finished"], delay_s=0.4)
    )
    p = _extraction()
    p.delay_s = 1.0
    fake.add_parse("ExtractionWire", p)
    sid = await _new_session()
    agen = _orch(fake, tmp_path).handle_turn(sid, "hello")
    got = [await agen.__anext__(), await agen.__anext__()]
    assert [e.data["text"] for e in got] == ["Partial ", "reply "]
    await agen.aclose()  # what the API layer does when the client goes away
    async with get_sessionmaker()() as db:
        turns = (
            (await db.execute(select(Turn).where(Turn.session_id == sid).order_by(Turn.idx)))
            .scalars()
            .all()
        )
        snaps = (
            await db.execute(select(ProfileSnapshot).where(ProfileSnapshot.session_id == sid))
        ).all()
    assert [(t.role, t.interrupted) for t in turns] == [("user", False), ("assistant", True)]
    assert turns[1].text == "Partial reply "
    assert snaps == []  # extraction was cancelled


async def test_refusal_counts_are_recorded_per_stage(tmp_path: Path) -> None:
    from app.core.logging import TurnLogger  # noqa: F401  (stage records come from it)

    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["ok"]))
    fake.add_parse("ExtractionWire", ScriptedParse(output="", stop_reason="refusal"))
    orch = _orch(fake, tmp_path)
    sid = await _new_session()
    seen: list[dict] = []  # type: ignore[type-arg]
    import app.counselor.orchestrator as mod

    real = mod.TurnLogger

    class Spy(real):  # type: ignore[valid-type,misc]
        def __init__(self, *a: object, **k: object) -> None:
            super().__init__(*a, **k)
            seen.append(self.__dict__)

    mod.TurnLogger = Spy  # type: ignore[misc]
    try:
        await _collect(orch, sid, "hello")
    finally:
        mod.TurnLogger = real  # type: ignore[misc]
    extract = next(s for s in seen[0]["stages"] if s["stage"] == "extract")
    assert extract["refusals"] == 1
