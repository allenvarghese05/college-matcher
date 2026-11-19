"""DB-backed retriever tests on the 200-school sample fixture.

The loader agent's ``loaded_db`` fixture and real embedder aren't available yet, so this
module loads ``data/fixtures/*.jsonl`` itself inside ONE transaction that is rolled back
at the end (it never leaves rows behind and never overwrites real embeddings), and gives
each CIP a deterministic fake 384-dim embedding of its title (``HashEmbedder``).

TODO(loader merge): swap ``fixture_session`` for ``loaded_db`` and ``HashEmbedder`` for
the loader's fake embedder once both land.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.logging import TurnLogger
from app.db.models import EMBED_DIM
from app.retrieval import rerank, sql_filters
from app.retrieval.geo import states_for_regions
from app.retrieval.major_match import by_embedding, by_intended_majors, vector_literal
from app.retrieval.retriever import Retriever
from app.schemas import Candidate, StudentProfile

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "data" / "fixtures"
DATA = Path(__file__).parent / "data"


class HashEmbedder:
    """Deterministic bag-of-words embedder: shared words → similar vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(t: str) -> list[float]:
        v = [0.0] * EMBED_DIM
        v[0] = 0.05  # never a zero vector
        for tok in re.findall(r"[a-z]+", t.lower()):
            if len(tok) < 3 or tok in {"and", "the", "general", "other"}:
                continue
            if len(tok) > 3 and tok.endswith("s"):
                tok = tok[:-1]
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[1 + h % (EMBED_DIM - 1)] += 1.0
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]


def _jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line]


async def load_fixture(session: AsyncSession, embedder: HashEmbedder) -> None:
    insts = _jsonl("institutions_sample.jsonl")
    progs = _jsonl("programs_sample.jsonl")
    cols = list(insts[0])
    await session.execute(
        text(
            f"INSERT INTO institution ({', '.join(cols)}) VALUES "
            f"({', '.join(':' + c for c in cols)}) ON CONFLICT (unitid) DO NOTHING"
        ),
        insts,
    )
    titles = {p["cip4"]: p["cip_title"] for p in progs}
    vecs = embedder.embed(list(titles.values()))
    await session.execute(
        text(
            "INSERT INTO cip_code (cip4, title, embedding)"
            " VALUES (:cip4, :title, CAST(:e AS vector))"
            " ON CONFLICT (cip4) DO UPDATE"
            " SET embedding = EXCLUDED.embedding, title = EXCLUDED.title"
        ),
        [
            {"cip4": c, "title": t, "e": vector_literal(v)}
            for (c, t), v in zip(titles.items(), vecs, strict=True)
        ],
    )
    pcols = [c for c in progs[0] if c != "cip_title"]
    await session.execute(
        text(
            f"INSERT INTO program ({', '.join(pcols)}) VALUES ({', '.join(':' + c for c in pcols)})"
            " ON CONFLICT ON CONSTRAINT uq_program DO NOTHING"
        ),
        [{c: p[c] for c in pcols} for p in progs],
    )
    await session.flush()


@pytest.fixture(scope="module")
async def fixture_session(db_available: bool) -> AsyncIterator[AsyncSession]:
    if not db_available:
        msg = f"Postgres unreachable at {get_settings().DATABASE_URL.split('@')[-1]}"
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
    engine = create_async_engine(get_settings().DATABASE_URL)
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
    try:
        await load_fixture(session, HashEmbedder())
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


def prof(**fields: Any) -> StudentProfile:
    return StudentProfile.model_validate(
        {k: {"value": v, "confidence": 1.0} for k, v in fields.items()}
    )


CS_TX = dict(
    home_state="TX",
    income_bracket="48-75k",
    sat=1250,
    gpa=3.6,
    interests=["computer programming", "computer science", "software"],
    dream_without_money="build software and computer systems",
    priorities=["outcomes"],
)
ART_CA = dict(
    home_state="CA",
    income_bracket="0-30k",
    interests=["drawing", "painting", "fine arts", "design"],
    dream_without_money="make art and design things",
    budget_cap=15000,
    regions=["west"],
)


async def _db_facts(session: AsyncSession, c: Candidate, bracket: str | None) -> dict[str, Any]:
    col = sql_filters.net_price_column(bracket)
    inst = (
        await session.execute(
            text(
                f"SELECT {col} AS net_price, admission_rate, sat_25, sat_75, act_25, act_75,"
                " completion_rate, median_earnings_10yr, median_debt, undergrad_size, city, state"
                " FROM institution WHERE unitid = :u"
            ),
            {"u": c.unitid},
        )
    ).one()
    prog = None
    if c.cip4:
        prog = (
            await session.execute(
                text(
                    "SELECT median_earnings, median_debt FROM program"
                    " WHERE unitid = :u AND cip4 = :c AND credential_level = 3"
                ),
                {"u": c.unitid, "c": c.cip4},
            )
        ).one()
    return {
        "net_price": inst.net_price,
        "admission_rate": inst.admission_rate,
        "sat_range": f"{inst.sat_25}-{inst.sat_75}"
        if inst.sat_25 is not None and inst.sat_75 is not None
        else None,
        "act_range": f"{inst.act_25}-{inst.act_75}"
        if inst.act_25 is not None and inst.act_75 is not None
        else None,
        "completion_rate": inst.completion_rate,
        "program_median_earnings": prog.median_earnings if prog else None,
        "program_median_debt": prog.median_debt if prog else None,
        "median_earnings_10yr": inst.median_earnings_10yr,
        "median_debt": inst.median_debt,
        "undergrad_size": inst.undergrad_size,
        "city_state": f"{inst.city}, {inst.state}",
    }


# ------------------------------------------------------------------ tests


@pytest.mark.parametrize("mode", ["sql_only", "hybrid", "hybrid_rerank"])
@pytest.mark.parametrize("persona", [CS_TX, ART_CA], ids=["cs_tx", "art_ca"])
async def test_candidates_valid(fixture_session: AsyncSession, mode: str, persona: dict) -> None:
    s = fixture_session
    p = prof(**persona)
    r = Retriever(embedder=HashEmbedder())
    cands = await r.retrieve(s, p, k=10, mode=mode)  # type: ignore[arg-type]
    assert 0 < len(cands) <= 10
    assert len({c.unitid for c in cands}) == len(cands), "duplicate school"
    selected = {c["cip4"] for c in r.last_trace["cips"]}
    for c in cands:
        # in scope: exists and offers >= 1 bachelor's program
        n = await s.scalar(
            text("SELECT count(*) FROM program WHERE unitid = :u AND credential_level = 3"),
            {"u": c.unitid},
        )
        assert n and n > 0
        if c.cip4 is not None:
            assert c.cip4 in selected
            offers = await s.scalar(
                text(
                    "SELECT count(*) FROM program WHERE unitid = :u AND cip4 = :c"
                    " AND credential_level = 3"
                ),
                {"u": c.unitid, "c": c.cip4},
            )
            assert offers == 1
        else:
            assert mode == "sql_only"
        assert c.facts == await _db_facts(s, c, p.income_bracket.value)
        assert set(c.facts) == {
            "net_price", "admission_rate", "sat_range", "act_range", "completion_rate",
            "program_median_earnings", "program_median_debt", "median_earnings_10yr",
            "median_debt", "undergrad_size", "city_state",
        }  # fmt: skip


async def test_ordering_matches_mode(fixture_session: AsyncSession) -> None:
    r = Retriever(embedder=HashEmbedder())
    p = prof(**CS_TX)
    for mode in ("sql_only", "hybrid"):
        cands = await r.retrieve(fixture_session, p, k=10, mode=mode)  # type: ignore[arg-type]
        totals = [c.scores.total for c in cands]
        assert totals == sorted(totals, reverse=True), mode


async def test_budget_and_region_filters(fixture_session: AsyncSession) -> None:
    p = prof(**ART_CA)
    r = Retriever(embedder=HashEmbedder())
    cands = await r.retrieve(fixture_session, p, k=10, mode="hybrid_rerank")
    if not r.last_trace["location_relaxed"]:
        assert {c.state for c in cands} <= states_for_regions(["west"], "CA")
    for c in cands:
        price = await fixture_session.scalar(
            text(
                "SELECT COALESCE(net_price_0_30k, avg_net_price) FROM institution WHERE unitid=:u"
            ),
            {"u": c.unitid},
        )
        assert price is not None and price <= 15000 * 1.15


async def test_distance_filter(fixture_session: AsyncSession) -> None:
    p = prof(home_state="OH", income_bracket="75-110k", interests=["nursing", "health"],
             max_distance_miles=400)  # fmt: skip
    rows = await sql_filters.candidates(fixture_session, p, ["5138"])
    assert rows
    assert all(r.distance_miles is not None and r.distance_miles <= 440 for r in rows)
    states = {r.state for r in rows}
    assert "CA" not in states and "OH" in states


async def test_distance_tolerance_is_ten_percent(fixture_session: AsyncSession) -> None:
    base = dict(home_state="OH", income_bracket="75-110k")
    all_rows = await sql_filters.candidates(fixture_session, prof(**base), ["5138"])
    dists = sorted(r.distance_miles for r in all_rows if r.distance_miles is not None)
    d = dists[len(dists) // 2]
    # a school at distance d is kept with max_distance = d / 1.05 (within ×1.10) ...
    kept = await sql_filters.candidates(
        fixture_session, prof(**base, max_distance_miles=int(d / 1.05) + 1), ["5138"]
    )
    assert any(r.distance_miles == d for r in kept)
    # ... and dropped with max_distance = d / 1.2
    dropped = await sql_filters.candidates(
        fixture_session, prof(**base, max_distance_miles=int(d / 1.2)), ["5138"]
    )
    assert all(r.distance_miles != d for r in dropped)


async def test_distance_hard_regions_soft_when_both(fixture_session: AsyncSession) -> None:
    # OH student, 600 mi, regions=[new_england]: distance is the hard rule; regions are soft
    p = prof(home_state="OH", income_bracket="75-110k", max_distance_miles=600,
             regions=["new_england"])  # fmt: skip
    rows = await sql_filters.candidates(fixture_session, p, ["5138", "1107", "1101"])
    assert rows
    assert all(r.distance_miles is not None and r.distance_miles <= 660 for r in rows)
    assert {r.state for r in rows} - {"CT", "ME", "MA", "NH", "RI", "VT"}, "regions not hard"
    assert all(r.region_match == (r.state in {"CT", "ME", "MA", "NH", "RI", "VT"}) for r in rows)
    # regions alone are hard
    only_regions = prof(home_state="OH", income_bracket="75-110k", regions=["new_england"])
    rows2 = await sql_filters.candidates(fixture_session, only_regions, ["5138", "1107", "1101"])
    assert rows2 and {r.state for r in rows2} <= {"CT", "ME", "MA", "NH", "RI", "VT"}
    assert all(r.region_match is None for r in rows2)


async def test_relax_distance_before_regions(fixture_session: AsyncSession) -> None:
    # 10 miles from RI: too few; dropping distance makes regions (northeast) hard, which
    # still leaves >= k schools in the fixture, so regions are kept.
    p = prof(home_state="RI", income_bracket="75-110k", interests=["computer science"],
             max_distance_miles=10, regions=["northeast", "south"])  # fmt: skip
    r = Retriever(embedder=HashEmbedder())
    cands = await r.retrieve(fixture_session, p, k=5, mode="hybrid_rerank")
    assert r.last_trace["relaxed"] == ["distance"]
    allowed = states_for_regions(["northeast", "south"], "RI")
    assert cands and {c.state for c in cands} <= allowed


async def test_stage_a_fallback_any_major(fixture_session: AsyncSession) -> None:
    p = prof(home_state="OH", income_bracket="48-75k", gpa=3.5)  # no interests, no majors
    for mode in ("hybrid", "hybrid_rerank"):
        r = Retriever(embedder=HashEmbedder())
        cands = await r.retrieve(fixture_session, p, k=10, mode=mode)  # type: ignore[arg-type]
        assert r.last_trace["stage_a_fallback"] is True
        assert len(cands) == 10 and all(c.cip4 is None for c in cands)
    r = Retriever(embedder=HashEmbedder())
    await r.retrieve(fixture_session, prof(**CS_TX), k=5)
    assert r.last_trace["stage_a_fallback"] is False


async def test_location_relaxed_when_too_few(fixture_session: AsyncSession) -> None:
    p = prof(home_state="RI", income_bracket="75-110k", interests=["computer science"],
             max_distance_miles=10)  # fmt: skip
    r = Retriever(embedder=HashEmbedder())
    cands = await r.retrieve(fixture_session, p, k=10, mode="hybrid_rerank")
    assert r.last_trace["location_relaxed"] is True
    assert r.last_trace["relaxed"] == ["distance"]
    assert len(cands) == 10


async def test_band_balance(fixture_session: AsyncSession) -> None:
    p = prof(home_state="NY", income_bracket="75-110k", sat=1300, gpa=3.7,
             interests=["biology", "psychology", "business", "computer science"])  # fmt: skip
    r = Retriever(embedder=HashEmbedder())
    k, pool = 10, 40
    cands = await r.retrieve(fixture_session, p, k=k, mode="hybrid_rerank", pool=pool)
    assert len(cands) == k

    # reconstruct the band availability in the balancing pool
    cips = await by_embedding(fixture_session, HashEmbedder(), p, 8)
    rows = await sql_filters.candidates(fixture_session, p, [c.cip4 for c in cips])
    med = await sql_filters.bracket_median(fixture_session, "75-110k")
    ranked = rerank.best_per_school(
        rerank.score_rows(rows, p, {c.cip4: c.similarity for c in cips}, med)
    )
    avail = {
        b: sum(1 for s in ranked[: max(pool, 2 * k)] if s.admission.band == b)
        for b in ("safety", "target", "reach")
    }

    bands = [c.admission_band for c in cands]
    for band, (lo, _hi) in rerank.band_quotas(k).items():
        assert bands.count(band) >= min(lo, avail[band]), (band, bands, avail)
    others_short = sum(avail.values()) - max(avail.values()) < k
    if not others_short:
        for band, (_, hi) in rerank.band_quotas(k).items():
            assert bands.count(band) <= hi, (band, bands)
    assert all(c.band_confidence == "normal" or c.admission_band != "unknown" for c in cands)


async def test_no_stats_means_unknown_bands(fixture_session: AsyncSession) -> None:
    p = prof(**ART_CA)
    cands = await Retriever(embedder=HashEmbedder()).retrieve(fixture_session, p, k=10)
    assert {c.admission_band for c in cands} == {"unknown"}


async def test_sql_only_vs_hybrid_differ_with_interests(fixture_session: AsyncSession) -> None:
    p = prof(**CS_TX)
    r = Retriever(embedder=HashEmbedder())
    sql = await r.retrieve(fixture_session, p, k=10, mode="sql_only")
    hyb = await r.retrieve(fixture_session, p, k=10, mode="hybrid")
    assert all(c.cip4 is None for c in sql)  # no intended majors → any major
    assert all(c.cip4 is not None for c in hyb)
    assert [c.unitid for c in sql] != [c.unitid for c in hyb]
    # the vector path finds computing majors from the interests
    assert any("Computer" in (c.cip_title or "") for c in hyb)


async def test_sql_only_uses_intended_majors(fixture_session: AsyncSession) -> None:
    p = prof(home_state="OH", income_bracket="30-48k", intended_majors=["nursing"], gpa=3.4)
    cips = await by_intended_majors(fixture_session, p)
    assert cips and cips[0].cip4 == "5138"
    cands = await Retriever().retrieve(fixture_session, p, k=10, mode="sql_only")
    assert cands and all(c.cip4 == "5138" for c in cands)


async def test_modes_errors(fixture_session: AsyncSession) -> None:
    p = prof(**CS_TX)
    with pytest.raises(NotImplementedError):
        await Retriever(HashEmbedder()).retrieve(fixture_session, p, mode="hybrid_riasec_rerank")
    with pytest.raises(ValueError):
        await Retriever().retrieve(fixture_session, p, mode="hybrid")


async def test_stage_timings_logged(fixture_session: AsyncSession) -> None:
    tl = TurnLogger(session_id="s", turn_id="t")
    await Retriever(HashEmbedder(), logger=tl).retrieve(fixture_session, prof(**CS_TX), k=5)
    names = [s["stage"] for s in tl.stages]
    assert names == ["retrieve.major_match", "retrieve.sql_filter", "retrieve.rerank"]
    assert all(s["ms"] >= 0 for s in tl.stages)


async def test_ablation_runner(fixture_session: AsyncSession) -> None:
    spec = importlib.util.spec_from_file_location("evals_ablation", REPO / "evals" / "ablation.py")
    assert spec and spec.loader
    ab = importlib.util.module_from_spec(spec)
    sys.modules["evals_ablation"] = ab
    spec.loader.exec_module(ab)
    personas = ab.load_personas(str(DATA / "personas" / "*.yaml"))
    labels = ab.load_labels(DATA / "labels.yaml")
    results = await ab.run_ablation(fixture_session, personas, labels, HashEmbedder())
    by_mode = {r.mode: r for r in results}
    assert list(by_mode) == ["sql_only", "hybrid", "hybrid_rerank", "hybrid_riasec_rerank"]
    assert by_mode["hybrid_riasec_rerank"].recall is None
    for m in ("sql_only", "hybrid", "hybrid_rerank"):
        assert by_mode[m].n == 2
        assert 0.0 <= by_mode[m].recall <= 1.0 and 0.0 <= by_mode[m].ndcg <= 1.0
        jp = by_mode[m].judged_precision
        assert jp is None or 0.0 <= jp <= 1.0
        assert 0 <= by_mode[m].unjudged <= 20
    table = ab.format_table(results)
    assert table.count("\n") == 5
    print("\n" + table)
