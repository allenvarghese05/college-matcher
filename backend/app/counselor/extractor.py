"""Per-turn profile extractor (Sonnet, structured output).

``schemas.ProfileDelta`` is the internal contract, but its 20 nullable fields exceed the
structured-outputs complexity limits (≤ 24 optional, ≤ 16 union params). The model
therefore fills a flat WIRE schema (:class:`ExtractionWire`): a list of updates, each
naming one field and carrying the value in the typed slot for that field's kind
(``text`` / ``number`` / ``items`` / ``activities``; unused slots hold the sentinels
``""``, ``0``, ``[]``). No optional or nullable params at all. :func:`wire_to_delta`
converts locally, validating every value against ``ProfileDelta`` field by field.

Deterministic guards then drop anything the contract forbids:

* updates whose ``quote`` is not an exact span (word-bounded) of the latest message;
* ``regions`` outside the fixed vocabulary / USPS codes (full state names are mapped);
* ``home_state`` that is not a US state (full names are mapped to USPS codes);
* enum values outside their Literal (after case-insensitive normalisation).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.core.llm import Effort, LLMClient
from app.core.logging import Stage, get_logger
from app.counselor.context import (
    REGION_VOCAB,
    HistoryTurn,
    profile_json,
    render_transcript,
    to_usps,
)
from app.counselor.prompts import load_prompt
from app.schemas import (
    LIST_FIELDS,
    Activity,
    ExtractionResult,
    NextTopic,
    ProfileDelta,
    StudentProfile,
    Update,
)

log = get_logger(__name__)

# ----------------------------------------------------------------- wire schema

TEXT_FIELDS = ("home_state", "home_zip", "dream_without_money")
ENUM_TEXT_FIELDS = ("income_bracket", "size_pref", "setting_pref")
INT_FIELDS = ("sat", "act", "budget_cap", "max_distance_miles")
FLOAT_FIELDS = ("gpa",)
ITEM_FIELDS = ("interests", "intended_majors", "strengths", "favorite_subjects", "regions")
ENUM_ITEM_FIELDS = ("work_values", "priorities")
ACTIVITY_FIELDS = ("activities",)

WireField = Literal[
    "home_state",
    "home_zip",
    "gpa",
    "sat",
    "act",
    "income_bracket",
    "budget_cap",
    "interests",
    "dream_without_money",
    "intended_majors",
    "strengths",
    "favorite_subjects",
    "activities",
    "work_values",
    "max_distance_miles",
    "regions",
    "size_pref",
    "setting_pref",
    "priorities",
]


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WireActivity(_Wire):
    name: str
    role: str = Field(description='Role if stated, else "".')
    years: float = Field(description="Years if stated, else 0.")
    hours_per_week: float = Field(description="Hours per week if stated, else 0.")


class WireUpdate(_Wire):
    field: WireField
    text: str = Field(
        description="Value for home_state, home_zip, dream_without_money, income_bracket, "
        'size_pref, setting_pref; otherwise "".'
    )
    number: float = Field(
        description="Value for gpa, sat, act, budget_cap, max_distance_miles; otherwise 0."
    )
    items: list[str] = Field(
        description="Values for interests, intended_majors, strengths, favorite_subjects, "
        "regions, work_values, priorities; otherwise []."
    )
    activities: list[WireActivity] = Field(description="Values for activities; otherwise [].")
    confidence: float = Field(description="0 to 1, per the confidence rubric.")
    quote: str = Field(description="Exact words from the latest student message.")


class ExtractionWire(_Wire):
    updates: list[WireUpdate]
    next_topic: NextTopic


def _enum_norm(s: str) -> str:
    """Case-insensitive enum normalisation: 'Working Conditions' -> 'working_conditions',
    '48-75K' -> '48-75k', ' Large ' -> 'large'."""
    return re.sub(r"\s+", "_", s.strip().lower())


def _wire_value(u: WireUpdate) -> Any:
    f = u.field
    if f in TEXT_FIELDS:
        return u.text.strip() or None
    if f in ENUM_TEXT_FIELDS:
        return _enum_norm(u.text) or None
    if f in INT_FIELDS:
        return int(round(u.number)) if u.number else None
    if f in FLOAT_FIELDS:
        return u.number if u.number else None
    if f in ITEM_FIELDS:
        return [s.strip() for s in u.items if s.strip()] or None
    if f in ENUM_ITEM_FIELDS:
        return [_enum_norm(s) for s in u.items if s.strip()] or None
    if f in ACTIVITY_FIELDS:
        acts = [
            Activity(
                name=a.name.strip(),
                role=a.role.strip() or None,
                years=a.years or None,
                hours_per_week=a.hours_per_week or None,
            )
            for a in u.activities
            if a.name.strip()
        ]
        return acts or None
    return None  # pragma: no cover - WireField is exhaustive


def _validate_one(name: str, value: Any, confidence: float, quote: str) -> Update[Any] | None:
    payload = {"value": value, "confidence": min(max(confidence, 0.0), 1.0), "quote": quote}
    try:
        upd: Update[Any] | None = getattr(ProfileDelta.model_validate({name: payload}), name)
        return upd
    except ValidationError:
        return None


def wire_to_delta(wire: ExtractionWire) -> tuple[ProfileDelta, list[str]]:
    """Convert wire updates to a validated ``ProfileDelta``; returns dropped field names.

    Enum lists keep their valid items only. Repeated fields: lists are concatenated,
    scalars keep the highest-confidence update.
    """
    out: dict[str, Update[Any]] = {}
    dropped: list[str] = []
    for u in wire.updates:
        value = _wire_value(u)
        if value is None:
            dropped.append(u.field)
            continue
        upd = _validate_one(u.field, value, u.confidence, u.quote)
        if upd is None and u.field in ENUM_ITEM_FIELDS:
            valid = [
                v for v in value if _validate_one(u.field, [v], u.confidence, u.quote) is not None
            ]
            upd = _validate_one(u.field, valid, u.confidence, u.quote) if valid else None
        if upd is None:
            dropped.append(u.field)
            continue
        prev = out.get(u.field)
        if prev is not None and u.field in LIST_FIELDS:
            upd = Update(
                value=list(prev.value) + list(upd.value),
                confidence=max(prev.confidence, upd.confidence),
                quote=prev.quote,
            )
        elif prev is not None and prev.confidence > upd.confidence:
            continue
        out[u.field] = upd
    return ProfileDelta(**out), dropped


# ---------------------------------------------------------------------- guards

_DASHES = str.maketrans({"–": "-", "—": "-", "‐": "-", "‑": "-", "’": "'", "‘": "'"})


def _norm(s: str) -> str:
    s = s.translate(_DASHES).replace("“", '"').replace("”", '"').replace("…", "...")
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in(quote: str, message: str) -> bool:
    """True if ``quote`` is a word-bounded span of ``message`` (after normalisation)."""
    q = _norm(quote).strip(" .,!?;:\"'")
    if not q:
        return False
    return re.search(rf"(?<!\w){re.escape(q)}(?!\w)", _norm(message)) is not None


def build_user_message(profile: StudentProfile, context: list[HistoryTurn], latest: str) -> str:
    return (
        "<current_profile>\n"
        f"{profile_json(profile)}\n"
        "</current_profile>\n\n"
        "<recent_conversation>\n"
        f"{render_transcript(context) or '(start of conversation)'}\n"
        "</recent_conversation>\n\n"
        "<latest_student_message>\n"
        f"{latest}\n"
        "</latest_student_message>\n\n"
        "Extract only what the latest student message states, then choose next_topic."
    )


def sanitize(delta: ProfileDelta, latest: str) -> tuple[ProfileDelta, list[str]]:
    """Return a cleaned delta and the names of dropped fields (for metrics/logs)."""
    data = delta.model_copy(deep=True)
    dropped: list[str] = []
    for name in ProfileDelta.model_fields:
        upd: Update[Any] | None = getattr(data, name)
        if upd is None:
            continue
        if name == "riasec" or not quote_in(upd.quote, latest):
            setattr(data, name, None)
            dropped.append(name)
            continue
        if name == "regions":
            kept: list[str] = []
            for r in upd.value:
                low = r.strip().lower().replace(" ", "_").replace("-", "_")
                code = to_usps(r)
                if low in REGION_VOCAB:
                    kept.append(low)
                elif code is not None:
                    kept.append(code)
            if kept:
                upd.value = list(dict.fromkeys(kept))
            else:
                setattr(data, name, None)
                dropped.append(name)
        elif name == "home_state":
            code = to_usps(upd.value)
            if code is not None:
                upd.value = code
            else:
                setattr(data, name, None)
                dropped.append(name)
    return data, dropped


@dataclass
class Extractor:
    llm: LLMClient
    model: str = field(default_factory=lambda: get_settings().MODEL_FAST)
    effort: Effort = "medium"
    max_tokens: int = 16000
    context_turns: int = 6

    async def extract(
        self,
        history: list[HistoryTurn],
        latest: str,
        profile: StudentProfile,
        *,
        stage: Stage | None = None,
    ) -> ExtractionResult:
        """``history`` = turns before the latest student message (oldest first)."""
        context = history[-self.context_turns :]
        prompt = load_prompt("extractor")
        wire = await self.llm.parse(
            self.model,
            prompt.text,
            [{"role": "user", "content": build_user_message(profile, context, latest)}],
            ExtractionWire,
            effort=self.effort,
            max_tokens=self.max_tokens,
            stage=stage,
        )
        delta, invalid = wire_to_delta(wire)
        delta, dropped = sanitize(delta, latest)
        dropped = invalid + dropped
        if stage is not None:
            stage.set(prompt=prompt.id, dropped_fields=dropped, next_topic=wire.next_topic)
        if dropped:
            log.info("extract_dropped_fields", fields=dropped)
        return ExtractionResult(delta=delta, next_topic=wire.next_topic)
