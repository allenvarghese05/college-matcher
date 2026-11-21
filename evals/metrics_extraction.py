"""Deterministic extraction metrics: final profile vs ``hidden_profile`` (SPEC §10).

Per field, each persona contributes true positives / false positives / false negatives:

* **Scalars** (one value). Hidden value present: match -> TP; nothing extracted -> FN;
  wrong value -> FP + FN. Key absent from ``hidden_profile`` -> anything extracted is FP.
  Tolerances: GPA ±0.05, SAT ±10, ACT ±1, ``budget_cap`` ±5%, ``max_distance_miles``
  ±10% (criteria.md H3: students' distances are rough). ``home_state`` compares USPS
  codes; ``home_zip`` the first 5 digits; enums (``income_bracket``, ``size_pref``,
  ``setting_pref``) exactly after lower-casing. ``dream_without_money`` is free text: it
  matches when at least half of the hidden sentence's content words (stemmed) appear.
* **Lists**: items are normalised and matched one-to-one (greedy). Free-text lists
  (``interests``, ``strengths``, ``favorite_subjects``, ``intended_majors``, activity
  names) match when one item's content words cover ≥ 50% of the other's, or one is a
  substring of the other. Enum lists (``work_values``, ``priorities``) and ``regions``
  (state names -> codes, Census names -> snake_case) match exactly. TP = matched items,
  FN = unmatched hidden items, FP = unmatched extracted items.
  Hidden ``[]`` (known empty): an empty/null extraction is correct and never counts;
  each extracted item is an FP. Absent key: each extracted item is an FP.
* ``riasec`` is never said aloud (README) and is not scored.

**Interest signal** (:func:`interest_signal_counts`): ``interests`` scored strictly
undercounts — the extractor reasonably files "i'm good at drawing" under ``strengths``
and "fixing bikes" under ``activities``. So a second, clearly labelled score counts a
hidden ``interests`` item as recovered if it fuzzy-matches (same rule as free-text
lists but with whole-word substrings, one-to-one) any extracted item in
``interests`` ∪ ``strengths`` ∪ ``activities[].name`` ∪ ``dream_without_money`` ∪
``favorite_subjects``. An extracted ``interests`` item left unmatched is an FP only if
it also matches nothing in the hidden profile's same five fields. Reported as the
``interests (any field)`` row and as micro totals with that row substituted for strict
``interests``; the strict per-field row and strict micro totals are unchanged and remain
the headline numbers.

**Questions-asked coverage** (:func:`questions_asked`): a hidden field counts as asked if
any counselor reply contains a *question sentence* about the field's intake topic
(:mod:`evals.topics` keyword heuristics, e.g. "how far from home…?" -> location ->
``home_state``, ``home_zip``, ``max_distance_miles``, ``regions``). The web app's fixed
greeting is not counted. As a second, independent signal the planner's persisted
``next_topic`` sequence gives **planned coverage** (topics the counselor was steered
to). Both are heuristics; spot-check transcripts before trusting small differences.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.counselor.context import to_usps
from app.schemas import PROFILE_FIELDS
from evals.common import UNSPOKEN_FIELDS
from evals.topics import FIELD_TOPIC, asked_topics

SCORED_FIELDS: tuple[str, ...] = tuple(f for f in PROFILE_FIELDS if f not in UNSPOKEN_FIELDS)
NUM_TOL: dict[str, tuple[str, float]] = {
    "gpa": ("abs", 0.05),
    "sat": ("abs", 10),
    "act": ("abs", 1),
    "budget_cap": ("rel", 0.05),
    "max_distance_miles": ("rel", 0.10),
}
ENUM_SCALARS = frozenset({"income_bracket", "size_pref", "setting_pref"})
FUZZY_LISTS = frozenset({"interests", "strengths", "favorite_subjects", "intended_majors"})
EXACT_LISTS = frozenset({"work_values", "priorities", "regions"})
LIST_FIELDS = FUZZY_LISTS | EXACT_LISTS | {"activities"}

_STOP = set(
    "a an the and or of to in on for with my i me at by from about stuff thing things like "
    "really just some all being be do doing".split()
)


def _stem(w: str) -> str:
    for suf in ("ing", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9']+", str(text).lower()) if w not in _STOP}


def norm_text(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+\- ]", " ", str(text).lower())).strip()


def _contains(outer: str, inner: str, word_bounded: bool) -> bool:
    if not word_bounded:
        return inner in outer
    return re.search(rf"(?<![a-z0-9]){re.escape(inner)}(?![a-z0-9])", outer) is not None


def fuzzy_match(a: str, b: str, *, word_bounded: bool = False) -> bool:
    """Substring or >= 50% content-word overlap. ``word_bounded`` makes the substring
    test whole-word ("art" does not match "start"); the interest signal uses it."""
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return False
    if _contains(nb, na, word_bounded) or _contains(na, nb, word_bounded):
        return True
    wa, wb = content_words(na), content_words(nb)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def norm_region(r: Any) -> str:
    s = str(r).strip()
    code = to_usps(s)
    if code:
        return code
    return s.lower().replace("-", "_").replace(" ", "_")


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __iadd__(self, other: Counts) -> Counts:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn
        return self

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
        }


def _empty(v: Any) -> bool:
    return v is None or v == [] or v == ""


def scalar_match(name: str, got: Any, want: Any) -> bool:
    if name in NUM_TOL:
        try:
            g, w = float(got), float(want)
        except (TypeError, ValueError):
            return False
        kind, tol = NUM_TOL[name]
        limit = tol if kind == "abs" else abs(w) * tol
        return abs(g - w) <= limit + 1e-9
    if name == "home_state":
        return (to_usps(str(got)) or str(got).upper()) == (to_usps(str(want)) or str(want).upper())
    if name == "home_zip":
        return re.sub(r"\D", "", str(got))[:5] == re.sub(r"\D", "", str(want))[:5]
    if name in ENUM_SCALARS:
        return norm_text(got).replace(" ", "_") == norm_text(want).replace(" ", "_")
    if name == "dream_without_money":
        want_w = content_words(want)
        return bool(want_w) and len(want_w & content_words(got)) / len(want_w) >= 0.5
    return norm_text(got) == norm_text(want)


def _items(name: str, values: list[Any]) -> list[str]:
    if name == "activities":
        return [str(v.get("name", "")) if isinstance(v, dict) else str(v) for v in values]
    if name == "regions":
        return [norm_region(v) for v in values]
    if name in EXACT_LISTS:
        return [norm_text(v).replace(" ", "_") for v in values]
    return [str(v) for v in values]


def list_counts(name: str, got: list[Any], want: list[Any]) -> Counts:
    g = list(dict.fromkeys(_items(name, got)))
    w = list(dict.fromkeys(_items(name, want)))
    exact = name in EXACT_LISTS
    used: set[int] = set()
    tp = 0
    for item in w:
        for j, cand in enumerate(g):
            if j in used:
                continue
            if (item == cand) if exact else fuzzy_match(item, cand):
                used.add(j)
                tp += 1
                break
    return Counts(tp=tp, fp=len(g) - len(used), fn=len(w) - tp)


def field_counts(name: str, extracted: Any, hidden: dict[str, Any]) -> Counts:
    present = name in hidden
    want = hidden.get(name)
    is_list = name in LIST_FIELDS
    if not present or (is_list and want == []):
        if _empty(extracted):
            return Counts()
        return Counts(fp=len(extracted) if is_list and isinstance(extracted, list) else 1)
    if _empty(extracted):
        return Counts(fn=len(want) if is_list else 1)
    if is_list:
        return list_counts(name, list(extracted), list(want))
    return Counts(tp=1) if scalar_match(name, extracted, want) else Counts(fp=1, fn=1)


def profile_values(profile: dict[str, Any]) -> dict[str, Any]:
    """``StudentProfile.model_dump()`` -> {field: value}."""
    out: dict[str, Any] = {}
    for name, pf in (profile or {}).items():
        out[name] = pf.get("value") if isinstance(pf, dict) else pf
    return out


def score_profile(profile: dict[str, Any], hidden: dict[str, Any]) -> dict[str, Counts]:
    values = profile_values(profile)
    return {f: field_counts(f, values.get(f), hidden) for f in SCORED_FIELDS}


# ------------------------------------------------------------ interest signal

INTEREST_SIGNAL_FIELDS: tuple[str, ...] = (
    "interests",
    "strengths",
    "activities",
    "dream_without_money",
    "favorite_subjects",
)


def interest_pool(values: dict[str, Any]) -> list[str]:
    """Free-text items from the interest-signal fields (activity names, the dream)."""
    pool: list[str] = []
    for name in INTEREST_SIGNAL_FIELDS:
        v = values.get(name)
        if _empty(v):
            continue
        items = v if isinstance(v, list) else [v]
        pool.extend(i for i in _items(name, items) if i)
    return pool


def interest_signal_counts(values: dict[str, Any], hidden: dict[str, Any]) -> Counts:
    """``interests`` scored as an interest *signal* across fields (module docstring).

    Falls back to the strict rule when the hidden ``interests`` key is absent or ``[]``.
    """
    want = hidden.get("interests")
    if not want:
        return field_counts("interests", values.get("interests"), hidden)
    pool = list(dict.fromkeys(interest_pool(values)))
    used: set[int] = set()
    tp = 0
    for item in dict.fromkeys(str(w) for w in want):
        for j, cand in enumerate(pool):
            if j not in used and fuzzy_match(item, cand, word_bounded=True):
                used.add(j)
                tp += 1
                break
    matched = {pool[j] for j in used}
    hidden_pool = interest_pool(hidden)
    got = list(dict.fromkeys(str(g) for g in values.get("interests") or []))
    fp = sum(
        1
        for g in got
        if g not in matched and not any(fuzzy_match(g, h, word_bounded=True) for h in hidden_pool)
    )
    return Counts(tp=tp, fp=fp, fn=len(dict.fromkeys(str(w) for w in want)) - tp)


def with_interest_signal(counts: dict[str, Counts], signal: Counts) -> Counts:
    """Micro totals with the interest-signal row substituted for strict ``interests``."""
    total = Counts()
    for f, c in counts.items():
        total += signal if f == "interests" else c
    return total


# ----------------------------------------------------------- questions-asked


def questions_asked(
    counselor_turns: list[str], hidden: dict[str, Any], next_topics: list[str | None] | None = None
) -> dict[str, Any]:
    fields = [f for f in hidden if f in FIELD_TOPIC]
    topics: set[str] = set()
    for text in counselor_turns:
        topics |= asked_topics(text)
    planned = {t for t in next_topics or [] if t}
    if "strengths" in planned:  # the planner's combined classes + strengths question
        planned.add("favorite_subjects")
    asked = sorted(f for f in fields if FIELD_TOPIC[f] in topics)
    planned_fields = sorted(f for f in fields if FIELD_TOPIC[f] in planned)
    n = len(fields)
    return {
        "n_fields": n,
        "asked": asked,
        "not_asked": sorted(set(fields) - set(asked)),
        "coverage": len(asked) / n if n else None,
        "planned_coverage": len(planned_fields) / n if n else None,
    }


# --------------------------------------------------------------- aggregate


@dataclass
class ExtractionSummary:
    per_field: dict[str, Counts] = field(default_factory=dict)
    overall: Counts = field(default_factory=Counts)
    interest_signal: Counts = field(default_factory=Counts)
    overall_interest_signal: Counts = field(default_factory=Counts)
    per_persona: dict[str, dict[str, Any]] = field(default_factory=dict)
    coverage: float | None = None
    planned_coverage: float | None = None
    n: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "overall": self.overall.to_dict(),
            "per_field": {f: c.to_dict() for f, c in self.per_field.items()},
            "interest_signal": self.interest_signal.to_dict(),
            "overall_interest_signal": self.overall_interest_signal.to_dict(),
            "coverage": self.coverage,
            "planned_coverage": self.planned_coverage,
            "per_persona": self.per_persona,
        }


def aggregate_extraction(
    results: list[dict[str, Any]], hidden_by_persona: dict[str, dict[str, Any]]
) -> ExtractionSummary:
    summ = ExtractionSummary(per_field={f: Counts() for f in SCORED_FIELDS})
    covs: list[float] = []
    planned: list[float] = []
    for res in results:
        pid = res.get("persona")
        if pid not in hidden_by_persona or res.get("final_profile") is None:
            continue
        hidden = hidden_by_persona[pid]
        counts = score_profile(res["final_profile"], hidden)
        overall = Counts()
        for f, c in counts.items():
            summ.per_field[f] += c
            overall += c
        summ.overall += overall
        signal = interest_signal_counts(profile_values(res["final_profile"]), hidden)
        overall_signal = with_interest_signal(counts, signal)
        summ.interest_signal += signal
        summ.overall_interest_signal += overall_signal
        qa = questions_asked(
            [t.get("counselor", "") for t in res.get("turns", [])],
            hidden,
            res.get("next_topics"),
        )
        if qa["coverage"] is not None:
            covs.append(qa["coverage"])
        if qa["planned_coverage"] is not None:
            planned.append(qa["planned_coverage"])
        summ.per_persona[pid] = {
            "overall": overall.to_dict(),
            "fields": {f: c.to_dict() for f, c in counts.items() if c.tp or c.fp or c.fn},
            "interests_any_field": signal.to_dict(),
            "overall_interest_signal": overall_signal.to_dict(),
            "questions_asked": qa,
        }
        summ.n += 1
    summ.coverage = sum(covs) / len(covs) if covs else None
    summ.planned_coverage = sum(planned) / len(planned) if planned else None
    return summ
