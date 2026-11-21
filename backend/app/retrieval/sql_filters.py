"""Stage B: hard filters in SQL (SPEC §9).

* In scope (D6): every row in ``institution`` is in scope by construction of the
  ingest; we additionally require ≥ 1 bachelor's program (``credential_level = 3``).
* Offers ≥ 1 selected CIP at the bachelor's level (one output row per school × CIP).
  ``cips=None`` means "any major": one row per school with ``cip4 = None``.
* Budget (:func:`budget_ceiling`): the student's net price (``pricing.student_net_price``:
  bracket price, plus the out-of-state surcharge at public schools outside the home
  state — the price the student would actually pay) ≤ the ceiling:
  - a stated ``budget_cap`` → cap × 1.15 (source ``cap``);
  - no cap → the income bracket's default ceiling (``BRACKET_DEFAULT_BUDGET``, source
    ``bracket_default``; 110k+ with the ``prestige`` priority has none);
  - no cap and no bracket → no budget filter.
  ``FilterOptions(budget_to_default=True)`` swaps a stated cap for the bracket default
  (the retriever's one relaxation step, see ``retriever``). If the bracket price is
  missing we fall back to the school's average net price; if no price can be computed
  the school is excluded (we can't show it is affordable). Applied in Python.
* Geography (criteria H3):
  - Distance (if ``max_distance_miles`` and ``home_state``): haversine from the home
    state's population centroid to the school ≤ max distance × 1.10 (computed in
    Python). See ``geo`` for the centroid limitation.
  - Regions (if ``regions``): school state ∈ ``states_for_regions(regions, home_state)``
    — hard **only when distance is not the hard rule**. When distance is enforced,
    regions become a soft preference (``CandidateRow.region_match``).
  - "Leave home" lists (``out_of_state`` plus named places, e.g. ``[out_of_state, CA,
    OR, WA]``): the hard filter is "not the home state"; the named places are a soft
    preference (``region_match``) instead of being swallowed by the union. The
    home-state exclusion stays hard even when distance is the hard rule.
  - Distance and regions are never relaxed (the student stated them).

Rows carry every fact the recommender may cite (see ``CandidateRow``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.geo import OUT_OF_STATE, distance_from_home, states_for_regions
from app.retrieval.pricing import (
    NET_PRICE_COLUMNS,
    NetPriceBasis,
    net_price_column,
    student_net_price,
)
from app.schemas import IncomeBracket, StudentProfile

__all__ = [
    "BRACKET_DEFAULT_BUDGET",
    "BUDGET_SLACK",
    "DISTANCE_SLACK",
    "NET_PRICE_COLUMNS",
    "CandidateRow",
    "FilterOptions",
    "bracket_median",
    "budget_ceiling",
    "region_sets",
    "candidates",
    "net_price_column",
]

BUDGET_SLACK = 1.15
DISTANCE_SLACK = 1.10
BACHELORS = 3

# Net-price ceiling when the student gave no budget: "a stretch most families in the
# bracket could plausibly manage with loans and work" (the same table the benchmark
# froze in evals/labels/criteria.md H2 before labeling; a product default, not tuned).
BRACKET_DEFAULT_BUDGET: dict[str, int] = {
    "0-30k": 12000,
    "30-48k": 15000,
    "48-75k": 20000,
    "75-110k": 27000,
    "110k+": 40000,
}

BudgetSource = Literal["cap", "bracket_default"]

_INST_COLS = (
    "unitid",
    "name",
    "city",
    "state",
    "lat",
    "lon",
    "control",
    "locale",
    "undergrad_size",
    "admission_rate",
    "open_admission",
    "sat_25",
    "sat_75",
    "act_25",
    "act_75",
    "net_price_0_30k",
    "net_price_30_48k",
    "net_price_48_75k",
    "net_price_75_110k",
    "net_price_110k_plus",
    "avg_net_price",
    "completion_rate",
    "median_earnings_10yr",
    "median_debt",
    "tuition_in_state",
    "tuition_out_of_state",
)


@dataclass
class CandidateRow:
    """One school × major (or school-only when ``cip4`` is None) after hard filters."""

    unitid: int
    name: str
    city: str
    state: str
    lat: float | None
    lon: float | None
    control: int
    locale: int | None
    undergrad_size: int | None
    admission_rate: float | None
    open_admission: bool | None
    sat_25: int | None
    sat_75: int | None
    act_25: int | None
    act_75: int | None
    net_price_0_30k: int | None
    net_price_30_48k: int | None
    net_price_48_75k: int | None
    net_price_75_110k: int | None
    net_price_110k_plus: int | None
    avg_net_price: int | None
    completion_rate: float | None
    median_earnings_10yr: int | None
    median_debt: int | None
    tuition_in_state: int | None = None
    tuition_out_of_state: int | None = None
    cip4: str | None = None
    cip_title: str | None = None
    program_median_earnings: int | None = None
    program_median_debt: int | None = None
    program_graduates: int | None = None
    distance_miles: float | None = None
    region_match: bool | None = None  # set when regions are a soft preference only

    def student_price(
        self, bracket: IncomeBracket | str | None, home_state: str | None
    ) -> tuple[int | None, NetPriceBasis]:
        """What the student is shown: ``pricing.student_net_price`` (no avg fallback)."""
        return student_net_price(self, bracket, home_state)

    def price_for_scoring(
        self, bracket: IncomeBracket | str | None, home_state: str | None
    ) -> int | None:
        """Same rule, falling back to the average net price (filtering/scoring only)."""
        return student_net_price(self, bracket, home_state, fallback_to_avg=True)[0]


@dataclass(frozen=True)
class FilterOptions:
    apply_budget: bool = True
    apply_distance: bool = True
    apply_regions: bool = True
    budget_to_default: bool = False  # replace a stated cap with the bracket default


def bracket_default_budget(profile: StudentProfile) -> int | None:
    """Default ceiling for the student's bracket (None: unknown bracket, or prestige
    at 110k+)."""
    bracket = profile.income_bracket.value
    if bracket is None:
        return None
    if bracket == "110k+" and "prestige" in (profile.priorities.value or []):
        return None
    return BRACKET_DEFAULT_BUDGET.get(bracket)


def budget_ceiling(
    profile: StudentProfile, opts: FilterOptions | None = None
) -> tuple[float | None, BudgetSource | None]:
    """(max net price, where it came from); ``(None, None)`` = no budget filter."""
    opts = opts or FilterOptions()
    if not opts.apply_budget:
        return None, None
    cap = profile.budget_cap.value
    if cap is not None and not opts.budget_to_default:
        return cap * BUDGET_SLACK, "cap"
    default = bracket_default_budget(profile)
    if default is None:
        return None, None
    return float(default), "bracket_default"


def wants_out_of_state(regions: list[str] | None) -> bool:
    """The student listed ``out_of_state`` (wants to leave their home state)."""
    return any(r.strip().lower().replace("-", "_") == OUT_OF_STATE for r in regions or [])


def region_sets(regions: list[str] | None, home: str | None) -> tuple[set[str], set[str]]:
    """(states allowed, states preferred) for ``regions``.

    Normally both are the union of the entries. A "leave home" list (``out_of_state``
    plus named places) allows every state but home and prefers the named places.
    """
    if not regions:
        return set(), set()
    allowed = states_for_regions(regions, home)
    named = [r for r in regions if r.strip().lower().replace("-", "_") != OUT_OF_STATE]
    if len(named) < len(regions) and named:
        preferred = states_for_regions(named, home) - {(home or "").strip().upper()}
        return allowed, preferred
    return allowed, allowed


async def candidates(
    session: AsyncSession,
    profile: StudentProfile,
    cips: list[str] | None,
    opts: FilterOptions | None = None,
) -> list[CandidateRow]:
    """Stage B rows for ``cips`` (or all schools when ``cips is None``)."""
    opts = opts or FilterOptions()
    if cips is not None and not cips:
        return []
    params: dict[str, Any] = {"lvl": BACHELORS}
    where: list[str] = []
    inst_sel = ", ".join(f"i.{c}" for c in _INST_COLS)

    if cips is None:
        sql = (
            f"SELECT {inst_sel} FROM institution i WHERE EXISTS ("
            " SELECT 1 FROM program p WHERE p.unitid = i.unitid AND p.credential_level = :lvl)"
        )
    else:
        sql = (
            f"SELECT {inst_sel}, p.cip4, c.title AS cip_title,"
            " p.median_earnings AS program_median_earnings,"
            " p.median_debt AS program_median_debt, p.graduates AS program_graduates"
            " FROM institution i"
            " JOIN program p ON p.unitid = i.unitid AND p.credential_level = :lvl"
            " JOIN cip_code c ON c.cip4 = p.cip4"
            " WHERE p.cip4 = ANY(:cips)"
        )
        params["cips"] = list(cips)

    home = profile.home_state.value
    max_d = profile.max_distance_miles.value
    distance_hard = opts.apply_distance and max_d is not None and bool(home)
    region_states, preferred_states = region_sets(profile.regions.value, home)
    regions_hard = opts.apply_regions and not distance_hard and bool(region_states)
    if regions_hard:
        where.append("i.state = ANY(:states)")
        params["states"] = sorted(region_states)
    elif opts.apply_regions and home and wants_out_of_state(profile.regions.value):
        where.append("i.state <> :home")  # an explicit "not my home state" stays hard
        params["home"] = home.strip().upper()

    if where:
        sql += " AND " + " AND ".join(where)
    sql += " ORDER BY i.unitid" + (", p.cip4" if cips is not None else "")

    result = await session.execute(text(sql), params)
    rows = [CandidateRow(**dict(r._mapping)) for r in result]

    for row in rows:
        row.distance_miles = distance_from_home(home, row.lat, row.lon)
        if preferred_states and (not regions_hard or preferred_states != region_states):
            row.region_match = row.state in preferred_states
    if distance_hard and max_d is not None:
        cutoff = max_d * DISTANCE_SLACK
        rows = [r for r in rows if r.distance_miles is not None and r.distance_miles <= cutoff]
    max_price, _source = budget_ceiling(profile, opts)
    if max_price is not None:
        bracket = profile.income_bracket.value
        rows = [
            r
            for r in rows
            if (p := r.price_for_scoring(bracket, home)) is not None and p <= max_price
        ]
    return rows


async def bracket_median(
    session: AsyncSession, bracket: IncomeBracket | str | None
) -> float | None:
    """National median net price at ``bracket`` over all in-scope schools."""
    col = net_price_column(bracket)
    res = await session.execute(
        text(f"SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY {col}) FROM institution")
    )
    v = res.scalar()
    return float(v) if v is not None else None
