"""Test doubles and the scripted conversation shared by the counselor tests.

* ``ScriptedAnthropic`` — stands in for ``anthropic.AsyncAnthropic`` (``.messages.stream``
  / ``.messages.parse``) so ``LLMClient`` can run in ``live``/``record`` mode with no
  network. Calls are logged (kwargs) so tests can assert the exact API params.
* ``FakeRetriever`` — builds ``schemas.Candidate`` from ``data/fixtures/*.jsonl``.
* ``SCENARIO`` — a realistic three-turn conversation (hand-written Claude replies and
  extraction outputs) plus a recommendation response builder. ``tests/cassettes`` is
  generated from it by ``python -m tests.cassettes.build`` (record mode, fake transport).
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.counselor.extractor import ExtractionWire, WireUpdate
from app.counselor.facts import institution_facts
from app.counselor.groundedness import format_fact
from app.db.models import CipCode, Institution, Program
from app.schemas import (
    Candidate,
    ExtractionResult,
    ProfileDelta,
    RetrievalMode,
    ScoreBreakdown,
    StudentProfile,
    Update,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "data" / "fixtures"
CASSETTE_DIR = Path(__file__).resolve().parent / "cassettes"

# ----------------------------------------------------------------- fake Anthropic


def usage(inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


@dataclass
class ScriptedStream:
    chunks: list[str]
    stop_reason: str = "end_turn"
    usage: SimpleNamespace = field(default_factory=lambda: usage(900, 60, 1500, 0))
    delay_s: float = 0.0
    refusal_category: str | None = None


@dataclass
class ScriptedParse:
    output: BaseModel | dict[str, Any] | str
    stop_reason: str = "end_turn"
    usage: SimpleNamespace = field(default_factory=lambda: usage(1200, 350, 1800, 0))
    delay_s: float = 0.0
    refusal_category: str | None = None

    @property
    def text(self) -> str:
        if isinstance(self.output, BaseModel):
            return self.output.model_dump_json()
        if isinstance(self.output, dict):
            return json.dumps(self.output)
        return self.output


def _message(text: str, stop_reason: str, u: SimpleNamespace, category: str | None) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        usage=u,
    )


class _StreamCM:
    def __init__(self, item: ScriptedStream, log: list[tuple[str, float]]):
        self.item = item
        self.log = log

    async def __aenter__(self) -> _StreamCM:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            loop = asyncio.get_running_loop()
            self.log.append(("stream_start", loop.time()))
            per_chunk = self.item.delay_s / max(1, len(self.item.chunks))
            for c in self.item.chunks:
                await asyncio.sleep(per_chunk)
                yield c
            self.log.append(("stream_end", loop.time()))

        return gen()

    async def get_final_message(self) -> Any:
        i = self.item
        return _message("".join(i.chunks), i.stop_reason, i.usage, i.refusal_category)


def _route(kwargs: dict[str, Any]) -> str | None:
    """Structured-output route: schema title (Pydantic models) or 'json_schema'."""
    fmt = (kwargs.get("output_config") or {}).get("format")
    if fmt is not None:
        return str(fmt["schema"].get("title") or "json_schema")
    if kwargs.get("output_format") is not None:
        return str(kwargs["output_format"].__name__)
    return None


def _sdk_eager_validate(kwargs: dict[str, Any], text: str) -> None:
    """Mimic the SDK: with ``output_format`` it validates eagerly and raises
    ``pydantic.ValidationError`` (escaping stop_reason handling)."""
    fmt = kwargs.get("output_format")
    if fmt is not None:
        fmt.model_validate_json(text)


class _Messages:
    def __init__(self, owner: ScriptedAnthropic):
        self.o = owner

    def _pop(self, route: str) -> ScriptedStream | ScriptedParse:
        item = self.o.queues[route].popleft()
        if isinstance(item, Exception):
            raise item
        return item

    def stream(self, **kwargs: Any) -> _StreamCM | _ParseCM:
        self.o.calls.append(("stream", kwargs))
        route = _route(kwargs)
        if route is None:
            item = self._pop("stream")
            assert isinstance(item, ScriptedStream)
            return _StreamCM(item, self.o.timeline)
        parsed = self._pop(route)
        assert isinstance(parsed, ScriptedParse)
        return _ParseCM(parsed, route, kwargs, self.o.timeline)

    async def parse(self, **kwargs: Any) -> Any:
        self.o.calls.append(("parse", kwargs))
        route = _route(kwargs) or "json_schema"
        item = self._pop(route)
        assert isinstance(item, ScriptedParse)
        await asyncio.sleep(item.delay_s)
        _sdk_eager_validate(kwargs, item.text)
        return _message(item.text, item.stop_reason, item.usage, item.refusal_category)


class _ParseCM:
    def __init__(
        self,
        item: ScriptedParse,
        route: str,
        kwargs: dict[str, Any],
        log: list[tuple[str, float]],
    ):
        self.item, self.route, self.kwargs, self.log = item, route, kwargs, log

    async def __aenter__(self) -> _ParseCM:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_final_message(self) -> Any:
        loop = asyncio.get_running_loop()
        self.log.append((f"parse_start:{self.route}", loop.time()))
        await asyncio.sleep(self.item.delay_s)
        self.log.append((f"parse_end:{self.route}", loop.time()))
        i = self.item
        _sdk_eager_validate(self.kwargs, i.text)
        return _message(i.text, i.stop_reason, i.usage, i.refusal_category)


class ScriptedAnthropic:
    """Queues: ``stream`` for text replies; structured calls are routed by the schema
    title (e.g. ``ExtractionWire``) or ``json_schema`` for raw-schema calls."""

    def __init__(self) -> None:
        self.queues: dict[str, deque[ScriptedStream | ScriptedParse | Exception]] = defaultdict(
            deque
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.timeline: list[tuple[str, float]] = []
        self.messages = _Messages(self)

    def add_stream(self, item: ScriptedStream | Exception) -> None:
        self.queues["stream"].append(item)

    def add_parse(self, route: str, item: ScriptedParse | Exception) -> None:
        self.queues[route].append(item)


# ------------------------------------------------------------------ fixture data


def _jsonl(name: str) -> list[dict[str, Any]]:
    with (FIXTURES / name).open() as f:
        return [json.loads(line) for line in f if line.strip()]


_INST = {r["unitid"]: r for r in _jsonl("institutions_sample.jsonl")}
_PROG = _jsonl("programs_sample.jsonl")

INST_COLUMNS = {c.name for c in Institution.__table__.columns}
PROG_COLUMNS = {c.name for c in Program.__table__.columns} - {"id"}


def institution_row(unitid: int) -> dict[str, Any]:
    return {k: v for k, v in _INST[unitid].items() if k in INST_COLUMNS}


def _band(rate: float | None, open_adm: bool | None) -> str:
    if open_adm:
        return "safety"
    if rate is None:
        return "unknown"
    if rate < 0.15:
        return "reach"
    return "safety" if rate >= 0.5 else "target"


@dataclass
class FakeRetriever:
    """Deterministic retriever over the fixture JSONL (computer-science programs)."""

    cips: tuple[str, ...] = ("1101", "1107")
    limit: int = 12
    calls: list[tuple[int, str]] = field(default_factory=list)
    loggers: list[Any] = field(default_factory=list)

    def candidates(self, profile: StudentProfile, k: int) -> list[Candidate]:
        bracket = profile.income_bracket.value
        rows = sorted(
            (
                p
                for p in _PROG
                if p["cip4"] in self.cips
                and p["credential_level"] == 3
                and p["median_earnings"] is not None
            ),
            key=lambda p: (p["unitid"], p["cip4"]),
        )
        out: list[Candidate] = []
        for p in rows:
            inst = _INST[p["unitid"]]
            facts = institution_facts(Institution(**institution_row(p["unitid"])), bracket)
            if facts["net_price"] is None:
                continue
            facts["program_median_earnings"] = p["median_earnings"]
            facts["program_median_debt"] = p["median_debt"]
            n = len(out)
            total = round(max(0.05, 0.9 - n * 0.03), 4)
            out.append(
                Candidate(
                    unitid=p["unitid"],
                    name=inst["name"],
                    city=inst["city"],
                    state=inst["state"],
                    cip4=p["cip4"],
                    cip_title=p["cip_title"],
                    admission_band=_band(inst["admission_rate"], inst["open_admission"]),  # type: ignore[arg-type]
                    band_confidence="normal",
                    scores=ScoreBreakdown(
                        major_fit=0.9,
                        affordability=0.7,
                        outcomes=0.8,
                        admission_fit=0.6,
                        preferences=0.5,
                        total=total,
                    ),
                    facts=facts,
                )
            )
            if len(out) >= min(k, self.limit):
                break
        return out

    async def retrieve(
        self,
        session: AsyncSession,
        profile: StudentProfile,
        k: int,
        mode: RetrievalMode,
        *,
        logger: Any = None,
    ) -> list[Candidate]:
        self.calls.append((k, mode))
        self.loggers.append(logger)
        return self.candidates(profile, k)


async def seed_reference_rows(db: AsyncSession, candidates: list[Candidate]) -> None:
    """Upsert the institutions / CIP codes / programs the candidates reference."""
    unitids = sorted({c.unitid for c in candidates})
    await db.execute(
        insert(Institution)
        .values([institution_row(u) for u in unitids])
        .on_conflict_do_nothing(index_elements=["unitid"])
    )
    progs = [p for p in _PROG if p["unitid"] in set(unitids) and p["credential_level"] == 3]
    cips = {p["cip4"]: p["cip_title"] for p in progs}
    await db.execute(
        insert(CipCode)
        .values([{"cip4": c, "title": t} for c, t in sorted(cips.items())])
        .on_conflict_do_nothing(index_elements=["cip4"])
    )
    await db.execute(
        insert(Program)
        .values([{k: v for k, v in p.items() if k in PROG_COLUMNS} for p in progs])
        .on_conflict_do_nothing(constraint="uq_program")
    )
    await db.commit()


# --------------------------------------------------------------------- scenario


def upd(value: Any, confidence: float, quote: str) -> Update[Any]:
    return Update(value=value, confidence=confidence, quote=quote)


@dataclass(frozen=True)
class ScenarioTurn:
    student: str
    reply_chunks: list[str]
    extraction: ExtractionResult


SCENARIO: list[ScenarioTurn] = [
    ScenarioTurn(
        student=(
            "Hi! I'm a junior and honestly kind of stressed about college. I really love "
            "coding and building little games on my computer."
        ),
        reply_chunks=[
            "Hi! It's completely normal to feel stressed",
            " about college, and you're starting early, which is great.",
            " Building your own games is a fantastic skill.",
            " If money weren't involved and you weren't getting paid,",
            " what would you happily do for the rest of your life?",
        ],
        extraction=ExtractionResult(
            delta=ProfileDelta(
                interests=upd(
                    ["coding", "building games"],
                    0.9,
                    "I really love coding and building little games on my computer",
                )
            ),
            next_topic="dream_without_money",
        ),
    ),
    ScenarioTurn(
        student=(
            "I live in Ohio, near Columbus. If money didn't matter I'd make video games all "
            "day, like the kind with really good stories."
        ),
        reply_chunks=[
            "Story-driven games are such a cool mix",
            " of creativity and technical skill, and Ohio gives you lots of options.",
            " To figure out what college would really cost your family,",
            " roughly which income range is your household in: under $30k, $30-48k,",
            " $48-75k, $75-110k, or over $110k?",
        ],
        extraction=ExtractionResult(
            delta=ProfileDelta(
                home_state=upd("OH", 0.95, "I live in Ohio"),
                dream_without_money=upd(
                    "make story-driven video games", 0.9, "I'd make video games all day"
                ),
            ),
            next_topic="money",
        ),
    ),
    ScenarioTurn(
        student=(
            "My parents make around 60 thousand a year together. I have a 3.7 GPA and got a "
            "1310 on the SAT."
        ),
        reply_chunks=[
            "Thanks for sharing that, it really helps me find schools",
            " that fit your budget, and your grades give you solid options.",
            " You can ask to see your college matches whenever you like.",
            " While we're at it, do you picture yourself at a big campus or somewhere smaller?",
        ],
        extraction=ExtractionResult(
            delta=ProfileDelta(
                income_bracket=upd("48-75k", 0.85, "My parents make around 60 thousand a year"),
                gpa=upd(3.7, 0.95, "I have a 3.7 GPA"),
                sat=upd(1310, 0.95, "got a 1310 on the SAT"),
            ),
            next_topic="size_setting",
        ),
    ),
]

REASONS = [
    [
        "Its computer science program is a strong match for your love of coding and "
        "building games.",
        "It is one of the more affordable options for your family's income range.",
        "Graduates of this program go on to well-paying careers in tech.",
    ],
    [
        "You could turn your passion for story-driven games into a computing degree here.",
        "The program's graduates report strong earnings after college.",
    ],
    [
        "A solid computing program where your creative side and technical skills can "
        "grow together.",
        "Your grades put this school in an estimated comfortable range.",
    ],
]


def _claim(c: Candidate, field_name: str) -> dict[str, Any] | None:
    v = c.facts.get(field_name)
    if v is None:
        return None
    if field_name in ("admission_rate", "completion_rate"):
        shown = f"{round(float(v) * 100)}%"
    else:
        shown = format_fact(field_name, v)
    return {"field": field_name, "value": shown}


def recommendation_output(candidates: list[Candidate], k: int) -> dict[str, Any]:
    """A realistic Opus response: picks, digit-free reasons, claims copied from facts."""
    picks = sorted(candidates, key=lambda c: c.facts["net_price"] or 0)[:k]  # type: ignore[arg-type,return-value]
    recs = []
    for i, c in enumerate(picks):
        fields = ["net_price", "admission_rate", "program_median_earnings", "city_state"]
        claims = [cl for f in fields if (cl := _claim(c, f)) is not None]
        recs.append(
            {
                "unitid": c.unitid,
                "cip4": c.cip4 or "",
                "reasons": REASONS[i % len(REASONS)],
                "claims": claims,
            }
        )
    return {"recommendations": recs}


def wire_update(name: str, value: Any, confidence: float, quote: str) -> WireUpdate:
    """A realistic wire update: the value in its typed slot, sentinels elsewhere."""
    slots: dict[str, Any] = {"text": "", "number": 0, "items": [], "activities": []}
    if name in ("activities",):
        slots["activities"] = [
            {
                "name": a.name,
                "role": a.role or "",
                "years": a.years or 0,
                "hours_per_week": a.hours_per_week or 0,
            }
            for a in value
        ]
    elif isinstance(value, list):
        slots["items"] = value
    elif isinstance(value, int | float):
        slots["number"] = value
    else:
        slots["text"] = value
    return WireUpdate(field=name, confidence=confidence, quote=quote, **slots)  # type: ignore[arg-type]


def to_wire(result: ExtractionResult) -> ExtractionWire:
    updates = [
        wire_update(name, upd.value, upd.confidence, upd.quote)
        for name in ProfileDelta.model_fields
        if (upd := getattr(result.delta, name)) is not None
    ]
    return ExtractionWire(updates=updates, next_topic=result.next_topic)


def script_scenario(fake: ScriptedAnthropic) -> None:
    for t in SCENARIO:
        fake.add_stream(ScriptedStream(chunks=t.reply_chunks))
        fake.add_parse("ExtractionWire", ScriptedParse(output=to_wire(t.extraction)))


def script_recommendation(fake: ScriptedAnthropic, profile: StudentProfile, k: int) -> None:
    out = recommendation_output(FakeRetriever().candidates(profile, 40), k)
    fake.add_parse("json_schema", ScriptedParse(output=out, usage=usage(5200, 1400, 2100, 0)))


def scenario_profile() -> StudentProfile:
    from app.schemas import apply_delta

    p = StudentProfile()
    for i, t in enumerate(SCENARIO):
        p = apply_delta(p, t.extraction.delta, i * 2, "chat")
    return p


SCENARIO_K = 3


def make_app(llm: Any, retriever: Any) -> Any:
    from app.api.sessions import get_retriever
    from app.core.llm import get_llm_client
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: retriever
    return app


@dataclass
class ScenarioRun:
    session_id: str
    turn_events: list[list[tuple[str, dict[str, Any]]]]
    turn_bodies: list[str]
    state: dict[str, Any]
    recommendations: dict[str, Any]


async def run_api_scenario(client: Any, k: int = SCENARIO_K) -> ScenarioRun:
    """Create a session, play the three scripted turns, then ask for recommendations."""
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as db:
        await seed_reference_rows(db, FakeRetriever().candidates(scenario_profile(), 40))

    r = await client.post("/api/sessions", json={"mode": "text"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    events, bodies = [], []
    for t in SCENARIO:
        resp = await client.post(f"/api/sessions/{sid}/turns", json={"text": t.student})
        assert resp.status_code == 200, resp.text
        bodies.append(resp.text)
        events.append(parse_sse(resp.text))
    state = (await client.get(f"/api/sessions/{sid}")).json()
    rec = await client.post(
        f"/api/sessions/{sid}/recommendations", json={"mode": "hybrid_rerank", "k": k}
    )
    assert rec.status_code == 200, rec.text
    return ScenarioRun(sid, events, bodies, state, rec.json())


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        name, data = "", ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if name:
            events.append((name, json.loads(data)))
    return events
