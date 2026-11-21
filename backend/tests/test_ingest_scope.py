"""File-level tests for the inclusion rule (SPEC D6) using tiny CSVs in tmp_path.

Covers compute_scope / iter_institutions / iter_programs end to end: CURROPER != 1,
territories, schools without a bachelor's (CREDLEV=3) row, and UNITID=NA rows.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ingest.scorecard import (
    SkipCounter,
    compute_scope,
    iter_institutions,
    iter_programs,
)

INST_COLS = ["UNITID", "INSTNM", "CITY", "STABBR", "CONTROL", "CURROPER"]
FOS_COLS = ["UNITID", "CIPCODE", "CIPDESC", "CREDLEV", "EARN_MDN_4YR", "IPEDSCOUNT1"]

# unitid -> (state, curroper)
SCHOOLS = {
    1: ("CA", "1"),  # in scope
    2: ("NY", "0"),  # closed -> excluded
    3: ("PR", "1"),  # territory -> excluded
    4: ("GU", "1"),  # territory -> excluded
    5: ("TX", "1"),  # only associate's / master's rows -> excluded
    6: ("DC", "1"),  # in scope (DC counts)
}


def _write(path: Path, cols: list[str], rows: list[dict[str, str]]) -> Path:
    # utf-8-sig mirrors the BOM on the real Scorecard exports.
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    inst = _write(
        tmp_path / "inst.csv",
        INST_COLS,
        [
            {
                "UNITID": str(u),
                "INSTNM": f"School {u}",
                "CITY": "Town",
                "STABBR": st,
                "CONTROL": "1",
                "CURROPER": cur,
            }
            for u, (st, cur) in SCHOOLS.items()
        ],
    )

    def prog(uid: str, cip: str, lvl: str) -> dict[str, str]:
        return {
            "UNITID": uid,
            "CIPCODE": cip,
            "CIPDESC": "Some Major.",
            "CREDLEV": lvl,
            "EARN_MDN_4YR": "PS",
            "IPEDSCOUNT1": "10",
        }

    fos_rows = [
        prog("1", "1107", "3"),
        prog("1", "5203", "3"),
        prog("1", "1107", "5"),  # master's: not a bachelor's row
        prog("2", "1107", "3"),
        prog("3", "1107", "3"),
        prog("4", "5203", "3"),
        prog("5", "1107", "2"),
        prog("5", "1107", "5"),
        prog("6", "2301", "3"),
        prog("NA", "1107", "3"),  # 5,573 such rows in the real file
        prog("NA", "5203", "3"),
        prog("NA", "5203", "5"),
    ]
    fos = _write(tmp_path / "fos.csv", FOS_COLS, fos_rows)
    return inst, fos


def test_compute_scope(files: tuple[Path, Path]) -> None:
    inst, fos = files
    assert compute_scope(inst, fos) == {1, 6}


def test_iter_institutions_respects_scope(files: tuple[Path, Path]) -> None:
    inst, fos = files
    recs = list(iter_institutions(inst, compute_scope(inst, fos)))
    assert sorted(r.unitid for r in recs) == [1, 6]
    assert {r.state for r in recs} == {"CA", "DC"}


def test_iter_programs_scope_and_level(files: tuple[Path, Path]) -> None:
    inst, fos = files
    progs = list(iter_programs(fos, 3, compute_scope(inst, fos)))
    assert sorted((p.unitid, p.cip4) for p in progs) == [(1, "1107"), (1, "5203"), (6, "2301")]
    assert all(p.credential_level == 3 for p in progs)


def test_iter_programs_skips_and_counts_na_unitid(files: tuple[Path, Path]) -> None:
    _, fos = files
    skipped = SkipCounter()
    # No scope: before the fix this crashed on int("NA").
    progs = list(iter_programs(fos, 3, None, skipped))
    assert skipped.no_unitid == 2  # only bachelor's-level NA rows are counted
    assert len(progs) == 6
    assert all(p.unitid > 0 for p in progs)


def test_iter_programs_counts_na_at_all_levels(files: tuple[Path, Path]) -> None:
    _, fos = files
    skipped = SkipCounter()
    progs = list(iter_programs(fos, None, None, skipped))
    assert skipped.no_unitid == 3
    assert len(progs) == 9


def test_iter_programs_counter_optional(files: tuple[Path, Path]) -> None:
    _, fos = files
    assert len(list(iter_programs(fos))) == 6
