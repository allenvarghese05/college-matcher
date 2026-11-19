"""Deterministic helpers shared by the counselor prompts: profile rendering and topics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from app.schemas import NextTopic, ProfileField, StudentProfile

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class HistoryTurn:
    idx: int
    role: Role
    text: str


# Topic -> profile fields that cover it (intake order, SPEC §8).
TOPIC_FIELDS: dict[NextTopic, tuple[str, ...]] = {
    "dream_without_money": ("dream_without_money",),
    "interests": ("interests", "intended_majors"),
    "strengths": ("strengths",),
    "favorite_subjects": ("favorite_subjects",),
    "activities": ("activities",),
    "work_values": ("work_values",),
    "academics": ("gpa", "sat", "act"),
    "money": ("income_bracket",),
    "location": ("home_state",),
    "size_setting": ("size_pref", "setting_pref"),
    "priorities": ("priorities",),
}

REGION_VOCAB = frozenset(
    {
        "northeast",
        "midwest",
        "south",
        "west",
        "new_england",
        "mid_atlantic",
        "east_north_central",
        "west_north_central",
        "south_atlantic",
        "east_south_central",
        "west_south_central",
        "mountain",
        "pacific",
        "out_of_state",
    }
)

US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
    "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split()
)


def _known(f: ProfileField[Any]) -> bool:
    return f.known and f.confidence > 0


def compact_profile(profile: StudentProfile) -> dict[str, Any]:
    """Known fields only, as {field: {"value", "confidence"}} (no evidence quotes)."""
    out: dict[str, Any] = {}
    for name in StudentProfile.model_fields:
        f: ProfileField[Any] = getattr(profile, name)
        if _known(f):
            dumped = f.model_dump(mode="json", exclude={"evidence"})
            out[name] = {"value": dumped["value"], "confidence": round(f.confidence, 2)}
    return out


def profile_json(profile: StudentProfile) -> str:
    """Deterministic JSON (stable key order) so prompts — and cassette keys — are stable."""
    return json.dumps(compact_profile(profile), sort_keys=True, ensure_ascii=False)


READINESS_FIRST: tuple[NextTopic, ...] = ("dream_without_money", "interests", "location", "money")


def plan_next_topic(profile: StudentProfile) -> NextTopic:
    """Next uncovered topic: the dream question and interests first, then the topics
    recommendations need (location, money), then the rest in intake order;
    ``ready_to_recommend`` when everything is covered."""
    order = list(READINESS_FIRST) + [t for t in TOPIC_FIELDS if t not in READINESS_FIRST]
    for topic in order:
        if not any(_known(getattr(profile, f)) for f in TOPIC_FIELDS[topic]):
            return topic
    return "ready_to_recommend"


def render_transcript(turns: list[HistoryTurn]) -> str:
    who = {"user": "student", "assistant": "counselor"}
    return "\n".join(f"{who[t.role]}: {t.text}" for t in turns)
