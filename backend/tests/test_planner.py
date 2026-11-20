"""Topic planner: readiness + the recommendation-quality checklist (SPEC §8)."""

from __future__ import annotations

from typing import Any

import pytest

from app.counselor.context import (
    LOCATION_PREF,
    asked_from_history,
    describe_topic,
    plan_next_topic,
    wants_matches,
)
from app.schemas import ProfileField, StudentProfile


def _p(**fields: Any) -> StudentProfile:
    return StudentProfile(
        **{k: ProfileField[Any](value=v, confidence=0.9) for k, v in fields.items()}
    )


READY = {"interests": ["coding"], "home_state": "OH", "income_bracket": "48-75k"}


def test_ordering_from_the_profile_alone() -> None:
    """dream -> interests -> home state -> location pref -> size/setting -> priorities ->
    money -> offer matches, each step skipped once the profile covers it."""
    steps = [
        ({}, "dream_without_money"),
        ({"dream_without_money": "games"}, "interests"),
        ({"interests": ["coding"]}, "location"),
        ({"home_state": "OH"}, "location"),  # now the distance/regions question
        ({"max_distance_miles": 300}, "size_setting"),
        ({"size_pref": "medium"}, "priorities"),
        ({"priorities": ["cost"]}, "money"),
        ({"income_bracket": "48-75k"}, "ready_to_recommend"),
    ]
    acc: dict[str, Any] = {}
    for add, want in steps:
        acc.update(add)
        assert plan_next_topic(_p(**acc)) == want, acc


def test_ready_profile_still_asks_the_quality_checklist_first() -> None:
    p = _p(**READY)
    assert p.is_ready()  # readiness contract unchanged: the UI button can enable now
    assert plan_next_topic(p, ["dream_without_money"]) == "location"
    assert "how far from home" in describe_topic("location", p)
    asked = ["dream_without_money", LOCATION_PREF]
    assert plan_next_topic(p, asked) == "size_setting"
    assert plan_next_topic(p, [*asked, "size_setting"]) == "priorities"
    assert plan_next_topic(p, [*asked, "size_setting", "priorities"]) == "ready_to_recommend"


def test_declined_topics_are_not_asked_again() -> None:
    """Asked = planned on an earlier turn; a 'no preference' answer leaves the profile
    empty but the topic is not re-asked."""
    p = _p(dream_without_money="games", interests=["art"], home_state="OH")
    asked = ["dream_without_money", "location", LOCATION_PREF, "size_setting", "priorities"]
    assert plan_next_topic(p, asked) == "money"


def test_lag_does_not_repeat_the_question_just_asked() -> None:
    """The plan sees the profile one turn behind; a topic asked last turn is skipped
    (the student is answering it now), so the counselor moves on."""
    p = _p(dream_without_money="games", interests=["art"])
    assert plan_next_topic(p, ["dream_without_money", "location"]) == "size_setting"


def test_evasive_student_readiness_re_asks_are_capped() -> None:
    """Empty profile that never fills: each readiness topic is asked at most 3 times
    (1 + 2 re-asks), no alternating interests/location loop, every enrichment topic
    still gets its turn."""
    p = StudentProfile()
    asked: list[str] = []
    for _ in range(17):
        asked.append(plan_next_topic(p, asked))
    for t in ("interests", "location", "money"):
        assert asked.count(t) == 3, (t, asked)
    assert set(asked) >= {
        "academics",
        "strengths",
        "favorite_subjects",
        "activities",
        "work_values",
        "size_setting",
        "priorities",
    }
    assert all(a != b for a, b in zip(asked, asked[1:], strict=False))  # never twice in a row
    # everything exhausted: one steady suggestion, not an alternation
    tail = [plan_next_topic(p, asked + ["interests"] * i) for i in range(1, 4)]
    assert len(set(tail)) == 1


def test_missing_readiness_is_re_asked_once_everything_else_was_asked() -> None:
    p = _p(dream_without_money="games", interests=["art"], home_state="OH")
    core = ["dream_without_money", "location", LOCATION_PREF, "size_setting", "priorities"]
    # money asked on the previous turn -> give the student a turn, ask enrichment
    assert plan_next_topic(p, [*core, "money"]) == "academics"
    # one more turn later, money is still missing -> re-ask it
    assert plan_next_topic(p, [*core, "money", "academics"]) == "money"


def test_after_offering_matches_enrichment_topics_follow() -> None:
    p = _p(**READY)
    asked = ["dream_without_money", LOCATION_PREF, "size_setting", "priorities"]
    asked.append("ready_to_recommend")
    assert plan_next_topic(p, asked) == "academics"
    rest = ["academics", "strengths", "favorite_subjects", "activities", "work_values"]
    assert plan_next_topic(p, [*asked, *rest]) == "ready_to_recommend"


def test_student_asking_for_matches_short_circuits_the_checklist() -> None:
    p = _p(**READY)
    assert plan_next_topic(p, student_wants_matches=True) == "ready_to_recommend"
    # only the CURRENT message waives the checklist: a persisted ready_to_recommend
    # (an earlier request, or a pre-planner snapshot) does not skip it later
    assert plan_next_topic(p, ["dream_without_money", "ready_to_recommend"]) == "location"
    # not ready: ask the one readiness item still missing, nothing else
    not_ready = _p(interests=["art"], home_state="OH")
    assert plan_next_topic(not_ready, student_wants_matches=True) == "money"


def test_asked_from_history_tells_home_state_from_location_preference() -> None:
    before_state = StudentProfile()
    with_state = _p(home_state="OH")
    history = [
        (before_state, "dream_without_money"),
        (before_state, "location"),  # planned before the state was known: home state
        (with_state, "location"),  # planned after: distance / regions
        (with_state, None),
    ]
    assert asked_from_history(history) == ["dream_without_money", "location", LOCATION_PREF]


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("just show me schools", True),
        ("can I see my matches?", True),
        ("ok show me some colleges please", True),
        ("what colleges would fit me?", True),
        ("can you recommend some schools", True),
        ("give me my recommendations", True),
        ("i love drawing and fixing bikes", False),
        ("i live in ohio", False),
        ("i want a school with good art", False),
        ("my sister goes to a big college", False),
        ("i'd like to see more of the country", False),
        ("I don't want to see schools yet", False),
        ("I'm not ready to see colleges", False),
        ("I went to see the school last week", False),
        ("please don't show me schools yet", False),
        ("we visited some colleges, show me more later maybe", False),
        ("no idea what to major in, just show me schools", True),
    ],
)
def test_wants_matches(text: str, want: bool) -> None:
    assert wants_matches(text) is want
