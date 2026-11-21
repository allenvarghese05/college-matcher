"""NCES CIP 2020 definitions -> ``cip_code.definition``.

Source: https://nces.ed.gov/ipeds/cipcode/Files/CIPCode2020.csv, saved (by hand
or ``make data``) to ``data/raw/cip/CIPCode2020.csv``. Untrusted input: parsed with
stdlib ``csv`` only.

Columns used: ``CIPCode``, ``CIPTitle``, ``CIPDefinition`` and ``Action``. NCES
writes codes Excel-style (``="01.0101"``); the wrapper is stripped. Codes look
like ``01`` (2-digit family), ``01.01`` (4-digit series, our ``cip4`` "0101") and
``01.0101`` (6-digit program).

``Action`` semantics in the 2020 file (checked on the real file, 2,848 rows):

* ``No substantive changes`` / ``New`` / title or definition changes: current codes.
* ``Moved to`` (149 rows): the NEW 2020 code, carrying the real title and
  definition (e.g. 01.1004 Viticulture and Enology; whole series 01.80, 01.81,
  19.10, 61.22). KEPT.
* ``Moved from`` (149 rows): the retired old code; its definition is only
  "Moved from 01.0309 to 01.1004". DROPPED.
* ``Deleted`` (12 rows): retired. DROPPED.

Definition rule per cip4. On the real file every 4-digit series definition is a
pointer ("Instructional content [for this group of programs] is defined in
code(s) ..."), so the text is normally built from the series' 6-digit children:

1. the series' own definition if it is a real paragraph (not empty, not a pointer);
2. else exactly one child -> that child's definition;
3. else several children -> "Child Title: child definition." items, the
   ``.XX01`` / "General" child first, then by code, stopping before
   ``MAX_WORDS`` (~400 words, inside bge-small's 512-token window);
4. else NULL.

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

MAX_WORDS = 400
_DROP_ACTIONS = ("deleted", "moved from")  # "moved to" rows are the live 2020 codes
_POINTER = re.compile(r"^instructional content\b.*\bdefined in codes?\b", re.IGNORECASE)
_SERIES = re.compile(r"^(\d{1,2})\.(\d{2})$")
_PROGRAM = re.compile(r"^(\d{1,2})\.(\d{2})(\d{2})$")


@dataclass(frozen=True, slots=True)
class CipDefinition:
    cip4: str
    title: str
    definition: str | None
    source: str  # "series" | "child" | "children" | "none"


@dataclass(frozen=True, slots=True)
class _Child:
    code: str
    title: str
    definition: str


def _clean(cell: str | None) -> str:
    """Strip Excel ``="..."`` wrappers, quotes and whitespace."""
    s = (cell or "").strip()
    if s.startswith('="') and s.endswith('"'):
        s = s[2:-1]
    return s.strip().strip('"').strip()


def _title(cell: str | None) -> str:
    return _clean(cell).rstrip(".").strip()


def _is_real(definition: str) -> bool:
    return bool(definition) and not _POINTER.match(definition)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _truncate_words(text: str, limit: int = MAX_WORDS) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]) + " ..."


def _child_order(c: _Child) -> tuple[int, str]:
    general = c.code.endswith("01") or "general" in c.title.lower()
    return (0 if general else 1, c.code)


def _from_children(kids: list[_Child]) -> tuple[str | None, str]:
    if not kids:
        return None, "none"
    if len(kids) == 1:
        k = kids[0]
        text = k.definition if _is_real(k.definition) else k.title
        return (_truncate_words(_sentence(text)) if text else None), "child"
    items: list[str] = []
    words = 0
    for k in sorted(kids, key=_child_order):
        item = (
            f"{k.title}: {_sentence(k.definition)}"
            if _is_real(k.definition)
            else _sentence(k.title)
        )
        n = len(item.split())
        if words + n > MAX_WORDS:
            if not items:  # first item alone is too long: keep it truncated
                items.append(_truncate_words(item))
            break
        items.append(item)
        words += n
    return " ".join(items), "children"


def parse_cip_csv(path: str | Path) -> dict[str, CipDefinition]:
    """Parse the NCES CIP 2020 CSV into ``{cip4: CipDefinition}``."""
    series: dict[str, tuple[str, str]] = {}  # cip4 -> (title, definition)
    children: dict[str, list[_Child]] = defaultdict(list)
    with Path(path).open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            if _clean(row.get("Action")).lower().startswith(_DROP_ACTIONS):
                continue
            code = _clean(row.get("CIPCode"))
            if m := _SERIES.match(code):
                cip4 = m.group(1).zfill(2) + m.group(2)
                series[cip4] = (_title(row.get("CIPTitle")), _clean(row.get("CIPDefinition")))
            elif m := _PROGRAM.match(code):
                cip4 = m.group(1).zfill(2) + m.group(2)
                children[cip4].append(
                    _Child(code, _title(row.get("CIPTitle")), _clean(row.get("CIPDefinition")))
                )

    out: dict[str, CipDefinition] = {}
    for cip4 in sorted(set(series) | set(children)):
        title, definition = series.get(cip4, ("", ""))
        if _is_real(definition):
            out[cip4] = CipDefinition(cip4, title, _truncate_words(definition), "series")
            continue
        text, source = _from_children(children.get(cip4, []))
        out[cip4] = CipDefinition(cip4, title, text, source)
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
