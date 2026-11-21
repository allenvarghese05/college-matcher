"""Deterministic admission estimator (SPEC §9), always labelled "estimated".

Tiers, applied in order:

0. **No student signal** (no GPA, SAT or ACT) → ``unknown``. SPEC D9: bands are shown
   only when GPA or test scores are present, so this check comes first — even
   open-admission and highly selective schools are ``unknown`` for a student who
   shared nothing.
1. **Open admission** (``open_admission``) → ``safety``.
2. **Selectivity cap**: admission rate < 15% → ``reach`` regardless of stats.
3. **No admission signal at the school** (no admission rate, not open admission)
   → ``unknown``.
4. **Test position**: SAT vs the school's SAT 25th–75th, ACT vs ACT 25th–75th
   (if both are usable the better position wins): below 25th → low,
   25th–75th inclusive → mid, above 75th → high.
5. **GPA modifier** (only when a test position exists): GPA ≥ 3.8 moves the position
   up one step, GPA < 3.0 down one step; never more than one step.
6. **GPA-only path** (no usable test position but a GPA): GPA ≥ 3.8 → high,
   GPA < 3.0 → low, otherwise mid; ``band_confidence = "low"``.
   No test position and no GPA → ``unknown``.
7. **Map** position + admission rate: high and admit ≥ 50% → ``safety``;
   low → ``reach``; otherwise ``target``.

Scorecard has no school GPA data, so GPA is a modifier, never a comparison.

Far reach (:func:`is_far_reach`)
--------------------------------
A *far reach* is a reach where nothing in the data suggests the student is competitive.
It does not change the band (the school stays an honest "reach"); Stage C uses it to
keep long shots from crowding the top of the list (``rerank.balance_bands``). The rule
is stated relative to each school's own score spread rather than in fixed points:

* open admission, or no admission rate → never far;
* admission rate < 15% (``SELECTIVE_CAP``) → far unless the student is in the school's
  top quartile on a test (≥ 75th percentile), or has no usable test position but a
  GPA ≥ 3.8 (``GPA_UP``); with no stats at all it is far (a long shot for anyone);
* admission rate < 50% with a usable test position → far when the student is below the
  25th percentile by more than half the school's interquartile range (25th–75th);
* admission rate < 25% with only a GPA → far when GPA < 3.5;
* otherwise not far.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.schemas import AdmissionBand, BandConfidence, StudentProfile

Position = Literal["low", "mid", "high"]
_ORDER: tuple[Position, ...] = ("low", "mid", "high")

SELECTIVE_CAP = 0.15
SAFETY_MIN_ADMIT = 0.50
GPA_UP = 3.8
GPA_DOWN = 3.0


@dataclass(frozen=True)
class AdmissionEstimate:
    band: AdmissionBand
    confidence: BandConfidence
    position: Position | None
    basis: str  # short machine-readable reason, e.g. "open_admission", "test", "gpa_only"


def _test_position(score: int | None, lo: int | None, hi: int | None) -> Position | None:
    if score is None or lo is None or hi is None:
        return None
    if score < lo:
        return "low"
    if score > hi:
        return "high"
    return "mid"


def _shift(pos: Position, step: int) -> Position:
    i = max(0, min(2, _ORDER.index(pos) + step))
    return _ORDER[i]


def _gpa_step(gpa: float) -> int:
    if gpa >= GPA_UP:
        return 1
    if gpa < GPA_DOWN:
        return -1
    return 0


def estimate(
    *,
    sat: int | None,
    act: int | None,
    gpa: float | None,
    admission_rate: float | None,
    open_admission: bool | None,
    sat_25: int | None,
    sat_75: int | None,
    act_25: int | None,
    act_75: int | None,
) -> AdmissionEstimate:
    """Pure function: student stats + school stats → band (see module docstring)."""
    if sat is None and act is None and gpa is None:
        return AdmissionEstimate("unknown", "normal", None, "no_student_stats")
    if open_admission:
        return AdmissionEstimate("safety", "normal", None, "open_admission")
    if admission_rate is not None and admission_rate < SELECTIVE_CAP:
        return AdmissionEstimate("reach", "normal", None, "selective_cap")
    if admission_rate is None:
        return AdmissionEstimate("unknown", "normal", None, "no_school_signal")

    positions = [
        p
        for p in (
            _test_position(sat, sat_25, sat_75),
            _test_position(act, act_25, act_75),
        )
        if p is not None
    ]
    confidence: BandConfidence
    if positions:
        pos = max(positions, key=_ORDER.index)
        if gpa is not None:
            pos = _shift(pos, _gpa_step(gpa))
        confidence, basis = "normal", "test"
    elif gpa is not None:
        pos = _shift("mid", _gpa_step(gpa))
        confidence, basis = "low", "gpa_only"
    else:
        return AdmissionEstimate("unknown", "normal", None, "no_test_position")

    band: AdmissionBand
    if pos == "high" and admission_rate >= SAFETY_MIN_ADMIT:
        band = "safety"
    elif pos == "low":
        band = "reach"
    else:
        band = "target"
    return AdmissionEstimate(band, confidence, pos, basis)


FAR_MAX_ADMIT = 0.50
FAR_IQR_FRACTION = 0.5
FAR_GPA_ONLY_ADMIT = 0.25
FAR_GPA_ONLY_GPA = 3.5


def _iqr_gap(score: int | None, lo: int | None, hi: int | None) -> float | None:
    """How far below the 25th percentile, in units of the school's IQR (≤ 0: not below)."""
    if score is None or lo is None or hi is None:
        return None
    return (lo - score) / max(hi - lo, 1)


def is_far_reach(profile: StudentProfile, school: Any) -> bool:
    """See the module docstring ("Far reach")."""
    if school.open_admission or school.admission_rate is None:
        return False
    rate = float(school.admission_rate)
    sat, act, gpa = profile.sat.value, profile.act.value, profile.gpa.value
    gaps = [
        g
        for g in (
            _iqr_gap(sat, school.sat_25, school.sat_75),
            _iqr_gap(act, school.act_25, school.act_75),
        )
        if g is not None
    ]
    if rate < SELECTIVE_CAP:
        top_quartile = (sat is not None and school.sat_75 is not None and sat >= school.sat_75) or (
            act is not None and school.act_75 is not None and act >= school.act_75
        )
        if top_quartile:
            return False
        return bool(gaps) or gpa is None or gpa < GPA_UP
    if rate >= FAR_MAX_ADMIT:
        return False
    if gaps:
        return min(gaps) > FAR_IQR_FRACTION
    if gpa is not None:
        return rate < FAR_GPA_ONLY_ADMIT and gpa < FAR_GPA_ONLY_GPA
    return False


def estimate_for(profile: StudentProfile, school: Any) -> AdmissionEstimate:
    """Convenience wrapper: ``school`` is any object with the Institution column attrs."""
    return estimate(
        sat=profile.sat.value,
        act=profile.act.value,
        gpa=profile.gpa.value,
        admission_rate=school.admission_rate,
        open_admission=school.open_admission,
        sat_25=school.sat_25,
        sat_75=school.sat_75,
        act_25=school.act_25,
        act_75=school.act_75,
    )
