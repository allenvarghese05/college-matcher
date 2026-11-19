"""Per-connection voice gateway (SPEC §11): listening -> thinking -> speaking -> listening.

Wire protocol (one WebSocket per voice session, ``WS /api/sessions/{id}/voice``).

Client -> server
  binary                          PCM16 LE mono 16 kHz mic audio
  {"type":"speech_end", "t_ms", "sent_ms"}     client VAD: student stopped talking (t0)
  {"type":"playback_start", "turn", "t_ms", "sent_ms"}   first audio of a turn played (t5)
  {"type":"played", "turn", "sentence"}        a sentence finished playing (informational)
  {"type":"interrupt", "turn", "last_played"}  barge-in (only honoured with VOICE_BARGE_IN)
  {"type":"stop"}                              end the voice session

Server -> client (JSON text frames, all carry ``type``)
  hello {barge_in, input_sample_rate, output_sample_rate, provider}
  state {state: listening|thinking|speaking}
  transcript_interim {text}            transcript_final {text, turn}
  assistant_text {delta, turn}         profile {profile}      ready {ready, missing}
  audio_start {turn, sentence, text, sample_rate} -> binary PCM16 frames -> audio_end {...}
  done {turn, turn_id, assistant_text, audio}
  interrupted {turn, turn_id, played_through, assistant_text}
  metrics {turn, turn_id, stt_final_ms, llm_ttft_ms, first_sentence_ms,
           tts_first_chunk_ms, playback_ms, ttfa_total_ms, ...}
  error {code, message, fatal}

Audio frames always belong to the most recent ``audio_start``. A TTS failure is not
fatal: the rest of the turn is delivered as text only (``done.audio == false``).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.counselor.orchestrator import CounselorOrchestrator
from app.db.models import Turn, TurnMetricRow
from app.voice.chunker import SentenceChunker
from app.voice.metrics import (
    TurnTiming,
    map_client_time,
    persisted_rows,
    voice_turn_record,
)
from app.voice.stt import STTError, STTEvent, STTProvider, STTStream
from app.voice.tts import TTSError, TTSProvider

log = get_logger(__name__)

State = Literal["listening", "thinking", "speaking"]
NOTHING_PLAYED = "…"  # assistant text kept when barge-in cut the reply before any audio


class Transport(Protocol):
    async def send_json(self, data: dict[str, Any]) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def receive(self) -> bytes | dict[str, Any] | None:
        """Next client message: bytes (audio), dict (control) or ``None`` when closed."""
        ...


@dataclass
class _TurnRun:
    timing: TurnTiming
    baseline_idx: int = -1
    sentences: list[str] = field(default_factory=list)
    tts_failed: bool = False
    turn_id: str | None = None
    task: asyncio.Task[None] | None = None


@dataclass
class VoiceGateway:
    transport: Transport
    orch: CounselorOrchestrator
    session_id: uuid.UUID
    stt: STTProvider
    tts: TTSProvider
    barge_in: bool = False
    provider_name: str = "deepgram"
    input_sample_rate: int = 16000
    clock: Callable[[], float] = time.perf_counter

    state: State = "listening"
    _stt_stream: STTStream | None = None
    _turn_no: int = 0
    _run: _TurnRun | None = None
    _pending_t0: tuple[float, float] | None = None  # (server-mapped, client ms)
    _closed: bool = False
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ------------------------------------------------------------------ plumbing

    async def _send(self, data: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            async with self._send_lock:
                await self.transport.send_json(data)
        except Exception as exc:  # client went away
            log.info("voice_send_failed", error=type(exc).__name__)
            self._closed = True

    async def _send_audio(self, pcm: bytes) -> None:
        if self._closed:
            return
        try:
            async with self._send_lock:
                await self.transport.send_bytes(pcm)
        except Exception as exc:
            log.info("voice_send_failed", error=type(exc).__name__)
            self._closed = True

    async def _set_state(self, state: State) -> None:
        if state != self.state:
            self.state = state
            await self._send({"type": "state", "state": state})

    async def _error(self, code: str, message: str, *, fatal: bool = False) -> None:
        await self._send({"type": "error", "code": code, "message": message, "fatal": fatal})

    @property
    def _busy(self) -> bool:
        return self._run is not None and self._run.task is not None and not self._run.task.done()

    # ---------------------------------------------------------------- lifecycle

    async def run(self) -> None:
        await self._send(
            {
                "type": "hello",
                "barge_in": self.barge_in,
                "input_sample_rate": self.input_sample_rate,
                "output_sample_rate": self.tts.sample_rate,
                "provider": self.provider_name,
            }
        )
        try:
            self._stt_stream = await self.stt.connect()
        except STTError as exc:
            log.error("stt_connect_failed", error=str(exc))
            await self._error(
                "stt_unavailable", "Couldn't reach the speech service. Try again soon.", fatal=True
            )
            return
        await self._send({"type": "state", "state": self.state})
        recv_task = asyncio.create_task(self._recv_loop())
        stt_task = asyncio.create_task(self._stt_loop())
        try:
            await asyncio.wait({recv_task, stt_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (recv_task, stt_task):
                t.cancel()
            await asyncio.gather(recv_task, stt_task, return_exceptions=True)
            await self._shutdown()

    async def _shutdown(self) -> None:
        run = self._run
        if run is not None and run.task is not None and not run.task.done():
            run.task.cancel()  # orchestrator persists the partial reply as interrupted
            with contextlib.suppress(BaseException):
                await run.task
            run.timing.interrupted = True
        self._closed = True
        if run is not None:
            await self._finalize_metrics(run)
        if self._stt_stream is not None:
            with contextlib.suppress(Exception):
                await self._stt_stream.close()

    # -------------------------------------------------------------- client side

    def _forwarding_audio(self) -> bool:
        return self.state == "listening" or self.barge_in

    async def _recv_loop(self) -> None:
        while True:
            msg = await self.transport.receive()
            if msg is None:
                return
            if isinstance(msg, bytes):
                if self._forwarding_audio() and self._stt_stream is not None:
                    with contextlib.suppress(STTError):  # the STT loop reports failures
                        await self._stt_stream.send_audio(msg)
                continue
            kind = msg.get("type")
            if kind == "stop":
                return
            if kind == "speech_end":
                await self._on_speech_end(msg)
            elif kind == "playback_start":
                await self._on_playback_start(msg)
            elif kind == "interrupt":
                await self._on_interrupt(msg)
            # "played" marks are informational; the interrupt carries last_played

    def _client_time(self, msg: dict[str, Any]) -> tuple[float, float] | None:
        try:
            t_ms = float(msg["t_ms"])
            sent_ms = float(msg.get("sent_ms", t_ms))
        except (KeyError, TypeError, ValueError):
            return None
        return map_client_time(self.clock(), t_ms, sent_ms), t_ms

    async def _on_speech_end(self, msg: dict[str, Any]) -> None:
        mapped = self._client_time(msg)
        if mapped is None:
            return
        run = self._run
        # STT endpointing can beat the client report; attach it to the turn it ended.
        if (
            run is not None
            and run.timing.t0 is None
            and run.timing.t1 is not None
            and mapped[0] <= run.timing.t1
        ):
            run.timing.t0, run.timing.t0_client_ms = mapped
            return
        self._pending_t0 = mapped
        if self.state == "listening" and self._stt_stream is not None:
            await self._stt_stream.finalize()

    async def _on_playback_start(self, msg: dict[str, Any]) -> None:
        run = self._run
        mapped = self._client_time(msg)
        if run is None or mapped is None or msg.get("turn") != run.timing.turn:
            return
        if run.timing.t5 is None:
            run.timing.t5, run.timing.t5_client_ms = mapped
            await self._finalize_metrics(run)

    # ----------------------------------------------------------------- STT side

    async def _stt_loop(self) -> None:
        reconnected = False
        while True:
            assert self._stt_stream is not None
            try:
                async for ev in self._stt_stream.events():
                    await self._on_stt(ev)
                return
            except STTError as exc:
                log.warning("stt_stream_failed", error=str(exc), reconnected=reconnected)
                with contextlib.suppress(Exception):
                    await self._stt_stream.close()
                if not reconnected:
                    reconnected = True
                    try:
                        self._stt_stream = await self.stt.connect()
                        continue
                    except STTError as exc2:
                        log.error("stt_reconnect_failed", error=str(exc2))
                await self._error(
                    "stt_disconnected",
                    "Lost the connection to the speech service. Tap the orb to try again.",
                    fatal=True,
                )
                return

    async def _on_stt(self, ev: STTEvent) -> None:
        if ev.kind == "interim":
            if not self._busy:
                await self._send({"type": "transcript_interim", "text": ev.text})
        elif ev.kind == "final":
            if self._busy:
                log.info("stt_final_dropped", state=self.state)
                return
            await self._start_turn(ev.text)

    # ---------------------------------------------------------------- the turn

    async def _start_turn(self, text: str) -> None:
        t1 = self.clock()
        if self._run is not None:
            await self._finalize_metrics(self._run)  # previous turn never reported t5
        self._turn_no += 1
        timing = TurnTiming(turn=self._turn_no, t1=t1)
        if self._pending_t0 is not None and self._pending_t0[0] <= t1:
            timing.t0, timing.t0_client_ms = self._pending_t0
        self._pending_t0 = None
        run = _TurnRun(timing=timing)
        self._run = run
        await self._send({"type": "transcript_final", "text": text, "turn": timing.turn})
        await self._set_state("thinking")
        run.task = asyncio.create_task(self._run_turn(run, text))

    async def _max_idx(self) -> int:
        async with self.orch.sessionmaker() as db:
            v = (
                await db.execute(
                    select(func.max(Turn.idx)).where(Turn.session_id == self.session_id)
                )
            ).scalar_one_or_none()
        return -1 if v is None else int(v)

    async def _run_turn(self, run: _TurnRun, text: str) -> None:
        timing = run.timing
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        tts_task = asyncio.create_task(self._tts_worker(run, queue))
        chunker = SentenceChunker()
        failed = False
        assistant_text = ""
        try:
            run.baseline_idx = await self._max_idx()
            agen = self.orch.handle_turn(self.session_id, text, "voice")
            try:
                async for ev in agen:
                    if ev.event == "token":
                        delta = str(ev.data.get("text", ""))
                        if timing.t2 is None:
                            timing.t2 = self.clock()
                        await self._send(
                            {"type": "assistant_text", "delta": delta, "turn": timing.turn}
                        )
                        for sentence in chunker.push(delta):
                            queue.put_nowait(sentence)
                    elif ev.event in ("profile", "ready"):
                        await self._send({"type": ev.event, **ev.data})
                    elif ev.event == "done":
                        run.turn_id = timing.turn_id = str(ev.data.get("turn_id"))
                        assistant_text = str(ev.data.get("assistant_text", ""))
                    elif ev.event == "error":
                        failed = True
                        await self._error(
                            "llm_failed",
                            str(ev.data.get("message") or "The counselor couldn't reply."),
                        )
            finally:
                await agen.aclose()
            rest = chunker.flush()
            if rest:
                queue.put_nowait(rest)
            queue.put_nowait(None)
            await tts_task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failed = True
            log.error("voice_turn_failed", error=type(exc).__name__)
            await self._error("turn_failed", "Something went wrong. Please try again.")
        finally:
            if not tts_task.done():
                tts_task.cancel()
                with contextlib.suppress(BaseException):
                    await tts_task
        timing.audio = not run.tts_failed and timing.t4 is not None
        if not failed:
            await self._send(
                {
                    "type": "done",
                    "turn": timing.turn,
                    "turn_id": run.turn_id,
                    "assistant_text": assistant_text,
                    "audio": timing.audio,
                }
            )
        await self._set_state("listening")
        if not timing.audio:
            await self._finalize_metrics(run)  # no playback mark will come

    async def _tts_worker(self, run: _TurnRun, queue: asyncio.Queue[str | None]) -> None:
        timing = run.timing
        while (sentence := await queue.get()) is not None:
            idx = len(run.sentences)
            run.sentences.append(sentence)
            if run.tts_failed:
                continue
            if timing.t3 is None:
                timing.t3 = self.clock()
            started = False
            try:
                async for pcm in self.tts.synthesize(sentence):
                    if not started:
                        started = True
                        await self._send(
                            {
                                "type": "audio_start",
                                "turn": timing.turn,
                                "sentence": idx,
                                "text": sentence,
                                "sample_rate": self.tts.sample_rate,
                            }
                        )
                        await self._set_state("speaking")
                    if timing.t4 is None:
                        timing.t4 = self.clock()
                    await self._send_audio(pcm)
            except TTSError as exc:
                log.error("tts_failed", error=str(exc), sentence=idx)
                run.tts_failed = True
                await self._error(
                    "tts_failed", "Voice playback hit a snag, so the reply is shown as text."
                )
            if started:
                await self._send({"type": "audio_end", "turn": timing.turn, "sentence": idx})

    # ----------------------------------------------------------------- barge-in

    async def _on_interrupt(self, msg: dict[str, Any]) -> None:
        run = self._run
        if not self.barge_in:
            log.info("interrupt_ignored", reason="barge_in_disabled")
            return
        if run is None or run.task is None or msg.get("turn") != run.timing.turn:
            return
        try:
            last_played = int(msg.get("last_played", -1))
        except (TypeError, ValueError):
            last_played = -1
        if not run.task.done():
            run.task.cancel()
            with contextlib.suppress(BaseException):
                await run.task
        played = run.sentences[: max(0, last_played + 1)]
        text = " ".join(played) or NOTHING_PLAYED
        turn_id = await self._truncate_assistant_turn(run, text)
        run.turn_id = run.timing.turn_id = turn_id or run.turn_id
        run.timing.interrupted = True
        await self._send(
            {
                "type": "interrupted",
                "turn": run.timing.turn,
                "turn_id": run.turn_id,
                "played_through": last_played,
                "assistant_text": text,
            }
        )
        self.state = "speaking"  # force a state frame
        await self._set_state("listening")
        await self._finalize_metrics(run)

    async def _truncate_assistant_turn(self, run: _TurnRun, text: str) -> str | None:
        """History must reflect what the student actually heard (SPEC §11)."""
        async with self.orch.sessionmaker() as db:
            row = (
                await db.execute(
                    select(Turn)
                    .where(Turn.session_id == self.session_id, Turn.idx > run.baseline_idx)
                    .order_by(Turn.idx.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None or row.role != "assistant":
                return None  # no reply text was persisted yet
            row.text = text
            row.interrupted = True
            await db.commit()
            return str(row.id)

    # ------------------------------------------------------------------ metrics

    async def _finalize_metrics(self, run: _TurnRun) -> None:
        timing = run.timing
        if timing.finalized:
            return
        timing.finalized = True
        record = voice_turn_record(timing)
        log.info("voice_turn", session_id=str(self.session_id), **record)
        await self._persist_metrics(timing)
        await self._send({"type": "metrics", **record})

    async def _persist_metrics(self, timing: TurnTiming) -> None:
        rows = persisted_rows(timing)
        if not rows:
            return
        turn_id = uuid.UUID(timing.turn_id) if timing.turn_id else None
        try:
            async with self.orch.sessionmaker() as db:
                db.add_all(
                    TurnMetricRow(
                        session_id=self.session_id,
                        turn_id=turn_id,
                        stage=r["stage"],
                        ms=float(r["ms"]),
                        input_tokens=0,
                        output_tokens=0,
                        cache_read_tokens=0,
                        cache_creation_tokens=0,
                        cost_usd=0.0,
                    )
                    for r in rows
                )
                await db.commit()
        except Exception as exc:
            log.error("voice_metrics_persist_failed", error=type(exc).__name__)
