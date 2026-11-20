"""Eval runner end to end (fake Anthropic transport, scripted simulator), budget guard,
and the Ollama / Claude simulator backends' record/replay."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.common import load_persona  # noqa: E402
from evals.fake_counselor import FakeCounselorAnthropic  # noqa: E402
from evals.run import BudgetExceeded, CostMeter, RunConfig, estimate_cost, run  # noqa: E402
from evals.simulator import ClaudeSimulator, OllamaSimulator  # noqa: E402

from app.core.llm import LLMClient, ReplayMissError  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.retrieval.embedder import FakeEmbedder  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PERSONAS = "maya-oh,zoe-co"


def _cfg(tmp: Path, mode: str, run_id: str, **kw: object) -> RunConfig:
    base: dict[str, object] = dict(
        mode=mode,
        sim="scripted",
        personas=PERSONAS,
        cassette_dir=tmp / "cassettes",
        out_dir=tmp / "results",
        run_id=run_id,
    )
    base.update(kw)
    return RunConfig(**base)  # type: ignore[arg-type]


def test_cost_meter_and_estimate() -> None:
    m = CostMeter(limit_usd=0.05)
    m.add(0.02)
    m.add(0.02, kind="sim")
    assert m.counselor_usd == 0.02 and m.sim_usd == 0.02
    with pytest.raises(BudgetExceeded):
        m.check(upcoming_usd=0.13)
    with pytest.raises(BudgetExceeded):
        m.add(0.02)
    assert CostMeter().check(1e9) is None  # no limit
    est = estimate_cost(36, "ollama", turns=9)
    assert est["per_session_usd"] == pytest.approx(9 * 0.01 + 0.13)
    assert est["total_usd"] == pytest.approx(36 * 0.22)


@pytest.mark.usefixtures("loaded_db")
async def test_record_then_replay_is_identical(tmp_path: Path) -> None:
    sm, emb = get_sessionmaker(), FakeEmbedder()
    rec = await run(
        _cfg(tmp_path, "record", "rec", transport="fake"), sessionmaker=sm, embedder=emb
    )
    assert rec.summary["statuses"] == {"ok": 2}
    assert (tmp_path / "cassettes" / "provenance.json").exists()
    rep = await run(_cfg(tmp_path, "replay", "rep"), sessionmaker=sm, embedder=emb)
    assert rep.summary["statuses"] == {"ok": 2}
    assert rep.summary["cassette_provenance"]["transport"] == "fake"
    for a, b in zip(rec.results, rep.results, strict=True):
        assert a["transcript"] == b["transcript"]
        assert a["final_profile"] == b["final_profile"]
        assert [r["unitid"] for r in a["recommendations"]] == [
            r["unitid"] for r in b["recommendations"]
        ]
        assert a["totals"]["cost_usd"] == pytest.approx(b["totals"]["cost_usd"])
        assert b["groundedness"]["groundedness"] == 1.0 and b["groundedness"]["n_claims"] > 0
        assert b["hallucinated_schools"] == 0
        t0 = b["turns"][0]
        assert set(t0["stages"]) >= {"extract", "reply_total"} and t0["next_topic"]
        assert {"retrieve", "recommend", "groundedness"} <= set(b["recommend_stages"])
        assert b["guard"]["multi_leaks"] == 0 and b["guard"]["character_breaks"] == 0
    retrieval = json.loads((rep.run_dir / "retrieval.json").read_text())
    assert set(retrieval["personas"]) == {"maya-oh", "zoe-co"}
    entry = retrieval["personas"]["maya-oh"]
    assert set(entry["gold"]) == set(retrieval["modes"]) == {"sql_only", "hybrid", "hybrid_rerank"}
    assert "hybrid_riasec_rerank" in retrieval["not_implemented"]
    assert all(len(v) <= 10 for v in entry["e2e"].values())
    files = {p.name for p in rep.run_dir.iterdir()}
    assert {"maya-oh.json", "zoe-co.json", "summary.json", "retrieval.json"} <= files


@pytest.mark.usefixtures("loaded_db")
async def test_replay_miss_marks_persona_error(tmp_path: Path) -> None:
    res = await run(
        _cfg(tmp_path, "replay", "miss", personas="maya-oh", skip_retrieval=True),
        sessionmaker=get_sessionmaker(),
        embedder=FakeEmbedder(),
    )
    assert res.summary["statuses"] == {"error": 1}
    assert "replay miss" in res.results[0]["error"]


@pytest.mark.usefixtures("loaded_db")
async def test_budget_guard_aborts_live_run(tmp_path: Path) -> None:
    res = await run(
        _cfg(tmp_path, "live", "budget", max_cost_usd=0.02, skip_retrieval=True),
        sessionmaker=get_sessionmaker(),
        anthropic_client=FakeCounselorAnthropic(),
        embedder=FakeEmbedder(),
    )
    s = res.summary
    assert s["aborted"] and "budget guard" in s["aborted"]
    assert s["cost_usd"] > 0.02
    # stopped long before the full run (~$0.11 per persona with the fake's token counts)
    assert s["cost_usd"] < 0.05
    assert json.loads((res.run_dir / "summary.json").read_text())["aborted"] == s["aborted"]


async def test_ollama_simulator_record_and_replay(tmp_path: Path) -> None:
    persona = load_persona(REPO / "evals" / "personas" / "maya-oh.yaml")
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": 'Student: "idk, art stuff?"'},
                "prompt_eval_count": 300,
                "eval_count": 6,
            },
        )

    sim = OllamaSimulator(
        persona, mode="record", cassette_dir=tmp_path, transport=httpx.MockTransport(handler)
    )
    first = await sim.opening()
    assert first.text == "idk, art stuff?" and first.input_tokens == 300
    body = seen[0]
    assert body["model"] == "qwen2.5:7b-instruct" and body["stream"] is False
    system = body["messages"][0]["content"]  # type: ignore[index]
    assert "edge_cases" not in system and "articulateness" not in system
    assert len(list(tmp_path.glob("ollama-*.json"))) == 1

    replay = OllamaSimulator(persona, mode="replay", cassette_dir=tmp_path)
    assert (await replay.opening()).text == "idk, art stuff?"
    with pytest.raises(ReplayMissError):
        await replay.reply("What's your GPA?")


async def test_claude_simulator_records_cost_and_replays(tmp_path: Path) -> None:
    persona = load_persona(REPO / "evals" / "personas" / "maya-oh.yaml")
    llm = LLMClient(mode="record", cassette_dir=tmp_path, anthropic_client=FakeCounselorAnthropic())
    sim = ClaudeSimulator(persona, llm)
    t = await sim.opening()
    assert t.text and t.cost_usd > 0
    replay = ClaudeSimulator(persona, LLMClient(mode="replay", cassette_dir=tmp_path))
    assert (await replay.opening()).text == t.text
