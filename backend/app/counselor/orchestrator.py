"""Counselor orchestrator (SPEC §7 ``CounselorOrchestrator``, §8 both pipelines).

``handle_turn`` — one student message:

1. persist the user turn;
2. run the reply stream (Sonnet) and the extraction (Sonnet, structured) **concurrently**;
   the reply prompt sees the profile as of the previous turn + missing fields + a
   next-topic hint (it is one turn behind by design);
3. merge the extraction delta with ``schemas.apply_delta``;
4. persist profile snapshot, assistant turn and ``turn_metric`` rows
   (``extract``, ``reply_ttft``, ``reply_total``);
5. yield SSE events: ``token``* -> ``profile`` -> ``ready`` -> ``done`` (or ``error``).

``recommend`` — retrieve -> synthesize (Opus) -> groundedness check -> persist.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.llm import Effort, LLMClient, LLMError, LLMRefusalError
from app.core.logging import TurnLogger, get_logger
from app.counselor.context import HistoryTurn, plan_next_topic, profile_json
from app.counselor.extractor import Extractor
from app.counselor.facts import load_db_facts
from app.counselor.groundedness import FactIndex, GroundednessReport, check
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
    EvidenceSource,
    ExtractionResult,
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
        self, session: AsyncSession, profile: StudentProfile, k: int, mode: RetrievalMode
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


async def latest_profile(db: AsyncSession, session_id: uuid.UUID) -> StudentProfile:
    snap = (
        await db.execute(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.session_id == session_id)
            .order_by(ProfileSnapshot.after_turn.desc(), ProfileSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return StudentProfile.model_validate(snap.profile) if snap else StudentProfile()


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
        cost_usd=float(rec.get("cost_usd") or 0.0),
    )


def build_reply_messages(
    history: list[HistoryTurn], text: str, profile: StudentProfile
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
        f"Suggested next topic: {plan_next_topic(profile)}\n"
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

    async def handle_turn(
        self, session_id: uuid.UUID, text: str, source: EvidenceSource = "chat"
    ) -> AsyncIterator[TurnEvent]:
        assert self.extractor is not None
        # 1. persist the user turn; load previous profile + history
        async with self.sessionmaker() as db:
            await get_chat_session(db, session_id)
            history = await recent_turns(db, session_id, self.history_window)
            prev_profile = await latest_profile(db, session_id)
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

        async def run_extraction() -> ExtractionResult:
            with tl.stage("extract") as st:
                return await extractor.extract(history, text, prev_profile, stage=st)

        # 2. extraction and reply run concurrently
        extract_task = asyncio.create_task(run_extraction())
        reply_parts: list[str] = []
        ttft_ms: float | None = None
        reply_error: str | None = None
        try:
            with tl.stage("reply_total") as st:
                stream = self.llm.stream_text(
                    self.reply_model,
                    load_prompt("counselor_reply").text,
                    build_reply_messages(history, text, prev_profile),
                    effort=self.reply_effort,
                    max_tokens=self.reply_max_tokens,
                    stage=st,
                )
                try:
                    async for chunk in stream:
                        reply_parts.append(chunk)
                        yield TurnEvent("token", {"text": chunk})
                except LLMRefusalError as exc:
                    st.set(refusal=exc.category)
                    if not reply_parts:
                        reply_parts.append(REFUSAL_FALLBACK)
                        yield TurnEvent("token", {"text": REFUSAL_FALLBACK})
                ttft_ms = stream.ttft_ms
                st.set(prompt=load_prompt("counselor_reply").id, ttft_ms=ttft_ms)
        except LLMError as exc:
            reply_error = str(exc)
            log.error("reply_failed", error=type(exc).__name__)
        except BaseException:
            extract_task.cancel()
            raise

        # 3. merge extraction
        profile = prev_profile
        extraction_ok = True
        try:
            result = await extract_task
            profile = apply_delta(prev_profile, result.delta, user_idx, source)
        except LLMError as exc:
            extraction_ok = False
            log.error("extract_failed", error=type(exc).__name__)

        # 4. persist
        assistant_text = "".join(reply_parts)
        metrics = list(tl.stages)
        if ttft_ms is not None:
            metrics.append({"stage": "reply_ttft", "ms": ttft_ms, "model": self.reply_model})
        async with self.sessionmaker() as db:
            if extraction_ok:
                db.add(
                    ProfileSnapshot(
                        session_id=session_id,
                        after_turn=user_idx,
                        profile=profile.model_dump(mode="json"),
                    )
                )
            assistant_turn: Turn | None = None
            if reply_error is None:
                assistant_turn = Turn(
                    session_id=session_id, idx=user_idx + 1, role="assistant",
                    text=assistant_text, source=source,
                )  # fmt: skip
                db.add(assistant_turn)
            db.add_all(_metric_row(session_id, user_turn_id, m) for m in metrics)
            await db.commit()

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
        assert self.recommender is not None
        tl = TurnLogger(session_id=str(session_id), stage_group="recommend")
        async with self.sessionmaker() as db:
            await get_chat_session(db, session_id)
            profile = await latest_profile(db, session_id)
            missing = profile.missing_for_recommendation()
            if missing:
                raise NotReady(missing)

            t0 = time.perf_counter()
            with tl.stage("retrieve") as st:
                candidates = await retriever.retrieve(db, profile, max(RETRIEVE_K, k), mode)
                st.set(n_candidates=len(candidates), mode=mode)
            retrieve_ms = round((time.perf_counter() - t0) * 1000, 2)

            with tl.stage("recommend") as st:
                recs = await self.recommender.synthesize(profile, candidates, k, stage=st)

            with tl.stage("groundedness") as st:
                facts = FactIndex.from_candidates(candidates)
                for (unitid, cip4), row in (
                    await load_db_facts(
                        db, {(r.unitid, r.cip4) for r in recs}, profile.income_bracket.value
                    )
                ).items():
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
                rec_row = RecommendationRow(
                    set_id=set_row.id,
                    unitid=rec.unitid,
                    cip4=rec.cip4,
                    rank=rec.rank,
                    admission_band=rec.admission_band,
                    band_confidence=cand.band_confidence,
                    score_breakdown=cand.scores.model_dump(),
                    reasons=rec.reasons,
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
                        reasons=rec.reasons,
                        claims=checked.claims,
                    )
                )
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
