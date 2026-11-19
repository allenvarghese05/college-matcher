"""Validate simulated-student persona files and print diversity stats.

Usage (from repo root):
    uv run --python 3.12 --no-project --with pyyaml python -I evals/personas/validate.py
    ... validate.py --table      # also print the README table rows

Exit code 0 when every file is valid AND every diversity requirement holds.
Only stdlib + PyYAML.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

# --- SPEC §6 StudentProfile field names (hard-coded on purpose) -------------
PROFILE_FIELDS = {
    "home_state", "home_zip",
    "gpa", "sat", "act",
    "income_bracket", "budget_cap",
    "interests", "dream_without_money", "intended_majors", "riasec",
    "strengths", "favorite_subjects", "activities", "work_values",
    "max_distance_miles", "regions", "size_pref", "setting_pref", "priorities",
}
# Fields every persona must carry (others are omitted when the student
# genuinely has / would not share them).
REQUIRED_PROFILE = {
    "home_state", "home_zip", "income_bracket",
    "interests", "dream_without_money", "intended_majors", "riasec",
    "strengths", "favorite_subjects", "activities", "work_values",
    "size_pref", "setting_pref", "priorities",
}

INCOME = ["0-30k", "30-48k", "48-75k", "75-110k", "110k+"]
SIZE = {"small", "medium", "large", "any"}
SETTING = {"city", "suburb", "town", "rural", "any"}
PRIORITIES = {"cost", "outcomes", "prestige", "location", "fit"}
WORK_VALUES = {"achievement", "independence", "recognition",
               "relationships", "support", "conditions"}
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
ACTIVITY_KEYS = {"name", "role", "years"}

STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
}
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
        e(f"hidden_profile.{k} is not a SPEC §6 StudentProfile field")
    for k in REQUIRED_PROFILE - hkeys:
        e(f"hidden_profile missing '{k}'")

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

    if "gpa" in hp:
        g = hp["gpa"]
        if not (isinstance(g, (int, float)) and not isinstance(g, bool) and 0 <= g <= 4.0):
            e(f"gpa {g!r} must be a number in 0..4 (unweighted)")
    if "sat" in hp:
        s = hp["sat"]
        if not (isinstance(s, int) and 400 <= s <= 1600 and s % 10 == 0):
            e(f"sat {s!r} must be an int 400..1600, multiple of 10")
    if "act" in hp:
        a = hp["act"]
        if not (isinstance(a, int) and 1 <= a <= 36):
            e(f"act {a!r} must be an int 1..36")

    if hp.get("income_bracket") not in INCOME:
        e(f"income_bracket {hp.get('income_bracket')!r} not in {INCOME}")
    for k in ("budget_cap", "max_distance_miles"):
        if k in hp and not (isinstance(hp[k], int) and not isinstance(hp[k], bool) and hp[k] >= 0):
            e(f"{k} must be a non-negative int")

    for k in ("interests", "intended_majors", "strengths", "favorite_subjects",
              "regions"):
        if k in hp and not (isinstance(hp[k], list) and _is_str_list(hp[k])):
            e(f"{k} must be a list of non-empty strings")
    if "interests" in hp and not hp["interests"]:
        e("interests must not be empty")
    if "dream_without_money" in hp and not (
            isinstance(hp["dream_without_money"], str) and hp["dream_without_money"].strip()):
        e("dream_without_money must be a non-empty string")

    wv = hp.get("work_values", [])
    if not isinstance(wv, list) or any(x not in WORK_VALUES for x in wv):
        e(f"work_values {wv!r} must be a subset of {sorted(WORK_VALUES)}")
    pr = hp.get("priorities", [])
    if not isinstance(pr, list) or any(x not in PRIORITIES for x in pr):
        e(f"priorities {pr!r} must be a subset of {sorted(PRIORITIES)}")
    elif len(set(pr)) != len(pr):
        e("priorities has duplicates")
    if hp.get("size_pref") not in SIZE:
        e(f"size_pref {hp.get('size_pref')!r} not in {sorted(SIZE)}")
    if hp.get("setting_pref") not in SETTING:
        e(f"setting_pref {hp.get('setting_pref')!r} not in {sorted(SETTING)}")

    acts = hp.get("activities", [])
    if not isinstance(acts, list):
        e("activities must be a list")
    else:
        for i, a in enumerate(acts):
            if not isinstance(a, dict) or "name" not in a:
                e(f"activities[{i}] must be a mapping with 'name'")
                continue
            for k in set(a) - ACTIVITY_KEYS:
                e(f"activities[{i}] unknown key '{k}'")
            if "years" in a and not (isinstance(a["years"], int) and 0 < a["years"] <= 6):
                e(f"activities[{i}].years must be an int 1..6")

    r = hp.get("riasec")
    if not isinstance(r, dict) or set(r) != set(RIASEC):
        e(f"riasec must have exactly keys {RIASEC}")
    else:
        for k, v in r.items():
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1):
                e(f"riasec.{k}={v!r} must be in 0..1")
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
