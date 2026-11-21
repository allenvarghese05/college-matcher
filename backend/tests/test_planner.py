"""Topic planner: readiness + the recommendation-quality checklist (SPEC §8)."""

from __future__ import annotations

from typing import Any

import pytest

from app.counselor.context import (
    LOCATION_PREF,
    STRENGTHS_SUBJECTS,
    asked_from_history,
    describe_topic,
    plan_next_topic,
    planner_history,
    wants_matches,
)
from app.schemas import ProfileField, StudentProfile


def _p(**fields: Any) -> StudentProfile:
    return StudentProfile(
        **{k: ProfileField[Any](value=v, confidence=0.9) for k, v in fields.items()}
    )


READY = {"interests": ["coding"], "home_state": "OH", "income_bracket": "48-75k"}
# Pre-location intake: dream, combined classes/strengths question, activities.
EARLY = ["dream_without_money", STRENGTHS_SUBJECTS, "activities"]


def test_ordering_from_the_profile_alone() -> None:
    """dream -> interests -> classes+strengths -> activities -> home state -> location
    pref -> size/setting -> priorities -> money -> offer matches, each step skipped once
    the profile covers it."""
    steps = [
        ({}, "dream_without_money"),
        ({"dream_without_money": "games"}, "interests"),
        ({"interests": ["coding"]}, "strengths"),  # the combined question
        ({"favorite_subjects": ["art"]}, "strengths"),  # still needs strengths
        ({"strengths": ["drawing"]}, "activities"),
        ({"activities": [{"name": "robotics"}]}, "location"),
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
    assert plan_next_topic(p, ["dream_without_money"]) == "strengths"
    assert plan_next_topic(p, EARLY) == "location"
    assert "how far from home" in describe_topic("location", p)
    asked = [*EARLY, LOCATION_PREF]
    assert plan_next_topic(p, asked) == "size_setting"
    assert plan_next_topic(p, [*asked, "size_setting"]) == "priorities"
    assert plan_next_topic(p, [*asked, "size_setting", "priorities"]) == "ready_to_recommend"


def test_declined_topics_are_not_asked_again() -> None:
    """Asked = planned on an earlier turn; a 'no preference' answer leaves the profile
    empty but the topic is not re-asked."""
    p = _p(dream_without_money="games", interests=["art"], home_state="OH")
    asked = [*EARLY, "location", LOCATION_PREF, "size_setting", "priorities"]
    assert plan_next_topic(p, asked) == "money"


def test_lag_does_not_repeat_the_question_just_asked() -> None:
    """The plan sees the profile one turn behind; a topic asked last turn is skipped
    (the student is answering it now), so the counselor moves on."""
    p = _p(dream_without_money="games", interests=["art"])
    assert plan_next_topic(p, ["dream_without_money", STRENGTHS_SUBJECTS]) == "activities"
    assert plan_next_topic(p, [*EARLY, "location"]) == "size_setting"


def test_evasive_student_readiness_re_asks_are_capped() -> None:
    """Empty profile that never fills: each readiness topic is asked at most 3 times
    (1 + 2 re-asks), no alternating interests/location loop, every enrichment topic
    still gets its turn."""
    p = StudentProfile()
    asked: list[str] = []
    for _ in range(16):
        asked.append(topic_key_of(p, plan_next_topic(p, asked)))
    for t in ("interests", "location", "money"):
        assert asked.count(t) == 3, (t, asked)
    assert set(asked) >= {
        "academics",
        STRENGTHS_SUBJECTS,
        "activities",
        "work_values",
        "size_setting",
        "priorities",
    }
    assert asked.count(STRENGTHS_SUBJECTS) == 1  # combined question asked once
    assert all(a != b for a, b in zip(asked, asked[1:], strict=False))  # never twice in a row
    # everything exhausted: one steady suggestion, not an alternation
    tail = [plan_next_topic(p, asked + ["interests"] * i) for i in range(1, 4)]
    assert len(set(tail)) == 1


def test_missing_readiness_is_re_asked_once_everything_else_was_asked() -> None:
    p = _p(dream_without_money="games", interests=["art"], home_state="OH")
    core = [*EARLY, "location", LOCATION_PREF, "size_setting", "priorities"]
    # money asked on the previous turn -> give the student a turn, ask enrichment
    assert plan_next_topic(p, [*core, "money"]) == "academics"
    # one more turn later, money is still missing -> re-ask it
    assert plan_next_topic(p, [*core, "money", "academics"]) == "money"


def test_after_offering_matches_enrichment_topics_follow() -> None:
    p = _p(**READY)
    asked = [*EARLY, LOCATION_PREF, "size_setting", "priorities"]
    asked.append("ready_to_recommend")
    assert plan_next_topic(p, asked) == "academics"
    assert plan_next_topic(p, [*asked, "academics"]) == "work_values"
    assert plan_next_topic(p, [*asked, "academics", "work_values"]) == "ready_to_recommend"


def test_enrichment_for_matching_comes_before_the_offer() -> None:
    """Classes/strengths and activities feed interests -> majors matching, so a ready
    profile still gets them before matches are offered; academics only after."""
    p = _p(**READY, dream_without_money="games")
    seq: list[str] = []
    for _ in range(9):
        seq.append(topic_key_of(p, plan_next_topic(p, seq)))
    offer = seq.index("ready_to_recommend")
    assert seq[:offer] == [
        STRENGTHS_SUBJECTS,
        "activities",
        LOCATION_PREF,
        "size_setting",
        "priorities",
    ]
    assert seq[offer + 1 : offer + 3] == ["academics", "work_values"]


def test_combined_topic_is_persisted_as_strengths_and_marks_both_asked() -> None:
    p = _p(interests=["art"])
    assert plan_next_topic(p, ["dream_without_money"]) == "strengths"
    assert describe_topic("strengths", p).startswith(f"{STRENGTHS_SUBJECTS} (")
    assert "classes" in describe_topic("strengths", p)
    # a stored "strengths" or legacy "favorite_subjects" hint reads back as the combined key
    hist = [(p, "dream_without_money"), (p, "strengths"), (p, "favorite_subjects")]
    assert asked_from_history(hist) == ["dream_without_money", *[STRENGTHS_SUBJECTS] * 2]
    assert plan_next_topic(p, asked_from_history(hist)) == "activities"
    # covered only when BOTH fields are known
    both = _p(interests=["art"], strengths=["drawing"], favorite_subjects=["art"])
    assert plan_next_topic(both, ["dream_without_money"]) == "activities"


def test_student_asking_for_matches_short_circuits_the_checklist() -> None:
    p = _p(**READY)
    assert plan_next_topic(p, student_wants_matches=True) == "ready_to_recommend"
    # only the CURRENT message waives the checklist: a persisted ready_to_recommend
    # (an earlier request, or a pre-planner snapshot) does not skip it later
    assert plan_next_topic(p, ["dream_without_money", "ready_to_recommend"]) == "strengths"
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


# (text, without a previous offer, right after the counselor offered matches)
WANTS_MATCHES_TABLE: list[tuple[str, bool, bool]] = [
    # explicit requests (allow-list)
    ("just show me schools", True, True),
    ("show me my matches please", True, True),
    ("ok show me some colleges please", True, True),
    ("no idea what to major in, just show me schools", True, True),
    ("show me my options for colleges", True, True),
    ("can I see my matches?", True, True),
    ("could I have the list", True, True),
    ("what are my matches?", True, True),
    ("what colleges would fit me?", True, True),
    ("which schools would work for me", True, True),
    ("I'm ready to see my matches", True, True),
    ("give me my recommendations", True, True),
    ("can you recommend some schools", True, True),
    # affirmations: only right after an offer
    ("ok show me", False, True),
    ("sure, show me", False, True),
    ("ok let's see them", False, True),
    ("go ahead", False, True),
    # not requests
    ("i love drawing and fixing bikes", False, False),
    ("i live in ohio", False, False),
    ("i want a school with good art", False, False),
    ("my sister goes to a big college", False, False),
    ("i'd like to see more of the country", False, False),
    ("I don't want to see schools yet", False, False),
    ("I'm not ready to see colleges", False, False),
    ("I went to see the school last week", False, False),
    ("please don't show me schools yet", False, False),
    ("we visited some colleges, show me more later maybe", False, False),
    # second review's false positives
    ("I want to get into a good college", False, False),
    ("can I get into a good school with a 3.0", False, False),
    ("could I get into colleges in california", False, False),
    ("I would like to get out of my state for college", False, False),
    ("I wanna get a job right after college", False, False),
    ("I'd like to get a scholarship at a big university", False, False),
    ("i want to see the world before college", False, False),
    ("I want to see what my options are for majors first", False, False),
    ("show me how to pick schools later", False, False),
    ("which colleges would my brother like", False, False),
    ("can you recommend some schools for my cousin", False, False),
    ("ok", False, False),
]


@pytest.mark.parametrize(("text", "cold", "after_offer"), WANTS_MATCHES_TABLE)
def test_wants_matches(text: str, cold: bool, after_offer: bool) -> None:
    assert wants_matches(text) is cold
    assert wants_matches(text, previous_offer=True) is after_offer


def test_offer_made_on_a_waiver_is_repeated_once_the_checklist_is_done() -> None:
    p = _p(**READY)
    waived = ["dream_without_money", "ready_to_recommend"]  # student asked early
    done = [*waived, STRENGTHS_SUBJECTS, "activities", LOCATION_PREF, "size_setting",
            "priorities"]  # fmt: skip
    assert plan_next_topic(p, done) == "ready_to_recommend"  # the normal offer still comes
    assert plan_next_topic(p, [*done, "ready_to_recommend"]) == "academics"  # only once


def test_waiver_offer_then_checklist_answered_re_offers_exactly_once() -> None:
    """Reviewer finding: the waiver must be judged against the profile at plan time. A
    student asks for matches early (one-turn waiver), then ANSWERS the checklist
    questions; the current profile now covers the checklist, but the early offer was
    still a waiver, so the normal offer comes exactly once."""
    early = _p(**READY, dream_without_money="games")
    full = _p(
        **READY,
        dream_without_money="games",
        strengths=["drawing"],
        favorite_subjects=["art"],
        activities=[{"name": "robotics"}],
        max_distance_miles=300,
        size_pref="medium",
        priorities=["cost"],
    )
    history: list[tuple[StudentProfile, str | None]] = [
        (StudentProfile(), "dream_without_money"),
        (early, "ready_to_recommend"),  # waiver: student asked, checklist not yet asked
        (early, "strengths"),
        (early, "activities"),
        (early, "location"),  # home state known -> location preference
        (early, "size_setting"),
        (early, "priorities"),
    ]
    asked, offered = planner_history(history)
    assert offered is False
    # the old current-profile judgement would wrongly count the waiver as the offer
    assert plan_next_topic(full, asked) == "academics"
    seq: list[str | None] = []
    for _ in range(3):
        hist = history + [(full, t) for t in seq]
        a, o = planner_history(hist)
        seq.append(plan_next_topic(full, a, offered_after_checklist=o))
    assert seq == ["ready_to_recommend", "academics", "work_values"]  # offered exactly once
    # once the real offer is in the history it counts
    a, o = planner_history([*history, (full, "ready_to_recommend")])
    assert o is True and plan_next_topic(full, a, offered_after_checklist=o) == "academics"


def test_offer_after_checklist_covered_by_volunteered_answers_counts() -> None:
    """An offer planned when the profile already covered the checklist (student
    volunteered it) is real even though the checklist topics were never asked."""
    full = _p(**READY, max_distance_miles=300, size_pref="medium", priorities=["cost"])
    _, offered = planner_history([(full, "ready_to_recommend")])
    assert offered is True


def topic_key_of(p: StudentProfile, topic: str) -> str:
    """The planner key a planned topic is recorded under (as asked_from_history)."""
    return asked_from_history([(p, topic)])[0]


# --------------------------------------------------------------- follow-ups


LONG = "I'd build video games with my friends all day long"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (LONG, True),
        ("I really love drawing comics and making characters", True),
        ("video games", False),  # too short to dig into
        ("I don't know, not really sure yet", False),  # a shrug
        (None, False),
        ("", False),
    ],
)
def test_is_substantive(answer: str | None, expected: bool) -> None:
    from app.counselor.context import is_substantive

    assert is_substantive(answer) is expected


def test_follow_up_after_a_substantive_open_answer() -> None:
    p = _p(dream_without_money="make video games")
    assert plan_next_topic(p, ["dream_without_money"], last_answer=LONG) == "follow_up"
    # the follow-up is asked once, then the checklist resumes
    assert plan_next_topic(p, ["dream_without_money", "follow_up"], last_answer=LONG) == (
        "interests"
    )


def test_no_follow_up_for_short_answers_closed_topics_or_match_requests() -> None:
    p = _p(**READY)
    assert plan_next_topic(_p(), ["dream_without_money"], last_answer="games") == "interests"
    # home state / money are closed questions: never followed up
    assert plan_next_topic(p, [*EARLY, "location"], last_answer=LONG) != "follow_up"
    assert (
        plan_next_topic(p, ["activities"], student_wants_matches=True, last_answer=LONG)
        == "ready_to_recommend"
    )
    # without last_answer (old callers) the planner never follows up
    assert plan_next_topic(_p(), ["dream_without_money"]) == "interests"


def test_follow_up_is_recorded_in_history_and_described() -> None:
    p = _p(dream_without_money="make video games")
    history = [(StudentProfile(), "dream_without_money"), (p, "follow_up")]
    assert asked_from_history(history) == ["dream_without_money", "follow_up"]
    assert describe_topic("follow_up", p).startswith("follow_up (one follow-up")
