"""Load Scorecard records into Postgres (institution, cip_code, program).

Idempotent: every table is upserted with ``INSERT ... ON CONFLICT DO UPDATE``, so
re-running refreshes values in place. Batched (``32767 // ncols`` rows per statement)
and run inside one transaction by the CLI. ``cip_code`` upserts only touch
``title``; definitions and embeddings written by ``ingest.cip`` / ``ingest.embed``
survive a reload.

Sources::

    python -m ingest.load --raw data/raw/scorecard   # full: 2,343 schools / 67,029 programs
    python -m ingest.load --fixture                  # data/fixtures/*.jsonl (CI sample)

The fixture load also reads ``data/fixtures/cip_embeddings.jsonl`` when present
(cip4, title, definition, text, model, embedding for all CIP codes) so tests and
replay never need the embedding model.

Python API (for tests and other agents)::

    counts = await load_records(session, institutions, programs)   # no commit
    counts = await load_fixture(session)                           # no commit
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CipCode, Institution, Program
from app.retrieval.embedder import Embedder
from ingest.scorecard import (
    BACHELORS,
    FIELD_OF_STUDY_FILE,
    INSTITUTION_FILE,
    InstitutionRecord,
    ProgramRecord,
    SkipCounter,
    compute_scope,
    iter_institutions,
    iter_programs,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"
INST_FIXTURE = "institutions_sample.jsonl"
PROG_FIXTURE = "programs_sample.jsonl"
EMBED_FIXTURE = "cip_embeddings.jsonl"
MAX_BIND_PARAMS = 32767  # asyncpg / Postgres wire-protocol limit per statement

_INST_T: Table = Institution.__table__  # type: ignore[assignment]
_CIP_T: Table = CipCode.__table__  # type: ignore[assignment]
_PROG_T: Table = Program.__table__  # type: ignore[assignment]


@dataclass
class LoadCounts:
    institutions: int = 0
    cip_codes: int = 0
    programs: int = 0
    embeddings: int = 0
    definitions: int = 0


def rows_per_statement(ncols: int, requested: int | None = None) -> int:
    """Rows per INSERT: as many as fit in asyncpg's 32,767 bind parameters
    (``MAX_BIND_PARAMS // ncols``), or ``requested`` if that is smaller."""
    cap = max(MAX_BIND_PARAMS // max(ncols, 1), 1)
    return cap if requested is None else max(1, min(requested, cap))


def _batches(rows: Sequence[dict[str, Any]], size: int) -> Iterable[Sequence[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


async def _upsert(
    session: AsyncSession,
    table: Table,
    rows: Sequence[dict[str, Any]],
    conflict: list[str],
    update_cols: Iterable[str],
    batch_size: int | None,
) -> int:
    if not rows:
        return 0
    cols = list(update_cols)
    for chunk in _batches(rows, rows_per_statement(len(rows[0]), batch_size)):
        stmt = insert(table).values(list(chunk))
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict, set_={c: stmt.excluded[c] for c in cols}
        )
        await session.execute(stmt)
    return len(rows)


def pick_cip_titles(programs: Iterable[ProgramRecord]) -> dict[str, str]:
    """One title per cip4: the most common CIPDESC (ties -> alphabetically first)."""
    seen: dict[str, Counter[str]] = defaultdict(Counter)
    for p in programs:
        if p.cip_title:
            seen[p.cip4][p.cip_title] += 1
    return {
        cip4: min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] for cip4, c in sorted(seen.items())
    }


def _inst_row(r: InstitutionRecord) -> dict[str, Any]:
    d = asdict(r)
    d["city"] = d["city"] or ""  # institution.city is NOT NULL
    return d


async def load_records(
    session: AsyncSession,
    institutions: Iterable[InstitutionRecord],
    programs: Iterable[ProgramRecord],
    batch_size: int | None = None,
) -> LoadCounts:
    """Upsert institutions, their cip_code rows and programs. Does not commit.

    ``batch_size=None`` packs ``32767 // ncols`` rows per statement (smaller values
    are honoured, larger ones capped).

    Programs whose unitid isn't among ``institutions`` or the existing table
    would violate the FK; pass records from the same scope.
    """
    inst_rows = [_inst_row(r) for r in institutions]
    progs = list(programs)
    titles = pick_cip_titles(progs)
    for p in progs:
        titles.setdefault(p.cip4, p.cip4)  # blank CIPDESC: fall back to the code
    cip_rows = [{"cip4": k, "title": v} for k, v in sorted(titles.items())]
    prog_cols = [f.name for f in fields(ProgramRecord) if f.name != "cip_title"]
    prog_rows = [{c: getattr(p, c) for c in prog_cols} for p in progs]

    counts = LoadCounts()
    inst_update = [c for c in inst_rows[0] if c != "unitid"] if inst_rows else []
    counts.institutions = await _upsert(
        session, _INST_T, inst_rows, ["unitid"], inst_update, batch_size
    )
    counts.cip_codes = await _upsert(session, _CIP_T, cip_rows, ["cip4"], ["title"], batch_size)
    key = ["unitid", "cip4", "credential_level"]
    counts.programs = await _upsert(
        session, _PROG_T, prog_rows, key, [c for c in prog_cols if c not in key], batch_size
    )
    return counts


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def load_cip_embeddings(
    session: AsyncSession, path: Path, batch_size: int | None = None
) -> tuple[int, int]:
    """Upsert cip_code (title, definition, embedding) from a cip_embeddings.jsonl.

    Returns (rows with embeddings, rows with definitions). Does not commit.
    """
    rows = [
        {
            "cip4": r["cip4"],
            "title": r["title"],
            "definition": r.get("definition"),
            "embedding": r["embedding"],
        }
        for r in _read_jsonl(path)
    ]
    await _upsert(session, _CIP_T, rows, ["cip4"], ["title", "definition", "embedding"], batch_size)
    return len(rows), sum(r["definition"] is not None for r in rows)


async def load_fixture(
    session: AsyncSession,
    fixtures_dir: Path = FIXTURES_DIR,
    fallback_embedder: Embedder | None = None,
) -> LoadCounts:
    """Load the committed sample (and CIP embeddings if present). Does not commit.

    If ``fallback_embedder`` is given, any cip_code row still lacking an embedding
    afterwards (e.g. cip_embeddings.jsonl not generated yet) is embedded with it.
    Tests pass ``FakeEmbedder()`` here; never use a fake on a real database.
    """
    insts = [InstitutionRecord(**d) for d in _read_jsonl(fixtures_dir / INST_FIXTURE)]
    progs = [ProgramRecord(**d) for d in _read_jsonl(fixtures_dir / PROG_FIXTURE)]
    counts = await load_records(session, insts, progs)

    emb_path = fixtures_dir / EMBED_FIXTURE
    if emb_path.exists():
        counts.embeddings, counts.definitions = await load_cip_embeddings(session, emb_path)

    if fallback_embedder is not None:
        from ingest.embed import embed_cip_codes

        counts.embeddings += await embed_cip_codes(session, fallback_embedder, only_missing=True)
    return counts


async def table_counts(session: AsyncSession) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, col in (
        ("institutions", Institution.unitid),
        ("cip_codes", CipCode.cip4),
        ("programs", Program.id),
    ):
        out[name] = int((await session.scalar(select(func.count(col)))) or 0)
    out["cip_with_embedding"] = int(
        (await session.scalar(select(func.count(CipCode.embedding)))) or 0
    )
    out["cip_with_definition"] = int(
        (await session.scalar(select(func.count(CipCode.definition)))) or 0
    )
    return out


async def _main(args: argparse.Namespace) -> int:
    from app.db.session import dispose_engine, get_sessionmaker

    skipped = SkipCounter()
    try:
        async with get_sessionmaker()() as session, session.begin():
            if args.fixture:
                counts = await load_fixture(session)
            else:
                inst_path = args.raw / INSTITUTION_FILE
                fos_path = args.raw / FIELD_OF_STUDY_FILE
                scope = compute_scope(inst_path, fos_path)
                counts = await load_records(
                    session,
                    iter_institutions(inst_path, scope),
                    iter_programs(fos_path, BACHELORS, scope, skipped),
                    batch_size=args.batch_size,
                )
            totals = await table_counts(session)
    finally:
        await dispose_engine()

    src = "fixture" if args.fixture else str(args.raw)
    print(f"source: {src}")
    print(f"upserted institutions:    {counts.institutions:,}")
    print(f"upserted cip_codes:       {counts.cip_codes:,}")
    print(f"upserted programs:        {counts.programs:,}")
    if args.fixture:
        print(f"cip embeddings loaded:    {counts.embeddings:,}")
    else:
        print(f"rows skipped (no UNITID): {skipped.no_unitid:,}")
    print("table totals: " + ", ".join(f"{k}={v:,}" for k, v in totals.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load Scorecard data into Postgres (idempotent).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--raw", type=Path, help="dir with the Scorecard CSVs (full load)")
    src.add_argument("--fixture", action="store_true", help="load data/fixtures/*.jsonl")
    ap.add_argument(
        "--batch-size", type=int, default=None, help="rows per INSERT (default: 32767 // ncols)"
    )
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
