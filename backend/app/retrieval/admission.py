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
