"""Unit tests for Stage C rerank, band balancing, geo helpers and fuzzy major matching."""

from __future__ import annotations

from typing import Any

import pytest

from app.retrieval import geo
from app.retrieval.admission import AdmissionEstimate
from app.retrieval.major_match import CipScore, fuzzy_score, match_titles, union
from app.retrieval.rerank import (
    BASE_WEIGHTS,
    Scored,
    admission_fit,
    affordability,
    balance_bands,
    band_quotas,
    best_per_school,
    outcome_scores,
    preferences,
    score_rows,
    setting_bucket,
    size_bucket,
    weights_for,
)
from app.retrieval.sql_filters import CandidateRow
from app.schemas import ProfileField, ScoreBreakdown, StudentProfile


def row(**kw: Any) -> CandidateRow:
    base: dict[str, Any] = dict(
        unitid=1,
        name="X",
        city="C",
        state="OH",
        lat=40.0,
        lon=-83.0,
        control=1,
        locale=12,
        undergrad_size=5000,
        admission_rate=0.6,
        open_admission=False,
        sat_25=1100,
        sat_75=1300,
        act_25=None,
        act_75=None,
        net_price_0_30k=10000,
        net_price_30_48k=12000,
        net_price_48_75k=15000,
        net_price_75_110k=20000,
        net_price_110k_plus=25000,
        avg_net_price=16000,
        completion_rate=0.6,
        median_earnings_10yr=50000,
        median_debt=20000,
    )
    base.update(kw)
    return CandidateRow(**base)


def prof(**fields: Any) -> StudentProfile:
    return StudentProfile.model_validate(
        {k: {"value": v, "confidence": 1.0} for k, v in fields.items()}
    )


# ------------------------------------------------------------------ weights


def test_base_weights_sum_to_one() -> None:
    assert sum(weights_for(None).values()) == pytest.approx(1.0)
    assert weights_for([]) == pytest.approx(BASE_WEIGHTS)


@pytest.mark.parametrize(
    "priority,component",
    [
        ("cost", "affordability"),
        ("outcomes", "outcomes"),
        ("prestige", "admission_fit"),
        ("location", "preferences"),
        ("fit", "major_fit"),
    ],
)
def test_priority_boosts_its_component(priority: str, component: str) -> None:
    w = weights_for([priority])  # type: ignore[list-item]
    assert sum(w.values()) == pytest.approx(1.0)
    assert w[component] > weights_for(None)[component]


def test_duplicate_priorities_count_once() -> None:
    assert weights_for(["cost", "cost"]) == weights_for(["cost"])


# ------------------------------------------------------------------ components


def test_affordability_with_cap() -> None:
    assert affordability(0, 20000, None) == pytest.approx(1.0)
    assert affordability(20000, 20000, None) == pytest.approx(0.8)
    assert affordability(10000, 20000, None) == pytest.approx(0.9)
    assert affordability(22000, 20000, None) == pytest.approx(0.8 * (1 - 0.4))
    assert affordability(25000, 20000, None) == 0.0
    assert affordability(40000, 20000, None) == 0.0


def test_affordability_vs_bracket_median() -> None:
    assert affordability(15000, None, 15000) == pytest.approx(0.5)
    assert affordability(0, None, 15000) == pytest.approx(1.0)
    assert affordability(30000, None, 15000) == 0.0
    assert affordability(None, None, 15000) == pytest.approx(0.4)
    assert affordability(5000, None, None) == pytest.approx(0.4)


def test_outcomes_never_mix_horizons() -> None:
    rows = [
        row(unitid=1, program_median_earnings=40000, program_median_debt=None),
        row(unitid=2, program_median_earnings=80000, program_median_debt=None),
        # school-wide only; very high, but ranked only against other school-wide rows
        row(unitid=3, program_median_earnings=None, median_earnings_10yr=200000, median_debt=None),
        row(unitid=4, program_median_earnings=None, median_earnings_10yr=None),
    ]
    s = outcome_scores(rows)
    assert s[0] == pytest.approx(0.1)  # pct 0 → 0.8*0 + 0.1
    assert s[1] == pytest.approx(0.9)  # pct 1
    assert s[2] == pytest.approx(0.5)  # alone in its group → pct 0.5 → 0.4 + 0.1
    assert s[3] == pytest.approx(0.3)  # unknown


def test_outcomes_debt_penalty() -> None:
    lo = outcome_scores([row(program_median_earnings=50000, program_median_debt=50000)])
    hi = outcome_scores([row(program_median_earnings=50000, program_median_debt=10000)])
    assert lo[0] == pytest.approx(0.4)
    assert hi[0] == pytest.approx(0.4 + 0.2 * 0.8)


def test_admission_fit_and_prestige() -> None:
    assert admission_fit("target", 0.5, False) == 1.0
    assert admission_fit("reach", 0.05, False) == 0.5
    assert admission_fit("reach", 0.05, True) == pytest.approx(0.5 * 0.5 + 0.5 * 0.95)
    assert admission_fit("unknown", None, True) == 0.6


def test_percentiles_midrank() -> None:
    from app.retrieval.rerank import _percentiles

    assert _percentiles([]) == {}
    assert _percentiles([5.0]) == {5.0: 0.5}
    assert _percentiles([1.0, 2.0, 2.0, 3.0]) == {1.0: 0.0, 2.0: 0.5, 3.0: 1.0}
    big = [float(i % 100) for i in range(20000)]
    pct = _percentiles(big)
    assert pct[0.0] == pytest.approx((0 + 0.5 * 199) / 19999)
    assert pct[99.0] == pytest.approx((19800 + 0.5 * 199) / 19999)


def test_region_match_soft_preference() -> None:
    p = prof()
    assert preferences(row(region_match=True), p) == 1.0
    assert preferences(row(region_match=False), p) == 0.0


def test_size_and_setting_buckets() -> None:
    assert [size_bucket(n) for n in (None, 1999, 2000, 15000, 15001)] == [
        None,
        "small",
        "medium",
        "medium",
        "large",
    ]
    assert [setting_bucket(x) for x in (None, 11, 13, 21, 32, 43)] == [
        None,
        "city",
        "city",
        "suburb",
        "town",
        "rural",
    ]


def test_preferences() -> None:
    p = prof(size_pref="small", setting_pref="rural", max_distance_miles=100)
    r = row(undergrad_size=1000, locale=42, distance_miles=50.0)
    assert preferences(r, p) == pytest.approx((1.0 + 1.0 + 0.5) / 3)
    r2 = row(undergrad_size=30000, locale=11, distance_miles=500.0)
    assert preferences(r2, p) == 0.0
    assert preferences(r2, prof()) == 0.5
    assert preferences(row(undergrad_size=8000), prof(size_pref="any")) == 0.5


def test_score_rows_breakdown_bounds_and_major_fit() -> None:
    p = prof(income_bracket="48-75k", sat=1200, priorities=["cost"])
    rows = [row(unitid=1, cip4="1107"), row(unitid=2, cip4="1101")]
    out = score_rows(rows, p, {"1107": 0.8, "1101": 0.4}, 18000.0)
    assert out[0].scores.major_fit == 1.0 and out[1].scores.major_fit == 0.5
    for s in out:
        d = s.scores.model_dump()
        assert all(0 <= v <= 1 for v in d.values())
        assert s.admission.band == "target"


# ------------------------------------------------------------------ balancing


def scored(unitid: int, band: str, total: float, cip: str = "1107") -> Scored:
    b = ScoreBreakdown(
        major_fit=0.5,
        affordability=0.5,
        outcomes=0.5,
        admission_fit=0.5,
        preferences=0.5,
        total=total,
    )
    return Scored(
        row=row(unitid=unitid, cip4=cip),
        admission=AdmissionEstimate(band, "normal", None, "test"),  # type: ignore[arg-type]
        scores=b,
    )


def test_band_quotas_k10() -> None:
    assert band_quotas(10) == {"safety": (2, 3), "target": (4, 5), "reach": (2, 3)}


def test_balance_bands_k10() -> None:
    # 12 reaches score highest, then 10 targets, then 10 safeties
    ranked = (
        [scored(100 + i, "reach", 0.99 - i * 0.001) for i in range(12)]
        + [scored(200 + i, "target", 0.8 - i * 0.001) for i in range(10)]
        + [scored(300 + i, "safety", 0.6 - i * 0.001) for i in range(10)]
    )
    out = balance_bands(ranked, 10)
    bands = [s.admission.band for s in out]
    assert len(out) == 10
    assert 2 <= bands.count("safety") <= 3
    assert 4 <= bands.count("target") <= 5
    assert 2 <= bands.count("reach") <= 3
    assert [s.scores.total for s in out] == sorted((s.scores.total for s in out), reverse=True)
    assert len({s.row.unitid for s in out}) == 10


def test_balance_bands_fills_when_band_missing() -> None:
    ranked = [scored(i, "target", 1 - i / 100) for i in range(20)]
    out = balance_bands(ranked, 10)
    assert len(out) == 10
    assert [s.row.unitid for s in out] == list(range(10))


def test_balance_bands_short_pool() -> None:
    ranked = [scored(1, "reach", 0.9), scored(2, "safety", 0.5)]
    assert len(balance_bands(ranked, 10)) == 2


def test_best_per_school() -> None:
    items = [
        scored(1, "target", 0.5, "1101"),
        scored(1, "target", 0.7, "1107"),
        scored(2, "reach", 0.6),
    ]
    out = best_per_school(items)
    assert [(s.row.unitid, s.row.cip4) for s in out] == [(1, "1107"), (2, "1107")]


# ------------------------------------------------------------------ geo


def test_every_state_has_one_division_and_region() -> None:
    assert len(geo.ALL_STATES) == 51
    for s in geo.ALL_STATES:
        divs = [d for d, states in geo.DIVISIONS.items() if s in states]
        regs = [r for r, states in geo.REGIONS.items() if s in states]
        assert len(divs) == 1, s
        assert len(regs) == 1, s
    assert set().union(*geo.DIVISIONS.values()) == geo.ALL_STATES


def test_dc_is_south_atlantic() -> None:
    assert geo.STATE_DIVISION["DC"] == "south_atlantic"
    assert geo.STATE_REGION["DC"] == "south"


def test_states_for_regions() -> None:
    assert geo.states_for_regions(["new_england"], None) == {"CT", "ME", "MA", "NH", "RI", "VT"}
    assert geo.states_for_regions(["Midwest"], None) == geo.REGIONS["midwest"]
    assert geo.states_for_regions(["pacific", "TX", "ny"], "OH") == geo.DIVISIONS["pacific"] | {
        "TX",
        "NY",
    }
    oos = geo.states_for_regions(["out_of_state"], "OH")
    assert "OH" not in oos and len(oos) == 50
    assert len(geo.states_for_regions(["out_of_state"], None)) == 51
    assert geo.states_for_regions(["narnia"], "OH") == set()
    # out_of_state always excludes home, even when another entry includes it
    combo = geo.states_for_regions(["south", "out_of_state"], "TX")
    assert "TX" not in combo and "OK" in combo and "OH" in combo
    assert "TX" not in geo.states_for_regions(["TX", "out_of_state"], "TX")
    assert "TX" not in geo.states_for_regions(["out_of_state", "west_south_central"], "tx")
    assert geo.states_for_regions(["narnia", "west"], None) == geo.REGIONS["west"]


def test_haversine() -> None:
    # Columbus OH → Chicago IL ≈ 276 miles
    assert geo.haversine_miles(39.96, -83.0, 41.88, -87.63) == pytest.approx(276, abs=5)
    assert geo.distance_from_home("OH", None, -80.0) is None
    assert geo.distance_from_home(None, 40.0, -80.0) is None
    assert geo.distance_from_home("oh", 40.48, -82.75) == pytest.approx(0.0, abs=0.01)


# ------------------------------------------------------------------ fuzzy majors

TITLES = {
    "1101": "Computer and Information Sciences, General",
    "1107": "Computer Science",
    "1401": "Engineering, General",
    "1419": "Mechanical Engineering",
    "2601": "Biology, General",
    "4201": "Psychology, General",
    "5138": "Registered Nursing, Nursing Administration, Nursing Research and Clinical Nursing",
    "4506": "Economics",
}


@pytest.mark.parametrize(
    "major,cip",
    [
        ("computer science", "1107"),
        ("CS", "1107"),
        ("mechanical engineering", "1419"),
        ("engineering", "1401"),
        ("nursing", "5138"),
        ("pre-med", "2601"),
        ("psych", "4201"),
        ("econ", "4506"),
    ],
)
def test_match_titles(major: str, cip: str) -> None:
    out = match_titles([major], TITLES)
    assert out and out[0].cip4 == cip
    assert all(c.source == "intended" for c in out)


def test_match_titles_rejects_nonsense() -> None:
    assert match_titles(["underwater basket weaving"], TITLES) == []
    assert fuzzy_score("", "Biology") == 0.0


def test_union_keeps_max_and_marks_both() -> None:
    a = [CipScore("1107", "CS", 0.7, "embedding")]
    b = [CipScore("1107", "CS", 0.9, "intended"), CipScore("2601", "Bio", 0.6, "intended")]
    out = union(a, b)
    assert [(c.cip4, c.similarity, c.source) for c in out] == [
        ("1107", 0.9, "both"),
        ("2601", 0.6, "intended"),
    ]


def test_profile_field_typing_smoke() -> None:
    # make sure the helper builds a real StudentProfile
    p = prof(home_state="OH", regions=["midwest"])
    assert isinstance(p.home_state, ProfileField) and p.regions.value == ["midwest"]
