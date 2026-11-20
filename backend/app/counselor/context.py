"""Deterministic helpers shared by the counselor prompts: profile rendering and topics."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
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


STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "washington dc": "DC", "washington d.c.": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "puerto rico": "PR",
}  # fmt: skip


def to_usps(text: str) -> str | None:
    """'oh' / 'Ohio' / ' new york ' -> USPS code; None if not a US state."""
    s = " ".join(text.strip().split())
    if len(s) == 2 and s.upper() in US_STATES:
        return s.upper()
    return STATE_NAMES.get(s.lower())


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


# ------------------------------------------------------------- topic planner
#
# Two checklists (SPEC §8):
#
# * **Readiness** (``StudentProfile.missing_for_recommendation``): home state, income
#   bracket, interests. Gates the "see my matches" button; unchanged here.
# * **Recommendation quality**: before the counselor *offers* matches on its own it must
#   have ASKED (not necessarily got answers to) location preference (distance or
#   regions), campus size/setting, and what matters most (priorities). "Asked" means
#   the planner steered the counselor to that topic on an earlier turn (the persisted
#   ``profile_snapshot.next_topic`` history), so a student who says "no preference" or
#   declines is never asked again. A student who explicitly asks for matches in the
#   CURRENT message skips the checklist for that turn only (no persisted waiver).
#
# Planner keys are NextTopic values plus ``location_pref`` (internal): the "location"
# topic asks for the home state until it is known and for distance/regions after that.

LOCATION_PREF = "location_pref"

# Readiness topic -> the missing_for_recommendation() entry it resolves.
READINESS_TOPICS: dict[str, str] = {
    "interests": "interests",
    "location": "home_state",
    "money": "income_bracket",
}
# Recommendation-quality checklist, in the order it is asked.
QUALITY_CHECKLIST: tuple[str, ...] = (LOCATION_PREF, "size_setting", "priorities")
QUALITY_FIELDS: dict[str, tuple[str, ...]] = {
    LOCATION_PREF: ("regions", "max_distance_miles"),
    "size_setting": ("size_pref", "setting_pref"),
    "priorities": ("priorities",),
}
# Core intake, asked before matches are offered: the dream question and interests,
# home state, the quality checklist, then money (which follows naturally from
# "what matters most" and completes readiness last).
CORE_ORDER: tuple[str, ...] = (
    "dream_without_money",
    "interests",
    "location",
    *QUALITY_CHECKLIST,
    "money",
)
# A missing readiness topic is asked at most this many times in all (1 + 2 re-asks).
MAX_READINESS_ASKS = 3
# Enrichment topics: asked once each after matches have been offered.
ENRICH_ORDER: tuple[NextTopic, ...] = (
    "academics",
    "strengths",
    "favorite_subjects",
    "activities",
    "work_values",
)

# Explicit match requests: a NARROW allow-list (SPEC §8). False negatives are cheap (the
# "Show my matches" button is always there); false positives skip the checklist.
# Each pattern must reach the end of its clause, so the noun is the immediate object
# ("show me how to pick schools later" and "which colleges would my brother like" fail).
_TAIL = r"(?:\s+(?:please|now|already|then))*\s*$"
_SHOW_DET = r"(?:(?:my|the|some|a few|any|the list of)\s+)?"
_SHOW_NOUN = r"(?:schools?|colleges?|match(?:es)?|recommendations?|lists?|options?)"
_MATCH_ALLOW = [
    re.compile(p, re.I)
    for p in (
        rf"\bshow me\s+{_SHOW_DET}{_SHOW_NOUN}{_TAIL}",
        rf"\bshow me my options for (?:schools|colleges){_TAIL}",
        rf"\b(?:can|could|may) i (?:see|get|have) (?:my|the) "
        rf"(?:matches|list|recommendations|results){_TAIL}",
        rf"\b(?:what|which) are my (?:matches|recommendations){_TAIL}",
        rf"\b(?:what|which) (?:schools|colleges) (?:would|should|could) "
        rf"(?:fit|suit|work for) me{_TAIL}",
        rf"\b(?:i'?m|i am) ready (?:to see|for) (?:my |the )?"
        rf"(?:matches|schools|colleges|list){_TAIL}",
        rf"\bgive me (?:my|some|a few|the) "
        rf"(?:schools|colleges|matches|recommendations|list){_TAIL}",
        rf"\b(?:can|could) you recommend (?:(?:some|a few) )?(?:schools|colleges){_TAIL}",
    )
]
# Only right after the counselor offered matches: "ok show me", "sure, let's see them".
_AFFIRM = re.compile(
    r"^(?:(?:ok|okay|sure|yes|yeah|yep|yup)\s*)?(?:please\s+)?"
    r"(?:show me|let'?s see(?: them)?|go ahead)(?:\s+(?:please|now))?$",
    re.I,
)
# A clause with a negation or a past-tense/visit verb is never a request.
_MATCH_BLOCK = re.compile(
    r"\b(don'?t|do\s+not|doesn'?t|not|no|never|isn'?t|aren'?t|won'?t|wouldn'?t|"
    r"can'?t|cannot|went|visited|saw|showed|toured|last\s+(week|year|month|time))\b",
    re.I,
)
_CLAUSES = re.compile(r"[.?!;,]+|\bbut\b", re.I)


def _norm_clause(text: str) -> str:
    return " ".join(text.replace("\u2019", "'").split()).strip()


def wants_matches(text: str, *, previous_offer: bool = False) -> bool:
    """True when the CURRENT student message explicitly asks to see their matches.

    Narrow allow-list per clause (``_MATCH_ALLOW``), with no negation or past-tense /
    visit word in the clause. ``previous_offer`` (the counselor's last reply offered
    matches) additionally accepts a bare affirmation: "ok show me", "sure, let's see
    them", "go ahead".
    """
    if previous_offer:
        whole = _norm_clause(re.sub(r"[.?!,;]+", " ", text or ""))
        if _AFFIRM.search(whole):
            return True
    for raw in _CLAUSES.split(text or ""):
        clause = _norm_clause(raw)
        if not clause or _MATCH_BLOCK.search(clause):
            continue
        if any(p.search(clause) for p in _MATCH_ALLOW):
            return True
    return False


def home_state_known(profile: StudentProfile) -> bool:
    """Home state known well enough for readiness (same threshold)."""
    return "home_state" not in profile.missing_for_recommendation()


def topic_key(topic: str | None, home_state_known: bool) -> str | None:
    """Planner key for a persisted hint: "location" asked once the home state was known
    is the location-preference question."""
    if topic == "location" and home_state_known:
        return LOCATION_PREF
    return topic


def asked_from_history(history: Sequence[tuple[StudentProfile, str | None]]) -> list[str]:
    """Planner keys of earlier hints, oldest first.

    ``history`` = (profile the hint was planned from, hint) per turn — i.e. each
    snapshot's ``next_topic`` paired with the *previous* snapshot's profile.
    """
    out: list[str] = []
    for profile, hint in history:
        key = topic_key(hint, home_state_known(profile))
        if key:
            out.append(key)
    return out


def _covered(profile: StudentProfile, key: str, missing: list[str]) -> bool:
    if key in READINESS_TOPICS:
        return READINESS_TOPICS[key] not in missing
    fields = QUALITY_FIELDS.get(key) or TOPIC_FIELDS[key]  # type: ignore[index]
    return any(_known(getattr(profile, f)) for f in fields)


def _as_topic(key: str) -> NextTopic:
    return "location" if key == LOCATION_PREF else key  # type: ignore[return-value]


def _offered_after_checklist(
    profile: StudentProfile, asked: Sequence[str], missing: list[str]
) -> bool:
    """True if some earlier ``ready_to_recommend`` was planned once every checklist item
    had been asked before it (or is covered now) — i.e. a real offer, not a waiver."""
    for i, key in enumerate(asked):
        if key != "ready_to_recommend":
            continue
        prior = set(asked[:i])
        if all(q in prior or _covered(profile, q, missing) for q in QUALITY_CHECKLIST):
            return True
    return False


def plan_next_topic(
    profile: StudentProfile,
    asked: Sequence[str] = (),
    *,
    student_wants_matches: bool = False,
) -> NextTopic:
    """The one topic the counselor should raise next (deterministic).

    ``asked`` = planner keys already steered to on earlier turns
    (:func:`asked_from_history`); ``student_wants_matches`` = the latest message asks
    for schools (:func:`wants_matches`).

    1. The current message asks for matches: ``ready_to_recommend`` if ready, else the
       first missing readiness topic. This applies to this turn only; nothing persisted
       waives the checklist later.
    2. Core intake in ``CORE_ORDER``; a topic is skipped once covered by the profile or
       once asked (a declined or "no preference" answer is never re-asked).
    3. Readiness still missing after everything was asked once: re-ask the first missing
       readiness topic (not the one asked on the immediately preceding turn), at most
       ``MAX_READINESS_ASKS`` asks per topic in all; past the cap, fall through to
       enrichment. Only when everything is exhausted does the first missing readiness
       topic stay the suggestion.
    4. Ready and matches not yet offered after the checklist: ``ready_to_recommend``.
       An offer made on a one-turn waiver (before the checklist was done) does not
       count, so the normal offer still comes once the checklist completes.
    5. Then enrichment topics once each, and ``ready_to_recommend`` when all are asked.
    """
    missing = profile.missing_for_recommendation()
    asked_set = set(asked)
    last = asked[-1] if asked else None
    first_missing = [t for t in READINESS_TOPICS if READINESS_TOPICS[t] in missing]

    if student_wants_matches:
        return "ready_to_recommend" if not missing else first_missing[0]  # type: ignore[return-value]

    offered = _offered_after_checklist(profile, asked, missing)
    for key in CORE_ORDER:
        if _covered(profile, key, missing) or key in asked_set:
            continue
        if key == LOCATION_PREF and "home_state" in missing:
            continue  # asked once the home state is known (else it reads as "location")
        return _as_topic(key)

    enrich = [t for t in ENRICH_ORDER if t not in asked_set and not _covered(profile, t, missing)]
    if missing:
        retry = [t for t in first_missing if t != last and asked.count(t) < MAX_READINESS_ASKS]
        if retry:
            return retry[0]  # type: ignore[return-value]
        return enrich[0] if enrich else first_missing[0]  # type: ignore[return-value]
    if not offered:
        return "ready_to_recommend"
    return enrich[0] if enrich else "ready_to_recommend"


TOPIC_GUIDANCE: dict[str, str] = {
    "dream_without_money": "ask the dream question in its exact words",
    "interests": "what they enjoy or might want to study",
    "location": "which state they live in",
    LOCATION_PREF: "how far from home they'd go, or which parts of the country they'd consider",
    "size_setting": "school size and setting (city, suburb, small town or rural)",
    "priorities": "what matters most in a college: cost, career outcomes, prestige, "
    "location or overall fit",
    "money": "roughly which household income range their family is in",
    "academics": "GPA and SAT or ACT (optional)",
    "strengths": "what they're good at",
    "favorite_subjects": "their favorite school subjects",
    "activities": "clubs, sports, jobs, volunteering or projects",
    "work_values": "what they want from work",
    "ready_to_recommend": "offer their college matches",
}


def describe_topic(topic: NextTopic, profile: StudentProfile) -> str:
    """'location (how far from home ...)' — the hint line for the reply prompt."""
    key = topic_key(topic, home_state_known(profile)) or topic
    return f"{topic} ({TOPIC_GUIDANCE[key]})"


def render_transcript(turns: list[HistoryTurn]) -> str:
    who = {"user": "student", "assistant": "counselor"}
    return "\n".join(f"{who[t.role]}: {t.text}" for t in turns)
