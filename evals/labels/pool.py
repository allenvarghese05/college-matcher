"""Candidate-pool generator for labeling (evals/labels/criteria.md, "Pooling").

    judged pool = stratified sample of schools passing H1–H4  ∪  top-10 of every
                  retrieval mode × {gold, e2e}  (from one or more run dirs)

Per persona (needs its ``major_cip4s`` in ``evals/labels/major_sets.yaml`` — pass 1,
written by the labeler before any pool exists):

* **H1** offers a bachelor's (``credential_level = 3``) program in a ``major_cip4s`` code.
* **H2** net price at the income bracket (``avg_net_price`` fallback; both missing ->
  fail) ≤ ``budget_cap × 1.15``, else the bracket default (110k+ with ``prestige``: no
  ceiling). **Out-of-state publics** use bracket net price + (``TUITIONFEE_OUT`` −
  ``TUITIONFEE_IN``) from the raw Scorecard institution CSV (read-only) or, when the
  CSV is absent, the DB's ``tuition_in_state`` / ``tuition_out_of_state``; missing
  tuition -> fail. Unlike the app's ``pricing.py`` the surcharge is NOT floored at 0.
  Reciprocity prices (WUE, MSEP, ACM, RSP) are not automated: the labeler applies them
  by hand and says so in ``notes``.
  Relaxation: if fewer than 5 schools pass H1–H4, the cap is relaxed once to the bracket
  default and recorded as ``relaxed: [budget]``.
* **H3** ``max_distance_miles × 1.10`` from the home ZIP (centroid of Scorecard
  institutions in the same ZIP5, else ZIP3, else the state's population centre — there
  is no ZIP geocoding table in the project), else ``regions`` with the frozen Census
  table (union; ``out_of_state`` excludes home), else no constraint.
* **H4** admission plausibility from raw Scorecard ranges (2018 ACT/SAT concordance),
  deliberately not the system's estimator. The set-level band-mix check happens after
  scoring, in ``label.py``.

Sample: if ≤ 60 schools pass, all of them; else 60 drawn stratified by control ×
admission band, largest-remainder allocation, fixed seed per persona. System top-10
schools that fail a hard criterion are **auto-judged not acceptable** and not shown.

Writes ``evals/labels/pools/<persona>.csv`` (shown rows, shuffled with a fixed seed, no
source / rank / score columns, duplicates collapsed) and ``<persona>.meta.yaml``
(``major_cip4s``, ``pool_size``, ``relaxed``, auto-judged unitids with reasons, tool
version). Usage (from ``backend/``)::

    uv run python ../evals/labels/pool.py --runs ../evals/results/<run_id> [--personas ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [p for p in (str(_REPO), str(_REPO / "backend")) if p not in sys.path]

import argparse  # noqa: E402
import asyncio  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402

import yaml  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import CipCode, Institution, Program  # noqa: E402
from app.retrieval.geo import STATE_CENTROIDS, haversine_miles  # noqa: E402
from evals.common import (  # noqa: E402
    DEFAULT_PERSONAS,
    LABELS_DIR,
    REPO,
    Persona,
    frozen_states_for_regions,
    git_sha,
    load_personas,
)

POOLS_DIR = LABELS_DIR / "pools"
MAJOR_SETS = LABELS_DIR / "major_sets.yaml"
RAW_INSTITUTIONS = REPO / "data" / "raw" / "scorecard" / "Most-Recent-Cohorts-Institution.csv"
DEFAULT_SEED = 20261119
SAMPLE_SIZE = 60
MIN_PASSING = 5
BUDGET_SLACK = 1.15
DISTANCE_SLACK = 1.10

BRACKET_DEFAULT: dict[str, float | None] = {
    "0-30k": 12000,
    "30-48k": 15000,
    "48-75k": 20000,
    "75-110k": 27000,
    "110k+": 40000,
}
BRACKET_COLUMN = {
    "0-30k": "net_price_0_30k",
    "30-48k": "net_price_30_48k",
    "48-75k": "net_price_48_75k",
    "75-110k": "net_price_75_110k",
    "110k+": "net_price_110k_plus",
}
# 2018 ACT/College Board concordance: ACT composite -> SAT total.
ACT_TO_SAT: dict[int, int] = {
    36: 1590, 35: 1540, 34: 1500, 33: 1460, 32: 1430, 31: 1400, 30: 1370, 29: 1340,
    28: 1310, 27: 1280, 26: 1240, 25: 1210, 24: 1180, 23: 1140, 22: 1110, 21: 1080,
    20: 1040, 19: 1010, 18: 970, 17: 930, 16: 890, 15: 850, 14: 800, 13: 760, 12: 710,
    11: 670, 10: 630, 9: 590,
}  # fmt: skip
CONTROL = {1: "public", 2: "private nonprofit", 3: "private for-profit"}
LOCALE = {1: "city", 2: "suburb", 3: "town", 4: "rural"}
CSV_COLUMNS = [
    "unitid",
    "name",
    "city",
    "state",
    "control",
    "undergrad_size",
    "locale",
    "net_price",
    "out_of_state_estimate",
    "admission_rate",
    "sat_range",
    "act_range",
    "programs",
    "distance_miles",
]


def sat_to_act(sat: int) -> int:
    """Highest ACT whose concordant SAT is ≤ ``sat`` (9 at the floor)."""
    best = 9
    for act, s in sorted(ACT_TO_SAT.items()):
        if s <= sat:
            best = act
    return best


def norm_cip4(code: str) -> str:
    """'50.04' / '5004' / '5.4' -> '5004' (the DB's 4-char CIP-4)."""
    s = str(code).strip()
    if "." in s:
        a, b = s.split(".", 1)
        return a.zfill(2) + b[:2].ljust(2, "0")
    return s.zfill(4)


@dataclass
class ProgramInfo:
    cip4: str
    title: str
    earnings: int | None = None


@dataclass
class School:
    unitid: int
    name: str
    city: str
    state: str
    control: int
    locale: int | None = None
    undergrad_size: int | None = None
    lat: float | None = None
    lon: float | None = None
    admission_rate: float | None = None
    open_admission: bool | None = None
    sat_25: int | None = None
    sat_75: int | None = None
    act_25: int | None = None
    act_75: int | None = None
    net_prices: dict[str, int | None] = field(default_factory=dict)
    avg_net_price: int | None = None
    programs: list[ProgramInfo] = field(default_factory=list)
    tuition_in: float | None = None
    tuition_out: float | None = None


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    net_price: float | None = None
    oos_estimate: float | None = None
    distance: float | None = None


# --------------------------------------------------------------- hard criteria


def h2_ceiling(hidden: dict[str, Any], relaxed: bool = False) -> float | None:
    bracket = hidden.get("income_bracket")
    default = BRACKET_DEFAULT.get(str(bracket))
    if bracket == "110k+" and "prestige" in (hidden.get("priorities") or []):
        default = None
    cap = hidden.get("budget_cap")
    if cap and not relaxed:
        return float(cap) * BUDGET_SLACK
    return default


def h2(school: School, hidden: dict[str, Any], relaxed: bool = False) -> Verdict:
    col = BRACKET_COLUMN.get(str(hidden.get("income_bracket")))
    net = school.net_prices.get(col) if col else None
    if net is None:
        net = school.avg_net_price
    if net is None:
        return Verdict(False, ["H2: no net price"])
    ceiling = h2_ceiling(hidden, relaxed)
    price: float = float(net)
    v = Verdict(True, net_price=float(net))
    home = str(hidden.get("home_state") or "").upper()
    if school.control == 1 and school.state.upper() != home:
        if school.tuition_in is None or school.tuition_out is None:
            return Verdict(False, ["H2: out-of-state public, tuition missing"], float(net))
        price = float(net) + (school.tuition_out - school.tuition_in)
        v.oos_estimate = price
    if ceiling is not None and price > ceiling:
        what = "out-of-state estimate" if v.oos_estimate is not None else "net price"
        v.ok = False
        v.reasons.append(f"H2: {what} {price:,.0f} > {ceiling:,.0f}")
    return v


def h3(school: School, hidden: dict[str, Any], home_ll: tuple[float, float] | None) -> Verdict:
    dist = None
    if home_ll and school.lat is not None and school.lon is not None:
        dist = haversine_miles(home_ll[0], home_ll[1], school.lat, school.lon)
    v = Verdict(True, distance=dist)
    maxd = hidden.get("max_distance_miles")
    regions = hidden.get("regions") or []
    if maxd:
        if dist is None or dist > float(maxd) * DISTANCE_SLACK:
            v.ok = False
            v.reasons.append(f"H3: distance {'?' if dist is None else round(dist)} > {maxd}")
    elif regions:
        if school.state.upper() not in frozen_states_for_regions(regions, hidden.get("home_state")):
            v.ok = False
            v.reasons.append(f"H3: {school.state} not in {regions}")
    return v


def student_score(
    hidden: dict[str, Any], school_has_sat: bool, school_has_act: bool
) -> tuple[str, float] | None:
    """The student's score in the units to compare with a school (criteria.md H4).

    Use the student's own test when the school reports it (SAT if the student has both
    and the school reports both); concord (2018 ACT/SAT table) ONLY when the school
    reports just the other test. None if either side has no usable score.
    """
    sat, act = hidden.get("sat"), hidden.get("act")
    if sat is not None and school_has_sat:
        return "sat", float(sat)
    if act is not None and school_has_act:
        return "act", float(act)
    if act is not None and school_has_sat:  # school reports only SAT
        return "sat", float(ACT_TO_SAT.get(int(act), 590))
    if sat is not None and school_has_act:  # school reports only ACT
        return "act", float(sat_to_act(int(sat)))
    return None


def _student_vs(school: School, hidden: dict[str, Any], pct: str) -> tuple[float, str] | None:
    """(student score − school's ``pct`` percentile, units) per :func:`student_score`."""
    s_sat = getattr(school, f"sat_{pct}")
    s_act = getattr(school, f"act_{pct}")
    got = student_score(hidden, s_sat is not None, s_act is not None)
    if got is None:
        return None
    unit, mine = got
    return mine - float(s_sat if unit == "sat" else s_act), unit


def h4(school: School, hidden: dict[str, Any]) -> Verdict:
    if school.open_admission:
        return Verdict(True)
    rate = school.admission_rate
    has_test = hidden.get("sat") is not None or hidden.get("act") is not None
    gpa = hidden.get("gpa")
    below25 = _student_vs(school, hidden, "25")
    if below25 is not None and rate is not None and rate < 0.5:
        diff, unit = below25
        if -diff > (80 if unit == "sat" else 3):
            return Verdict(False, ["H4: far below 25th percentile at a <50% school"])
    if rate is not None and rate < 0.15:
        vs75 = _student_vs(school, hidden, "75")
        if not ((vs75 is not None and vs75[0] >= 0) or (not has_test and gpa and gpa >= 3.85)):
            return Verdict(False, ["H4: admission rate < 15%"])
    if not has_test and gpa is not None and rate is not None:
        if gpa < 3.0 and rate < 0.30:
            return Verdict(False, ["H4: GPA < 3.0 at a <30% school"])
        if 3.0 <= gpa < 3.5 and rate < 0.20:
            return Verdict(False, ["H4: GPA 3.0-3.49 at a <20% school"])
    return Verdict(True)


def judge(
    school: School,
    hidden: dict[str, Any],
    cip4s: set[str],
    home_ll: tuple[float, float] | None,
    relaxed: bool = False,
) -> Verdict:
    matched = [p for p in school.programs if p.cip4 in cip4s]
    reasons: list[str] = [] if matched else ["H1: no bachelor's in the major set"]
    v2, v3, v4 = h2(school, hidden, relaxed), h3(school, hidden, home_ll), h4(school, hidden)
    reasons += v2.reasons + v3.reasons + v4.reasons
    return Verdict(not reasons, reasons, v2.net_price, v2.oos_estimate, v3.distance)


# ------------------------------------------------------------------ sampling


def admission_band(s: School) -> str:
    r = s.admission_rate
    if s.open_admission:
        return "open"
    if r is None:
        return "unknown"
    for cut, name in ((0.15, "<15"), (0.25, "15-25"), (0.5, "25-50"), (0.75, "50-75")):
        if r < cut:
            return name
    return "75+"


def stratified_sample(schools: list[School], n: int, rng: random.Random) -> list[School]:
    if len(schools) <= n:
        return list(schools)
    strata: dict[tuple[int, str], list[School]] = {}
    for s in sorted(schools, key=lambda s: s.unitid):
        strata.setdefault((s.control, admission_band(s)), []).append(s)
    total = len(schools)
    quotas = {k: n * len(v) / total for k, v in strata.items()}
    alloc = {k: int(q) for k, q in quotas.items()}
    left = n - sum(alloc.values())
    for k in sorted(quotas, key=lambda k: (-(quotas[k] - alloc[k]), k))[:left]:
        alloc[k] += 1
    out: list[School] = []
    for k in sorted(strata):
        out += rng.sample(strata[k], min(alloc[k], len(strata[k])))
    return out


# --------------------------------------------------------------------- pool


@dataclass
class Pool:
    persona: str
    rows: list[dict[str, Any]]
    pool_size: int
    relaxed: list[str]
    auto_judged: list[dict[str, Any]]
    major_cip4s: list[str]
    n_sampled: int
    n_system: int


def _row(s: School, v: Verdict, cip4s: set[str]) -> dict[str, Any]:
    progs = []
    for p in s.programs:
        if p.cip4 in cip4s:
            earn = f" (earnings ${p.earnings:,})" if p.earnings else ""
            progs.append(f"{p.title}{earn}")

    def rng(lo: int | None, hi: int | None) -> str:
        return f"{lo}-{hi}" if lo is not None and hi is not None else ""

    return {
        "unitid": s.unitid,
        "name": s.name,
        "city": s.city,
        "state": s.state,
        "control": CONTROL.get(s.control, str(s.control)),
        "undergrad_size": s.undergrad_size if s.undergrad_size is not None else "",
        "locale": LOCALE.get((s.locale or 0) // 10, ""),
        "net_price": round(v.net_price) if v.net_price is not None else "",
        "out_of_state_estimate": round(v.oos_estimate) if v.oos_estimate is not None else "",
        "admission_rate": f"{s.admission_rate:.2f}" if s.admission_rate is not None else "",
        "sat_range": rng(s.sat_25, s.sat_75),
        "act_range": rng(s.act_25, s.act_75),
        "programs": "; ".join(progs),
        "distance_miles": round(v.distance) if v.distance is not None else "",
    }


def build_pool(
    persona: Persona,
    schools: dict[int, School],
    major_cip4s: list[str],
    system_unitids: set[int],
    home_ll: tuple[float, float] | None,
    seed: int = DEFAULT_SEED,
    sample_size: int = SAMPLE_SIZE,
) -> Pool:
    """Pure: everything after the DB/CSV reads. ``schools`` must include every system
    unitid (unknown ones are auto-judged "not in database")."""
    cip4s = {norm_cip4(c) for c in major_cip4s}
    hidden = persona.hidden
    relaxed: list[str] = []

    def passing(relax: bool) -> dict[int, Verdict]:
        out = {}
        for uid, s in schools.items():
            v = judge(s, hidden, cip4s, home_ll, relax)
            if v.ok:
                out[uid] = v
        return out

    ok = passing(False)
    if len(ok) < MIN_PASSING and hidden.get("budget_cap"):
        ok = passing(True)
        relaxed.append("budget")
    rng = random.Random(f"{seed}:{persona.id}")
    sample = stratified_sample([schools[u] for u in sorted(ok)], sample_size, rng)
    shown: dict[int, Verdict] = {s.unitid: ok[s.unitid] for s in sample}
    auto: list[dict[str, Any]] = []
    n_system = 0
    for uid in sorted(system_unitids):
        if uid in ok:
            if uid not in shown:
                n_system += 1
            shown[uid] = ok[uid]
            continue
        s = schools.get(uid)
        reasons = (
            judge(s, hidden, cip4s, home_ll, bool(relaxed)).reasons if s else ["not in database"]
        )
        auto.append({"unitid": uid, "reasons": reasons})
    rows = [_row(schools[u], v, cip4s) for u, v in sorted(shown.items())]
    random.Random(f"{seed}:{persona.id}:shuffle").shuffle(rows)
    return Pool(persona.id, rows, len(ok), relaxed, auto, sorted(cip4s), len(sample), n_system)


# ------------------------------------------------------------------ IO / DB


def system_topk(run_dirs: list[Path], persona_id: str) -> set[int]:
    out: set[int] = set()
    for d in run_dirs:
        p = Path(d) / "retrieval.json"
        if not p.exists():
            continue
        entry = json.loads(p.read_text()).get("personas", {}).get(persona_id, {})
        for kind in ("gold", "e2e"):
            for ids in (entry.get(kind) or {}).values():
                out.update(int(u) for u in ids[:10])
    return out


def _f(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "", "NULL", "PrivacySuppressed") else None
    except ValueError:
        return None


@dataclass
class RawInstitutions:
    """Read-only extract of the raw Scorecard institution CSV."""

    tuition: dict[int, tuple[float | None, float | None]] = field(default_factory=dict)
    zip_ll: dict[str, list[tuple[float, float]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> RawInstitutions:
        out = cls()
        if path is None or not Path(path).exists():
            return out
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    uid = int(row["UNITID"])
                except (KeyError, ValueError):
                    continue
                out.tuition[uid] = (_f(row.get("TUITIONFEE_IN")), _f(row.get("TUITIONFEE_OUT")))
                lat, lon = _f(row.get("LATITUDE")), _f(row.get("LONGITUDE"))
                z = (row.get("ZIP") or "")[:5]
                if lat is not None and lon is not None and len(z) == 5 and z.isdigit():
                    out.zip_ll.setdefault(z, []).append((lat, lon))
        return out

    def home_latlon(self, zip5: str | None, state: str | None) -> tuple[float, float] | None:
        def mean(pts: list[tuple[float, float]]) -> tuple[float, float]:
            return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

        if zip5:
            z = str(zip5)[:5]
            if z in self.zip_ll:
                return mean(self.zip_ll[z])
            near = [pt for k, pts in self.zip_ll.items() if k[:3] == z[:3] for pt in pts]
            if near:
                return mean(near)
        return STATE_CENTROIDS.get(str(state or "").upper())


async def load_schools(
    session: AsyncSession, cip4s: set[str], extra_unitids: set[int], raw: RawInstitutions
) -> dict[int, School]:
    """Schools with a bachelor's in ``cip4s`` plus every ``extra_unitids`` school."""
    prog_rows = (
        await session.execute(
            select(Program.unitid, Program.cip4, CipCode.title, Program.median_earnings)
            .join(CipCode, CipCode.cip4 == Program.cip4)
            .where(Program.credential_level == 3)
            .where(Program.cip4.in_(sorted(cip4s)) | Program.unitid.in_(sorted(extra_unitids)))
        )
    ).all()
    progs: dict[int, list[ProgramInfo]] = {}
    for uid, cip4, title, earn in prog_rows:
        progs.setdefault(uid, []).append(ProgramInfo(cip4, title, earn))
    ids = set(progs) | set(extra_unitids)
    insts = (
        (await session.execute(select(Institution).where(Institution.unitid.in_(sorted(ids)))))
        .scalars()
        .all()
    )
    out: dict[int, School] = {}
    for i in insts:
        # raw CSV first (read-only source of truth for the labels), else the DB columns
        tin, tout = raw.tuition.get(i.unitid, (None, None))
        if tin is None and tout is None:
            tin = float(i.tuition_in_state) if i.tuition_in_state is not None else None
            tout = float(i.tuition_out_of_state) if i.tuition_out_of_state is not None else None
        out[i.unitid] = School(
            unitid=i.unitid,
            name=i.name,
            city=i.city,
            state=i.state,
            control=i.control,
            locale=i.locale,
            undergrad_size=i.undergrad_size,
            lat=i.lat,
            lon=i.lon,
            admission_rate=i.admission_rate,
            open_admission=i.open_admission,
            sat_25=i.sat_25,
            sat_75=i.sat_75,
            act_25=i.act_25,
            act_75=i.act_75,
            net_prices={c: getattr(i, c) for c in BRACKET_COLUMN.values()},
            avg_net_price=i.avg_net_price,
            programs=progs.get(i.unitid, []),
            tuition_in=tin,
            tuition_out=tout,
        )
    return out


def write_pool(pool: Pool, out_dir: Path, meta_extra: dict[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{pool.persona}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(pool.rows)
    meta = {
        "persona": pool.persona,
        "major_cip4s": pool.major_cip4s,
        "pool_size": pool.pool_size,
        "relaxed": pool.relaxed,
        "shown": len(pool.rows),
        "auto_judged": pool.auto_judged,
        **meta_extra,
    }
    meta_path = out_dir / f"{pool.persona}.meta.yaml"
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
    return csv_path, meta_path


def load_major_sets(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return {str(k): [str(c) for c in v or []] for k, v in doc.items() if not str(k).startswith("_")}


async def generate(
    personas: list[Persona],
    major_sets: dict[str, list[str]],
    run_dirs: list[Path],
    session: AsyncSession,
    raw: RawInstitutions,
    out_dir: Path = POOLS_DIR,
    seed: int = DEFAULT_SEED,
) -> list[Pool]:
    pools: list[Pool] = []
    version = git_sha(Path(__file__))
    for p in personas:
        cips = major_sets.get(p.id)
        if not cips:
            print(f"[{p.id}] skipped: no major_cip4s in major_sets.yaml (criteria pass 1)")
            continue
        system = system_topk(run_dirs, p.id)
        schools = await load_schools(session, {norm_cip4(c) for c in cips}, system, raw)
        home = raw.home_latlon(p.hidden.get("home_zip"), p.hidden.get("home_state"))
        pool = build_pool(p, schools, cips, system, home, seed)
        write_pool(
            pool,
            out_dir,
            {
                "n_sampled": pool.n_sampled,
                "n_system_only": pool.n_system,
                "seed": seed,
                "runs": [str(d) for d in run_dirs],
                "candidate_tool_version": version,
                "criteria_commit": git_sha(LABELS_DIR / "criteria.md"),
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        print(
            f"[{p.id}] pool_size={pool.pool_size} shown={len(pool.rows)} "
            f"auto_judged={len(pool.auto_judged)} relaxed={pool.relaxed}"
        )
        pools.append(pool)
    return pools


async def extra_rows(
    persona: Persona,
    major_cip4s: list[str],
    extra_unitids: set[int],
    relaxed: bool,
    session: AsyncSession,
    raw: RawInstitutions,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Top-up for a later system version: picks outside ``judged_unitids``.

    Returns (rows passing H1–H4 in the pool CSV format, shuffled with the persona's
    seed; auto-judged failures ``{unitid, name, reasons}``), using the same hard
    criteria (and the persona's recorded ``relaxed`` budget) as the original pool.
    """
    cip4s = {norm_cip4(c) for c in major_cip4s}
    schools = await load_schools(session, cip4s, extra_unitids, raw)
    home = raw.home_latlon(persona.hidden.get("home_zip"), persona.hidden.get("home_state"))
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for uid in sorted(extra_unitids):
        s = schools.get(uid)
        if s is None:
            failed.append({"unitid": uid, "name": None, "reasons": ["not in database"]})
            continue
        v = judge(s, persona.hidden, cip4s, home, relaxed)
        if v.ok:
            rows.append(_row(s, v, cip4s))
        else:
            failed.append({"unitid": uid, "name": s.name, "reasons": v.reasons})
    random.Random(f"{DEFAULT_SEED}:{persona.id}:extra").shuffle(rows)
    return rows, failed


def write_extra(
    persona_id: str, rows: list[dict[str, Any]], meta: dict[str, Any], out_dir: Path = POOLS_DIR
) -> Path:
    """``<persona>.extra.csv`` (same columns as the pool CSV) + ``.extra.meta.yaml``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{persona_id}.extra.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (out_dir / f"{persona_id}.extra.meta.yaml").write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    )
    return csv_path


async def _main(a: argparse.Namespace) -> int:
    personas = load_personas(a.personas)
    major_sets = load_major_sets(a.major_sets)
    if not major_sets:
        print(f"no major sets in {a.major_sets}: write pass-1 major_cip4s first", file=sys.stderr)
        return 2
    from evals.report import resolve_run

    run_dirs = [resolve_run(r) for r in a.runs]
    if not run_dirs:
        print("warning: no --runs given; pools contain only the stratified sample")
    raw = RawInstitutions.load(a.raw_institutions)
    if not raw.tuition:
        print(
            f"note: raw CSV not found ({a.raw_institutions}); using the DB tuition columns",
            file=sys.stderr,
        )
    engine = create_async_engine(a.database_url or get_settings().DATABASE_URL)
    try:
        async with AsyncSession(engine) as session:
            await generate(personas, major_sets, run_dirs, session, raw, a.out_dir, a.seed)
    finally:
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--personas", default=DEFAULT_PERSONAS)
    ap.add_argument("--major-sets", type=Path, default=MAJOR_SETS)
    ap.add_argument(
        "--runs", nargs="*", default=[], help="run dirs or ids with retrieval.json, or 'latest'"
    )
    ap.add_argument("--raw-institutions", type=Path, default=RAW_INSTITUTIONS)
    ap.add_argument("--database-url", default="")
    ap.add_argument("--out-dir", type=Path, default=POOLS_DIR)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
