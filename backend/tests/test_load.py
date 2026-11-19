"""DB tests for ingest.load / ingest.cip / ingest.embed (need Postgres + pgvector).

Use ``db_session`` (rolled back per test) on top of ``loaded_db`` (fixture loaded
once per session). Skipped locally if the DB is down; fail under REQUIRE_DB=1.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBED_DIM, CipCode, Institution, Program
from app.retrieval.embedder import FakeEmbedder
from ingest.cip import CipDefinition, apply_definitions
from ingest.embed import embed_cip_codes, export_fixture
from ingest.load import (
    FIXTURES_DIR,
    INST_FIXTURE,
    PROG_FIXTURE,
    load_cip_embeddings,
    load_fixture,
    load_records,
    pick_cip_titles,
    rows_per_statement,
    table_counts,
)
from ingest.scorecard import InstitutionRecord, ProgramRecord


def _jsonl(name: str) -> list[dict]:
    with (FIXTURES_DIR / name).open() as f:
        return [json.loads(line) for line in f]


def _inst(unitid: int, **kw) -> InstitutionRecord:
    base = {f.name: None for f in dataclasses.fields(InstitutionRecord)}
    base.update(unitid=unitid, name=f"Test U {unitid}", state="ZZ", control=1, city=None)
    base.update(kw)
    return InstitutionRecord(**base)


def _prog(unitid: int, cip4: str, title: str = "Test Major", **kw) -> ProgramRecord:
    base = dict(
        unitid=unitid,
        cip4=cip4,
        cip_title=title,
        credential_level=3,
        median_earnings=None,
        earnings_suppressed=True,
        median_debt=None,
        debt_suppressed=False,
        graduates=5,
    )
    base.update(kw)
    return ProgramRecord(**base)  # type: ignore[arg-type]


async def test_fixture_loaded(db_session: AsyncSession) -> None:
    insts = _jsonl(INST_FIXTURE)
    progs = _jsonl(PROG_FIXTURE)
    uids = [d["unitid"] for d in insts]
    n = await db_session.scalar(
        select(func.count()).select_from(Institution).where(Institution.unitid.in_(uids))
    )
    assert n == len(insts) == 200
    n_prog = await db_session.scalar(
        select(func.count()).select_from(Program).where(Program.unitid.in_(uids))
    )
    assert n_prog == len(progs)
    # every program's major exists and every major has an embedding
    cips = {p["cip4"] for p in progs}
    rows = (await db_session.execute(select(CipCode).where(CipCode.cip4.in_(cips)))).scalars()
    rows = list(rows)
    assert len(rows) == len(cips)
    assert all(r.embedding is not None and len(r.embedding) == EMBED_DIM for r in rows)


async def test_fixture_values_roundtrip(db_session: AsyncSession) -> None:
    d = _jsonl(INST_FIXTURE)[0]
    inst = await db_session.get(Institution, d["unitid"])
    assert inst is not None
    for k, v in d.items():
        assert getattr(inst, k) == (v if not (k == "city" and v is None) else "")
    p = next(p for p in _jsonl(PROG_FIXTURE) if p["median_earnings"] is not None)
    row = await db_session.scalar(
        select(Program).where(
            Program.unitid == p["unitid"],
            Program.cip4 == p["cip4"],
            Program.credential_level == p["credential_level"],
        )
    )
    assert row is not None
    assert row.median_earnings == p["median_earnings"]
    assert row.earnings_suppressed is p["earnings_suppressed"]


async def test_load_fixture_idempotent(db_session: AsyncSession) -> None:
    before = await table_counts(db_session)
    counts = await load_fixture(db_session)
    after = await table_counts(db_session)
    assert counts.institutions == 200
    assert counts.programs == len(_jsonl(PROG_FIXTURE))
    assert before == after


async def test_load_records_upsert_updates_and_keeps_cip_extras(db_session: AsyncSession) -> None:
    uid, cip = 999_001, "9998"
    c1 = await load_records(db_session, [_inst(uid)], [_prog(uid, cip, median_earnings=1)])
    assert (c1.institutions, c1.cip_codes, c1.programs) == (1, 1, 1)
    inst = await db_session.get(Institution, uid)
    assert inst is not None and inst.city == ""  # NULL city coerced for NOT NULL column

    cip_row = await db_session.get(CipCode, cip)
    assert cip_row is not None
    cip_row.definition = "kept"
    cip_row.embedding = [0.0] * EMBED_DIM
    await db_session.flush()

    await load_records(
        db_session,
        [_inst(uid, name="Renamed U")],
        [_prog(uid, cip, title="New Title", median_earnings=50_000, earnings_suppressed=False)],
    )
    db_session.expire_all()
    inst = await db_session.get(Institution, uid)
    assert inst is not None and inst.name == "Renamed U"
    prog = await db_session.scalar(select(Program).where(Program.unitid == uid))
    assert prog is not None
    assert (prog.median_earnings, prog.earnings_suppressed) == (50_000, False)
    cip_row = await db_session.get(CipCode, cip)
    assert cip_row is not None
    assert cip_row.title == "New Title"
    assert cip_row.definition == "kept"
    assert cip_row.embedding is not None
    n = await db_session.scalar(
        select(func.count()).select_from(Program).where(Program.unitid == uid)
    )
    assert n == 1


async def test_load_records_batches(db_session: AsyncSession) -> None:
    insts = [_inst(998_000 + i) for i in range(7)]
    progs = [_prog(998_000 + i, "9997") for i in range(7)]
    c = await load_records(db_session, insts, progs, batch_size=3)
    assert (c.institutions, c.programs, c.cip_codes) == (7, 7, 1)


def test_rows_per_statement_respects_bind_limit() -> None:
    assert rows_per_statement(26) == 32767 // 26
    assert rows_per_statement(8) == 32767 // 8
    assert rows_per_statement(8, 3) == 3
    assert rows_per_statement(26, 10_000) == 32767 // 26
    assert rows_per_statement(26) * 26 <= 32767


def test_pick_cip_titles_majority_then_alpha() -> None:
    progs = [
        _prog(1, "0101", "B"),
        _prog(2, "0101", "A"),
        _prog(3, "0101", "B"),
        _prog(4, "0202", "Z"),
        _prog(5, "0202", "Y"),
    ]
    assert pick_cip_titles(progs) == {"0101": "B", "0202": "Y"}


async def test_apply_definitions(db_session: AsyncSession) -> None:
    await load_records(db_session, [_inst(997_001)], [_prog(997_001, "9996")])
    defs = {
        "9996": CipDefinition("9996", "T", "A definition.", "series"),
        "0000": CipDefinition("0000", "Missing", "ignored", "series"),
    }
    n = await apply_definitions(db_session, defs)
    assert n == 1
    db_session.expire_all()
    row = await db_session.get(CipCode, "9996")
    assert row is not None and row.definition == "A definition."


async def test_embed_and_nearest_neighbour(db_session: AsyncSession) -> None:
    await load_records(
        db_session,
        [_inst(996_001)],
        [
            _prog(996_001, "9990", "Vehicle Engine Repair Mechanics"),
            _prog(996_001, "9991", "Medieval Poetry Studies"),
        ],
    )
    fake = FakeEmbedder()
    n = await embed_cip_codes(db_session, fake)
    assert n == await db_session.scalar(select(func.count()).select_from(CipCode))
    (q,) = fake.embed(["engine repair"])
    dist = CipCode.embedding.cosine_distance(q)
    top = (
        await db_session.execute(
            select(CipCode.cip4).where(CipCode.cip4.in_(["9990", "9991"])).order_by(dist).limit(1)
        )
    ).scalar_one()
    assert top == "9990"


async def test_embed_only_missing(db_session: AsyncSession) -> None:
    assert await embed_cip_codes(db_session, FakeEmbedder(), only_missing=True) == 0


def test_embed_cli_rejects_export_with_only_missing() -> None:
    from ingest.embed import main

    with pytest.raises(SystemExit) as exc:
        main(["--only-missing", "--export"])
    assert exc.value.code == 2


async def test_export_and_reload_embeddings(db_session: AsyncSession, tmp_path: Path) -> None:
    await load_records(db_session, [_inst(995_001)], [_prog(995_001, "9995", "Export Me")])
    out = tmp_path / "cip_embeddings.jsonl"

    # only the new row embedded this run -> the other (pre-existing) vectors are stale
    partial: set[str] = set()
    await embed_cip_codes(db_session, FakeEmbedder(), only_missing=True, written=partial)
    assert partial == {"9995"}
    with pytest.raises(ValueError, match="not embedded"):
        await export_fixture(db_session, out, "test-model", partial)
    assert not out.exists()

    written: set[str] = set()
    await embed_cip_codes(db_session, FakeEmbedder(), written=written)
    with pytest.raises(ValueError, match="FakeEmbedder"):
        await export_fixture(db_session, out, FakeEmbedder.model_name, written)
    n = await export_fixture(db_session, out, "test-model", written)
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(lines) == n
    rec = next(r for r in lines if r["cip4"] == "9995")
    assert rec["text"] == "Export Me." and rec["model"] == "test-model"
    assert len(rec["embedding"]) == EMBED_DIM

    # reload over a cleared embedding
    row = await db_session.get(CipCode, "9995")
    assert row is not None
    row.embedding = None
    await db_session.flush()
    n_emb, _ = await load_cip_embeddings(db_session, out)
    assert n_emb == n
    db_session.expire_all()
    row = await db_session.get(CipCode, "9995")
    assert row is not None and row.embedding is not None
