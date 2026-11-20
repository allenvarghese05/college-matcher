"""Shared helpers for the eval harness: paths, persona loading, the frozen region table.

Every eval script imports this first; it puts ``backend/`` and the repo root on
``sys.path`` so ``app.*`` and ``evals.*`` resolve no matter where the script is run from.
"""

from __future__ import annotations

import glob
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
EVALS = REPO / "evals"
for _p in (str(BACKEND), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402

from app.schemas import StudentProfile  # noqa: E402

PERSONA_DIR = EVALS / "personas"
DEFAULT_PERSONAS = str(PERSONA_DIR / "*.yaml")
RESULTS_DIR = EVALS / "results"
LABELS_DIR = EVALS / "labels"
DEFAULT_LABELS = LABELS_DIR / "labels.yaml"

# Keys the simulator may see (evals/personas/README.md): ``meta`` is always stripped.
SIM_KEYS: tuple[str, ...] = ("summary", "hidden_profile", "style", "reveal", "quirks")

# Fields never scored / never said aloud (README "Other field notes").
UNSPOKEN_FIELDS = frozenset({"riasec"})


@dataclass
class Persona:
    id: str
    path: Path
    summary: str
    hidden: dict[str, Any]
    style: str
    reveal: str
    quirks: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def sim_view(self) -> dict[str, Any]:
        """What the simulator receives: summary, hidden_profile, style, reveal, quirks."""
        return {
            "summary": self.summary,
            "hidden_profile": dict(self.hidden),
            "style": self.style,
            "reveal": self.reveal,
            "quirks": list(self.quirks),
        }


def persona_from_doc(doc: dict[str, Any], path: Path | None = None) -> Persona:
    doc = dict(doc)
    meta = doc.pop("meta", None) or {}
    pid = str(doc.get("id") or (path.stem if path else "persona"))
    return Persona(
        id=pid,
        path=path or Path(f"{pid}.yaml"),
        summary=str(doc.get("summary") or ""),
        hidden=dict(doc.get("hidden_profile") or {}),
        style=str(doc.get("style") or ""),
        reveal=str(doc.get("reveal") or "only_when_asked"),
        quirks=[str(q) for q in doc.get("quirks") or []],
        meta=dict(meta),
    )


def load_persona(path: str | Path) -> Persona:
    p = Path(path)
    return persona_from_doc(yaml.safe_load(p.read_text()) or {}, p)


def load_personas(pattern: str = DEFAULT_PERSONAS, limit: int | None = None) -> list[Persona]:
    """Personas matching ``pattern`` (a glob, or a comma-separated list of ids/globs)."""
    paths: list[str] = []
    for part in [x.strip() for x in pattern.split(",") if x.strip()]:
        if not any(ch in part for ch in "*?[/") and not part.endswith(".yaml"):
            part = str(PERSONA_DIR / f"{part}.yaml")
        paths.extend(sorted(glob.glob(part)))
    out = [load_persona(p) for p in dict.fromkeys(paths)]
    return out[:limit] if limit else out


def gold_profile(hidden: dict[str, Any]) -> StudentProfile:
    """Gold profile: every hidden field as a ProfileField with confidence 1.0."""
    from evals.ablation import profile_from_hidden

    return profile_from_hidden(hidden)


# Frozen Census table (evals/labels/criteria.md H3) — deliberately NOT imported from
# app.retrieval.geo, so a mapping bug in the retriever can't leak into labels/scoring.
DIVISIONS: dict[str, frozenset[str]] = {
    "new_england": frozenset("CT ME MA NH RI VT".split()),
    "mid_atlantic": frozenset("NJ NY PA".split()),
    "east_north_central": frozenset("IL IN MI OH WI".split()),
    "west_north_central": frozenset("IA KS MN MO NE ND SD".split()),
    "south_atlantic": frozenset("DE DC FL GA MD NC SC VA WV".split()),
    "east_south_central": frozenset("AL KY MS TN".split()),
    "west_south_central": frozenset("AR LA OK TX".split()),
    "mountain": frozenset("AZ CO ID MT NV NM UT WY".split()),
    "pacific": frozenset("AK CA HI OR WA".split()),
}
REGIONS: dict[str, frozenset[str]] = {
    "northeast": DIVISIONS["new_england"] | DIVISIONS["mid_atlantic"],
    "midwest": DIVISIONS["east_north_central"] | DIVISIONS["west_north_central"],
    "south": DIVISIONS["south_atlantic"]
    | DIVISIONS["east_south_central"]
    | DIVISIONS["west_south_central"],
    "west": DIVISIONS["mountain"] | DIVISIONS["pacific"],
}
ALL_STATES: frozenset[str] = frozenset().union(*DIVISIONS.values())


def frozen_states_for_regions(regions: list[str], home_state: str | None) -> set[str]:
    """Union of listed regions/divisions/states; ``out_of_state`` also excludes home."""
    out: set[str] = set()
    exclude_home = False
    for raw in regions:
        key = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
        if key in REGIONS:
            out |= REGIONS[key]
        elif key in DIVISIONS:
            out |= DIVISIONS[key]
        elif key == "out_of_state":
            out |= ALL_STATES
            exclude_home = True
        elif str(raw).strip().upper() in ALL_STATES:
            out.add(str(raw).strip().upper())
    if exclude_home and home_state:
        out.discard(home_state.upper())
    return out


def git_sha(path: str | Path | None = None) -> str:
    """Last commit touching ``path`` (or HEAD); ``"unknown"`` outside git."""
    cmd = ["git", "-C", str(REPO), "log", "-1", "--format=%H"]
    if path is not None:
        cmd += ["--", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank-with-interpolation percentile (q in 0..100); None when empty."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
