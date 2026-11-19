"""Counselor orchestrator (SPEC §7 ``CounselorOrchestrator``, §8 both pipelines).

``handle_turn`` — one student message:

1. persist the user turn;
2. run the reply stream (Sonnet) and the extraction (Sonnet, structured) **concurrently**;
   the reply prompt sees the profile as of the previous turn + missing fields + the
   previous extraction's next-topic hint (it is one turn behind by design);
3. merge the extraction delta with ``schemas.apply_delta`` (an extraction failure of
   any kind is logged and never blocks the reply);
4. persist profile snapshot (+ ``next_topic``), assistant turn and ``turn_metric`` rows
   (``extract``, ``reply_ttft``, ``reply_total``);
5. yield SSE events: ``token``* -> ``profile`` -> ``ready`` -> ``done`` (or ``error``).

If the client disconnects mid-reply the model stream is closed and the partial
assistant text is persisted with ``interrupted=True``.

``recommend`` — retrieve -> synthesize (Opus) -> groundedness check -> persist. No DB
session is held open across the Opus call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.llm import Effort, LLMClient, LLMError, LLMRefusalError
from app.core.logging import TurnLogger, get_logger
from app.counselor.context import HistoryTurn, plan_next_topic, profile_json
from app.counselor.extractor import ExtractionOutcome, Extractor, add_extra_evidence
from app.counselor.facts import load_db_facts
from app.counselor.groundedness import (
    CheckedRecommendation,
    FactIndex,
    GroundednessReport,
    check,
    has_digit,
)
from app.counselor.prompts import load_prompt
from app.counselor.recommender import Recommender
from app.db.models import (
    ChatSession,
    ClaimRow,
    ProfileSnapshot,
    RecommendationRow,
    RecommendationSetRow,
    Turn,
    TurnMetricRow,
)
from app.schemas import (
    Candidate,
    Claim,
    EvidenceSource,
    NetPriceBasis,
    NextTopic,
    Recommendation,
    RecommendationOut,
    RecommendationSet,
    RetrievalMode,
    StudentProfile,
    apply_delta,
)

log = get_logger(__name__)

HISTORY_WINDOW = 20  # turns of history sent to the reply model
RETRIEVE_K = 40  # candidates handed to the recommender (SPEC §8)
REFUSAL_FALLBACK = (
    "I'm not able to help with that one, but I'm happy to keep talking about college, "
    "majors and careers. What's been on your mind about life after high school?"
)


class RetrieverProtocol(Protocol):
    async def retrieve(
        self,
        session: AsyncSession,
        profile: StudentProfile,
        k: int,
        mode: RetrievalMode,
        *,
        logger: TurnLogger | None = None,
    ) -> list[Candidate]: ...


class SessionNotFound(LookupError):
    pass


class NotReady(RuntimeError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"profile not ready for recommendations; missing {missing}")


@dataclass(frozen=True)
class TurnEvent:
    event: str
    data: dict[str, Any]

    def sse(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


# ------------------------------------------------------------------ DB helpers


async def get_chat_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
    row = await db.get(ChatSession, session_id)
    if row is None:
        raise SessionNotFound(str(session_id))
    return row


async def latest_state(
    db: AsyncSession, session_id: uuid.UUID
) -> tuple[StudentProfile, NextTopic | None]:
    """Latest profile snapshot and the extractor's ``next_topic`` stored with it."""
    snap = (
        await db.execute(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.session_id == session_id)
            .order_by(ProfileSnapshot.after_turn.desc(), ProfileSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if snap is None:
        return StudentProfile(), None
    return StudentProfile.model_validate(snap.profile), snap.next_topic  # type: ignore[return-value]


async def latest_profile(db: AsyncSession, session_id: uuid.UUID) -> StudentProfile:
    return (await latest_state(db, session_id))[0]


async def recent_turns(db: AsyncSession, session_id: uuid.UUID, limit: int) -> list[HistoryTurn]:
    rows = (
        (
            await db.execute(
                select(Turn)
                .where(Turn.session_id == session_id)
                .order_by(Turn.idx.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        HistoryTurn(idx=t.idx, role="user" if t.role == "user" else "assistant", text=t.text)
        for t in reversed(rows)
    ]


RECENT_SET_WINDOW_S = 60.0  # reuse a set this fresh for an identical request
_INFLIGHT: dict[tuple[uuid.UUID, str, str, int], asyncio.Future[Any]] = {}


def _profile_key(profile: StudentProfile) -> str:
    dumped = json.dumps(profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(dumped.encode()).hexdigest()


async def recent_recommendation_set(
    db: AsyncSession,
    session_id: uuid.UUID,
    profile: StudentProfile,
    mode: RetrievalMode,
    k: int,
) -> tuple[RecommendationSet, GroundednessReport] | None:
    """The newest set for this session created in the last ``RECENT_SET_WINDOW_S`` s
    from the same profile snapshot, mode and k — rebuilt from its stored response."""
    cutoff = func.now() - timedelta(seconds=RECENT_SET_WINDOW_S)
    row = (
        await db.execute(
            select(RecommendationSetRow)
            .where(
                RecommendationSetRow.session_id == session_id,
                RecommendationSetRow.retrieval_mode == mode,
                RecommendationSetRow.created_at >= cutoff,
            )
            .order_by(RecommendationSetRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    trace = row.retrieval_trace or {}
    if (
        trace.get("k") != k
        or "response" not in trace
        or row.profile_used != profile.model_dump(mode="json")
    ):
        return None
    outs = [RecommendationOut.model_validate(o) for o in trace["response"]]
    report = GroundednessReport(
        reason_digit_violations=int(trace.get("reason_digit_violations", 0))
    )
    for o in outs:
        rec = Recommendation(
            unitid=o.unitid,
            cip4=o.cip4,
            rank=o.rank,
            admission_band=o.admission_band,
            reasons=o.reasons,
            claims=[
                Claim(unitid=c.unitid, field=c.field, cip4=c.cip4, value=c.value) for c in o.claims
            ],
        )
        report.recommendations.append(CheckedRecommendation(rec, list(o.claims)))
        report.n_claims += len(o.claims)
        report.n_verified += sum(c.verified for c in o.claims)
    result = RecommendationSet(
        id=row.id,
        session_id=session_id,
        retrieval_mode=mode,
        recommendations=outs,
        groundedness=row.groundedness if row.groundedness is not None else report.groundedness,
        created_at=row.created_at,
    )
    return result, report


def _basis(facts: dict[str, Any]) -> NetPriceBasis:
    b = facts.get("net_price_basis")
    return b if b in ("in_state", "est_out_of_state", "private") else "unknown"  # type: ignore[return-value]


def _metric_row(
    session_id: uuid.UUID, turn_id: uuid.UUID | None, rec: dict[str, Any]
) -> TurnMetricRow:
    return TurnMetricRow(
        session_id=session_id,
        turn_id=turn_id,
        stage=rec["stage"],
        ms=float(rec["ms"]),
        model=rec.get("model"),
        input_tokens=int(rec.get("input_tokens") or 0),
        output_tokens=int(rec.get("output_tokens") or 0),
        cache_read_tokens=int(rec.get("cache_read_tokens") or 0),
        cache_creation_tokens=int(rec.get("cache_creation_tokens") or 0),
        cost_usd=float(rec.get("cost_usd") or 0.0),
    )


def build_reply_messages(
    history: list[HistoryTurn],
    text: str,
    profile: StudentProfile,
    next_topic: NextTopic | None = None,
) -> list[dict[str, Any]]:
    """History window + new user message + a trailing mid-conversation system note.

    The note (profile, gaps, next-topic hint) is the only per-turn-variable part and
    sits after the history, so system prompt + history stay a stable cache prefix.
    """
    turns = list(history)
    while turns and turns[0].role != "user":
        turns.pop(0)
    msgs: list[dict[str, Any]] = [{"role": t.role, "content": t.text} for t in turns]
    msgs.append({"role": "user", "content": text})
    missing = profile.missing_for_recommendation()
    note = (
        "Private counselor note (never reveal or quote it).\n"
        f"Known about the student: {profile_json(profile)}\n"
        f"Still needed before recommendations: {', '.join(missing) if missing else 'nothing'}\n"
        f"Suggested next topic: {next_topic or plan_next_topic(profile)}\n"
        f"Ready for recommendations: {'yes' if not missing else 'no'}"
    )
    msgs.append({"role": "system", "content": note})
    return msgs


# ---------------------------------------------------------------- orchestrator


@dataclass
class CounselorOrchestrator:
    llm: LLMClient
    sessionmaker: async_sessionmaker[AsyncSession]
    reply_model: str = field(default_factory=lambda: get_settings().MODEL_FAST)
    reply_effort: Effort = "low"
    reply_max_tokens: int = 4096
    history_window: int = HISTORY_WINDOW
    extractor: Extractor | None = None
    recommender: Recommender | None = None

    def __post_init__(self) -> None:
        self.extractor = self.extractor or Extractor(self.llm)
        self.recommender = self.recommender or Recommender(self.llm)

    # ------------------------------------------------------------- turn pipeline

    async def _persist_turn(
        self,
        *,
        session_id: uuid.UUID,
        user_idx: int,
        user_turn_id: uuid.UUID,
        source: EvidenceSource,
        assistant_text: str | None,
        interrupted: bool,
        snapshot: tuple[StudentProfile, NextTopic] | None,
        metrics: list[dict[str, Any]],
    ) -> Turn | None:
        async with self.sessionmaker() as db:
            if snapshot is not None:
                db.add(
                    ProfileSnapshot(
                        session_id=session_id,
                        after_turn=user_idx,
                        profile=snapshot[0].model_dump(mode="json"),
                        next_topic=snapshot[1],
                    )
                )
            assistant_turn: Turn | None = None
            if assistant_text is not None:
                assistant_turn = Turn(
                    session_id=session_id, idx=user_idx + 1, role="assistant",
                    text=assistant_text, source=source, interrupted=interrupted,
                )  # fmt: skip
                db.add(assistant_turn)
            db.add_all(_metric_row(session_id, user_turn_id, m) for m in metrics)
            await db.commit()
        return assistant_turn

    async def handle_turn(
        self, session_id: uuid.UUID, text: str, source: EvidenceSource = "chat"
    ) -> AsyncGenerator[TurnEvent, None]:
        assert self.extractor is not None
        # 1. persist the user turn; load previous profile + history
        async with self.sessionmaker() as db:
            await get_chat_session(db, session_id)
            history = await recent_turns(db, session_id, self.history_window)
            prev_profile, prev_topic = await latest_state(db, session_id)
            max_idx = (
                await db.execute(select(func.max(Turn.idx)).where(Turn.session_id == session_id))
            ).scalar_one_or_none()
            user_idx = 0 if max_idx is None else max_idx + 1
            user_turn = Turn(session_id=session_id, idx=user_idx, role="user", text=text,
                             source=source)  # fmt: skip
            db.add(user_turn)
            await db.commit()
            user_turn_id = user_turn.id

        tl = TurnLogger(session_id=str(session_id), turn_id=str(user_turn_id))
        extractor = self.extractor

        async def run_extraction() -> ExtractionOutcome:
            with tl.stage("extract") as st:
                try:
                    return await extractor.extract_with_evidence(
                        history, text, prev_profile, stage=st
                    )
                except LLMRefusalError as exc:
                    st.set(refusals=1, refusal=exc.category)
                    raise

        # 2. extraction and reply run concurrently
        extract_task = asyncio.create_task(run_extraction())
        stream = self.llm.stream_text(
            self.reply_model,
            load_prompt("counselor_reply").text,
            build_reply_messages(history, text, prev_profile, prev_topic),
            effort=self.reply_effort,
            max_tokens=self.reply_max_tokens,
        )
        reply_parts: list[str] = []
        reply_error: str | None = None
        stream_stage = None
        finished = False
        try:
            with tl.stage("reply_total") as st:
                st.set(prompt=load_prompt("counselor_reply").id)
                stream_stage = st
                try:
                    async for chunk in stream:
                        reply_parts.append(chunk)
                        yield TurnEvent("token", {"text": chunk})
                except LLMRefusalError as exc:
                    st.set(refusals=1, refusal=exc.category)
                    if not reply_parts:
                        reply_parts.append(REFUSAL_FALLBACK)
                        yield TurnEvent("token", {"text": REFUSAL_FALLBACK})
                except LLMError as exc:
                    reply_error = type(exc).__name__
                    log.error("reply_failed", error=reply_error)
                st.record_usage(
                    model=self.reply_model,
                    input_tokens=stream.usage.input_tokens,
                    output_tokens=stream.usage.output_tokens,
                    cache_read_tokens=stream.usage.cache_read_tokens,
                    cache_creation_tokens=stream.usage.cache_creation_tokens,
                    cost=stream.usage.cost(self.reply_model),
                )
                st.set(ttft_ms=stream.ttft_ms)
            finished = True
        finally:
            if not finished:  # client went away (GeneratorExit / cancellation)
                await stream.aclose()
                extract_task.cancel()
                if stream_stage is not None:
                    stream_stage.set(interrupted=True)
                await asyncio.shield(
                    self._persist_turn(
                        session_id=session_id,
                        user_idx=user_idx,
                        user_turn_id=user_turn_id,
                        source=source,
                        assistant_text="".join(reply_parts) if reply_parts else None,
                        interrupted=True,
                        snapshot=None,
                        metrics=list(tl.stages),
                    )
                )

        # 3. merge extraction — any failure keeps the previous profile
        profile = prev_profile
        snapshot: tuple[StudentProfile, NextTopic] | None = None
        try:
            outcome = await extract_task
            profile = apply_delta(prev_profile, outcome.result.delta, user_idx, source)
            profile = add_extra_evidence(profile, outcome.extra_quotes, user_idx, source)
            snapshot = (profile, outcome.result.next_topic)
        except Exception as exc:
            log.error("extract_failed", error=type(exc).__name__)

        # 4. persist (partial text after a mid-stream error is kept as interrupted)
        metrics = list(tl.stages)
        if stream.ttft_ms is not None:
            metrics.append({"stage": "reply_ttft", "ms": stream.ttft_ms, "model": self.reply_model})
        assistant_text = "".join(reply_parts)
        assistant_turn = await self._persist_turn(
            session_id=session_id,
            user_idx=user_idx,
            user_turn_id=user_turn_id,
            source=source,
            assistant_text=assistant_text if (reply_error is None or reply_parts) else None,
            interrupted=reply_error is not None,
            snapshot=snapshot,
            metrics=metrics,
        )

        # 5. remaining events
        if reply_error is not None:
            yield TurnEvent("error", {"message": "The counselor couldn't reply. Please retry."})
            return
        yield TurnEvent("profile", {"profile": profile.model_dump(mode="json")})
        yield TurnEvent(
            "ready", {"ready": profile.is_ready(), "missing": profile.missing_for_recommendation()}
        )
        assert assistant_turn is not None
        yield TurnEvent(
            "done", {"turn_id": str(assistant_turn.id), "assistant_text": assistant_text}
        )

    # ---------------------------------------------------------- recommendations

    async def recommend(
        self,
        session_id: uuid.UUID,
        retriever: RetrieverProtocol,
        *,
        mode: RetrievalMode = "hybrid_rerank",
        k: int = 10,
    ) -> tuple[RecommendationSet, GroundednessReport]:
        """Retrieve -> Opus -> groundedness -> persist, at most once per identical request.

        Idempotency (one Opus call per session x profile x mode x k): a concurrent
        duplicate (e.g. React StrictMode firing twice) awaits the request already in
        flight, and a set persisted in the last ``RECENT_SET_WINDOW_S`` seconds for the
        same profile snapshot is returned as-is.
        """
        assert self.recommender is not None
        async with self.sessionmaker() as db:
            await get_chat_session(db, session_id)
            profile = await latest_profile(db, session_id)
            missing = profile.missing_for_recommendation()
            if missing:
                raise NotReady(missing)
            recent = await recent_recommendation_set(db, session_id, profile, mode, k)
        if recent is not None:
            log.info("recommend_reused", session_id=str(session_id), set_id=str(recent[0].id))
            return recent

        key = (session_id, _profile_key(profile), mode, k)
        task = _INFLIGHT.get(key)
        if task is None:
            task = asyncio.ensure_future(
                self._recommend_fresh(session_id, profile, retriever, mode, k)
            )
            _INFLIGHT[key] = task
            task.add_done_callback(lambda _t: _INFLIGHT.pop(key, None))
        else:
            log.info("recommend_coalesced", session_id=str(session_id))
        # shield: a disconnecting caller must not cancel the work another caller awaits
        return await asyncio.shield(task)

    async def _recommend_fresh(
        self,
        session_id: uuid.UUID,
        profile: StudentProfile,
        retriever: RetrieverProtocol,
        mode: RetrievalMode,
        k: int,
    ) -> tuple[RecommendationSet, GroundednessReport]:
        assert self.recommender is not None
        tl = TurnLogger(session_id=str(session_id), stage_group="recommend")

        # A: retrieval (short-lived session)
        async with self.sessionmaker() as db:
            t0 = time.perf_counter()
            with tl.stage("retrieve") as st:
                candidates = await retriever.retrieve(
                    db, profile, max(RETRIEVE_K, k), mode, logger=tl
                )
                st.set(n_candidates=len(candidates), mode=mode)
            retrieve_ms = round((time.perf_counter() - t0) * 1000, 2)

        # B: Opus synthesis — no DB connection held
        with tl.stage("recommend") as st:
            try:
                recs = await self.recommender.synthesize(profile, candidates, k, stage=st)
            except LLMRefusalError as exc:
                st.set(refusals=1, refusal=exc.category)
                raise

        # C: groundedness against Postgres + persist
        async with self.sessionmaker() as db:
            with tl.stage("groundedness") as st:
                facts = FactIndex.from_candidates(candidates)
                claim_keys = {(c.unitid, c.cip4) for r in recs for c in r.claims}
                rec_keys = {(r.unitid, r.cip4) for r in recs}
                db_facts = await load_db_facts(
                    db,
                    claim_keys | rec_keys,
                    profile.income_bracket.value,
                    profile.home_state.value,
                )
                for (unitid, cip4), row in db_facts.items():
                    facts.add(unitid, cip4, row)  # Postgres values override candidate copies
                report = check(recs, facts)
                st.set(
                    n_claims=report.n_claims,
                    n_verified=report.n_verified,
                    groundedness=round(report.groundedness, 4),
                    reason_digit_violations=report.reason_digit_violations,
                )

            by_pair = {(c.unitid, c.cip4): c for c in candidates}
            set_row = RecommendationSetRow(
                session_id=session_id,
                retrieval_mode=mode,
                profile_used=profile.model_dump(mode="json"),
                retrieval_trace={
                    "k": k,
                    "retrieve_ms": retrieve_ms,
                    "candidates": [c.model_dump(mode="json") for c in candidates],
                    "reason_digit_violations": report.reason_digit_violations,
                },
                groundedness=report.groundedness,
            )
            db.add(set_row)
            await db.flush()
            outs: list[RecommendationOut] = []
            for checked in report.recommendations:
                rec = checked.recommendation
                cand = by_pair[(rec.unitid, rec.cip4)]
                reasons = [r for r in rec.reasons if not has_digit(r)]  # never display digits
                rec_row = RecommendationRow(
                    set_id=set_row.id,
                    unitid=rec.unitid,
                    cip4=rec.cip4,
                    rank=rec.rank,
                    admission_band=rec.admission_band,
                    band_confidence=cand.band_confidence,
                    score_breakdown=cand.scores.model_dump(),
                    reasons=reasons,
                )
                db.add(rec_row)
                await db.flush()
                db.add_all(
                    ClaimRow(
                        recommendation_id=rec_row.id,
                        field=c.field,
                        cip4=c.cip4,
                        stated_value=c.value,
                        db_value=c.db_value,
                        verified=c.verified,
                    )
                    for c in checked.claims
                )
                outs.append(
                    RecommendationOut(
                        unitid=rec.unitid,
                        name=cand.name,
                        city=cand.city,
                        state=cand.state,
                        cip4=rec.cip4,
                        cip_title=cand.cip_title,
                        rank=rec.rank,
                        admission_band=rec.admission_band,
                        band_confidence=cand.band_confidence,
                        scores=cand.scores,
                        reasons=reasons,
                        claims=checked.claims,
                        net_price_basis=_basis(db_facts.get((rec.unitid, rec.cip4), cand.facts)),
                    )
                )
            # the exact response, so a duplicate request can be answered without Opus
            set_row.retrieval_trace = {
                **set_row.retrieval_trace,
                "response": [o.model_dump(mode="json") for o in outs],
            }
            db.add_all(_metric_row(session_id, None, m) for m in tl.stages)
            await db.commit()
            await db.refresh(set_row)

        result = RecommendationSet(
            id=set_row.id,
            session_id=session_id,
            retrieval_mode=mode,
            recommendations=outs,
            groundedness=report.groundedness,
            created_at=set_row.created_at,
        )
        return result, report
