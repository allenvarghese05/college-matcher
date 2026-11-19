"""Embed ``cip_code`` rows and export them to a committed fixture.

Embedding text = ``"<title>. <definition>"`` (just ``"<title>."`` when the
definition is NULL). Model: ``app.retrieval.embedder`` (bge-small-en-v1.5, 384-dim,
normalised).

Usage::

    python -m ingest.embed                                    # re-embed every cip_code row
    python -m ingest.embed --export data/fixtures/cip_embeddings.jsonl

Export refuses to write vectors from the FakeEmbedder (``EMBEDDER=fake``) so a
test double can never end up in the committed fixture.
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
) -> int:
    """Compute and store embeddings for cip_code rows. Does not commit. Returns rows written."""
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
    return n


async def export_fixture(session: AsyncSession, path: Path, model_name: str) -> int:
    """Write every embedded cip_code row to ``path`` as JSONL (sorted by cip4)."""
    if model_name == FAKE_MODEL:
        raise ValueError("refusing to export FakeEmbedder vectors to a fixture")
    rows = (
        await session.execute(
            select(CipCode.cip4, CipCode.title, CipCode.definition, CipCode.embedding)
            .where(CipCode.embedding.is_not(None))
            .order_by(CipCode.cip4)
        )
    ).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
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
    return len(rows)


async def _main(args: argparse.Namespace) -> int:
    from app.db.session import dispose_engine, get_sessionmaker

    emb = get_embedder()
    try:
        async with get_sessionmaker()() as session, session.begin():
            n = await embed_cip_codes(session, emb, only_missing=args.only_missing)
            with_def = len(
                (
                    await session.scalars(
                        select(CipCode.cip4).where(CipCode.definition.is_not(None))
                    )
                ).all()
            )
            exported = None
            if args.export is not None:
                exported = await export_fixture(session, args.export, emb.model_name)
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
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
