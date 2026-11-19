"""Build the deterministic sample fixture used by tests and CI.

Picks ~200 in-scope schools and writes them plus ALL their bachelor's programs:

    data/fixtures/institutions_sample.jsonl
    data/fixtures/programs_sample.jsonl

Selection (fixed seed, every candidate list sorted by UNITID before sampling,
so output is identical across runs and machines):

1. one school per state (50 states + DC) so geography is covered;
2. top up "must-have" strata until each has its quota: open admission,
   highly selective (<15%), with and without SAT ranges, all-suppressed
   program earnings, mixed suppressed/reported earnings, for-profit;
3. fill to the target size per control type, cycling through states in a
   shuffled order so no single state dominates.

Usage::

    python -m ingest.sample --raw data/raw/scorecard [--out data/fixtures]
"""

from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ingest.scorecard import (
    BACHELORS,
    FIELD_OF_STUDY_FILE,
    INSTITUTION_FILE,
    InstitutionRecord,
    ProgramRecord,
    compute_scope,
    iter_institutions,
    iter_programs,
    write_jsonl,
)

SEED = 20261119
TARGET_BY_CONTROL = {1: 70, 2: 95, 3: 35}  # public, private nonprofit, for-profit (=200)
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "fixtures"
INST_FIXTURE = "institutions_sample.jsonl"
PROG_FIXTURE = "programs_sample.jsonl"


@dataclass(frozen=True)
class SchoolInfo:
    inst: InstitutionRecord
    n_programs: int
    n_earnings: int
    n_suppressed: int


Pred = Callable[[SchoolInfo], bool]

# name -> (predicate, minimum count in sample)
STRATA: dict[str, tuple[Pred, int]] = {
    "open_admission": (lambda s: s.inst.open_admission is True, 20),
    "selective_lt_15pct": (
        lambda s: s.inst.admission_rate is not None and s.inst.admission_rate < 0.15, 15),
    "has_sat_range": (lambda s: s.inst.sat_25 is not None, 40),
    "no_sat_range_not_open": (
        lambda s: s.inst.sat_25 is None and s.inst.open_admission is not True, 20),
    "earnings_all_suppressed": (lambda s: s.n_earnings == 0 and s.n_suppressed > 0, 20),
    "earnings_mixed": (lambda s: s.n_earnings > 0 and s.n_suppressed > 0, 20),
    "earnings_none_suppressed": (lambda s: s.n_earnings > 0 and s.n_suppressed == 0, 10),
    "for_profit": (lambda s: s.inst.control == 3, 25),
}


def select(schools: dict[int, SchoolInfo], seed: int = SEED) -> list[int]:
    """Return the sorted UNITIDs of the sample."""
    rng = random.Random(seed)
    chosen: set[int] = set()
    uids = sorted(schools)

    by_state: dict[str, list[int]] = defaultdict(list)
    for u in uids:
        by_state[schools[u].inst.state].append(u)

    # 1. geography: one school per state
    for state in sorted(by_state):
        chosen.add(rng.choice(by_state[state]))

    # 2. must-have strata
    for _, (pred, quota) in STRATA.items():
        have = sum(1 for u in chosen if pred(schools[u]))
        pool = [u for u in uids if u not in chosen and pred(schools[u])]
        need = min(max(quota - have, 0), len(pool))
        chosen.update(rng.sample(pool, need))

    # 3. fill per control type, round-robin over shuffled states
    for control, target in sorted(TARGET_BY_CONTROL.items()):
        states = sorted(by_state)
        rng.shuffle(states)
        pools = {
            st: [u for u in by_state[st] if schools[u].inst.control == control]
            for st in states
        }
        count = sum(1 for u in chosen if schools[u].inst.control == control)
        while count < target:
            progressed = False
            for st in states:
                if count >= target:
                    break
                pool = [u for u in pools[st] if u not in chosen]
                if not pool:
                    continue
                chosen.add(rng.choice(pool))
                count += 1
                progressed = True
            if not progressed:
                break
    return sorted(chosen)


def build(raw: Path, out: Path, seed: int = SEED) -> dict[str, object]:
    inst_path = raw / INSTITUTION_FILE
    fos_path = raw / FIELD_OF_STUDY_FILE
    scope = compute_scope(inst_path, fos_path)
    insts = {i.unitid: i for i in iter_institutions(inst_path, scope)}
    progs: dict[int, list[ProgramRecord]] = defaultdict(list)
    for p in iter_programs(fos_path, BACHELORS, scope):
        progs[p.unitid].append(p)

    schools = {
        u: SchoolInfo(
            inst=i,
            n_programs=len(progs[u]),
            n_earnings=sum(p.median_earnings is not None for p in progs[u]),
            n_suppressed=sum(p.earnings_suppressed for p in progs[u]),
        )
        for u, i in insts.items()
    }
    picked = select(schools, seed)

    out.mkdir(parents=True, exist_ok=True)
    n_inst = write_jsonl(out / INST_FIXTURE, (insts[u] for u in picked))
    sample_progs = sorted(
        (p for u in picked for p in progs[u]), key=lambda p: (p.unitid, p.cip4)
    )
    n_prog = write_jsonl(out / PROG_FIXTURE, sample_progs)

    return {
        "schools": n_inst,
        "programs": n_prog,
        "programs_with_earnings": sum(p.median_earnings is not None for p in sample_progs),
        "programs_earnings_suppressed": sum(p.earnings_suppressed for p in sample_progs),
        "states": len({insts[u].state for u in picked}),
        "by_control": dict(sorted(Counter(insts[u].control for u in picked).items())),
        "strata": {name: sum(1 for u in picked if pred(schools[u]))
                   for name, (pred, _) in STRATA.items()},
        "bytes": (out / INST_FIXTURE).stat().st_size + (out / PROG_FIXTURE).stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the deterministic Scorecard sample fixture.")
    ap.add_argument("--raw", required=True, type=Path, help="dir with the Scorecard CSVs")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"default: {DEFAULT_OUT}")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)
    stats = build(args.raw, args.out, args.seed)
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
