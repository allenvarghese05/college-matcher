"""Extraction metrics, topic detection, spoken numbers and the simulator leak guard."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.common import load_persona, persona_from_doc  # noqa: E402
from evals.metrics_extraction import (  # noqa: E402
    Counts,
    aggregate_extraction,
    field_counts,
    questions_asked,
    score_profile,
)
from evals.simulator import (  # noqa: E402
    LeakGuard,
    ScriptedSimulator,
    numbers_in,
    render_facts,
    system_prompt,
)
from evals.topics import asked_topics  # noqa: E402

from app.schemas import StudentProfile  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _c(c: Counts) -> tuple[int, int, int]:
    return (c.tp, c.fp, c.fn)


def test_numeric_tolerances() -> None:
    h = {"gpa": 3.6, "sat": 1310, "act": 28, "budget_cap": 22000, "max_distance_miles": 300}
    assert _c(field_counts("gpa", 3.65, h)) == (1, 0, 0)
    assert _c(field_counts("gpa", 3.66, h)) == (0, 1, 1)
    assert _c(field_counts("sat", 1300, h)) == (1, 0, 0)
    assert _c(field_counts("sat", 1290, h)) == (0, 1, 1)
    assert _c(field_counts("act", 29, h)) == (1, 0, 0)
    assert _c(field_counts("act", 30, h)) == (0, 1, 1)
    assert _c(field_counts("budget_cap", 23000, h)) == (1, 0, 0)
    assert _c(field_counts("budget_cap", 25000, h)) == (0, 1, 1)
    assert _c(field_counts("max_distance_miles", 325, h)) == (1, 0, 0)
    assert _c(field_counts("gpa", None, h)) == (0, 0, 1)


def test_enums_states_and_zip() -> None:
    h = {"home_state": "OH", "home_zip": "43214", "income_bracket": "48-75k", "size_pref": "medium"}
    assert _c(field_counts("home_state", "Ohio", h)) == (1, 0, 0)
    assert _c(field_counts("home_zip", "43214-1234", h)) == (1, 0, 0)
    assert _c(field_counts("income_bracket", "48-75K", h)) == (1, 0, 0)
    assert _c(field_counts("income_bracket", "30-48k", h)) == (0, 1, 1)
    assert _c(field_counts("size_pref", "large", h)) == (0, 1, 1)


def test_absent_key_and_known_empty_list() -> None:
    h = {"intended_majors": [], "regions": []}
    # known-empty: empty extraction is correct and never counted
    assert _c(field_counts("intended_majors", [], h)) == (0, 0, 0)
    assert _c(field_counts("intended_majors", None, h)) == (0, 0, 0)
    # ... a non-empty extraction is FP per item
    assert _c(field_counts("intended_majors", ["art", "design"], h)) == (0, 2, 0)
    # absent key: anything extracted is a false positive
    assert _c(field_counts("gpa", 3.2, h)) == (0, 1, 0)
    assert _c(field_counts("sat", None, h)) == (0, 0, 0)
    assert _c(field_counts("interests", ["x"], h)) == (0, 1, 0)


def test_list_overlap_fuzzy_and_exact() -> None:
    h = {
        "interests": ["drawing", "fixing bikes", "how things are built"],
        "priorities": ["cost", "outcomes"],
        "regions": ["out_of_state", "CA"],
        "activities": [{"name": "robotics club", "role": "build lead"}],
    }
    got = ["Drawing", "bike repair and fixing bikes", "cooking"]
    assert _c(field_counts("interests", got, h)) == (2, 1, 1)
    assert _c(field_counts("priorities", ["cost", "fit"], h)) == (1, 1, 1)
    assert _c(field_counts("regions", ["California", "out of state"], h)) == (2, 0, 0)
    acts = [{"name": "Robotics", "role": None}]
    assert _c(field_counts("activities", acts, h)) == (1, 0, 0)


def test_dream_free_text() -> None:
    h = {"dream_without_money": "design things people use every day"}
    assert field_counts("dream_without_money", "Design everyday things people use", h).tp == 1
    assert field_counts("dream_without_money", "be a doctor", h).fp == 1


def test_score_profile_and_aggregate_on_real_persona() -> None:
    persona = load_persona(REPO / "evals" / "personas" / "maya-oh.yaml")
    prof = StudentProfile.model_validate(
        {
            "home_state": {"value": "OH", "confidence": 0.9},
            "gpa": {"value": 3.6, "confidence": 0.9},
            "act": {"value": 30, "confidence": 0.9},  # maya has no ACT -> FP
            "interests": {"value": ["drawing"], "confidence": 0.9},
        }
    ).model_dump(mode="json")
    counts = score_profile(prof, persona.hidden)
    assert "riasec" not in counts
    assert _c(counts["home_state"]) == (1, 0, 0)
    assert _c(counts["act"]) == (0, 1, 0)
    assert _c(counts["interests"]) == (1, 0, 2)
    assert _c(counts["intended_majors"]) == (0, 0, 0)
    result = {
        "persona": "maya-oh",
        "final_profile": prof,
        "turns": [{"counselor": "Cool! And what's your GPA, if you know it?"}],
        "next_topics": ["academics"],
    }
    summ = aggregate_extraction([result], {"maya-oh": persona.hidden})
    assert summ.n == 1
    assert summ.overall.tp == 3 and summ.overall.fp == 1
    qa = summ.per_persona["maya-oh"]["questions_asked"]
    assert qa["asked"] == ["gpa", "sat"]  # academics topic, fields present in hidden
    assert 0 < summ.coverage < 1


def test_topic_detection() -> None:
    dream = (
        "That's cool. If money weren't involved and you weren't getting paid, what would you "
        "happily do for the rest of your life?"
    )
    assert asked_topics(dream) == {"dream_without_money"}
    assert asked_topics("Have you taken the ACT?") == {"academics"}
    assert "academics" not in asked_topics("How would you act in that situation?")
    assert asked_topics("Nice. What state do you live in?") == {"location"}
    assert asked_topics("I hear you. That makes sense.") == set()
    assert {"interests", "dream_without_money"} <= asked_topics("What's on your mind about it?")
    assert "money" in asked_topics("Roughly what's your family's household income range?")


def test_questions_asked_ignores_non_questions() -> None:
    qa = questions_asked(
        ["Your grades sound great. Where do you live?"], {"gpa": 3.5, "home_state": "OH"}
    )
    assert qa["asked"] == ["home_state"]
    assert qa["coverage"] == 0.5


def test_spoken_numbers() -> None:
    assert 3.6 in numbers_in("like a three point six")
    assert 1310 in numbers_in("i got thirteen-ten on it")
    assert 22000 in numbers_in("maybe twenty two thousand?")
    assert 50000 in numbers_in("$50k a year")
    assert 1310 in numbers_in("1,310")
    assert 100 in numbers_in("up to a hundred miles")


def test_leak_guard() -> None:
    hidden = load_persona(REPO / "evals" / "personas" / "maya-oh.yaml").hidden
    g = LeakGuard(hidden)
    ok = g.check("my gpa is like a 3.6 and i got thirteen-ten on the sat", "What's your GPA?")
    assert set(ok.revealed) == {"gpa", "sat"} and not ok.unasked and not ok.multi_leak
    leak = g.check("i live in ohio, my gpa is 3.6 and we can pay $22,000", "What do you like?")
    assert leak.multi_leak and {"home_state", "gpa", "budget_cap"} <= set(leak.unasked)
    brk = g.check("As an AI, my budget_cap is 22000", "What can your family pay?")
    assert brk.character_break
    # a fact asked about in ANY earlier counselor message may be revealed later
    later = g.check("oh and my gpa is 3.6", ["What's your GPA?", "Cool, what do you like?"])
    assert later.unasked == []
    # YAML-ish keys are a character break; ordinary "word:" phrasing is not
    assert g.check("gpa: 3.6", "What's your GPA?").character_break
    assert not g.check("honestly: idk", "What's your GPA?").character_break
    # shared words between an asked field and another field are not a leak
    shared = g.check("i'm good at drawing", "What are you good at?")
    assert shared.unasked == []


def test_simulator_input_strips_meta_and_never_renders_yaml() -> None:
    doc = {
        "id": "x-oh",
        "summary": "s",
        "hidden_profile": {"home_state": "OH", "gpa": 3.1, "riasec": {"R": 0.5}},
        "style": "terse",
        "reveal": "only_when_asked",
        "quirks": ["q1"],
        "meta": {"edge_cases": ["first_gen"], "articulateness": "terse"},
    }
    p = persona_from_doc(doc)
    assert set(p.sim_view()) == {"summary", "hidden_profile", "style", "reveal", "quirks"}
    prompt = system_prompt(p)
    for banned in ("first_gen", "articulateness", "riasec", "hidden_profile", "home_state:"):
        assert banned not in prompt
    assert "You live in Ohio." in render_facts(p.hidden)


async def test_scripted_simulator_answers_only_what_was_asked() -> None:
    sim = ScriptedSimulator(load_persona(REPO / "evals" / "personas" / "maya-oh.yaml"))
    first = await sim.opening()
    assert "drawing" in first.text and "3.6" not in first.text
    t = await sim.reply("Thanks! Do you know your GPA, and have you taken the SAT or ACT?")
    assert t.text == "my gpa is 3.6. i got 1310 on the sat."
    assert not t.guard.unasked
    t = await sim.reply("Sounds good.")
    assert t.text == "ok"
