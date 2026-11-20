"""Time-to-first-audio accounting (SPEC §11, §12).

Timestamps (seconds on the server's ``perf_counter`` clock unless noted):

* ``t0`` — student stopped speaking (client VAD; client clock, mapped to server clock)
* ``t1`` — STT final transcript received by the gateway
* ``t2`` — first LLM token received from the orchestrator
* ``t3`` — first TTS request issued (first sentence chunk ready)
* ``t4`` — first audio chunk sent to the client
* ``t5`` — first audio actually played (client clock, mapped to server clock)

Client timestamps arrive as ``{t_ms, sent_ms}`` on the client's ``performance.now()``
clock. They are mapped onto the server clock as ``recv - (sent_ms - t_ms)``, i.e. the
one-way network delay of the report itself is ignored (a small, conservative bias that
shifts time out of ``stt_final`` into ``playback``). ``ttfa_total`` uses the two client
timestamps directly (same clock, exact) when both exist.

Stage deltas (ms): ``stt_final = t1-t0``, ``llm_ttft = t2-t1``, ``first_sentence = t3-t2``
(chunker wait), ``tts_first_chunk = t4-t3``, ``playback = t5-t4``. With both client
marks present they sum to ``ttfa_total`` up to that mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A client end-of-speech mark is only trusted this long before the STT final; older
# marks (a cough with no transcript, a report that missed its turn) are discarded.
MAX_T0_AGE_S = 3.0

# Stage names persisted to ``turn_metric`` (the full breakdown goes to the log record).
PERSISTED_STAGES = ("stt_final", "llm_ttft", "tts_first_chunk", "ttfa_total")


def map_client_time(recv_s: float, t_ms: float, sent_ms: float) -> float:
    """Client event time -> server clock (seconds)."""
    return recv_s - max(0.0, sent_ms - t_ms) / 1000.0


def accept_t0(t0: float, t1: float, max_age_s: float = MAX_T0_AGE_S) -> bool:
    """Is the end-of-speech mark ``t0`` plausibly the end of the utterance finalized at ``t1``?"""
    return t0 <= t1 and t1 - t0 <= max_age_s


@dataclass
class TurnTiming:
    turn: int
    t0: float | None = None
    t0_client_ms: float | None = None
    t1: float | None = None
    t2: float | None = None
    t3: float | None = None
    t4: float | None = None
    t5: float | None = None
    t5_client_ms: float | None = None
    turn_id: str | None = None
    interrupted: bool = False
    audio: bool = True
    finalized: bool = False


def _ms(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a) * 1000.0, 1)


def ttfa_breakdown(t: TurnTiming) -> dict[str, float | None]:
    if t.t0_client_ms is not None and t.t5_client_ms is not None:
        total: float | None = round(t.t5_client_ms - t.t0_client_ms, 1)
    else:
        total = _ms(t.t0, t.t5)
    return {
        "stt_final": _ms(t.t0, t.t1),
        "llm_ttft": _ms(t.t1, t.t2),
        "first_sentence": _ms(t.t2, t.t3),
        "tts_first_chunk": _ms(t.t3, t.t4),
        "playback": _ms(t.t4, t.t5),
        "ttfa_total": total,
    }


def voice_turn_record(t: TurnTiming) -> dict[str, Any]:
    """The single ``voice_turn`` log record for one turn."""
    stages = ttfa_breakdown(t)
    return {
        "turn": t.turn,
        "turn_id": t.turn_id,
        **{f"{k}_ms": v for k, v in stages.items()},
        "t0_source": "client" if t.t0 is not None else "missing",
        "t5_source": "client" if t.t5 is not None else "missing",
        "interrupted": t.interrupted,
        "audio": t.audio,
    }


def persisted_rows(t: TurnTiming) -> list[dict[str, Any]]:
    """``turn_metric`` rows for the stages that could be measured."""
    stages = ttfa_breakdown(t)
    return [
        {"stage": name, "ms": stages[name]}
        for name in PERSISTED_STAGES
        if stages.get(name) is not None
    ]
