"""Retriever: Stage A (majors) → Stage B (SQL filters) → Stage C (rerank), SPEC §9/§10.

Modes (the §10 ablation):

``sql_only``
    No vectors. Majors come only from fuzzy-matching ``intended_majors`` to CIP titles;
    with no intended majors every school is a candidate (``cip4 = None``). Ordered by
    ``0.5·affordability + 0.5·admission_fit`` (this heuristic is reported as ``total``).
``hybrid``
    Vector majors ∪ intended majors, SQL filters, ordered by the Stage A similarity of
    each school's best-matching CIP (ties: larger program first, then unitid).
    ``total`` = ``major_fit``.
``hybrid_rerank``
    Full Stage C weighted score (see ``rerank``), then band balancing over the top
    ``max(pool, 2k)`` schools when the student gave GPA/SAT/ACT.
``hybrid_riasec_rerank``
    Tier 2; not implemented yet.

Every mode returns at most one program per school. If location filters (regions /
max distance) leave fewer than ``k`` schools they are relaxed — distance first, then
regions — and recorded in ``last_trace["relaxed"]``. The budget filter is never relaxed.
If Stage A finds no majors (no interests, no intended majors) every mode falls back to
"any major" (``cip4 = None``) and ``last_trace["stage_a_fallback"]`` is true.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import TurnLogger
from app.retrieval import major_match, rerank, sql_filters
from app.retrieval.major_match import CipScore, Embedder
from app.retrieval.rerank import Scored
from app.retrieval.sql_filters import CandidateRow, FilterOptions
from app.schemas import Candidate, IncomeBracket, RetrievalMode, ScoreBreakdown, StudentProfile

STAGE_A_K = 8

# Location relaxation order (criteria H3): distance first, then regions.
RELAX_STEPS: tuple[tuple[str, FilterOptions], ...] = (
    ("distance", FilterOptions(apply_distance=False)),
    ("regions", FilterOptions(apply_distance=False, apply_regions=False)),
)


def _filter_active(profile: StudentProfile, step: str) -> bool:
    if step == "distance":
        return profile.max_distance_miles.value is not None and bool(profile.home_state.value)
    return bool(profile.regions.value)


def facts_for(
    row: CandidateRow, bracket: IncomeBracket | None, home_state: str | None = None
) -> dict[str, Any]:
    """ClaimField → DB value for a candidate (the only numbers the LLM may cite).

    ``net_price`` is ``pricing.student_net_price`` (out-of-state estimate at public
    schools outside ``home_state``); ``net_price_basis`` says which rule applied.
    """

    def rng(lo: int | None, hi: int | None) -> str | None:
        return f"{lo}-{hi}" if lo is not None and hi is not None else None

    net_price, basis = row.student_price(bracket, home_state)
    return {
        "net_price": net_price,
        "net_price_basis": basis,
        "admission_rate": row.admission_rate,
        "sat_range": rng(row.sat_25, row.sat_75),
        "act_range": rng(row.act_25, row.act_75),
        "completion_rate": row.completion_rate,
        "program_median_earnings": row.program_median_earnings,
        "program_median_debt": row.program_median_debt,
        "median_earnings_10yr": row.median_earnings_10yr,
        "median_debt": row.median_debt,
        "undergrad_size": row.undergrad_size,
        "city_state": f"{row.city}, {row.state}",
    }


def _with_total(s: Scored, total: float) -> Scored:
    data = s.scores.model_dump()
    data["total"] = round(max(0.0, min(1.0, total)), 4)
    s.scores = ScoreBreakdown(**data)
    return s


class Retriever:
    def __init__(self, embedder: Embedder | None = None, logger: TurnLogger | None = None):
        self.embedder = embedder
        self.logger = logger
        self.last_trace: dict[str, Any] = {}

    async def retrieve(
        self,
        session: AsyncSession,
        profile: StudentProfile,
        k: int = 10,
        mode: RetrievalMode = "hybrid_rerank",
        pool: int = 40,
        *,
        logger: TurnLogger | None = None,
    ) -> list[Candidate]:
        if mode == "hybrid_riasec_rerank":
            raise NotImplementedError("RIASEC path is tier 2")
        if mode not in ("sql_only", "hybrid", "hybrid_rerank"):
            raise ValueError(f"unknown retrieval mode {mode!r}")
        tl = logger or self.logger or TurnLogger()
        trace: dict[str, Any] = {"mode": mode, "k": k, "pool": pool}
        self.last_trace = trace

        # ---- Stage A
        with tl.stage("retrieve.major_match", mode=mode) as st:
            cips: list[CipScore]
            if mode == "sql_only":
                cips = await major_match.by_intended_majors(session, profile)
            else:
                if self.embedder is None:
                    raise ValueError(f"mode {mode!r} needs an embedder")
                cips = await major_match.by_embedding(session, self.embedder, profile, STAGE_A_K)
            st.set(n_cips=len(cips))
        trace["cips"] = [
            {"cip4": c.cip4, "title": c.title, "similarity": c.similarity, "source": c.source}
            for c in cips
        ]
        cip_codes: list[str] | None = [c.cip4 for c in cips]
        trace["stage_a_fallback"] = not cips
        if not cips:
            cip_codes = None  # no interest/major signal: every school is a candidate
        cip_sims = {c.cip4: c.similarity for c in cips}

        # ---- Stage B
        with tl.stage("retrieve.sql_filter") as st:
            relaxed: list[str] = []
            rows = await sql_filters.candidates(session, profile, cip_codes)
            for step, opts in RELAX_STEPS:
                if len({r.unitid for r in rows}) >= k or not _filter_active(profile, step):
                    continue
                rows = await sql_filters.candidates(session, profile, cip_codes, opts)
                relaxed.append(step)
            median = await sql_filters.bracket_median(session, profile.income_bracket.value)
            st.set(n_rows=len(rows), n_schools=len({r.unitid for r in rows}), relaxed=relaxed)
        trace.update(
            n_rows=len(rows),
            location_relaxed=bool(relaxed),
            relaxed=relaxed,
            bracket_median=median,
        )

        # ---- Stage C
        with tl.stage("retrieve.rerank", mode=mode) as st:
            scored = rerank.score_rows(rows, profile, cip_sims, median)
            final = self._order(scored, profile, k, pool, mode)
            st.set(n_out=len(final))
        trace["unitids"] = [s.row.unitid for s in final]

        bracket = profile.income_bracket.value
        return [
            Candidate(
                unitid=s.row.unitid,
                name=s.row.name,
                city=s.row.city,
                state=s.row.state,
                cip4=s.row.cip4,
                cip_title=s.row.cip_title,
                admission_band=s.admission.band,
                band_confidence=s.admission.confidence,
                scores=s.scores,
                facts=facts_for(s.row, bracket, profile.home_state.value),
            )
            for s in final
        ]

    @staticmethod
    def _order(
        scored: list[Scored], profile: StudentProfile, k: int, pool: int, mode: RetrievalMode
    ) -> list[Scored]:
        if mode == "sql_only":
            for s in scored:
                _with_total(s, 0.5 * s.scores.affordability + 0.5 * s.scores.admission_fit)
            return rerank.best_per_school(scored)[:k]
        if mode == "hybrid":
            best: dict[int, Scored] = {}

            def key(s: Scored) -> tuple[float, int, int, str]:
                return (
                    -s.similarity,
                    -(s.row.program_graduates or 0),
                    s.row.unitid,
                    s.row.cip4 or "",
                )

            for s in sorted(scored, key=key):
                best.setdefault(s.row.unitid, s)
            ordered = sorted(best.values(), key=key)[:k]
            return [_with_total(s, s.scores.major_fit) for s in ordered]
        ranked = rerank.best_per_school(scored)
        if not rerank.bands_known(profile):
            return ranked[:k]
        return rerank.balance_bands(ranked[: max(pool, 2 * k)], k)
