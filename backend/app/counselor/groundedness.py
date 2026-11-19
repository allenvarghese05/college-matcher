"""Deterministic groundedness checker (SPEC §8 recommendation pipeline, §10 metrics).

Every number a student sees is a :class:`~app.schemas.Claim`. This module parses the
claim's stated value and compares it to the fact from Postgres (or the retriever's
candidate facts, which are copied from Postgres):

* money (net price, earnings, debt) and counts (undergrad size): within 1% relative;
* rates (admission, completion): the claim must round correctly — within half a
  percentage point of the fact — or be within 1% relative;
* ranges (SAT/ACT "1200-1400"): exact on both ends;
* strings (``city_state`` "Chapel Hill, NC"): exact after case/whitespace normalisation.

A missing fact, an unparsable claim, or an unknown (unitid, cip4) is unverified.
Digits inside ``reasons`` are counted as violations of the no-numbers-in-prose rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.schemas import Candidate, Claim, Recommendation, VerifiedClaim

FactValue = float | int | str | None
Facts = Mapping[str, FactValue]

MONEY_FIELDS = frozenset(
    {
        "net_price",
        "program_median_earnings",
        "program_median_debt",
        "median_earnings_10yr",
        "median_debt",
    }
)
RATE_FIELDS = frozenset({"admission_rate", "completion_rate"})
COUNT_FIELDS = frozenset({"undergrad_size"})
RANGE_FIELDS = frozenset({"sat_range", "act_range"})
STRING_FIELDS = frozenset({"city_state"})
PROGRAM_FIELDS = frozenset({"program_median_earnings", "program_median_debt"})

REL_TOL = 0.01
RATE_ABS_TOL = 0.005 + 1e-9  # half a percentage point (correct rounding to a whole %)

_DIGIT = re.compile(r"\d")
_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*([kKmM])?\b")


# ----------------------------------------------------------------------- parsing


def _strip_commas(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)


def parse_number(text: str) -> float | None:
    """'$14,200' -> 14200; '$14.2k' -> 14200; '12,500 students' -> 12500; '62%' -> 62.

    Exactly one number must be present (ranges are rejected).
    """
    s = _strip_commas(text.strip())
    matches = _NUM.findall(s)
    if len(matches) != 1:
        return None
    num, suffix = matches[0]
    value = float(num)
    if suffix.lower() == "k":
        value *= 1_000
    elif suffix.lower() == "m":
        value *= 1_000_000
    return value


def parse_rate(text: str) -> float | None:
    """'62%' -> 0.62; '62.5 %' -> 0.625; '0.62' -> 0.62. Returns a fraction 0..1."""
    v = parse_number(text)
    if v is None:
        return None
    if "%" in text or v > 1:
        v = v / 100
    return v if 0 <= v <= 1 else None


def parse_range(text: str) -> tuple[int, int] | None:
    """'1200-1400', '1200–1400', '1200 to 1400' -> (1200, 1400)."""
    s = _strip_commas(text.strip())
    m = re.fullmatch(r"\s*(\d+)\s*(?:-|–|—|to)\s*(\d+)\s*", s)
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    return (lo, hi) if lo <= hi else None


def normalize_place(text: str) -> str:
    s = re.sub(r"\s*,\s*", ", ", text.strip())
    return re.sub(r"\s+", " ", s).lower()


def fact_rate(v: FactValue) -> float | None:
    if v is None or isinstance(v, str):
        return parse_rate(v) if isinstance(v, str) else None
    f = float(v)
    return f / 100 if f > 1 else f


def fact_number(v: FactValue) -> float | None:
    if v is None:
        return None
    if isinstance(v, str):
        return parse_number(v)
    return float(v)


def fact_range(v: FactValue) -> tuple[int, int] | None:
    return parse_range(v) if isinstance(v, str) else None


def format_fact(field_name: str, v: FactValue) -> str | None:
    """Canonical display string of a DB fact (stored as ``db_value``)."""
    if v is None:
        return None
    if field_name in MONEY_FIELDS:
        n = fact_number(v)
        return f"${n:,.0f}" if n is not None else str(v)
    if field_name in RATE_FIELDS:
        r = fact_rate(v)
        return f"{r * 100:.1f}%" if r is not None else str(v)
    if field_name in COUNT_FIELDS:
        n = fact_number(v)
        return f"{n:,.0f}" if n is not None else str(v)
    return str(v)


def _close(a: float, b: float, rel: float = REL_TOL) -> bool:
    if b == 0:
        return a == 0
    return abs(a - b) <= rel * abs(b)


def value_matches(field_name: str, stated: str, fact: FactValue) -> bool:
    if fact is None:
        return False
    if field_name in MONEY_FIELDS or field_name in COUNT_FIELDS:
        a, b = parse_number(stated), fact_number(fact)
        return a is not None and b is not None and _close(a, b)
    if field_name in RATE_FIELDS:
        a, b = parse_rate(stated), fact_rate(fact)
        return a is not None and b is not None and (abs(a - b) <= RATE_ABS_TOL or _close(a, b))
    if field_name in RANGE_FIELDS:
        ra, rb = parse_range(stated), fact_range(fact)
        return ra is not None and ra == rb
    if field_name in STRING_FIELDS:
        return isinstance(fact, str) and normalize_place(stated) == normalize_place(fact)
    return False


# ------------------------------------------------------------------------- facts


class FactIndex:
    """Facts keyed by (unitid, cip4). School-level fields resolve from any cip4."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[int, str | None], dict[str, FactValue]] = {}

    def add(self, unitid: int, cip4: str | None, facts: Facts) -> None:
        self._by_key.setdefault((unitid, cip4), {}).update(facts)

    @classmethod
    def from_candidates(cls, candidates: Iterable[Candidate]) -> FactIndex:
        idx = cls()
        for c in candidates:
            idx.add(c.unitid, c.cip4, c.facts)
        return idx

    def lookup(self, unitid: int, cip4: str | None, field_name: str) -> tuple[bool, FactValue]:
        """Return (found, value). ``found`` is False if no fact row exists for the key."""
        if field_name in PROGRAM_FIELDS:
            row = self._by_key.get((unitid, cip4))
            if row is None or field_name not in row:
                return False, None
            return True, row[field_name]
        for (uid, _), row in self._by_key.items():
            if uid == unitid and field_name in row:
                return True, row[field_name]
        return False, None


# ------------------------------------------------------------------------ report


@dataclass
class CheckedRecommendation:
    recommendation: Recommendation
    claims: list[VerifiedClaim]


@dataclass
class GroundednessReport:
    recommendations: list[CheckedRecommendation] = field(default_factory=list)
    n_claims: int = 0
    n_verified: int = 0
    reason_digit_violations: int = 0

    @property
    def groundedness(self) -> float:
        """Verified / all claims; 1.0 when there are no claims (nothing ungrounded)."""
        return 1.0 if self.n_claims == 0 else self.n_verified / self.n_claims

    @property
    def unverified(self) -> list[VerifiedClaim]:
        return [c for r in self.recommendations for c in r.claims if not c.verified]


def check_claim(claim: Claim, facts: FactIndex, default_cip4: str | None = None) -> VerifiedClaim:
    cip4 = claim.cip4 if claim.cip4 is not None else default_cip4
    found, fact = facts.lookup(claim.unitid, cip4, claim.field)
    verified = found and value_matches(claim.field, claim.value, fact)
    return VerifiedClaim(
        **claim.model_dump(), verified=verified, db_value=format_fact(claim.field, fact)
    )


def has_digit(text: str) -> bool:
    return _DIGIT.search(text) is not None


def count_digit_reasons(reasons: Iterable[str]) -> int:
    return sum(1 for r in reasons if has_digit(r))


def check(recs: Iterable[Recommendation], facts: FactIndex) -> GroundednessReport:
    report = GroundednessReport()
    for rec in recs:
        checked = [
            check_claim(c, facts, rec.cip4 if c.unitid == rec.unitid else None) for c in rec.claims
        ]
        report.recommendations.append(CheckedRecommendation(rec, checked))
        report.n_claims += len(checked)
        report.n_verified += sum(c.verified for c in checked)
        report.reason_digit_violations += count_digit_reasons(rec.reasons)
    return report
