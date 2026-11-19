from __future__ import annotations

from pathlib import Path

import pytest

from app.core.llm import LLMClient
from app.core.logging import Stage
from app.counselor.context import HistoryTurn, plan_next_topic
from app.counselor.extractor import Extractor, build_user_message, quote_in, sanitize
from app.schemas import (
    ExtractionResult,
    ProfileDelta,
    ProfileField,
    Riasec,
    StudentProfile,
    Update,
)
from tests.counselor_fixtures import CASSETTE_DIR, SCENARIO, ScriptedAnthropic, ScriptedParse

LATEST = "I live in Ohio, near Columbus. I'd love somewhere on the West Coast though."


def _client(fake: ScriptedAnthropic, tmp_path: Path) -> LLMClient:
    return LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)


async def test_extract_returns_delta_and_next_topic_with_sonnet_params(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse(
        "ExtractionResult",
        ScriptedParse(
            output=ExtractionResult(
                delta=ProfileDelta(
                    home_state=Update(value="OH", confidence=0.95, quote="I live in Ohio"),
                    regions=Update(
                        value=["pacific"], confidence=0.8, quote="somewhere on the West Coast"
                    ),
                ),
                next_topic="money",
            )
        ),
    )
    profile = StudentProfile(
        interests=ProfileField[list[str]](value=["coding"], confidence=0.9),
    )
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
    assert kind == "parse"
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["output_format"] is ExtractionResult
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "extract ONLY what the student states in the LATEST" in kw["system"][0]["text"]
    content = kw["messages"][0]["content"]
    assert LATEST in content and "counselor: Nice! Where do you live?" in content
    assert '"interests"' in content  # previous profile is in context
    assert st.extra["next_topic"] == "money" and st.extra["prompt"] == "extractor.v1"
    assert st.input_tokens > 0


def test_extractor_prompt_contains_region_vocabulary_and_no_invented_scores() -> None:
    from app.counselor.prompts import load_prompt

    text = load_prompt("extractor").text
    for code in ["new_england", "mid_atlantic", "pacific", "mountain", "out_of_state"]:
        assert code in text
    assert "leave that field null" in text
    assert "0.8 or higher" in text  # corrections rubric


def test_build_user_message_marks_start_of_conversation() -> None:
    msg = build_user_message(StudentProfile(), [], "hello")
    assert "(start of conversation)" in msg and "<latest_student_message>\nhello\n" in msg


@pytest.mark.parametrize(
    ("quote", "ok"),
    [
        ("I live in Ohio", True),
        ("i live   in ohio.", True),  # case, whitespace, trailing punctuation
        ("“West Coast”", True),
        ("I live in Michigan", False),  # not said
        ("", False),
        ("...", False),
    ],
)
def test_quote_in(quote: str, ok: bool) -> None:
    assert quote_in(quote, LATEST) is ok


def test_sanitize_drops_unquoted_riasec_and_bad_regions() -> None:
    delta = ProfileDelta(
        home_state=Update(value="oh", confidence=0.9, quote="I live in Ohio"),
        interests=Update(value=["coding"], confidence=0.9, quote="I like coding"),  # earlier turn
        riasec=Update(
            value=Riasec(R=0, I=1, A=0, S=0, E=0, C=0), confidence=0.6, quote="I live in Ohio"
        ),
        regions=Update(
            value=["Pacific", "ca", "west coast", "Narnia"],
            confidence=0.8,
            quote="somewhere on the West Coast",
        ),
    )
    clean, dropped = sanitize(delta, LATEST)
    assert clean.home_state is not None and clean.home_state.value == "OH"
    assert clean.interests is None and clean.riasec is None
    assert clean.regions is not None and clean.regions.value == ["pacific", "CA"]
    assert set(dropped) == {"interests", "riasec"}


def test_sanitize_drops_all_invalid_regions_and_unknown_state() -> None:
    delta = ProfileDelta(
        home_state=Update(value="Ohio", confidence=0.9, quote="I live in Ohio"),
        regions=Update(value=["the coast"], confidence=0.8, quote="West Coast"),
    )
    clean, dropped = sanitize(delta, LATEST)
    assert clean.home_state is None and clean.regions is None
    assert set(dropped) == {"home_state", "regions"}


def test_plan_next_topic_prioritises_readiness_after_dream_and_interests() -> None:
    p = StudentProfile()
    assert plan_next_topic(p) == "dream_without_money"
    p.dream_without_money = ProfileField[str](value="games", confidence=0.9)
    assert plan_next_topic(p) == "interests"
    p.interests = ProfileField[list[str]](value=["coding"], confidence=0.9)
    assert plan_next_topic(p) == "location"
    p.home_state = ProfileField[str](value="OH", confidence=0.9)
    assert plan_next_topic(p) == "money"
    p.income_bracket = ProfileField(value="48-75k", confidence=0.9)
    assert plan_next_topic(p) == "strengths"


async def test_extract_replays_from_committed_cassette() -> None:
    """The first scenario turn replays offline from tests/cassettes (no transport)."""
    llm = LLMClient(mode="replay", cassette_dir=CASSETTE_DIR)
    t = SCENARIO[0]
    res = await Extractor(llm).extract([], t.student, StudentProfile())
    assert res == t.extraction
