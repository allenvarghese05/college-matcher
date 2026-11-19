"""Stage B: hard filters in SQL (SPEC §9).

* In scope (D6): every row in ``institution`` is in scope by construction of the
  ingest; we additionally require ≥ 1 bachelor's program (``credential_level = 3``).
* Offers ≥ 1 selected CIP at the bachelor's level (one output row per school × CIP).
  ``cips=None`` means "any major": one row per school with ``cip4 = None``.
* Budget (if ``budget_cap``): net price at the student's bracket ≤ cap × 1.15. If the
  bracket price is missing we fall back to the school's average net price; if both are
  missing the school is excluded (we can't show it is affordable).
* Geography (criteria H3):
  - Distance (if ``max_distance_miles`` and ``home_state``): haversine from the home
    state's population centroid to the school ≤ max distance × 1.10 (computed in
    Python). See ``geo`` for the centroid limitation.
  - Regions (if ``regions``): school state ∈ ``states_for_regions(regions, home_state)``
    — hard **only when distance is not the hard rule**. When distance is enforced,
    regions become a soft preference (``CandidateRow.region_match``).
  - Relaxation order (done by the retriever): distance first, then regions.

Rows carry every fact the recommender may cite (see ``CandidateRow``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.geo import distance_from_home, states_for_regions
from app.schemas import IncomeBracket, StudentProfile

BUDGET_SLACK = 1.15
DISTANCE_SLACK = 1.10
BACHELORS = 3

NET_PRICE_COLUMNS: dict[str, str] = {
    "0-30k": "net_price_0_30k",
    "30-48k": "net_price_30_48k",
    "48-75k": "net_price_48_75k",
    "75-110k": "net_price_75_110k",
    "110k+": "net_price_110k_plus",
}


def net_price_column(bracket: IncomeBracket | str | None) -> str:
    """Institution column holding the net price for ``bracket`` (avg if unknown).

    The groundedness checker should use this same mapping for ``net_price`` claims.
    """
    if bracket is None:
        return "avg_net_price"
    return NET_PRICE_COLUMNS[bracket]


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
    cip4: str | None = None
    cip_title: str | None = None
    program_median_earnings: int | None = None
    program_median_debt: int | None = None
    program_graduates: int | None = None
    distance_miles: float | None = None
    region_match: bool | None = None  # set when regions are a soft preference only

    def net_price_at(self, bracket: IncomeBracket | str | None) -> int | None:
        """Net price at the bracket (DB value, may be None)."""
        value: int | None = getattr(self, net_price_column(bracket))
        return value

    def price_for_scoring(self, bracket: IncomeBracket | str | None) -> int | None:
        """Bracket price, falling back to the average net price (filtering/scoring only)."""
        p = self.net_price_at(bracket)
        return p if p is not None else self.avg_net_price


@dataclass(frozen=True)
class FilterOptions:
    apply_budget: bool = True
    apply_distance: bool = True
    apply_regions: bool = True


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

    cap = profile.budget_cap.value
    if opts.apply_budget and cap is not None:
        col = net_price_column(profile.income_bracket.value)
        where.append(f"COALESCE(i.{col}, i.avg_net_price) <= :max_price")
        params["max_price"] = cap * BUDGET_SLACK

    home = profile.home_state.value
    max_d = profile.max_distance_miles.value
    distance_hard = opts.apply_distance and max_d is not None and bool(home)
    region_states: set[str] = (
        states_for_regions(profile.regions.value, home) if profile.regions.value else set()
    )
    regions_hard = opts.apply_regions and not distance_hard and bool(region_states)
    if regions_hard:
        where.append("i.state = ANY(:states)")
        params["states"] = sorted(region_states)

    if where:
        sql += " AND " + " AND ".join(where)
    sql += " ORDER BY i.unitid" + (", p.cip4" if cips is not None else "")

    result = await session.execute(text(sql), params)
    rows = [CandidateRow(**dict(r._mapping)) for r in result]

    for row in rows:
        row.distance_miles = distance_from_home(home, row.lat, row.lon)
        if region_states and not regions_hard:
            row.region_match = row.state in region_states
    if distance_hard and max_d is not None:
        cutoff = max_d * DISTANCE_SLACK
        rows = [r for r in rows if r.distance_miles is not None and r.distance_miles <= cutoff]
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
