"""NCES CIP 2020 definitions -> ``cip_code.definition``.

Source: https://nces.ed.gov/ipeds/cipcode/Files/CIPCode2020.csv, saved (by hand
or ``make data``) to ``data/raw/cip/CIPCode2020.csv``. Untrusted input: parsed with
stdlib ``csv`` only.

Columns used: ``CIPCode``, ``CIPTitle``, ``CIPDefinition`` (also ``Action`` to drop
deleted/moved codes). NCES writes codes Excel-style (``="01.0101"``); the wrapper
is stripped. Codes look like ``01`` (2-digit family), ``01.01`` (4-digit series,
our ``cip4`` "0101") and ``01.0101`` (6-digit program).

Definition rule per cip4: the 4-digit series' own definition, unless it is empty
or only a pointer ("Instructional content for this group of programs is defined
in codes ..."); then the titles of its 6-digit children joined with "; ".

The file is optional. Without it every definition stays NULL and the embedding
text falls back to the title (see ``ingest.embed.embedding_text``).

Usage::

    python -m ingest.cip [--csv data/raw/cip/CIPCode2020.csv]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import bindparam, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CipCode

csv.field_size_limit(sys.maxsize)

CIP_URL = "https://nces.ed.gov/ipeds/cipcode/Files/CIPCode2020.csv"
DEFAULT_CIP_CSV = Path(__file__).resolve().parents[2] / "data" / "raw" / "cip" / "CIPCode2020.csv"

_POINTER = re.compile(r"^instructional content .* defined in code", re.IGNORECASE)
_SERIES = re.compile(r"^(\d{1,2})\.(\d{2})$")
_PROGRAM = re.compile(r"^(\d{1,2})\.(\d{2})(\d{2})$")


@dataclass(frozen=True, slots=True)
class CipDefinition:
    cip4: str
    title: str
    definition: str | None
    source: str  # "series" | "children" | "none"


def _clean(cell: str | None) -> str:
    """Strip Excel ``="..."`` wrappers, quotes and whitespace."""
    s = (cell or "").strip()
    if s.startswith('="') and s.endswith('"'):
        s = s[2:-1]
    return s.strip().strip('"').strip()


def _title(cell: str | None) -> str:
    return _clean(cell).rstrip(".").strip()


def parse_cip_csv(path: str | Path) -> dict[str, CipDefinition]:
    """Parse the NCES CIP 2020 CSV into ``{cip4: CipDefinition}``."""
    series: dict[str, tuple[str, str]] = {}  # cip4 -> (title, definition)
    children: dict[str, list[tuple[str, str]]] = defaultdict(list)  # cip4 -> [(code6, title)]
    with Path(path).open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            action = _clean(row.get("Action")).lower()
            if action.startswith(("deleted", "moved")):
                continue
            code = _clean(row.get("CIPCode"))
            if m := _SERIES.match(code):
                cip4 = m.group(1).zfill(2) + m.group(2)
                series[cip4] = (_title(row.get("CIPTitle")), _clean(row.get("CIPDefinition")))
            elif m := _PROGRAM.match(code):
                cip4 = m.group(1).zfill(2) + m.group(2)
                children[cip4].append((code, _title(row.get("CIPTitle"))))

    out: dict[str, CipDefinition] = {}
    for cip4 in sorted(set(series) | set(children)):
        title, definition = series.get(cip4, ("", ""))
        if definition and not _POINTER.match(definition):
            out[cip4] = CipDefinition(cip4, title, definition, "series")
            continue
        kids = [t for _, t in sorted(children.get(cip4, [])) if t]
        if kids:
            out[cip4] = CipDefinition(cip4, title, "; ".join(kids) + ".", "children")
        else:
            out[cip4] = CipDefinition(cip4, title, None, "none")
    return out


async def apply_definitions(session: AsyncSession, defs: dict[str, CipDefinition]) -> int:
    """Set ``cip_code.definition`` for every existing cip4 found in ``defs``.

    Titles are left alone (they come from Scorecard CIPDESC). Does not commit.
    Returns the number of cip_code rows updated with a non-null definition.
    """
    existing = (await session.scalars(select(CipCode.cip4))).all()
    params = [
        {"k": c, "d": defs[c].definition}
        for c in existing
        if c in defs and defs[c].definition is not None
    ]
    if params:
        stmt = (
            update(CipCode.__table__)  # type: ignore[arg-type]
            .where(CipCode.__table__.c.cip4 == bindparam("k"))
            .values(definition=bindparam("d"))
        )
        await session.execute(stmt, params)
    return len(params)


async def _main(csv_path: Path) -> int:
    from app.db.session import dispose_engine, get_sessionmaker

    if not csv_path.exists():
        print(f"CIP file not found: {csv_path}")
        print(f"Download it from {CIP_URL} to that path; definitions stay NULL until then.")
        return 0
    defs = parse_cip_csv(csv_path)
    by_source: dict[str, int] = defaultdict(int)
    for d in defs.values():
        by_source[d.source] += 1
    try:
        async with get_sessionmaker()() as session, session.begin():
            n = await apply_definitions(session, defs)
            total = len((await session.scalars(select(CipCode.cip4))).all())
    finally:
        await dispose_engine()
    print(f"CIP series parsed:            {len(defs):,} {dict(sorted(by_source.items()))}")
    print(f"cip_code rows:                {total:,}")
    print(f"  definitions written:        {n:,}")
    print(f"  without definition:         {total - n:,}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fill cip_code.definition from NCES CIP 2020.")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CIP_CSV, help=f"default: {DEFAULT_CIP_CSV}")
    args = ap.parse_args(argv)
    return asyncio.run(_main(args.csv))


if __name__ == "__main__":
    raise SystemExit(main())
