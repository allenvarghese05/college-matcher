"""Shared contracts for College Matcher v2 — the source of truth (docs/SPEC.md §6).

Every agent builds against these types. Change them only through the orchestrator.

Design rules
------------
* Every profile field carries value + confidence + evidence (the student's own words).
* ``ProfileDelta`` is the INTERNAL extraction result. It is NOT sent to Claude as a
  structured-output schema: its 20 nullable fields exceed the structured-outputs
  complexity limits (max 16 union-typed params). The extractor uses its own flat
  wire schema and converts to ``ProfileDelta`` locally.
* Recommendation prose (``reasons``) contains no numbers; every number shown to a
  student is a ``Claim`` that the groundedness checker verifies against Postgres.

HTTP API (FastAPI, prefix ``/api``)
-----------------------------------
POST   /api/sessions                        SessionCreate        -> SessionOut
GET    /api/sessions/{id}                                         -> SessionState
POST   /api/sessions/{id}/turns             TurnIn               -> text/event-stream of TurnEvent
POST   /api/sessions/{id}/recommendations   RecommendRequest     -> RecommendationSet
POST   /api/sessions/{id}/resume            multipart PDF        -> StudentProfile
WS     /api/sessions/{id}/voice             (phase 6; see SPEC §11)
GET    /health                                                    -> {"status", "db"}

TurnEvent (SSE ``event:`` name -> ``data:`` JSON):
  token   {"text": str}                       streamed assistant text
  profile {"profile": StudentProfile}         after extraction merges
  ready   {"ready": bool, "missing": [str]}   recommendation readiness
  done    {"turn_id": str, "assistant_text": str}
  error   {"message": str}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# --------------------------------------------------------------------------- enums

IncomeBracket = Literal["0-30k", "30-48k", "48-75k", "75-110k", "110k+"]
EvidenceSource = Literal["chat", "voice", "resume", "quiz"]
SizePref = Literal["small", "medium", "large", "any"]
SettingPref = Literal["city", "suburb", "town", "rural", "any"]
Priority = Literal["cost", "outcomes", "prestige", "location", "fit"]
WorkValue = Literal[
    "achievement", "independence", "recognition", "relationships", "support", "working_conditions"
]
AdmissionBand = Literal["safety", "target", "reach", "unknown"]
BandConfidence = Literal["normal", "low"]
SessionMode = Literal["text", "voice"]
RetrievalMode = Literal["sql_only", "hybrid", "hybrid_rerank", "hybrid_riasec_rerank"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------ profile


class Evidence(_Strict):
    quote: str = Field(description="The student's exact words supporting this value.")
    turn_idx: int
    source: EvidenceSource


class ProfileField[T](_Strict):
    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)

    @property
    def known(self) -> bool:
        return self.value is not None and self.value != [] and self.value != ""


class Activity(_Strict):
    name: str
    role: str | None = None
    years: float | None = None
    hours_per_week: float | None = None


class Riasec(_Strict):
    """Holland interest profile, each dimension 0..1."""

    R: float = Field(ge=0, le=1)
    I: float = Field(ge=0, le=1)  # noqa: E741 - Holland's letter
    A: float = Field(ge=0, le=1)
    S: float = Field(ge=0, le=1)
    E: float = Field(ge=0, le=1)
    C: float = Field(ge=0, le=1)


def _f() -> Any:
    return Field(default_factory=ProfileField)


class StudentProfile(_Strict):
    # identity & location
    home_state: ProfileField[str] = _f()  # USPS code, e.g. "OH"
    home_zip: ProfileField[str] = _f()
    # academics (self-reported, trusted)
    gpa: ProfileField[float] = _f()  # unweighted 0-4
    sat: ProfileField[int] = _f()  # composite 400-1600
    act: ProfileField[int] = _f()  # composite 1-36
    # money
    income_bracket: ProfileField[IncomeBracket] = _f()
    budget_cap: ProfileField[int] = _f()  # $/year the family can pay
    # interests & direction
    interests: ProfileField[list[str]] = _f()
    dream_without_money: ProfileField[str] = _f()
    intended_majors: ProfileField[list[str]] = _f()
    riasec: ProfileField[Riasec] = _f()
    strengths: ProfileField[list[str]] = _f()
    favorite_subjects: ProfileField[list[str]] = _f()
    activities: ProfileField[list[Activity]] = _f()
    work_values: ProfileField[list[WorkValue]] = _f()
    # fit preferences
    max_distance_miles: ProfileField[int] = _f()
    regions: ProfileField[list[str]] = _f()
    size_pref: ProfileField[SizePref] = _f()
    setting_pref: ProfileField[SettingPref] = _f()
    priorities: ProfileField[list[Priority]] = _f()

    READY_MIN_CONFIDENCE: ClassVar[float] = 0.6

    def missing_for_recommendation(self) -> list[str]:
        """SPEC §8 readiness: home_state + income_bracket + (interests or intended_majors)."""
        ok = lambda f: f.known and f.confidence >= self.READY_MIN_CONFIDENCE  # noqa: E731
        missing: list[str] = []
        if not ok(self.home_state):
            missing.append("home_state")
        if not ok(self.income_bracket):
            missing.append("income_bracket")
        if not (ok(self.interests) or ok(self.intended_majors)):
            missing.append("interests")
        return missing

    def is_ready(self) -> bool:
        return not self.missing_for_recommendation()


StudentProfile.model_rebuild()

PROFILE_FIELDS: tuple[str, ...] = tuple(StudentProfile.model_fields)

# ----------------------------------------------------------------- extraction


class Update[T](_Strict):
    value: T
    confidence: float = Field(ge=0.0, le=1.0)
    quote: str = Field(description="Exact words from the latest student message (or resume).")


class ProfileDelta(_Strict):
    """Only fields changed by this turn are non-null. Mirrors StudentProfile field names."""

    home_state: Update[str] | None = None
    home_zip: Update[str] | None = None
    gpa: Update[float] | None = None
    sat: Update[int] | None = None
    act: Update[int] | None = None
    income_bracket: Update[IncomeBracket] | None = None
    budget_cap: Update[int] | None = None
    interests: Update[list[str]] | None = None
    dream_without_money: Update[str] | None = None
    intended_majors: Update[list[str]] | None = None
    riasec: Update[Riasec] | None = None
    strengths: Update[list[str]] | None = None
    favorite_subjects: Update[list[str]] | None = None
    activities: Update[list[Activity]] | None = None
    work_values: Update[list[WorkValue]] | None = None
    max_distance_miles: Update[int] | None = None
    regions: Update[list[str]] | None = None
    size_pref: Update[SizePref] | None = None
    setting_pref: Update[SettingPref] | None = None
    priorities: Update[list[Priority]] | None = None


NextTopic = Literal[
    "dream_without_money",
    "interests",
    "strengths",
    "favorite_subjects",
    "activities",
    "work_values",
    "academics",
    "money",
    "location",
    "size_setting",
    "priorities",
    "ready_to_recommend",
]


class ExtractionResult(_Strict):
    delta: ProfileDelta
    next_topic: NextTopic


LIST_FIELDS = frozenset(
    {
        "interests",
        "intended_majors",
        "strengths",
        "favorite_subjects",
        "activities",
        "work_values",
        "regions",
        "priorities",
    }
)


def apply_delta(
    profile: StudentProfile, delta: ProfileDelta, turn_idx: int, source: EvidenceSource
) -> StudentProfile:
    """Merge an extraction delta into a profile (pure; returns a new profile).

    Scalars: replaced when the update's confidence >= current confidence, or when the
    student clearly corrected themselves (the extractor signals that with confidence >= 0.8).
    Lists: union, order-preserving, de-duplicated case-insensitively for strings.
    Evidence is always appended.
    """
    data = profile.model_copy(deep=True)
    for name in ProfileDelta.model_fields:
        upd: Update | None = getattr(delta, name)
        if upd is None:
            continue
        current: ProfileField = getattr(data, name)
        ev = Evidence(quote=upd.quote, turn_idx=turn_idx, source=source)
        if name in LIST_FIELDS:
            merged = list(current.value or [])
            seen = {_key(x) for x in merged}
            for item in upd.value:
                if _key(item) not in seen:
                    merged.append(item)
                    seen.add(_key(item))
            current.value = merged
            current.confidence = max(current.confidence, upd.confidence)
        elif upd.confidence >= current.confidence or upd.confidence >= 0.8:
            current.value = upd.value
            current.confidence = upd.confidence
        current.evidence.append(ev)
    return data


def _key(x: object) -> object:
    if isinstance(x, str):
        return x.strip().lower()
    if isinstance(x, BaseModel):
        return x.model_dump_json()
    return x


# ------------------------------------------------------------- retrieval / recs


class ScoreBreakdown(_Strict):
    """Each component 0..1; total is the weighted sum used for ranking (SPEC §9)."""

    major_fit: float = Field(ge=0, le=1)
    affordability: float = Field(ge=0, le=1)
    outcomes: float = Field(ge=0, le=1)
    admission_fit: float = Field(ge=0, le=1)
    preferences: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)


class Candidate(_Strict):
    """Retriever output: one school x major, with the DB facts the recommender may cite."""

    unitid: int
    name: str
    city: str
    state: str
    cip4: str | None
    cip_title: str | None
    admission_band: AdmissionBand
    band_confidence: BandConfidence
    scores: ScoreBreakdown
    facts: dict[str, float | int | str | None] = Field(
        description="ClaimField -> DB value for this candidate; the only numbers the LLM may use."
    )


ClaimField = Literal[
    "net_price",  # at the student's income bracket
    "admission_rate",
    "sat_range",  # "1200-1400"
    "act_range",
    "completion_rate",
    "program_median_earnings",  # EARN_MDN_4YR for (unitid, cip4)
    "program_median_debt",
    "median_earnings_10yr",  # school-wide
    "median_debt",  # school-wide
    "undergrad_size",
    "city_state",
]


class Claim(_Strict):
    unitid: int
    field: ClaimField
    cip4: str | None = None
    value: str = Field(description="Value as shown to the student, e.g. '$14,200' or '62%'.")


class Recommendation(_Strict):
    unitid: int
    cip4: str | None
    rank: int
    admission_band: AdmissionBand
    reasons: list[str] = Field(description="Short prose reasons. Must not contain numbers.")
    claims: list[Claim]


class VerifiedClaim(Claim):
    verified: bool
    db_value: str | None = None


class RecommendationOut(_Strict):
    """What the web app renders for one school."""

    unitid: int
    name: str
    city: str
    state: str
    cip4: str | None
    cip_title: str | None
    rank: int
    admission_band: AdmissionBand
    band_confidence: BandConfidence
    scores: ScoreBreakdown
    reasons: list[str]
    claims: list[VerifiedClaim]


class RecommendationSet(_Strict):
    id: UUID
    session_id: UUID
    retrieval_mode: RetrievalMode
    recommendations: list[RecommendationOut]
    groundedness: float = Field(ge=0, le=1, description="verified claims / all claims")
    created_at: datetime


# ---------------------------------------------------------------------- API I/O


class SessionCreate(_Strict):
    mode: SessionMode = "text"


class SessionOut(_Strict):
    id: UUID
    mode: SessionMode
    created_at: datetime


class TurnIn(_Strict):
    text: str = Field(min_length=1, max_length=4000)


class TurnOut(_Strict):
    idx: int
    role: Literal["user", "assistant"]
    text: str
    interrupted: bool = False
    at: datetime


class SessionState(_Strict):
    session: SessionOut
    profile: StudentProfile
    turns: list[TurnOut]
    ready: bool
    missing: list[str]


class RecommendRequest(_Strict):
    mode: RetrievalMode = "hybrid_rerank"
    k: int = Field(default=10, ge=1, le=25)


# ---------------------------------------------------------------- observability


class TurnMetric(_Strict):
    stage: str  # e.g. "extract", "reply_ttft", "reply_total", "retrieve", "recommend", "stt_final"
    ms: float
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
