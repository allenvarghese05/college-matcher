"""Embed ``cip_code`` rows and export them to a committed fixture.

Embedding text = ``"<title>. <definition>"`` (just ``"<title>."`` when the
definition is NULL). Model: ``app.retrieval.embedder`` (bge-small-en-v1.5, 384-dim,
normalised).

Usage::

    python -m ingest.embed                                    # re-embed every cip_code row
    python -m ingest.embed --export data/fixtures/cip_embeddings.jsonl

Export refuses to write vectors from the FakeEmbedder (``EMBEDDER=fake``), refuses
``--only-missing``, and refuses if any row's vector was not written by the real
model in the same run, so a test double or stale vector can never end up in the
committed fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import bindparam, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CipCode
from app.retrieval.embedder import FAKE_MODEL, Embedder, get_embedder

DEFAULT_EXPORT = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "cip_embeddings.jsonl"
ROUND = 6  # decimals kept in the fixture (cosine error ~1e-6, file ~1/2 the size)


def embedding_text(title: str, definition: str | None) -> str:
    t = title.strip().rstrip(".").strip()
    d = (definition or "").strip()
    return f"{t}. {d}" if d else f"{t}."


async def embed_cip_codes(
    session: AsyncSession,
    embedder: Embedder | None = None,
    only_missing: bool = False,
    batch_size: int = 128,
    written: set[str] | None = None,
) -> int:
    """Compute and store passage embeddings for cip_code rows. Does not commit.

    Returns rows written; their cip4s are added to ``written`` if given (needed by
    ``export_fixture`` to prove every exported vector came from this run).
    """
    emb = embedder or get_embedder()
    q = select(CipCode.cip4, CipCode.title, CipCode.definition).order_by(CipCode.cip4)
    if only_missing:
        q = q.where(CipCode.embedding.is_(None))
    rows = (await session.execute(q)).all()
    table = CipCode.__table__
    stmt = (
        update(table)  # type: ignore[arg-type]
        .where(table.c.cip4 == bindparam("k"))
        .values(embedding=bindparam("v"))
    )
    n = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        vecs = emb.embed([embedding_text(r.title, r.definition) for r in chunk])
        await session.execute(
            stmt, [{"k": r.cip4, "v": v} for r, v in zip(chunk, vecs, strict=True)]
        )
        n += len(chunk)
        if written is not None:
            written.update(r.cip4 for r in chunk)
    return n


async def export_fixture(
    session: AsyncSession, path: Path, model_name: str, embedded_this_run: set[str]
) -> int:
    """Write every embedded cip_code row to ``path`` as JSONL (sorted by cip4).

    Refuses (ValueError, nothing written) unless ``model_name`` is a real model and
    EVERY cip_code row has an embedding written in this run by that model, i.e.
    ``embedded_this_run`` covers all rows. Stale vectors (e.g. FakeEmbedder ones a
    test fixture left behind, or rows skipped by ``--only-missing``) can't leak.
    """
    if model_name == FAKE_MODEL:
        raise ValueError("refusing to export FakeEmbedder vectors to a fixture")
    rows = (
        await session.execute(
            select(CipCode.cip4, CipCode.title, CipCode.definition, CipCode.embedding).order_by(
                CipCode.cip4
            )
        )
    ).all()
    stale = sorted(r.cip4 for r in rows if r.cip4 not in embedded_this_run or r.embedding is None)
    if stale:
        raise ValueError(
            f"refusing to export: {len(stale)} cip_code rows were not embedded by "
            f"{model_name} in this run (e.g. {stale[:5]}); re-embed all rows first"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            rec = {
                "cip4": r.cip4,
                "title": r.title,
                "definition": r.definition,
                "text": embedding_text(r.title, r.definition),
                "model": model_name,
                "embedding": [round(float(x), ROUND) for x in r.embedding],
            }
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return len(rows)


async def _main(args: argparse.Namespace) -> int:
    from app.db.session import dispose_engine, get_sessionmaker

    emb = get_embedder()
    written: set[str] = set()
    try:
        async with get_sessionmaker()() as session, session.begin():
            n = await embed_cip_codes(session, emb, only_missing=args.only_missing, written=written)
            with_def = len(
                (
                    await session.scalars(
                        select(CipCode.cip4).where(CipCode.definition.is_not(None))
                    )
                ).all()
            )
            exported = None
            if args.export is not None:
                exported = await export_fixture(session, args.export, emb.model_name, written)
    finally:
        await dispose_engine()
    print(f"model:                     {emb.model_name}")
    print(f"embeddings written:        {n:,}")
    print(f"  cip rows with definition: {with_def:,}")
    if exported is not None:
        print(f"exported:                  {exported:,} -> {args.export}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Embed cip_code rows (title. definition).")
    ap.add_argument("--only-missing", action="store_true", help="skip rows already embedded")
    ap.add_argument(
        "--export",
        type=Path,
        nargs="?",
        const=DEFAULT_EXPORT,
        default=None,
        help=f"also write a JSONL fixture (default path: {DEFAULT_EXPORT})",
    )
    args = ap.parse_args(argv)
    if args.export is not None and args.only_missing:
        ap.error("--export needs every row embedded in this run; drop --only-missing")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
