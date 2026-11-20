"""Recommendation synthesis (Opus, structured output with a per-request JSON schema).

The output schema is built for each request so that ``unitid`` (on recommendations
and claims) is an ``enum`` of the retrieved candidate IDs and ``cip4`` an enum of the
candidates' CIP codes: the model cannot name a school that was not retrieved.
``field`` is :data:`GENERATED_CLAIM_FIELDS` — the ``ClaimField`` values the LLM may
emit. ``city_state`` is excluded: location is rendered from the DB
(``RecommendationOut.city/state``), and letting the model restate it invited errors
(the live pilot saw "Providence, GA" for a Georgia student). ``ClaimField`` itself
keeps ``city_state`` so stored rows stay valid, and groundedness still checks any
``city_state`` claim it is given. Post-processing then pins each recommendation
to a real candidate (unitid, cip4) pair, copies the deterministic admission band,
de-duplicates schools, and assigns ranks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, get_args

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.llm import Effort, LLMClient, LLMOutputError
from app.core.logging import Stage, get_logger
from app.counselor.context import compact_profile
from app.counselor.prompts import load_prompt
from app.schemas import Candidate, Claim, ClaimField, Recommendation, StudentProfile

log = get_logger(__name__)

# ClaimField values the recommender must never generate (see module docstring).
NON_GENERATED_CLAIM_FIELDS: frozenset[str] = frozenset({"city_state"})
GENERATED_CLAIM_FIELDS: list[str] = [
    f for f in get_args(ClaimField) if f not in NON_GENERATED_CLAIM_FIELDS
]


def build_output_schema(candidates: list[Candidate]) -> dict[str, Any]:
    """Wire schema: no optional and no union params (structured-outputs limits).

    Claims carry only ``field`` + ``value``; their unitid/cip4 come from the parent
    recommendation in :func:`finalize`, so a claim can't be attached to another school.
    ``cip4`` uses ``""`` as the no-major sentinel instead of ``null``.
    """
    unitids = sorted({c.unitid for c in candidates})
    cips = sorted({c.cip4 or "" for c in candidates})
    claim = {
        "type": "object",
        "properties": {
            "field": {"type": "string", "enum": GENERATED_CLAIM_FIELDS},
            "value": {
                "type": "string",
                "description": "Copied from this candidate's facts, e.g. '$14,200' or '62%'.",
            },
        },
        "required": ["field", "value"],
        "additionalProperties": False,
    }
    rec = {
        "type": "object",
        "properties": {
            "unitid": {"type": "integer", "enum": unitids},
            "cip4": {"type": "string", "enum": cips},
            "reasons": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short prose reasons with no digits or numbers.",
            },
            "claims": {"type": "array", "items": claim},
        },
        "required": ["unitid", "cip4", "reasons", "claims"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"recommendations": {"type": "array", "items": rec}},
        "required": ["recommendations"],
        "additionalProperties": False,
    }


def candidate_payload(c: Candidate) -> dict[str, Any]:
    return {
        "unitid": c.unitid,
        "name": c.name,
        "city": c.city,
        "state": c.state,
        "cip4": c.cip4 or "",
        "major": c.cip_title,
        "estimated_admission_band": c.admission_band,
        "band_confidence": c.band_confidence,
        "scores": c.scores.model_dump(),
        "facts": {k: v for k, v in sorted(c.facts.items())},
    }


def build_user_message(profile: StudentProfile, candidates: list[Candidate], k: int) -> str:
    cands = json.dumps(
        [candidate_payload(c) for c in candidates], ensure_ascii=False, sort_keys=True
    )
    return (
        "<student_profile>\n"
        f"{json.dumps(compact_profile(profile), ensure_ascii=False, sort_keys=True)}\n"
        "</student_profile>\n\n"
        "<candidates>\n"
        f"{cands}\n"
        "</candidates>\n\n"
        f"Choose the best {k} recommendations from the candidates, best first."
    )


class _WireClaim(BaseModel):
    field: ClaimField
    value: str


class _WireRec(BaseModel):
    unitid: int
    cip4: str
    reasons: list[str]
    claims: list[_WireClaim]


class _WireOut(BaseModel):
    recommendations: list[_WireRec]


def finalize(raw: dict[str, Any], candidates: list[Candidate], k: int) -> list[Recommendation]:
    """Validate the wire output, pin to real candidates, copy admission band, dedupe
    schools, rank 1..n. Malformed output raises ``LLMOutputError`` (never a 500)."""
    try:
        wire = _WireOut.model_validate(raw)
    except ValidationError as exc:
        raise LLMOutputError(f"recommendation output failed validation: {exc}") from exc
    by_pair = {(c.unitid, c.cip4): c for c in candidates}
    best_by_unitid: dict[int, Candidate] = {}
    for c in sorted(candidates, key=lambda c: c.scores.total, reverse=True):
        best_by_unitid.setdefault(c.unitid, c)

    out: list[Recommendation] = []
    seen: set[int] = set()
    for item in wire.recommendations:
        unitid = item.unitid
        if unitid in seen or unitid not in best_by_unitid:
            continue
        cand = by_pair.get((unitid, item.cip4 or None)) or best_by_unitid[unitid]
        claims = [
            Claim(unitid=cand.unitid, field=cl.field, cip4=cand.cip4, value=cl.value)
            for cl in item.claims
        ]
        out.append(
            Recommendation(
                unitid=unitid,
                cip4=cand.cip4,
                rank=len(out) + 1,
                admission_band=cand.admission_band,
                reasons=list(item.reasons),
                claims=claims,
            )
        )
        seen.add(unitid)
        if len(out) >= k:
            break
    return out


@dataclass
class Recommender:
    llm: LLMClient
    model: str = field(default_factory=lambda: get_settings().MODEL_STRONG)
    effort: Effort = "high"
    max_tokens: int = 32000

    async def synthesize(
        self,
        profile: StudentProfile,
        candidates: list[Candidate],
        k: int,
        *,
        stage: Stage | None = None,
    ) -> list[Recommendation]:
        if not candidates:
            return []
        prompt = load_prompt("recommender")
        raw = await self.llm.parse(
            self.model,
            prompt.text,
            [{"role": "user", "content": build_user_message(profile, candidates, k)}],
            build_output_schema(candidates),
            effort=self.effort,
            max_tokens=self.max_tokens,
            stage=stage,
        )
        recs = finalize(raw, candidates, k)
        if stage is not None:
            stage.set(prompt=prompt.id, n_candidates=len(candidates), n_recs=len(recs))
        return recs
