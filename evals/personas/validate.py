"""Validate simulated-student persona files and print diversity stats.

Field names, enum values and value types come from the backend contract
(backend/app/schemas.py) so the personas can't drift from it. Each
hidden_profile value is validated with a pydantic TypeAdapter against the
StudentProfile field's value type.

Usage (from repo root):
    UV_CACHE_DIR="$TMPDIR/uv-cache" uv run --directory backend python ../evals/personas/validate.py
    ... validate.py --table      # also print the README table rows

Exit code 0 when every file is valid AND every diversity requirement holds.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import get_args

import yaml
from pydantic import TypeAdapter, ValidationError

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.schemas import (  # noqa: E402
    Activity,
    IncomeBracket,
    Priority,
    SettingPref,
    SizePref,
    StudentProfile,
    WorkValue,
)

# --- from the contract -------------------------------------------------------
PROFILE_FIELDS = set(StudentProfile.model_fields)
INCOME = list(get_args(IncomeBracket))
SIZE = set(get_args(SizePref))
SETTING = set(get_args(SettingPref))
PRIORITIES = set(get_args(Priority))
WORK_VALUES = set(get_args(WorkValue))
ACTIVITY_KEYS = set(Activity.model_fields)


def _value_adapter(field: str) -> TypeAdapter:
    """TypeAdapter for the `value` type inside ProfileField[T] (i.e. T | None)."""
    pf = StudentProfile.model_fields[field].annotation
    return TypeAdapter(pf.model_fields["value"].annotation)


ADAPTERS = {f: _value_adapter(f) for f in PROFILE_FIELDS}

# --- persona policy (not in the contract) ------------------------------------
# Fields every persona must carry. Others are omitted when the student
# genuinely has / won't share them (key absent = unknown, SPEC §6).
REQUIRED_PROFILE = {
    "home_state", "home_zip", "income_bracket",
    "interests", "dream_without_money", "intended_majors", "riasec",
    "strengths", "favorite_subjects", "activities", "work_values",
    "size_pref", "setting_pref", "priorities",
}
assert REQUIRED_PROFILE <= PROFILE_FIELDS, REQUIRED_PROFILE - PROFILE_FIELDS

RIASEC = ["R", "I", "A", "S", "E", "C"]
REVEAL = {"only_when_asked"}
ARTICULATENESS = {"terse", "casual", "rambling", "anxious", "confident"}
EDGE_CASES = {
    "undecided", "leave_home_far", "low_income_high_stats", "first_gen",
    "specific_major_outcomes", "prestige", "arts", "trades_adjacent",
    "contradicts_self", "unrealistic_budget", "nursing_health", "cs",
    "military_rotc", "small_rural_college",
}
TOP_REQUIRED = {"id", "summary", "hidden_profile", "style", "reveal", "meta"}
TOP_OPTIONAL = {"quirks"}
META_KEYS = {"articulateness", "edge_cases", "voice_subset"}

# --- regions vocabulary (SPEC §6, decided Nov 19) ----------------------------
# Census divisions -> states. Same table is frozen in evals/labels/criteria.md.
DIVISIONS = {
    "new_england": {"CT", "ME", "MA", "NH", "RI", "VT"},
    "mid_atlantic": {"NJ", "NY", "PA"},
    "east_north_central": {"IL", "IN", "MI", "OH", "WI"},
    "west_north_central": {"IA", "KS", "MN", "MO", "NE", "ND", "SD"},
    "south_atlantic": {"DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV"},
    "east_south_central": {"AL", "KY", "MS", "TN"},
    "west_south_central": {"AR", "LA", "OK", "TX"},
    "mountain": {"AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"},
    "pacific": {"AK", "CA", "HI", "OR", "WA"},
}
CENSUS_REGIONS = {
    "northeast": DIVISIONS["new_england"] | DIVISIONS["mid_atlantic"],
    "midwest": DIVISIONS["east_north_central"] | DIVISIONS["west_north_central"],
    "south": DIVISIONS["south_atlantic"] | DIVISIONS["east_south_central"]
             | DIVISIONS["west_south_central"],
    "west": DIVISIONS["mountain"] | DIVISIONS["pacific"],
}
STATES = set().union(*DIVISIONS.values())
assert len(STATES) == 51
REGION_VOCAB = set(DIVISIONS) | set(CENSUS_REGIONS) | STATES | {"out_of_state"}

# Mostly-rural states (lowest urban share per Census); used for the stats only.
RURAL_STATES = {"VT", "ME", "WV", "MS", "MT", "AR", "SD", "KY", "AL", "ND",
                "NH", "WY", "IA", "NE", "KS", "ID", "NM", "OK"}

# USPS ZIP3 prefix ranges per state (inclusive), enough to catch typos.
ZIP3 = {
    "AL": [(350, 369)], "AK": [(995, 999)], "AZ": [(850, 865)],
    "AR": [(716, 729)], "CA": [(900, 961)], "CO": [(800, 816)],
    "CT": [(60, 69)], "DE": [(197, 199)], "DC": [(200, 205), (569, 569)],
    "FL": [(320, 349)], "GA": [(300, 319), (398, 399)], "HI": [(967, 968)],
    "ID": [(832, 838)], "IL": [(600, 629)], "IN": [(460, 479)],
    "IA": [(500, 528)], "KS": [(660, 679)], "KY": [(400, 427)],
    "LA": [(700, 714)], "ME": [(39, 49)], "MD": [(206, 219)],
    "MA": [(10, 27), (55, 55)], "MI": [(480, 499)], "MN": [(550, 567)],
    "MS": [(386, 397)], "MO": [(630, 658)], "MT": [(590, 599)],
    "NE": [(680, 693)], "NV": [(889, 898)], "NH": [(30, 38)],
    "NJ": [(70, 89)], "NM": [(870, 884)], "NY": [(100, 149), (5, 5), (63, 63)],
    "NC": [(270, 289)], "ND": [(580, 588)], "OH": [(430, 459)],
    "OK": [(730, 749)], "OR": [(970, 979)], "PA": [(150, 196)],
    "RI": [(28, 29)], "SC": [(290, 299)], "SD": [(570, 577)],
    "TN": [(370, 385)], "TX": [(750, 799), (733, 733), (885, 885)],
    "UT": [(840, 847)], "VT": [(50, 59)], "VA": [(220, 246), (201, 201)],
    "WA": [(980, 994)], "WV": [(247, 268)], "WI": [(530, 549)],
    "WY": [(820, 831)],
}
assert set(ZIP3) == STATES

FILENAME_RE = re.compile(r"^[a-z]+-[a-z]{2}$")


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


def validate(path: Path, data) -> list[str]:
    errs: list[str] = []
    e = errs.append
    if not isinstance(data, dict):
        return ["file is not a mapping"]

    keys = set(data)
    for k in TOP_REQUIRED - keys:
        e(f"missing top-level key '{k}'")
    for k in keys - TOP_REQUIRED - TOP_OPTIONAL:
        e(f"unknown top-level key '{k}'")

    pid = data.get("id")
    stem = path.stem
    if pid != stem:
        e(f"id '{pid}' != filename '{stem}'")
    if not FILENAME_RE.match(stem):
        e(f"filename '{stem}' is not <firstname>-<state>")
    for k in ("summary", "style"):
        if k in data and not (isinstance(data[k], str) and data[k].strip()):
            e(f"'{k}' must be a non-empty string")
    if "reveal" in data and data["reveal"] not in REVEAL:
        e(f"reveal '{data['reveal']}' not in {sorted(REVEAL)}")
    if "quirks" in data and not _is_str_list(data["quirks"]):
        e("quirks must be a list of strings")

    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        e("meta must be a mapping")
        meta = {}
    for k in META_KEYS - set(meta):
        e(f"meta missing '{k}'")
    for k in set(meta) - META_KEYS:
        e(f"meta has unknown key '{k}'")
    if "articulateness" in meta and meta["articulateness"] not in ARTICULATENESS:
        e(f"meta.articulateness '{meta['articulateness']}' not allowed")
    if "edge_cases" in meta:
        ec = meta["edge_cases"]
        if not isinstance(ec, list):
            e("meta.edge_cases must be a list")
        else:
            for x in ec:
                if x not in EDGE_CASES:
                    e(f"meta.edge_cases: unknown '{x}'")
    if "voice_subset" in meta and not isinstance(meta["voice_subset"], bool):
        e("meta.voice_subset must be a bool")

    hp = data.get("hidden_profile")
    if not isinstance(hp, dict):
        e("hidden_profile must be a mapping")
        return errs

    hkeys = set(hp)
    for k in hkeys - PROFILE_FIELDS:
        e(f"hidden_profile.{k} is not a StudentProfile field (app/schemas.py)")
    for k in REQUIRED_PROFILE - hkeys:
        e(f"hidden_profile missing '{k}'")

    # Type check every value against the contract.
    for k in hkeys & PROFILE_FIELDS:
        if hp[k] is None:
            e(f"{k}: null value; omit the key instead (absent = unknown)")
            continue
        try:
            ADAPTERS[k].validate_python(hp[k], strict=k not in ("gpa", "activities"))
        except ValidationError as ex:
            first = ex.errors()[0]
            e(f"{k}: does not match schemas.py type: {first['msg']} at {first['loc']}")

    # Extra domain checks the type system doesn't express.
    st = hp.get("home_state")
    if st not in STATES:
        e(f"home_state '{st}' is not a US state/DC code")
    elif not stem.endswith("-" + st.lower()):
        e(f"filename state suffix does not match home_state {st}")
    z = hp.get("home_zip")
    if not (isinstance(z, str) and re.fullmatch(r"\d{5}", z)):
        e(f"home_zip must be a quoted 5-digit string, got {z!r}")
    elif st in ZIP3:
        z3 = int(z[:3])
        if not any(lo <= z3 <= hi for lo, hi in ZIP3[st]):
            e(f"home_zip {z} is not in {st}")

    g = hp.get("gpa")
    if g is not None and not (isinstance(g, (int, float)) and 0 <= g <= 4.0):
        e(f"gpa {g!r} must be in 0..4 (unweighted)")
    s = hp.get("sat")
    if s is not None and not (isinstance(s, int) and 400 <= s <= 1600 and s % 10 == 0):
        e(f"sat {s!r} must be 400..1600, multiple of 10")
    a = hp.get("act")
    if a is not None and not (isinstance(a, int) and 1 <= a <= 36):
        e(f"act {a!r} must be 1..36")
    for k in ("budget_cap", "max_distance_miles"):
        if k in hp and isinstance(hp[k], int) and hp[k] < 0:
            e(f"{k} must be non-negative")

    for k in ("interests", "intended_majors", "strengths", "favorite_subjects", "regions"):
        if k in hp and isinstance(hp[k], list) and not _is_str_list(hp[k]):
            e(f"{k} items must be non-empty strings")
    if hp.get("interests") == []:
        e("interests must not be empty")
    if isinstance(hp.get("dream_without_money"), str) and not hp["dream_without_money"].strip():
        e("dream_without_money must be non-empty")

    regions = hp.get("regions", [])
    if isinstance(regions, list):
        for r in regions:
            if r not in REGION_VOCAB:
                e(f"regions: '{r}' not in SPEC §6 vocabulary")
        if len(set(regions)) != len(regions):
            e("regions has duplicates")
    pr = hp.get("priorities", [])
    if isinstance(pr, list) and len(set(pr)) != len(pr):
        e("priorities has duplicates")
    edge = meta.get("edge_cases") or []
    if "leave_home_far" in edge and "out_of_state" not in (regions or []):
        e("leave_home_far persona must include out_of_state in regions")

    acts = hp.get("activities", [])
    if isinstance(acts, list):
        for i, act in enumerate(acts):
            if isinstance(act, dict):
                y = act.get("years")
                if y is not None and not (isinstance(y, (int, float)) and 0 < y <= 6):
                    e(f"activities[{i}].years must be in (0, 6]")

    r = hp.get("riasec")
    if isinstance(r, dict) and set(r) == set(RIASEC):
        vals = sorted(r.values(), reverse=True)
        if vals[0] == vals[1]:
            e("riasec has a tie for dominant type (make the top score unique)")
    return errs


def academics(hp: dict) -> str:
    g = "gpa" in hp
    t = "sat" in hp or "act" in hp
    return {(True, True): "both", (True, False): "gpa_only",
            (False, True): "test_only", (False, False): "neither"}[(g, t)]


def dominant(hp: dict) -> str:
    r = hp["riasec"]
    return max(RIASEC, key=lambda k: r[k])


def main(argv: list[str]) -> int:
    files = sorted(HERE.glob("*.yaml"))
    personas = []
    n_err = 0
    seen: dict[str, Path] = {}
    for f in files:
        try:
            data = yaml.safe_load(f.read_text())
        except yaml.YAMLError as ex:
            print(f"ERROR {f.name}: YAML parse error: {ex}")
            n_err += 1
            continue
        errs = validate(f, data)
        pid = data.get("id") if isinstance(data, dict) else None
        if pid in seen:
            errs.append(f"duplicate id '{pid}' (also in {seen[pid].name})")
        elif pid:
            seen[pid] = f
        for msg in errs:
            print(f"ERROR {f.name}: {msg}")
        n_err += len(errs)
        if not errs:
            personas.append(data)

    print(f"\n{len(files)} persona files, {len(personas)} valid, {n_err} errors\n")
    if not personas:
        return 1

    hps = [p["hidden_profile"] for p in personas]
    income = Counter(hp["income_bracket"] for hp in hps)
    states = Counter(hp["home_state"] for hp in hps)
    acad = Counter(academics(hp) for hp in hps)
    dom = Counter(dominant(hp) for hp in hps)
    art = Counter(p["meta"]["articulateness"] for p in personas)
    edge = defaultdict(list)
    for p in personas:
        for x in p["meta"]["edge_cases"]:
            edge[x].append(p["id"])
    voice = [p["id"] for p in personas if p["meta"]["voice_subset"]]
    rural = sorted(s for s in states if s in RURAL_STATES)

    print("== Diversity stats ==")
    print("income brackets: " + ", ".join(f"{b}={income.get(b, 0)}" for b in INCOME))
    print(f"states: {len(states)} distinct; rural states ({len(rural)}): {' '.join(rural)}")
    print("academics: " + ", ".join(f"{k}={acad.get(k, 0)}"
                                    for k in ("both", "gpa_only", "test_only", "neither")))
    print("dominant RIASEC: " + ", ".join(f"{k}={dom.get(k, 0)}" for k in RIASEC))
    print("articulateness: " + ", ".join(f"{k}={art.get(k, 0)}" for k in sorted(ARTICULATENESS)))
    print("edge cases:")
    for x in sorted(EDGE_CASES):
        print(f"  {x:24s} {len(edge[x]):2d}  {' '.join(edge[x])}")
    print(f"voice subset ({len(voice)}): {' '.join(voice)}")

    checks = {
        "36 personas": len(personas) == 36,
        "each income bracket >= 6": all(income.get(b, 0) >= 6 for b in INCOME),
        ">= 20 states": len(states) >= 20,
        ">= 5 rural states": len(rural) >= 5,
        "gpa_only >= 4": acad.get("gpa_only", 0) >= 4,
        "test_only >= 4": acad.get("test_only", 0) >= 4,
        "neither >= 4": acad.get("neither", 0) >= 4,
        "each RIASEC dominant >= 4": all(dom.get(k, 0) >= 4 for k in RIASEC),
        "terse/rambling/anxious/confident all present":
            all(art.get(k, 0) >= 2 for k in ("terse", "rambling", "anxious", "confident")),
        "every edge case covered": all(edge[x] for x in EDGE_CASES),
        "voice subset 8-10": 8 <= len(voice) <= 10,
    }
    print("\n== Requirement checks ==")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    if "--table" in argv:
        print("\n| id | state | income | gpa? | test? | dominant RIASEC | priorities | edge case | voice |")
        print("|---|---|---|---|---|---|---|---|---|")
        for p in sorted(personas, key=lambda p: p["id"]):
            hp = p["hidden_profile"]
            test = ("SAT" if "sat" in hp else "ACT" if "act" in hp else "-")
            print(f"| {p['id']} | {hp['home_state']} | {hp['income_bracket']} | "
                  f"{'yes' if 'gpa' in hp else '-'} | {test} | {dominant(hp)} | "
                  f"{', '.join(hp['priorities'])} | "
                  f"{', '.join(p['meta']['edge_cases']) or '-'} | "
                  f"{'yes' if p['meta']['voice_subset'] else ''} |")

    return 0 if n_err == 0 and all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
