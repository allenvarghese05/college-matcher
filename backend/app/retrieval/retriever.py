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

Every mode returns at most one program per school, and may return fewer than ``k``.

Too few results (SPEC §9 "Relaxation policy"): the student's stated distance and regions
are never relaxed. If the hard filters leave fewer than ``MIN_RESULTS`` schools and the
student stated a ``budget_cap``, ONE step is taken: the cap is replaced by the bracket
default ceiling (``sql_filters.budget_ceiling``), recorded as
``last_trace["relaxed"] == ["budget"]``; the recommender must disclose it. Whatever is
left is returned; ``last_trace["too_few"]`` is true when fewer than ``k`` schools came
back, and ``last_trace["filters"]`` describes the hard filters that applied (distance,
regions, budget ceiling and its source, cheapest price found).
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
MIN_RESULTS = 3  # below this many schools the result set is "thin" (one relaxation step)

BUDGET_TO_DEFAULT = FilterOptions(budget_to_default=True)


def _n_schools(rows: list[CandidateRow]) -> int:
    return len({r.unitid for r in rows})


def _can_relax_budget(profile: StudentProfile) -> bool:
    """A stated cap whose bracket default would let more schools in."""
    cap = profile.budget_cap.value
    if cap is None or profile.income_bracket.value is None:
        return False
    default, _ = sql_filters.budget_ceiling(profile, BUDGET_TO_DEFAULT)
    return default is None or default > cap * sql_filters.BUDGET_SLACK


def filters_summary(
    profile: StudentProfile, rows: list[CandidateRow], opts: FilterOptions
) -> dict[str, Any]:
    """The hard filters that applied (for the trace and the student-facing notices)."""
    ceiling, source = sql_filters.budget_ceiling(profile, opts)
    home = profile.home_state.value
    distance = profile.max_distance_miles.value if home else None
    bracket = profile.income_bracket.value
    prices = [p for r in rows if (p := r.student_price(bracket, home)[0]) is not None]
    return {
        "max_distance_miles": distance,
        "regions": None if distance is not None else (profile.regions.value or None),
        "budget_cap": profile.budget_cap.value,
        "budget_ceiling": round(ceiling) if ceiling is not None else None,
        "budget_source": source,
        "cheapest_price": min(prices) if prices else None,
    }


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
            opts = FilterOptions()
            rows = await sql_filters.candidates(session, profile, cip_codes, opts)
            if _n_schools(rows) < MIN_RESULTS and _can_relax_budget(profile):
                wider = await sql_filters.candidates(session, profile, cip_codes, BUDGET_TO_DEFAULT)
                if _n_schools(wider) > _n_schools(rows):
                    rows, opts = wider, BUDGET_TO_DEFAULT
                    relaxed.append("budget")
            median = await sql_filters.bracket_median(session, profile.income_bracket.value)
            st.set(n_rows=len(rows), n_schools=_n_schools(rows), relaxed=relaxed)
        trace.update(
            n_rows=len(rows),
            n_schools=_n_schools(rows),
            relaxed=relaxed,
            filters=filters_summary(profile, rows, opts),
            bracket_median=median,
        )

        # ---- Stage C
        with tl.stage("retrieve.rerank", mode=mode) as st:
            scored = rerank.score_rows(rows, profile, cip_sims, median)
            final = self._order(scored, profile, k, pool, mode)
            st.set(n_out=len(final))
        trace["unitids"] = [s.row.unitid for s in final]
        trace["too_few"] = len(final) < k
        trace["far_reaches"] = {
            "found": len({s.row.unitid for s in scored if s.far_reach}),
            "kept": sum(1 for s in final if s.far_reach),
        }

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
            return rerank.limit_far_reaches(ranked, k)
        return rerank.balance_bands(ranked[: max(pool, 2 * k)], k)
