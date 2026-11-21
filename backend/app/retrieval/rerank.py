"""Stage C: transparent weighted rerank + band balancing (SPEC §9).

Components (each 0..1)
----------------------
``major_fit``
    Stage A similarity of the row's CIP divided by the best similarity among the
    selected CIPs (so the best-matching major scores 1.0). 0 when the row has no CIP.
``affordability``
    ``price`` = the student's net price from ``pricing.student_net_price`` (bracket price,
    + out-of-state surcharge at public schools outside the home state; fallback:
    average net price).
    With a budget cap: ``price ≤ cap`` → ``0.8 + 0.2·(1 − price/cap)``; above the cap it
    falls linearly from 0.8 to 0 at ``1.25·cap``. Without a cap: ``1 − price/(2·M)``
    clipped, where ``M`` is the national median net price at that bracket (computed
    from the data), so a median-priced school scores 0.5. Unknown price → 0.4.
``outcomes``
    Earnings percentile within the candidate set — program ``EARN_MDN_4YR`` ranked only
    against other program earnings, school-wide 10-year earnings only against other
    school-wide earnings (the two horizons are never compared). Then
    ``0.8·pct + 0.2·(1 − min(debt/earnings, 1))`` with debt from the same scope
    (``0.8·pct + 0.1`` when debt is unknown). Unknown earnings → 0.3.
``admission_fit``
    From the estimated band: target 1.0, safety 0.8, unknown 0.6, reach 0.5. With the
    ``prestige`` priority it is blended 50/50 with selectivity ``1 − admission_rate``.
``preferences``
    Mean of the sub-scores that apply: distance ``1 − d/max_distance`` (or
    ``1 − d/1000`` with the ``location`` priority and no max distance); region match
    (1/0, when ``regions`` are given but not enforced as a hard filter); size match
    (small < 2k, medium 2k–15k, large > 15k: exact 1, adjacent 0.5, opposite 0);
    setting match from ``LOCALE`` (11–13 city, 21–23 suburb, 31–33 town, 41–43 rural:
    exact 1, adjacent 0.5, else 0). Neutral 0.5 when nothing applies.

Weights
-------
Base weights, plus a boost for each stated priority, then renormalised to sum to 1:

=================  =====  ====  ========  ========  ========  ===
component          base   cost  outcomes  prestige  location  fit
=================  =====  ====  ========  ========  ========  ===
major_fit          0.30                                       +.10
affordability      0.20   +.15
outcomes           0.20         +.15      +.05
admission_fit      0.15                   +.10
preferences        0.15                             +.15      +.05
=================  =====  ====  ========  ========  ========  ===

``total`` = Σ weight·component (0..1).

Band balancing
--------------
When the student gave GPA/SAT/ACT (bands are known), the final top-k keeps one program
per school and aims for ~20–30% safety, 40–50% target, 20–30% reach (k=10: 2–3 safety,
4–5 target, 2–3 reach): first the top ``min`` of each band are reserved, then slots
fill in score order up to each band's ``max``, then (if still short) by score alone.
The final list is sorted by total score.

Far reaches (``admission.is_far_reach``) never take a slot in those passes: they only
fill slots that would otherwise stay empty, at most ``max(1, floor(0.1·k + 0.5))`` of them
(1 in a top 10). The same cap applies when bands are unknown (no student stats; then
only schools admitting < 15% are far). Fewer than ``k`` results is acceptable.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.retrieval.admission import AdmissionEstimate, estimate_for, is_far_reach
from app.retrieval.sql_filters import CandidateRow, wants_out_of_state
from app.schemas import AdmissionBand, Priority, ScoreBreakdown, StudentProfile

COMPONENTS = ("major_fit", "affordability", "outcomes", "admission_fit", "preferences")

BASE_WEIGHTS: dict[str, float] = {
    "major_fit": 0.30,
    "affordability": 0.20,
    "outcomes": 0.20,
    "admission_fit": 0.15,
    "preferences": 0.15,
}

PRIORITY_BOOSTS: dict[str, dict[str, float]] = {
    "cost": {"affordability": 0.15},
    "outcomes": {"outcomes": 0.15},
    "prestige": {"outcomes": 0.05, "admission_fit": 0.10},
    "location": {"preferences": 0.15},
    "fit": {"major_fit": 0.10, "preferences": 0.05},
}

BAND_VALUE: dict[str, float] = {"target": 1.0, "safety": 0.8, "unknown": 0.6, "reach": 0.5}

UNKNOWN_PRICE = 0.4
UNKNOWN_OUTCOMES = 0.3
NEUTRAL_PREF = 0.5

SIZE_ORDER = ("small", "medium", "large")
SETTING_ORDER = ("city", "suburb", "town", "rural")


def weights_for(priorities: Iterable[Priority] | None) -> dict[str, float]:
    w = dict(BASE_WEIGHTS)
    for p in set(priorities or []):
        for comp, boost in PRIORITY_BOOSTS.get(p, {}).items():
            w[comp] += boost
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


# ------------------------------------------------------------------ components


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def affordability(price: float | None, cap: float | None, median: float | None) -> float:
    if price is None:
        return UNKNOWN_PRICE
    if cap is not None and cap > 0:
        if price <= cap:
            return _clip(0.8 + 0.2 * (1 - price / cap))
        return _clip(0.8 * (1 - (price - cap) / (0.25 * cap)))
    if median is not None and median > 0:
        return _clip(1 - price / (2 * median))
    return UNKNOWN_PRICE


def _percentiles(values: list[float]) -> dict[float, float]:
    """Mid-rank percentile (0..1) for each distinct value."""
    n = len(values)
    if n == 0:
        return {}
    if n == 1:
        return {values[0]: 0.5}
    s = sorted(values)
    out: dict[float, float] = {}
    for v in set(s):
        below = bisect.bisect_left(s, v)
        ties = bisect.bisect_right(s, v) - below
        out[v] = (below + 0.5 * (ties - 1)) / (n - 1)
    return out


def outcome_scores(rows: list[CandidateRow]) -> list[float]:
    prog = _percentiles(
        [float(r.program_median_earnings) for r in rows if r.program_median_earnings]
    )
    school = _percentiles(
        [
            float(r.median_earnings_10yr)
            for r in rows
            if not r.program_median_earnings and r.median_earnings_10yr
        ]
    )
    out = []
    for r in rows:
        if r.program_median_earnings:
            earn, debt = r.program_median_earnings, r.program_median_debt
            pct = prog[float(earn)]
        elif r.median_earnings_10yr:
            earn, debt = r.median_earnings_10yr, r.median_debt
            pct = school[float(earn)]
        else:
            out.append(UNKNOWN_OUTCOMES)
            continue
        if debt is not None:
            out.append(_clip(0.8 * pct + 0.2 * (1 - min(debt / earn, 1.0))))
        else:
            out.append(_clip(0.8 * pct + 0.1))
    return out


def admission_fit(band: AdmissionBand, admission_rate: float | None, prestige: bool) -> float:
    v = BAND_VALUE[band]
    if prestige and admission_rate is not None:
        v = 0.5 * v + 0.5 * (1 - admission_rate)
    return _clip(v)


def size_bucket(n: int | None) -> str | None:
    if n is None:
        return None
    if n < 2000:
        return "small"
    if n <= 15000:
        return "medium"
    return "large"


def setting_bucket(locale: int | None) -> str | None:
    if locale is None:
        return None
    return {1: "city", 2: "suburb", 3: "town", 4: "rural"}.get(locale // 10)


def _ordinal_match(a: str, b: str, order: tuple[str, ...]) -> float:
    d = abs(order.index(a) - order.index(b))
    return 1.0 if d == 0 else 0.5 if d == 1 else 0.0


def preferences(row: CandidateRow, profile: StudentProfile) -> float:
    subs: list[float] = []
    d = row.distance_miles
    max_d = profile.max_distance_miles.value
    if d is not None and not wants_out_of_state(profile.regions.value):
        if max_d:
            subs.append(_clip(1 - d / max_d))
        elif "location" in (profile.priorities.value or []):
            subs.append(_clip(1 - d / 1000))
    if row.region_match is not None:
        subs.append(1.0 if row.region_match else 0.0)
    size_pref = profile.size_pref.value
    if size_pref and size_pref != "any":
        b = size_bucket(row.undergrad_size)
        if b is not None:
            subs.append(_ordinal_match(size_pref, b, SIZE_ORDER))
    setting_pref = profile.setting_pref.value
    if setting_pref and setting_pref != "any":
        s = setting_bucket(row.locale)
        if s is not None:
            subs.append(_ordinal_match(setting_pref, s, SETTING_ORDER))
    return sum(subs) / len(subs) if subs else NEUTRAL_PREF


# ------------------------------------------------------------------ scoring


@dataclass
class Scored:
    row: CandidateRow
    admission: AdmissionEstimate
    scores: ScoreBreakdown
    similarity: float = 0.0  # raw Stage A similarity of row.cip4
    extra: dict[str, float] = field(default_factory=dict)
    far_reach: bool = False


def score_rows(
    rows: list[CandidateRow],
    profile: StudentProfile,
    cip_sims: dict[str, float],
    bracket_median: float | None,
    weights: dict[str, float] | None = None,
) -> list[Scored]:
    priorities = profile.priorities.value or []
    w = weights or weights_for(priorities)
    prestige = "prestige" in priorities
    best_sim = max(cip_sims.values(), default=0.0)
    outs = outcome_scores(rows)
    bracket = profile.income_bracket.value
    cap = profile.budget_cap.value
    home = profile.home_state.value
    scored: list[Scored] = []
    for row, out in zip(rows, outs, strict=True):
        sim = cip_sims.get(row.cip4, 0.0) if row.cip4 else 0.0
        est = estimate_for(profile, row)
        comps = {
            "major_fit": _clip(sim / best_sim) if best_sim > 0 else 0.0,
            "affordability": affordability(
                row.price_for_scoring(bracket, home), cap, bracket_median
            ),
            "outcomes": out,
            "admission_fit": admission_fit(est.band, row.admission_rate, prestige),
            "preferences": preferences(row, profile),
        }
        total = _clip(sum(w[c] * comps[c] for c in COMPONENTS))
        scored.append(
            Scored(
                row=row,
                admission=est,
                scores=ScoreBreakdown(
                    **{c: round(v, 4) for c, v in comps.items()}, total=round(total, 4)
                ),
                similarity=sim,
                far_reach=is_far_reach(profile, row),
            )
        )
    return scored


def best_per_school(scored: list[Scored], key: str = "total") -> list[Scored]:
    """Keep the highest-scoring row per school; return sorted by score desc."""

    def k(s: Scored) -> tuple[float, float, int, str]:
        primary = s.scores.total if key == "total" else s.similarity
        return (-primary, -s.scores.total, s.row.unitid, s.row.cip4 or "")

    best: dict[int, Scored] = {}
    for s in sorted(scored, key=k):
        best.setdefault(s.row.unitid, s)
    return sorted(best.values(), key=k)


def band_quotas(k: int) -> dict[str, tuple[int, int]]:
    """(min, max) per band for a list of ``k``."""
    return {
        "safety": (round(0.2 * k), round(0.3 * k)),
        "target": (round(0.4 * k), round(0.5 * k)),
        "reach": (round(0.2 * k), round(0.3 * k)),
    }


def max_far_reach(k: int) -> int:
    return max(1, math.floor(0.1 * k + 0.5))  # half-up, not banker's rounding


def limit_far_reaches(ranked: list[Scored], k: int) -> list[Scored]:
    """Top ``k`` (score order) with far reaches only filling otherwise-empty slots."""
    near = [s for s in ranked if not s.far_reach]
    far = [s for s in ranked if s.far_reach][: max(0, min(max_far_reach(k), k - len(near)))]
    chosen = near[:k] + far
    return sorted(chosen, key=lambda s: (-s.scores.total, s.row.unitid))


def balance_bands(ranked: list[Scored], k: int) -> list[Scored]:
    """Pick ``k`` items from ``ranked`` (score-desc, one per school) balancing bands;
    far reaches only fill slots left empty (see module docstring)."""
    far = [s for s in ranked if s.far_reach]
    ranked = [s for s in ranked if not s.far_reach]
    quotas = band_quotas(k)
    chosen: list[Scored] = []
    ids: set[int] = set()

    def take(s: Scored) -> None:
        chosen.append(s)
        ids.add(s.row.unitid)

    def count(band: str) -> int:
        return sum(1 for s in chosen if s.admission.band == band)

    for band, (lo, _) in quotas.items():
        for s in [x for x in ranked if x.admission.band == band][:lo]:
            if len(chosen) < k:
                take(s)
    for s in ranked:
        if len(chosen) >= k:
            break
        if s.row.unitid in ids:
            continue
        b = s.admission.band
        if b in quotas and count(b) >= quotas[b][1]:
            continue
        take(s)
    for s in ranked:
        if len(chosen) >= k:
            break
        if s.row.unitid not in ids:
            take(s)
    for s in far[: max_far_reach(k)]:
        if len(chosen) >= k:
            break
        take(s)
    return sorted(chosen, key=lambda s: (-s.scores.total, s.row.unitid))


def bands_known(profile: StudentProfile) -> bool:
    return any(f.value is not None for f in (profile.gpa, profile.sat, profile.act))
