from __future__ import annotations

import pytest

from app.counselor.groundedness import (
    FactIndex,
    check,
    check_claim,
    count_digit_reasons,
    format_fact,
    normalize_place,
    parse_number,
    parse_range,
    parse_rate,
    value_matches,
)
from app.schemas import Candidate, Claim, Recommendation, ScoreBreakdown

UNC = 199120
FACTS = {
    "net_price": 14200,
    "admission_rate": 0.1683,
    "sat_range": "1300-1500",
    "act_range": "29-33",
    "completion_rate": 0.9123,
    "median_earnings_10yr": 68000,
    "median_debt": 13500,
    "undergrad_size": 19897,
    "city_state": "Chapel Hill, NC",
    "program_median_earnings": 98765,
    "program_median_debt": 21000,
}


def _cand(unitid: int = UNC, cip4: str | None = "1107", **facts: object) -> Candidate:
    return Candidate(
        unitid=unitid,
        name="UNC",
        city="Chapel Hill",
        state="NC",
        cip4=cip4,
        cip_title="Computer Science",
        admission_band="reach",
        band_confidence="normal",
        scores=ScoreBreakdown(
            major_fit=1, affordability=1, outcomes=1, admission_fit=1, preferences=1, total=1
        ),
        facts={**FACTS, **facts},  # type: ignore[dict-item]
    )


def _claim(field: str, value: str, unitid: int = UNC, cip4: str | None = "1107") -> Claim:
    return Claim(unitid=unitid, field=field, cip4=cip4, value=value)  # type: ignore[arg-type]


# ---------------------------------------------------------------- parsers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$14,200", 14200),
        ("14200", 14200),
        ("$14,200/year", 14200),
        ("$14,200 per year", 14200),
        ("about $14.2k", 14200),
        ("$1.5M", 1_500_000),
        ("12,500 students", 12500),
        ("62%", 62),
        ("$1,234,567", 1234567),
        ("1200-1400", None),  # two numbers
        ("free", None),
        ("", None),
    ],
)
def test_parse_number(text: str, expected: float | None) -> None:
    assert parse_number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("62%", 0.62),
        ("62.5 %", 0.625),
        ("0.62", 0.62),
        ("62", 0.62),
        ("100%", 1.0),
        ("150%", None),
        ("n/a", None),
    ],
)
def test_parse_rate(text: str, expected: float | None) -> None:
    got = parse_rate(text)
    assert got == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1200-1400", (1200, 1400)),
        ("1200–1400", (1200, 1400)),
        ("1200 — 1400", (1200, 1400)),
        ("1200 to 1400", (1200, 1400)),
        ("1,200-1,400", (1200, 1400)),
        ("1400-1200", None),
        ("1200", None),
        ("around 1200-1400", None),
    ],
)
def test_parse_range(text: str, expected: tuple[int, int] | None) -> None:
    assert parse_range(text) == expected


def test_normalize_place() -> None:
    assert normalize_place("  Chapel  Hill ,NC ") == "chapel hill, nc"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("net_price", 14200, "$14,200"),
        ("admission_rate", 0.1683, "16.8%"),
        ("admission_rate", 16.83, "16.8%"),
        ("undergrad_size", 19897, "19,897"),
        ("sat_range", "1300-1500", "1300-1500"),
        ("city_state", "Chapel Hill, NC", "Chapel Hill, NC"),
        ("net_price", None, None),
    ],
)
def test_format_fact(field: str, value: object, expected: str | None) -> None:
    assert format_fact(field, value) == expected  # type: ignore[arg-type]


# ----------------------------------------------------------- value matching


@pytest.mark.parametrize(
    ("field", "stated", "fact", "ok"),
    [
        # money: 1% relative tolerance
        ("net_price", "$14,200", 14200, True),
        ("net_price", "$14,300", 14200, True),  # 0.7%
        ("net_price", "$14,400", 14200, False),  # 1.4%
        ("net_price", "$14.2k", 14200, True),
        ("net_price", "$14,200", None, False),
        ("net_price", "cheap", 14200, False),
        ("median_debt", "$13,500", "13500", True),  # string fact
        ("program_median_earnings", "$98,765", 98765, True),
        # rates: correct rounding (0.5 pp) or 1% relative
        ("admission_rate", "17%", 0.1683, True),
        ("admission_rate", "16.8%", 0.1683, True),
        ("admission_rate", "16%", 0.1683, False),  # mis-rounded
        ("admission_rate", "0.17", 0.1683, True),
        ("admission_rate", "17%", 16.83, True),  # fact stored as percent
        ("completion_rate", "91%", 0.9123, True),
        ("completion_rate", "93%", 0.9123, False),
        ("completion_rate", "4%", 0.0449, True),
        ("completion_rate", "4.5%", 0.0449, True),
        ("completion_rate", "5%", 0.0449, False),  # 4.49 rounds to 4
        ("completion_rate", "6%", 0.0449, False),
        # counts
        ("undergrad_size", "19,897 students", 19897, True),
        ("undergrad_size", "about 20,000 students", 19897, True),  # 0.5%
        ("undergrad_size", "21,000", 19897, False),
        # ranges: exact
        ("sat_range", "1300-1500", "1300-1500", True),
        ("sat_range", "1300–1500", "1300-1500", True),
        ("sat_range", "1300-1510", "1300-1500", False),
        ("act_range", "29 to 33", "29-33", True),
        ("act_range", "29-33", None, False),
        # strings: exact after normalisation
        ("city_state", "Chapel Hill, NC", "Chapel Hill, NC", True),
        ("city_state", "chapel hill,NC", "Chapel Hill, NC", True),
        ("city_state", "Chapel Hill, North Carolina", "Chapel Hill, NC", False),
        ("city_state", "Durham, NC", "Chapel Hill, NC", False),
    ],
)
def test_value_matches(field: str, stated: str, fact: object, ok: bool) -> None:
    assert value_matches(field, stated, fact) is ok  # type: ignore[arg-type]


# ------------------------------------------------------------- fact lookup


def test_program_fields_need_matching_cip4_school_fields_do_not() -> None:
    idx = FactIndex.from_candidates([_cand(cip4="1107")])
    assert idx.lookup(UNC, "1107", "program_median_earnings") == (True, 98765)
    assert idx.lookup(UNC, "1101", "program_median_earnings") == (False, None)
    assert idx.lookup(UNC, "1101", "net_price") == (True, 14200)  # school-level
    assert idx.lookup(999999, "1107", "net_price") == (False, None)


def test_check_claim_unknown_school_or_missing_fact_is_unverified() -> None:
    idx = FactIndex.from_candidates([_cand(median_debt=None)])
    vc = check_claim(_claim("net_price", "$14,200", unitid=111), idx)
    assert not vc.verified and vc.db_value is None
    vc = check_claim(_claim("median_debt", "$13,500"), idx)
    assert not vc.verified and vc.db_value is None


def test_check_claim_reports_db_value() -> None:
    idx = FactIndex.from_candidates([_cand()])
    vc = check_claim(_claim("net_price", "$19,000"), idx)
    assert vc.verified is False
    assert vc.db_value == "$14,200"
    assert vc.value == "$19,000" and vc.field == "net_price"


def test_check_claim_defaults_cip4_from_recommendation() -> None:
    idx = FactIndex.from_candidates([_cand()])
    vc = check_claim(_claim("program_median_earnings", "$98,765", cip4=None), idx, "1107")
    assert vc.verified


def test_later_facts_override_earlier_ones() -> None:
    idx = FactIndex.from_candidates([_cand(net_price=99999)])
    idx.add(UNC, "1107", {"net_price": 14200})  # DB value wins
    assert check_claim(_claim("net_price", "$14,200"), idx).verified


# ------------------------------------------------------------------ report


def _rec(claims: list[Claim], reasons: list[str]) -> Recommendation:
    return Recommendation(
        unitid=UNC, cip4="1107", rank=1, admission_band="reach", reasons=reasons, claims=claims
    )


def test_check_report_ratio_and_digit_violations() -> None:
    idx = FactIndex.from_candidates([_cand()])
    recs = [
        _rec(
            [
                _claim("net_price", "$14,200"),
                _claim("admission_rate", "17%"),
                _claim("sat_range", "1300-1500"),
                _claim("city_state", "Chapel Hill, NC"),
                _claim("program_median_earnings", "$150,000"),  # wrong
            ],
            ["Strong CS program for you.", "Only 17% get in."],  # one digit violation
        )
    ]
    report = check(recs, idx)
    assert report.n_claims == 5 and report.n_verified == 4
    assert report.groundedness == pytest.approx(0.8)
    assert report.reason_digit_violations == 1
    assert [c.field for c in report.unverified] == ["program_median_earnings"]


def test_check_with_no_claims_is_fully_grounded() -> None:
    report = check([_rec([], ["A good fit."])], FactIndex())
    assert report.groundedness == 1.0 and report.n_claims == 0


def test_count_digit_reasons() -> None:
    assert count_digit_reasons(["no numbers here", "top 10 school", "class of 2028"]) == 2
