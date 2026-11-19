"""Exhaustive table tests for the SPEC §9 admission estimator."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.retrieval.admission import estimate, estimate_for
from app.schemas import ProfileField, StudentProfile

# School archetypes
OPEN = dict(
    admission_rate=None, open_admission=True, sat_25=None, sat_75=None, act_25=None, act_75=None
)
ELITE = dict(
    admission_rate=0.08, open_admission=False, sat_25=1480, sat_75=1560, act_25=33, act_75=35
)
EASY = dict(
    admission_rate=0.80, open_admission=False, sat_25=1050, sat_75=1250, act_25=20, act_75=26
)
MID = dict(
    admission_rate=0.40, open_admission=False, sat_25=1200, sat_75=1400, act_25=25, act_75=31
)
SAT_ONLY = dict(
    admission_rate=0.60, open_admission=False, sat_25=1100, sat_75=1300, act_25=None, act_75=None
)
NO_RANGES = dict(
    admission_rate=0.70, open_admission=False, sat_25=None, sat_75=None, act_25=None, act_75=None
)
NO_SIGNAL = dict(
    admission_rate=None, open_admission=False, sat_25=1100, sat_75=1300, act_25=None, act_75=None
)
EDGE_15 = dict(
    admission_rate=0.15, open_admission=False, sat_25=1300, sat_75=1450, act_25=None, act_75=None
)
EDGE_50 = dict(
    admission_rate=0.50, open_admission=False, sat_25=1100, sat_75=1300, act_25=None, act_75=None
)

# (id, student(sat, act, gpa), school, band, confidence, position, basis)
CASES = [
    # tier 0 — no student signal (D9) beats every school rule
    ("none-open", (None, None, None), OPEN, "unknown", "normal", None, "no_student_stats"),
    ("none-elite", (None, None, None), ELITE, "unknown", "normal", None, "no_student_stats"),
    ("none-easy", (None, None, None), EASY, "unknown", "normal", None, "no_student_stats"),
    # tier 1 — open admission
    ("open-low-gpa", (None, None, 2.0), OPEN, "safety", "normal", None, "open_admission"),
    ("open-sat", (900, None, None), OPEN, "safety", "normal", None, "open_admission"),
    # tier 2 — selectivity cap (<15%), regardless of stats
    ("elite-perfect", (1600, 36, 4.0), ELITE, "reach", "normal", None, "selective_cap"),
    ("elite-gpa-only", (None, None, 4.0), ELITE, "reach", "normal", None, "selective_cap"),
    ("edge-15-not-capped", (1500, None, None), EDGE_15, "target", "normal", "high", "test"),
    # tier 3 — no admission signal at the school
    ("no-signal", (1400, None, 3.9), NO_SIGNAL, "unknown", "normal", None, "no_school_signal"),
    # tier 4 — SAT position, no GPA
    ("sat-below", (1000, None, None), EASY, "reach", "normal", "low", "test"),
    ("sat-at-25", (1050, None, None), EASY, "target", "normal", "mid", "test"),
    ("sat-mid", (1150, None, None), EASY, "target", "normal", "mid", "test"),
    ("sat-at-75", (1250, None, None), EASY, "target", "normal", "mid", "test"),
    ("sat-above-easy", (1300, None, None), EASY, "safety", "normal", "high", "test"),
    ("sat-above-mid40", (1450, None, None), MID, "target", "normal", "high", "test"),
    ("sat-above-edge50", (1350, None, None), EDGE_50, "safety", "normal", "high", "test"),
    # ACT position
    ("act-below", (None, 18, None), EASY, "reach", "normal", "low", "test"),
    ("act-mid", (None, 23, None), EASY, "target", "normal", "mid", "test"),
    ("act-above", (None, 30, None), EASY, "safety", "normal", "high", "test"),
    # both tests: better position wins
    ("sat-low-act-high", (1000, 30, None), EASY, "safety", "normal", "high", "test"),
    ("sat-high-act-low", (1300, 18, None), EASY, "safety", "normal", "high", "test"),
    # ACT given but school only reports SAT → no test position → GPA path / unknown
    ("act-vs-sat-only-gpa", (None, 30, 3.5), SAT_ONLY, "target", "low", "mid", "gpa_only"),
    (
        "act-vs-sat-only-nogpa",
        (None, 30, None),
        SAT_ONLY,
        "unknown",
        "normal",
        None,
        "no_test_position",
    ),
    # tier 5 — GPA modifier, at most one step
    ("mid-up-gpa38", (1150, None, 3.8), EASY, "safety", "normal", "high", "test"),
    ("mid-up-gpa40-mid40", (1300, None, 4.0), MID, "target", "normal", "high", "test"),
    ("mid-same-gpa35", (1150, None, 3.5), EASY, "target", "normal", "mid", "test"),
    ("mid-same-gpa30", (1150, None, 3.0), EASY, "target", "normal", "mid", "test"),
    ("mid-down-gpa29", (1150, None, 2.9), EASY, "reach", "normal", "low", "test"),
    ("low-up-gpa39", (1000, None, 3.9), EASY, "target", "normal", "mid", "test"),
    ("low-down-clamped", (1000, None, 2.5), EASY, "reach", "normal", "low", "test"),
    ("high-up-clamped", (1300, None, 4.0), EASY, "safety", "normal", "high", "test"),
    ("high-down-gpa25", (1300, None, 2.5), EASY, "target", "normal", "mid", "test"),
    # tier 6 — GPA only (student has no tests, or school reports no ranges)
    ("gpa-only-high-easy", (None, None, 3.9), EASY, "safety", "low", "high", "gpa_only"),
    ("gpa-only-high-mid40", (None, None, 3.9), MID, "target", "low", "high", "gpa_only"),
    ("gpa-only-mid", (None, None, 3.4), EASY, "target", "low", "mid", "gpa_only"),
    ("gpa-only-low", (None, None, 2.8), EASY, "reach", "low", "low", "gpa_only"),
    ("sat-no-ranges-gpa", (1400, None, 3.85), NO_RANGES, "safety", "low", "high", "gpa_only"),
    (
        "sat-no-ranges-nogpa",
        (1400, None, None),
        NO_RANGES,
        "unknown",
        "normal",
        None,
        "no_test_position",
    ),
]


@pytest.mark.parametrize(
    "student,school,band,conf,pos,basis",
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_estimate_table(student, school, band, conf, pos, basis) -> None:
    sat, act, gpa = student
    est = estimate(sat=sat, act=act, gpa=gpa, **school)
    assert (est.band, est.confidence, est.position, est.basis) == (band, conf, pos, basis)


def test_gpa_never_moves_more_than_one_step() -> None:
    for sat in (1000, 1150, 1300):
        base = estimate(sat=sat, act=None, gpa=None, **MID).position
        for gpa in (0.0, 2.0, 2.99, 3.0, 3.79, 3.8, 4.0):
            moved = estimate(sat=sat, act=None, gpa=gpa, **MID).position
            order = ["low", "mid", "high"]
            assert abs(order.index(moved) - order.index(base)) <= 1


def test_estimate_for_reads_profile_and_row() -> None:
    profile = StudentProfile(
        sat=ProfileField[int](value=1300, confidence=1.0),
        gpa=ProfileField[float](value=3.9, confidence=1.0),
    )
    row = SimpleNamespace(**EASY)
    est = estimate_for(profile, row)
    assert est.band == "safety" and est.basis == "test"
