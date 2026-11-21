from __future__ import annotations

from pathlib import Path

import pytest

from app.core.llm import LLMClient, LLMOutputError, wire_schema
from app.core.logging import Stage
from app.counselor.context import HistoryTurn, to_usps
from app.counselor.extractor import (
    ExtractionWire,
    Extractor,
    WireActivity,
    WireUpdate,
    build_user_message,
    quote_in,
    sanitize,
    wire_to_delta,
)
from app.schemas import Activity, ProfileDelta, ProfileField, Riasec, StudentProfile, Update
from tests.counselor_fixtures import (
    CASSETTE_DIR,
    SCENARIO,
    ScriptedAnthropic,
    ScriptedParse,
    wire_update,
)

LATEST = "I live in Ohio, near Columbus. I'd love somewhere on the West Coast though."


def _client(fake: ScriptedAnthropic, tmp_path: Path) -> LLMClient:
    return LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)


def _wire(*updates: WireUpdate, next_topic: str = "money") -> ExtractionWire:
    return ExtractionWire(updates=list(updates), next_topic=next_topic)  # type: ignore[arg-type]


async def test_extract_returns_delta_and_next_topic_with_sonnet_params(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse(
        "ExtractionWire",
        ScriptedParse(
            output=_wire(
                wire_update("home_state", "OH", 0.95, "I live in Ohio"),
                wire_update("regions", ["pacific"], 0.8, "somewhere on the West Coast"),
            )
        ),
    )
    profile = StudentProfile(interests=ProfileField[list[str]](value=["coding"], confidence=0.9))
    history = [
        HistoryTurn(0, "user", "I like coding."),
        HistoryTurn(1, "assistant", "Nice! Where do you live?"),
    ]
    st = Stage("extract")
    res = await Extractor(_client(fake, tmp_path)).extract(history, LATEST, profile, stage=st)
    assert res.next_topic == "money"
    assert res.delta.home_state is not None and res.delta.home_state.value == "OH"
    assert res.delta.regions is not None and res.delta.regions.value == ["pacific"]

    kind, kw = fake.calls[0]
    assert kind == "stream" and "output_format" not in kw
    assert kw["model"] == "claude-sonnet-5-5" and kw["max_tokens"] == 16000
    assert kw["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": wire_schema(ExtractionWire)},
    }
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "extract ONLY what the student states in the LATEST" in kw["system"][0]["text"]
    content = kw["messages"][0]["content"]
    assert LATEST in content and "counselor: Nice! Where do you live?" in content
    assert '"interests"' in content  # previous profile is in context
    assert st.extra["next_topic"] == "money" and st.extra["prompt"] == "extractor.v4"
    assert st.input_tokens > 0


async def test_schema_invalid_output_is_llm_output_error(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse("ExtractionWire", ScriptedParse(output='{"updates": "nope"}'))
    st = Stage("extract")
    with pytest.raises(LLMOutputError):
        await Extractor(_client(fake, tmp_path)).extract([], "hi", StudentProfile(), stage=st)
    assert st.input_tokens > 0  # usage still recorded


# The exact student message from the first live run, where "cost matters a lot" was
# not extracted into priorities under extractor.v3.
LIVE_COST_MESSAGE = (
    "Probably design things people actually use every day, like bikes or furniture. "
    "My family makes around 60k a year, so cost matters a lot. "
    "I have a 3.6 GPA and got a 1310 on the SAT."
)


def test_extractor_v4_has_priorities_rule_and_v3_is_kept() -> None:
    from app.counselor.prompts import ACTIVE, load_prompt

    assert ACTIVE["extractor"] == 4
    v4 = load_prompt("extractor").text
    assert '"cost matters a lot" -> ["cost"]' in v4
    for phrase in ("afford", "budget", "salary", "career", "ranking", "prestige",
                   "close to home", "vibe", "community"):  # fmt: skip
        assert phrase in v4, phrase
    assert "Stating income or a budget alone" in v4
    v3 = load_prompt("extractor", 3).text
    assert '"cost matters a lot"' not in v3  # v3 stays as recorded


async def test_live_cost_message_extracts_cost_priority(tmp_path: Path) -> None:
    """What the v4 prompt asks for on the live message: every stated field, including
    priorities=["cost"] quoted from the student's words, survives the quote check."""
    fake = ScriptedAnthropic()
    fake.add_parse(
        "ExtractionWire",
        ScriptedParse(
            output=_wire(
                wire_update(
                    "interests",
                    ["designing everyday products", "bikes", "furniture"],
                    0.8,
                    "design things people actually use every day, like bikes or furniture",
                ),
                wire_update("income_bracket", "48-75k", 0.85, "My family makes around 60k a year"),
                wire_update("priorities", ["cost"], 0.9, "cost matters a lot"),
                wire_update("gpa", 3.6, 0.95, "I have a 3.6 GPA"),
                wire_update("sat", 1310, 0.95, "got a 1310 on the SAT"),
                next_topic="location",
            )
        ),
    )
    st = Stage("extract")
    res = await Extractor(_client(fake, tmp_path)).extract(
        [], LIVE_COST_MESSAGE, StudentProfile(), stage=st
    )
    d = res.delta
    assert d.priorities == Update(value=["cost"], confidence=0.9, quote="cost matters a lot")
    assert d.income_bracket is not None and d.income_bracket.value == "48-75k"
    assert d.gpa is not None and d.gpa.value == 3.6
    assert d.sat is not None and d.sat.value == 1310
    assert d.interests is not None and "furniture" in d.interests.value
    assert st.extra["dropped_fields"] == [] and st.extra["prompt"] == "extractor.v4"
    _, kw = fake.calls[0]
    assert '"cost matters a lot" -> ["cost"]' in kw["system"][0]["text"]
    assert LIVE_COST_MESSAGE in kw["messages"][0]["content"]


def test_extractor_prompt_describes_wire_region_vocabulary_and_budget_rule() -> None:
    from app.counselor.prompts import load_prompt

    text = load_prompt("extractor").text
    for code in ["new_england", "mid_atlantic", "pacific", "mountain", "out_of_state"]:
        assert code in text
    assert "add no update for that field" in text
    assert "0.8 or higher" in text  # corrections rubric
    assert "Update format" in text and "null" not in text
    assert "add no budget_cap update" in text


def test_build_user_message_marks_start_of_conversation() -> None:
    msg = build_user_message(StudentProfile(), [], "hello")
    assert "(start of conversation)" in msg and "<latest_student_message>\nhello\n" in msg


# --------------------------------------------------------------- wire -> delta


def test_wire_to_delta_types_and_sentinels() -> None:
    wire = _wire(
        wire_update("gpa", 3.7, 0.95, "q"),
        wire_update("sat", 1310.0, 0.95, "q"),
        wire_update("income_bracket", "48-75K", 0.85, "q"),  # case-insensitive enum
        wire_update("size_pref", " Large ", 0.8, "q"),
        wire_update("work_values", ["Independence", "Working Conditions", "money"], 0.7, "q"),
        wire_update("interests", ["coding", " "], 0.9, "q"),
        WireUpdate(
            field="activities",
            text="",
            number=0,
            items=[],
            activities=[WireActivity(name="Robotics", role="", years=2, hours_per_week=0)],
            confidence=0.9,
            quote="q",
        ),
    )
    conv = wire_to_delta(wire, "q")
    delta, dropped = conv.delta, conv.dropped
    assert delta.gpa == Update(value=3.7, confidence=0.95, quote="q")
    assert delta.sat is not None and delta.sat.value == 1310
    assert delta.income_bracket is not None and delta.income_bracket.value == "48-75k"
    assert delta.size_pref is not None and delta.size_pref.value == "large"
    assert delta.work_values is not None
    assert delta.work_values.value == ["independence", "working_conditions"]  # "money" dropped
    assert delta.interests is not None and delta.interests.value == ["coding"]
    assert delta.activities is not None
    assert delta.activities.value == [Activity(name="Robotics", role=None, years=2)]
    assert dropped == []


def test_wire_to_delta_drops_empty_and_invalid_values() -> None:
    wire = _wire(
        wire_update("sat", 0, 0.9, "q"),  # 0 = not stated
        wire_update("income_bracket", "rich", 0.9, "q"),  # not an enum value
        wire_update("home_zip", "", 0.9, "q"),
        wire_update("priorities", ["fame"], 0.9, "q"),  # no valid items
    )
    conv = wire_to_delta(wire, "q")
    delta, dropped = conv.delta, conv.dropped
    assert delta == ProfileDelta()
    assert sorted(dropped) == ["home_zip", "income_bracket", "priorities", "sat"]


def test_wire_to_delta_repeated_fields() -> None:
    wire = _wire(
        wire_update("interests", ["coding"], 0.7, "a"),
        wire_update("interests", ["art"], 0.9, "b"),
        wire_update("home_state", "OH", 0.9, "c"),
        wire_update("home_state", "MI", 0.5, "d"),
    )
    conv = wire_to_delta(wire, "a b c d")
    delta = conv.delta
    assert delta.interests is not None and delta.interests.value == ["coding", "art"]
    assert conv.extra_quotes == {"interests": ["b"]}
    assert delta.interests.confidence == 0.9
    assert delta.home_state is not None and delta.home_state.value == "OH"


# ---------------------------------------------------------------------- guards


@pytest.mark.parametrize(
    ("quote", "ok"),
    [
        ("I live in Ohio", True),
        ("i live   in ohio.", True),  # case, whitespace, trailing punctuation
        ("“West Coast”", True),
        ("I live in Oh", False),  # word boundary: not a prefix of "Ohio"
        ("ive in Ohio", False),
        ("I live in Michigan", False),  # not said
        ("", False),
        ("...", False),
    ],
)
def test_quote_in(quote: str, ok: bool) -> None:
    assert quote_in(quote, LATEST) is ok


def test_quote_in_normalises_dashes_and_ellipsis() -> None:
    msg = "Maybe 1200–1400 on the SAT… not sure"
    assert quote_in("1200-1400 on the SAT...", msg)
    assert quote_in("Maybe 1200—1400", msg)


@pytest.mark.parametrize(
    ("text", "code"),
    [("oh", "OH"), ("Ohio", "OH"), (" new  york ", "NY"), ("District of Columbia", "DC"),
     ("Narnia", None), ("O", None)],
)  # fmt: skip
def test_to_usps(text: str, code: str | None) -> None:
    assert to_usps(text) == code


def test_sanitize_drops_unquoted_riasec_and_bad_regions() -> None:
    delta = ProfileDelta(
        home_state=Update(value="Ohio", confidence=0.9, quote="I live in Ohio"),
        interests=Update(value=["coding"], confidence=0.9, quote="I like coding"),  # earlier turn
        riasec=Update(
            value=Riasec(R=0, I=1, A=0, S=0, E=0, C=0), confidence=0.6, quote="I live in Ohio"
        ),
        regions=Update(
            value=["Pacific", "ca", "California", "west coast", "New England", "Narnia"],
            confidence=0.8,
            quote="somewhere on the West Coast",
        ),
    )
    clean, dropped = sanitize(delta, LATEST)
    assert clean.home_state is not None and clean.home_state.value == "OH"
    assert clean.interests is None and clean.riasec is None
    assert clean.regions is not None and clean.regions.value == ["pacific", "CA", "new_england"]
    assert set(dropped) == {"interests", "riasec"}


def test_sanitize_drops_all_invalid_regions_and_unknown_state() -> None:
    delta = ProfileDelta(
        home_state=Update(value="Ohioland", confidence=0.9, quote="I live in Ohio"),
        regions=Update(value=["the coast"], confidence=0.8, quote="West Coast"),
    )
    clean, dropped = sanitize(delta, LATEST)
    assert clean.home_state is None and clean.regions is None
    assert set(dropped) == {"home_state", "regions"}


async def test_extract_replays_from_committed_cassette() -> None:
    """The first scenario turn replays offline from tests/cassettes (no transport)."""
    llm = LLMClient(mode="replay", cassette_dir=CASSETTE_DIR)
    t = SCENARIO[0]
    res = await Extractor(llm).extract([], t.student, StudentProfile())
    assert res == t.extraction


ROBOTICS = "I love robotics and I hate math."


def test_invented_quote_cannot_ride_along_in_a_merged_list_field() -> None:
    wire = _wire(
        wire_update("interests", ["robotics"], 0.9, "I love robotics"),
        wire_update("interests", ["marine biology"], 0.95, "I adore marine biology"),
    )
    conv = wire_to_delta(wire, ROBOTICS)
    assert conv.delta.interests == Update(
        value=["robotics"], confidence=0.9, quote="I love robotics"
    )
    assert conv.dropped == ["interests"] and conv.extra_quotes == {}


def test_invented_high_confidence_scalar_does_not_displace_valid_one() -> None:
    msg = "I think my GPA is around 3.4 or so."
    wire = _wire(
        wire_update("gpa", 3.4, 0.7, "my GPA is around 3.4"),
        wire_update("gpa", 4.0, 0.99, "I have a perfect 4.0"),
    )
    conv = wire_to_delta(wire, msg)
    assert conv.delta.gpa == Update(value=3.4, confidence=0.7, quote="my GPA is around 3.4")
    assert conv.dropped == ["gpa"]


async def test_merged_list_keeps_evidence_for_each_surviving_quote(tmp_path: Path) -> None:
    from app.counselor.extractor import add_extra_evidence
    from app.schemas import apply_delta

    fake = ScriptedAnthropic()
    fake.add_parse(
        "ExtractionWire",
        ScriptedParse(
            output=_wire(
                wire_update("interests", ["robotics"], 0.9, "I love robotics"),
                wire_update("interests", ["math"], 0.6, "I hate math"),  # odd but quoted
                wire_update("interests", ["marine biology"], 0.95, "I adore marine biology"),
            )
        ),
    )
    out = await Extractor(_client(fake, tmp_path)).extract_with_evidence(
        [], ROBOTICS, StudentProfile()
    )
    assert out.result.delta.interests is not None
    assert out.result.delta.interests.value == ["robotics", "math"]
    assert out.extra_quotes == {"interests": ["I hate math"]}
    prof = apply_delta(StudentProfile(), out.result.delta, 4, "chat")
    prof = add_extra_evidence(prof, out.extra_quotes, 4, "chat")
    assert [e.quote for e in prof.interests.evidence] == ["I love robotics", "I hate math"]
