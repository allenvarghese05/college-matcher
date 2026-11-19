"""SQLAlchemy 2 models (docs/SPEC.md §5 ER diagram). Owned by the orchestrator.

Embedding dimension is 384 (BAAI/bge-small-en-v1.5 via fastembed, SPEC P3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBED_DIM = 384


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ------------------------------------------------------------------ reference data


class Institution(Base):
    __tablename__ = "institution"

    unitid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(2), index=True)
    zip: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    control: Mapped[int] = mapped_column(
        SmallInteger
    )  # 1 public, 2 private nonprofit, 3 for-profit
    locale: Mapped[int | None] = mapped_column(SmallInteger)
    undergrad_size: Mapped[int | None] = mapped_column(Integer)
    admission_rate: Mapped[float | None] = mapped_column(Float)
    open_admission: Mapped[bool | None] = mapped_column(Boolean)
    sat_25: Mapped[int | None] = mapped_column(Integer)
    sat_75: Mapped[int | None] = mapped_column(Integer)
    act_25: Mapped[int | None] = mapped_column(Integer)
    act_75: Mapped[int | None] = mapped_column(Integer)
    net_price_0_30k: Mapped[int | None] = mapped_column(Integer)
    net_price_30_48k: Mapped[int | None] = mapped_column(Integer)
    net_price_48_75k: Mapped[int | None] = mapped_column(Integer)
    net_price_75_110k: Mapped[int | None] = mapped_column(Integer)
    net_price_110k_plus: Mapped[int | None] = mapped_column(Integer)
    avg_net_price: Mapped[int | None] = mapped_column(Integer)
    completion_rate: Mapped[float | None] = mapped_column(Float)
    median_earnings_10yr: Mapped[int | None] = mapped_column(Integer)
    median_debt: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(Text)

    programs: Mapped[list[Program]] = relationship(back_populates="institution")


class CipCode(Base):
    __tablename__ = "cip_code"

    cip4: Mapped[str] = mapped_column(String(4), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    definition: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class Program(Base):
    __tablename__ = "program"
    __table_args__ = (
        UniqueConstraint("unitid", "cip4", "credential_level", name="uq_program"),
        Index("ix_program_cip_level", "cip4", "credential_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unitid: Mapped[int] = mapped_column(ForeignKey("institution.unitid"), index=True)
    cip4: Mapped[str] = mapped_column(ForeignKey("cip_code.cip4"))
    credential_level: Mapped[int] = mapped_column(SmallInteger)
    median_earnings: Mapped[int | None] = mapped_column(Integer)  # EARN_MDN_4YR
    earnings_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    median_debt: Mapped[int | None] = mapped_column(Integer)  # DEBT_ALL_STGP_EVAL_MDN
    debt_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    graduates: Mapped[int | None] = mapped_column(Integer)

    institution: Mapped[Institution] = relationship(back_populates="programs")


# ---------------------------------------------------------------- conversation


class ChatSession(Base):
    __tablename__ = "session"

    id: Mapped[uuid.UUID] = _uuid_pk()
    mode: Mapped[str] = mapped_column(String(8), default="text")
    created_at: Mapped[datetime] = _now()

    turns: Mapped[list[Turn]] = relationship(back_populates="session", order_by="Turn.idx")


class Turn(Base):
    __tablename__ = "turn"
    __table_args__ = (UniqueConstraint("session_id", "idx", name="uq_turn_idx"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("session.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(8), default="chat")  # chat | voice | resume | quiz
    audio_ref: Mapped[str | None] = mapped_column(Text)
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = _now()

    session: Mapped[ChatSession] = relationship(back_populates="turns")


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshot"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session.id", ondelete="CASCADE"), index=True
    )
    after_turn: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict] = mapped_column(JSONB)  # StudentProfile.model_dump()
    next_topic: Mapped[str | None] = mapped_column(String(32))  # extractor's NextTopic
    created_at: Mapped[datetime] = _now()


class RecommendationSetRow(Base):
    __tablename__ = "recommendation_set"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session.id", ondelete="CASCADE"), index=True
    )
    retrieval_mode: Mapped[str] = mapped_column(String(32))
    profile_used: Mapped[dict] = mapped_column(JSONB)
    retrieval_trace: Mapped[dict] = mapped_column(JSONB)  # candidates, scores, timings
    groundedness: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = _now()

    recommendations: Mapped[list[RecommendationRow]] = relationship(
        back_populates="set", order_by="RecommendationRow.rank"
    )


class RecommendationRow(Base):
    __tablename__ = "recommendation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_set.id", ondelete="CASCADE"), index=True
    )
    unitid: Mapped[int] = mapped_column(ForeignKey("institution.unitid"))
    cip4: Mapped[str | None] = mapped_column(String(4))
    rank: Mapped[int] = mapped_column(Integer)
    admission_band: Mapped[str] = mapped_column(String(8))
    band_confidence: Mapped[str] = mapped_column(String(8))
    score_breakdown: Mapped[dict] = mapped_column(JSONB)
    reasons: Mapped[list] = mapped_column(JSONB)

    set: Mapped[RecommendationSetRow] = relationship(back_populates="recommendations")
    claims: Mapped[list[ClaimRow]] = relationship(back_populates="recommendation")


class ClaimRow(Base):
    __tablename__ = "claim"

    id: Mapped[uuid.UUID] = _uuid_pk()
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(32))
    cip4: Mapped[str | None] = mapped_column(String(4))
    stated_value: Mapped[str] = mapped_column(Text)
    db_value: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean)

    recommendation: Mapped[RecommendationRow] = relationship(back_populates="claims")


class TurnMetricRow(Base):
    __tablename__ = "turn_metric"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("session.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turn.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))
    ms: Mapped[float] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    at: Mapped[datetime] = _now()
