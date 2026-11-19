"""Structured JSON logging (SPEC §12).

One record per stage per turn with: session_id, turn_id, stage, ms, model,
input_tokens, output_tokens, cache_read_tokens, cost_usd.

PII-safe by default: use `redact(text)` / `TurnLogger.text_field()` to log the
length of student text instead of the text itself unless LOG_PII=true.

Usage:
    configure_logging()
    tl = TurnLogger(session_id="s1", turn_id="t1")
    with tl.stage("extract") as st:
        resp = await client.messages.create(...)
        st.record_usage(model=..., input_tokens=..., output_tokens=..., cache_read_tokens=...)
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.config import get_settings
from app.core.cost import cost_usd

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Configure structlog to emit one JSON object per line on stdout. Idempotent."""
    global _configured
    if _configured:
        return
    lvl = getattr(logging, (level or get_settings().LOG_LEVEL).upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=lvl)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None, **initial: Any) -> Any:
    return structlog.get_logger(name, **initial)


def redact(text: str | None, *, log_pii: bool | None = None) -> str | dict[str, int]:
    """Return text unchanged if PII logging is on, else only its length."""
    if text is None:
        return {"len": 0}
    if log_pii is None:
        log_pii = get_settings().LOG_PII
    return text if log_pii else {"len": len(text)}


@dataclass
class Stage:
    """Mutable record for a single stage; filled in by the caller inside `with`."""

    name: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def record_usage(
        self,
        *,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cost: float | None = None,
    ) -> None:
        """Accumulate token usage (a stage may make several calls)."""
        self.model = model
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        if cost is None:
            try:
                cost = cost_usd(model, input_tokens, output_tokens, cache_read_tokens)
            except KeyError:
                cost = None
        if cost is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost

    def set(self, **kwargs: Any) -> None:
        """Attach extra non-PII fields (counts, ids, flags) to the stage record."""
        self.extra.update(kwargs)


class TurnLogger:
    """Per-turn logger binding session_id/turn_id; emits one record per stage."""

    def __init__(self, session_id: str | None = None, turn_id: str | None = None, **ctx: Any):
        self.session_id = session_id
        self.turn_id = turn_id
        self.log = get_logger("turn", session_id=session_id, turn_id=turn_id, **ctx)
        self.stages: list[dict[str, Any]] = []

    @contextmanager
    def stage(
        self,
        name: str,
        *,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cost_usd: float | None = None,
        **extra: Any,
    ) -> Iterator[Stage]:
        st = Stage(name=name, extra=dict(extra))
        if model is not None:
            st.record_usage(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cost=cost_usd,
            )
        t0 = time.perf_counter()
        error: str | None = None
        try:
            yield st
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            ms = round((time.perf_counter() - t0) * 1000, 2)
            record: dict[str, Any] = {
                "stage": st.name,
                "ms": ms,
                "model": st.model,
                "input_tokens": st.input_tokens,
                "output_tokens": st.output_tokens,
                "cache_read_tokens": st.cache_read_tokens,
                "cost_usd": round(st.cost_usd, 6) if st.cost_usd is not None else None,
                **st.extra,
            }
            if error:
                record["error"] = error
            self.stages.append(record)
            (self.log.error if error else self.log.info)("stage", **record)

    def text_field(self, text: str | None) -> str | dict[str, int]:
        return redact(text)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(s["cost_usd"] or 0.0 for s in self.stages), 6)

    @property
    def total_ms(self) -> float:
        return round(sum(s["ms"] for s in self.stages), 2)
