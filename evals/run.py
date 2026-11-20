"""Run simulated students through the real counselor, in-process (SPEC §10).

Same code path as the API: ``CounselorOrchestrator.handle_turn`` for every student
message, then ``CounselorOrchestrator.recommend``. Each persona plays until the profile
is ready plus ``--turns-after-ready`` more turns, or ``--max-turns``; then it asks for
recommendations. Afterwards retrieval is re-run on the **gold** (hidden) and the
**end-to-end** (extracted) profile for every mode (``evals/retrieval_eval.py``).

Outputs ``evals/results/<run_id>/``::

    <persona>.json     transcript, per-turn stage metrics + simulator guard, final profile,
                       next topics, recommendations, groundedness report, cost/latency
    retrieval.json     top-k unitids per persona x {gold, e2e} x mode
    summary.json       run metadata, statuses, total cost, guard counts, abort reason

Modes (``--mode``): ``replay`` (cassettes only — free, CI), ``record`` (call the API and
save cassettes), ``live`` (call the API). ``--transport fake`` answers every Claude call
with :mod:`evals.fake_counselor` instead of the API (for building offline cassettes).

Budget guard: ``--max-cost-usd`` aborts the run as soon as the cumulative cost (the
TurnLogger stage costs persisted in ``turn_metric`` plus simulator cost) exceeds it, and
refuses to start a recommendation (Opus) call that would cross it. Real-API runs require
``--confirm`` and default to a $5 cap.

Examples (from ``backend/``)::

    EMBEDDER=fake uv run python ../evals/run.py --mode replay --sim scripted \
        --personas 'aaliyah-ga,maya-oh,zoe-co' --cassette-dir tests/cassettes/evals
    uv run python ../evals/run.py --mode record --sim ollama --max-cost-usd 6 --confirm
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [p for p in (str(_REPO), str(_REPO / "backend")) if p not in sys.path]

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator, Callable  # noqa: E402
from dataclasses import asdict, dataclass, field  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.llm import (  # noqa: E402
    DEFAULT_CASSETTE_DIR,
    LLMClient,
    ReplayMissError,
    TextStream,
)
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.counselor.groundedness import GroundednessReport  # noqa: E402
from app.counselor.orchestrator import CounselorOrchestrator, NotReady  # noqa: E402
from app.db.models import (  # noqa: E402
    ChatSession,
    ProfileSnapshot,
    RecommendationSetRow,
    TurnMetricRow,
)
from app.schemas import StudentProfile  # noqa: E402
from evals.common import (  # noqa: E402
    DEFAULT_PERSONAS,
    RESULTS_DIR,
    Persona,
    git_sha,
    load_personas,
)
from evals.simulator import DEFAULT_OLLAMA_MODEL, SimTurn, make_simulator  # noqa: E402
from evals.topics import asked_topics  # noqa: E402

log = get_logger(__name__)

# Measured live numbers (owner's spot checks): Sonnet reply + extraction per turn, one
# Opus recommendation per session. Used for the pre-run estimate and the Opus pre-check.
EST_COST_PER_TURN = 0.01
EST_COST_PER_RECOMMEND = 0.13
EST_SIM_COST_PER_TURN = {"claude": 0.004, "ollama": 0.0, "scripted": 0.0}
EST_TURNS = 8  # ready after ~5-6 turns (interests, location, money) + 2


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class CostMeter:
    """Cumulative run cost; raises :class:`BudgetExceeded` past ``limit_usd``."""

    limit_usd: float | None = None
    total_usd: float = 0.0
    counselor_usd: float = 0.0
    sim_usd: float = 0.0

    def add(self, usd: float, *, kind: str = "counselor") -> None:
        usd = float(usd or 0.0)
        self.total_usd += usd
        if kind == "sim":
            self.sim_usd += usd
        else:
            self.counselor_usd += usd
        self.check()

    def check(self, upcoming_usd: float = 0.0) -> None:
        if self.limit_usd is None:
            return
        if self.total_usd + upcoming_usd > self.limit_usd:
            raise BudgetExceeded(
                f"budget guard: cumulative ${self.total_usd:.4f}"
                + (f" + upcoming ${upcoming_usd:.2f}" if upcoming_usd else "")
                + f" exceeds --max-cost-usd ${self.limit_usd:.2f}"
            )


@dataclass
class RunConfig:
    mode: str = "replay"
    sim: str = "scripted"
    personas: str = DEFAULT_PERSONAS
    limit: int | None = None
    max_turns: int = 12
    turns_after_ready: int = 2
    concurrency: int = 1
    max_cost_usd: float | None = None
    cassette_dir: Path | None = None
    transport: str = "anthropic"
    retrieval_mode: str = "hybrid_rerank"
    k: int = 10
    run_id: str = ""
    out_dir: Path = RESULTS_DIR
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    skip_retrieval: bool = False

    def resolved_run_id(self) -> str:
        if not self.run_id:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            self.run_id = f"{stamp}-{self.mode}-{self.sim}"
        return self.run_id


def estimate_cost(n_personas: int, sim: str, turns: int = EST_TURNS) -> dict[str, float]:
    per_session = turns * (EST_COST_PER_TURN + EST_SIM_COST_PER_TURN.get(sim, 0.0))
    per_session += EST_COST_PER_RECOMMEND
    return {
        "personas": n_personas,
        "turns_per_session": turns,
        "per_session_usd": round(per_session, 4),
        "total_usd": round(per_session * n_personas, 2),
    }


# ----------------------------------------------------------------- DB helpers


def _stage_record(row: TurnMetricRow) -> dict[str, Any]:
    return {
        "ms": row.ms,
        "model": row.model,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "cache_creation_tokens": row.cache_creation_tokens,
        "cost_usd": row.cost_usd,
    }


async def _new_metrics(
    sm: async_sessionmaker[AsyncSession], sid: uuid.UUID, seen: set[uuid.UUID]
) -> dict[str, dict[str, Any]]:
    async with sm() as db:
        rows = (
            (await db.execute(select(TurnMetricRow).where(TurnMetricRow.session_id == sid)))
            .scalars()
            .all()
        )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.id in seen:
            continue
        seen.add(r.id)
        rec = _stage_record(r)
        if r.stage in out:  # same stage twice (shouldn't happen): sum
            prev = out[r.stage]
            for key in ("ms", "input_tokens", "output_tokens", "cost_usd"):
                prev[key] = (prev[key] or 0) + (rec[key] or 0)
        else:
            out[r.stage] = rec
    return out


def _report_dict(report: GroundednessReport) -> dict[str, Any]:
    return {
        "n_claims": report.n_claims,
        "n_verified": report.n_verified,
        "groundedness": report.groundedness,
        "reason_digit_violations": report.reason_digit_violations,
        "unverified": [c.model_dump(mode="json") for c in report.unverified],
    }


# ---------------------------------------------------------------- one persona


@dataclass
class TrackingLLM(LLMClient):
    """LLMClient that remembers replay misses. The orchestrator turns a reply miss into
    an ``error`` event and silently keeps the old profile on an extraction miss; the
    harness must still fail loudly when a cassette is stale."""

    misses: list[str] = field(default_factory=list)

    async def parse(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        try:
            return await super().parse(*args, **kwargs)
        except ReplayMissError as exc:
            self.misses.append(str(exc))
            raise

    def stream_text(self, *args: Any, **kwargs: Any) -> TextStream:  # type: ignore[override]
        ts = super().stream_text(*args, **kwargs)
        inner = ts._gen
        misses = self.misses

        async def tracked() -> AsyncIterator[str]:
            try:
                async for chunk in inner:
                    yield chunk
            except ReplayMissError as exc:
                misses.append(str(exc))
                raise

        ts._gen = tracked()
        return ts


@dataclass
class Deps:
    make_llm: Callable[[], TrackingLLM]
    sessionmaker: async_sessionmaker[AsyncSession]
    retriever: Any


async def run_persona(
    persona: Persona, cfg: RunConfig, deps: Deps, meter: CostMeter
) -> dict[str, Any]:
    sm = deps.sessionmaker
    llm = deps.make_llm()
    orch = CounselorOrchestrator(llm=llm, sessionmaker=sm)
    sim = make_simulator(
        cfg.sim,
        persona,
        mode=cfg.mode,
        llm=llm,
        cassette_dir=cfg.cassette_dir,
        ollama_model=cfg.ollama_model,
    )
    async with sm() as db:
        row = ChatSession(mode="text")
        db.add(row)
        await db.commit()
        sid = row.id

    result: dict[str, Any] = {
        "persona": persona.id,
        "persona_path": str(persona.path),
        "run_id": cfg.run_id,
        "mode": cfg.mode,
        "sim": {"kind": cfg.sim, "model": getattr(sim, "model", "")},
        "session_id": str(sid),
        "status": "running",
        "transcript": [],
        "turns": [],
    }
    seen: set[uuid.UUID] = set()
    t_start = time.perf_counter()

    def add_sim(st: SimTurn) -> None:
        meter.add(st.cost_usd, kind="sim")

    student = await sim.opening()
    add_sim(student)
    ready_turn: int | None = None
    for t in range(cfg.max_turns):
        meter.check()
        events = [ev async for ev in orch.handle_turn(sid, student.text)]
        stages = await _new_metrics(sm, sid, seen)
        meter.add(sum(s["cost_usd"] or 0.0 for s in stages.values()))
        by = {e.event: e.data for e in events}
        reply = (by.get("done") or {}).get("assistant_text", "")
        ready = bool((by.get("ready") or {}).get("ready"))
        turn = {
            "idx": t,
            "student": student.text,
            "counselor": reply,
            "sim": student.to_dict(),
            "stages": stages,
            "ready": ready,
            "missing": (by.get("ready") or {}).get("missing"),
            "asked_topics": sorted(asked_topics(reply)),
        }
        result["turns"].append(turn)
        result["transcript"] += [
            {"role": "student", "text": student.text},
            {"role": "counselor", "text": reply},
        ]
        if "error" in by:
            turn["error"] = by["error"].get("message")
            result["status"] = "error"
            result["error"] = f"counselor error at turn {t}"
            break
        if ready and ready_turn is None:
            ready_turn = t
        if ready_turn is not None and t - ready_turn >= cfg.turns_after_ready:
            break
        if t + 1 < cfg.max_turns:
            student = await sim.reply(reply)
            add_sim(student)
    result["n_turns"] = len(result["turns"])
    result["ready_turn"] = ready_turn

    async with sm() as db:
        snaps = (
            (
                await db.execute(
                    select(ProfileSnapshot)
                    .where(ProfileSnapshot.session_id == sid)
                    .order_by(ProfileSnapshot.after_turn, ProfileSnapshot.created_at)
                )
            )
            .scalars()
            .all()
        )
    profile = StudentProfile.model_validate(snaps[-1].profile) if snaps else StudentProfile()
    result["final_profile"] = profile.model_dump(mode="json")
    result["next_topics"] = [s.next_topic for s in snaps]
    # turn idx (0-based, user turns) -> next_topic chosen after that turn
    for turn, snap_topic in zip(result["turns"], [s.next_topic for s in snaps], strict=False):
        turn["next_topic"] = snap_topic

    result["recommendations"] = None
    if result["status"] != "error":
        try:
            meter.check(EST_COST_PER_RECOMMEND if cfg.mode != "replay" else 0.0)
            rs, report = await orch.recommend(
                sid,
                deps.retriever,
                mode=cfg.retrieval_mode,  # type: ignore[arg-type]
                k=cfg.k,
            )
            rec_stages = await _new_metrics(sm, sid, seen)
            meter.add(sum(s["cost_usd"] or 0.0 for s in rec_stages.values()))
            async with sm() as db:
                set_row = await db.get(RecommendationSetRow, rs.id)
                trace = set_row.retrieval_trace if set_row else {}
            retrieved = [c["unitid"] for c in (trace or {}).get("candidates", [])]
            result["recommend_stages"] = rec_stages
            result["retrieved_unitids"] = retrieved
            result["recommendations"] = [
                {
                    "rank": r.rank,
                    "unitid": r.unitid,
                    "name": r.name,
                    "city": r.city,
                    "state": r.state,
                    "cip4": r.cip4,
                    "cip_title": r.cip_title,
                    "admission_band": r.admission_band,
                    "reasons": r.reasons,
                    "claims": [c.model_dump(mode="json") for c in r.claims],
                }
                for r in rs.recommendations
            ]
            result["groundedness"] = _report_dict(report)
            result["hallucinated_schools"] = sum(
                1 for r in rs.recommendations if r.unitid not in set(retrieved)
            )
            result["status"] = "ok"
        except NotReady as exc:
            result["status"] = "not_ready"
            result["not_ready_missing"] = exc.missing

    if llm.misses:
        result["status"] = "error"
        result["error"] = f"replay miss ({len(llm.misses)}): {llm.misses[0]}"
        result["replay_misses"] = llm.misses
    guards = [t["sim"]["guard"] for t in result["turns"]]
    result["guard"] = {
        "messages": len(guards),
        "multi_leaks": sum(1 for g in guards if g["multi_leak"]),
        "unasked_reveals": sum(len(g["unasked"]) for g in guards),
        "character_breaks": sum(1 for g in guards if g["character_break"]),
    }
    counselor_cost = sum(
        (s.get("cost_usd") or 0.0) for t in result["turns"] for s in t["stages"].values()
    ) + sum((s.get("cost_usd") or 0.0) for s in (result.get("recommend_stages") or {}).values())
    sim_cost = sum(t["sim"]["cost_usd"] for t in result["turns"])
    result["totals"] = {
        "cost_usd": round(counselor_cost + sim_cost, 6),
        "counselor_cost_usd": round(counselor_cost, 6),
        "sim_cost_usd": round(sim_cost, 6),
        "wall_s": round(time.perf_counter() - t_start, 2),
    }
    return result


# ------------------------------------------------------------------ the run


@dataclass
class RunResult:
    run_dir: Path
    summary: dict[str, Any]
    results: list[dict[str, Any]] = field(default_factory=list)


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


async def run(
    cfg: RunConfig,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    anthropic_client: Any = None,
    embedder: Any = None,
) -> RunResult:
    from app.db.session import get_sessionmaker
    from app.retrieval.embedder import get_embedder
    from app.retrieval.retriever import Retriever

    run_id = cfg.resolved_run_id()
    run_dir = Path(cfg.out_dir) / run_id
    personas = load_personas(cfg.personas, cfg.limit)
    if not personas:
        raise SystemExit(f"no personas match {cfg.personas!r}")
    if anthropic_client is None and cfg.transport == "fake":
        from evals.fake_counselor import FakeCounselorAnthropic

        anthropic_client = FakeCounselorAnthropic()
    cfg.cassette_dir = Path(
        cfg.cassette_dir or get_settings().LLM_CASSETTE_DIR or DEFAULT_CASSETTE_DIR
    )
    cassettes = cfg.cassette_dir

    def make_llm() -> TrackingLLM:
        return TrackingLLM(
            mode=cfg.mode,  # type: ignore[arg-type]
            cassette_dir=cassettes,
            anthropic_client=anthropic_client,
        )

    sm = sessionmaker or get_sessionmaker()
    emb = embedder or get_embedder()
    deps = Deps(make_llm=make_llm, sessionmaker=sm, retriever=Retriever(embedder=emb))
    template = CounselorOrchestrator(llm=make_llm(), sessionmaker=sm)
    meter = CostMeter(limit_usd=cfg.max_cost_usd)
    started = datetime.now(UTC).isoformat()
    sem = asyncio.Semaphore(max(1, cfg.concurrency))
    results: dict[str, dict[str, Any]] = {}
    aborted: str | None = None

    async def one(p: Persona) -> None:
        async with sem:
            try:
                res = await run_persona(p, cfg, deps, meter)
            except BudgetExceeded:
                raise
            except Exception as exc:  # one persona failing never kills the run
                log.error("persona_failed", persona=p.id, error=repr(exc))
                res = {"persona": p.id, "status": "error", "error": repr(exc), "turns": []}
            results[p.id] = res
            _write(run_dir / f"{p.id}.json", res)
            print(
                f"[{p.id}] {res['status']} turns={len(res.get('turns', []))} "
                f"cost=${(res.get('totals') or {}).get('cost_usd', 0):.4f} "
                f"cum=${meter.total_usd:.4f}",
                flush=True,
            )

    tasks = [asyncio.create_task(one(p)) for p in personas]
    try:
        await asyncio.gather(*tasks)
    except BudgetExceeded as exc:
        aborted = str(exc)
        print(f"ABORTED: {aborted}", flush=True)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if not cfg.skip_retrieval and aborted is None:
        from evals.retrieval_eval import evaluate_run

        retrieval = await evaluate_run(
            [r for r in results.values() if r.get("status") != "error" or r.get("turns")],
            personas,
            sm,
            emb,
            k=cfg.k,
        )
        _write(run_dir / "retrieval.json", retrieval)

    prov_path = cfg.cassette_dir / "provenance.json"
    if cfg.mode == "record":
        _write(
            prov_path,
            {
                "transport": cfg.transport,
                "sim": cfg.sim,
                "recorded_at": datetime.now(UTC).isoformat(),
                "git_sha": git_sha(),
                "personas": sorted(results),
            },
        )
    provenance = json.loads(prov_path.read_text()) if prov_path.exists() else None

    statuses: dict[str, int] = {}
    for r in results.values():
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    summary = {
        "run_id": run_id,
        "mode": cfg.mode,
        "transport": cfg.transport,
        "sim": cfg.sim,
        "sim_model": cfg.ollama_model if cfg.sim == "ollama" else cfg.sim,
        "models": {
            "reply": template.reply_model,
            "extract": template.extractor.model if template.extractor else None,
            "recommend": template.recommender.model if template.recommender else None,
        },
        "cassette_provenance": provenance,
        "retrieval_mode": cfg.retrieval_mode,
        "embedder": getattr(emb, "model_name", type(emb).__name__),
        "git_sha": git_sha(),
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "personas": [p.id for p in personas],
        "completed": sorted(results),
        "statuses": statuses,
        "cost_usd": round(meter.total_usd, 6),
        "counselor_cost_usd": round(meter.counselor_usd, 6),
        "sim_cost_usd": round(meter.sim_usd, 6),
        "max_cost_usd": cfg.max_cost_usd,
        "aborted": aborted,
        "guard": {
            k: sum((r.get("guard") or {}).get(k, 0) for r in results.values())
            for k in ("messages", "multi_leaks", "unasked_reveals", "character_breaks")
        },
        "config": {
            k: str(v) if isinstance(v, Path) else v
            for k, v in asdict(cfg).items()
            if k not in ("out_dir",)
        },
    }
    _write(run_dir / "summary.json", summary)
    return RunResult(run_dir, summary, [results[k] for k in sorted(results)])


async def _run_and_dispose(cfg: RunConfig) -> RunResult:
    from app.db.session import dispose_engine

    try:
        return await run(cfg)
    finally:
        await dispose_engine()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["replay", "record", "live"], default="replay")
    ap.add_argument("--sim", choices=["ollama", "claude", "scripted"], default="ollama")
    ap.add_argument("--personas", default=DEFAULT_PERSONAS, help="glob or comma-separated ids")
    ap.add_argument("--limit", type=int, default=None, help="first N matching personas")
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--turns-after-ready", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--max-cost-usd", type=float, default=None)
    ap.add_argument("--cassette-dir", type=Path, default=None)
    ap.add_argument("--transport", choices=["anthropic", "fake"], default="anthropic")
    ap.add_argument("--retrieval-mode", default="hybrid_rerank")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    ap.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL)
    ap.add_argument("--skip-retrieval", action="store_true")
    ap.add_argument("--confirm", action="store_true", help="required for real API spending")
    ap.add_argument("--estimate-only", action="store_true", help="print the estimate and exit")
    return ap.parse_args(argv)


def config_from_args(a: argparse.Namespace) -> RunConfig:
    real_api = a.mode in ("live", "record") and a.transport == "anthropic"
    max_cost = a.max_cost_usd
    if real_api and max_cost is None:
        max_cost = 5.0
    return RunConfig(
        mode=a.mode,
        sim=a.sim,
        personas=a.personas,
        limit=a.limit,
        max_turns=a.max_turns,
        turns_after_ready=a.turns_after_ready,
        concurrency=a.concurrency,
        max_cost_usd=max_cost,
        cassette_dir=a.cassette_dir.resolve() if a.cassette_dir else None,
        transport=a.transport,
        retrieval_mode=a.retrieval_mode,
        k=a.k,
        run_id=a.run_id,
        out_dir=a.out_dir,
        ollama_model=a.ollama_model,
        skip_retrieval=a.skip_retrieval,
    )


def main(argv: list[str] | None = None) -> int:
    configure_logging("WARNING")
    a = parse_args(argv)
    cfg = config_from_args(a)
    n = len(load_personas(cfg.personas, cfg.limit))
    est = estimate_cost(n, cfg.sim)
    real_api = cfg.mode in ("live", "record") and cfg.transport == "anthropic"
    print(
        f"eval run: mode={cfg.mode} sim={cfg.sim} transport={cfg.transport} personas={n} "
        f"max_turns={cfg.max_turns} budget={cfg.max_cost_usd}",
        flush=True,
    )
    if real_api or a.estimate_only:
        print(
            f"estimated cost: {n} personas x ~{est['turns_per_session']} turns x "
            f"${EST_COST_PER_TURN}/turn + ${EST_COST_PER_RECOMMEND}/recommendation "
            f"= ~${est['total_usd']:.2f}",
            flush=True,
        )
    if a.estimate_only:
        return 0
    if real_api and not a.confirm:
        print("refusing to call the Anthropic API without --confirm", file=sys.stderr)
        return 3
    res = asyncio.run(_run_and_dispose(cfg))
    s = res.summary
    print(
        f"run {s['run_id']}: statuses={s['statuses']} cost=${s['cost_usd']:.4f} "
        f"guard={s['guard']} -> {res.run_dir}",
        flush=True,
    )
    if s["aborted"]:
        return 2
    return 1 if s["statuses"].get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
