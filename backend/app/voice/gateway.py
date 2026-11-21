"""Per-connection voice gateway (SPEC §11): listening -> thinking -> speaking -> listening.

Wire protocol (one WebSocket per voice session, ``WS /api/sessions/{id}/voice``).

Client -> server
  binary                          PCM16 LE mono 16 kHz mic audio (<= 64 KB per frame)
  {"type":"speech_end", "t_ms", "sent_ms"}     client VAD: student stopped talking (t0)
  {"type":"playback_start", "turn", "t_ms", "sent_ms"}   first audio of a turn played (t5)
  {"type":"played", "turn", "sentence"}        a sentence finished playing (informational)
  {"type":"interrupt", "turn", "last_played"}  barge-in (only honoured with VOICE_BARGE_IN)
  {"type":"backchannel", "text"}                the client just played a "mhm" clip: a final
                                                that is only its echo is dropped
  {"type":"stop"}                              end the voice session

Server -> client (JSON text frames, all carry ``type``)
  hello {barge_in, backchannel, input_sample_rate, output_sample_rate, provider}
  state {state: listening|thinking|speaking}
  transcript_interim {text, during_reply}   transcript_final {text, turn}
      (``during_reply``: the counselor is thinking or speaking; with barge-in the client
      uses these words to confirm the student is really talking over it, not echo)
  assistant_text {delta, turn}         profile {profile}      ready {ready, missing}
  audio_start {turn, sentence, text, sample_rate} -> binary PCM16 frames -> audio_end {...}
  done {turn, turn_id, assistant_text, audio}
  interrupted {turn, turn_id, played_through, assistant_text}
  metrics {turn, turn_id, stt_final_ms, llm_ttft_ms, first_sentence_ms,
           tts_first_chunk_ms, playback_ms, ttfa_total_ms, ...}
  error {code, message, fatal}

Audio frames always belong to the most recent ``audio_start``. A TTS failure is not
fatal: the rest of the turn is delivered as text only (``done.audio == false``).

Stopping a reply (barge-in, ``stop``, disconnect) never cancels the orchestrator task
outright: cancellation landing while ``handle_turn`` awaits the extraction would skip
its persistence entirely. Instead TTS is cancelled at once and the turn loop stops
consuming at the next ``token`` (closing the generator, so the orchestrator saves the
partial reply as interrupted); if the reply has already finished streaming, the turn
runs on to ``done`` (profile delta saved) and is then truncated. A hard cancel is only
the last resort after ``FINISH_TIMEOUT_S``.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.counselor.orchestrator import CounselorOrchestrator, TurnEvent
from app.db.models import Turn, TurnMetricRow
from app.voice.chunker import SentenceChunker
from app.voice.metrics import (
    TurnTiming,
    accept_t0,
    map_client_time,
    persisted_rows,
    voice_turn_record,
)
from app.voice.stt import STTError, STTEvent, STTProvider, STTStream
from app.voice.tts import TTSError, TTSProvider

log = get_logger(__name__)

State = Literal["listening", "thinking", "speaking"]
NOTHING_PLAYED = "…"  # assistant text kept when barge-in cut the reply before any audio
FINISH_TIMEOUT_S = 10.0  # wait for a stopped turn to persist before hard-cancelling it
# A final transcript that trails off ("...and", "um") is held this long for more speech
# before the turn starts, so a mid-thought pause doesn't hand the floor to the counselor.
TRAILING_HOLD_S = 1.6
TRAILING_HOLD_MAX_S = 3.0  # total cap, however much noise/speech keeps extending it
# With barge-in, a final of at least this many words while the counselor is still
# thinking (no audio sent yet) means the student wasn't done: restart the turn.
CONTINUE_MIN_WORDS = 2
# After terminal punctuation only true connectives/fillers count ("I think so." is done).
_TRAILING_STRONG = frozenset("and but or because cause um uh umm uhh er hmm".split())
_TRAILING_WORDS = _TRAILING_STRONG | frozenset(
    "so like the a an to of with if that then my i i'm it's which when where who also plus".split()
)


def trails_off(text: str) -> bool:
    """The utterance sounds unfinished: ends on a comma/ellipsis or a connective/filler."""
    t = text.strip()
    if not t:
        return False
    if t.endswith((",", "...", "…", "-", "—")):
        return True
    body = t.rstrip(".!?")
    if not body.split():
        return False
    last = body.split()[-1].lower().strip(",.'\"")
    return last in (_TRAILING_STRONG if body != t else _TRAILING_WORDS)


# A final heard this soon after a backchannel clip that is just that clip is its echo.
BACKCHANNEL_ECHO_S = 2.5


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def strip_echo(text: str, clips: list[str]) -> str:
    """Remove a just-played backchannel clip heard back through the mic: the whole final,
    or the clip's words at its very start or end ("Mhm. And I like robots")."""
    words = text.split()
    for clip in clips:
        c = _norm(clip)
        if not c:
            continue
        n = len(c.split())
        if _norm(text) == c:
            return ""
        if len(words) > n and _norm(" ".join(words[:n])) == c:
            words = words[n:]
        elif len(words) > n and _norm(" ".join(words[-n:])) == c:
            words = words[:-n]
    return " ".join(words)


def word_count(text: str) -> int:
    return len(text.split())


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
    tts_task: asyncio.Task[None] | None = None
    # stop requested: "interrupt" (truncate to last_played) or "shutdown" (keep as is)
    cancel: Literal["interrupt", "shutdown"] | None = None
    last_played: int = -1
    done: bool = False  # task finished, including truncation / done frame

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()


@dataclass
class VoiceGateway:
    transport: Transport
    orch: CounselorOrchestrator
    session_id: uuid.UUID
    stt: STTProvider
    tts: TTSProvider
    barge_in: bool = False
    backchannel: bool = False
    provider_name: str = "deepgram"
    input_sample_rate: int = 16000
    idle_timeout_s: float = 90.0
    clock: Callable[[], float] = time.perf_counter

    state: State = "listening"
    _stt_stream: STTStream | None = None
    _turn_no: int = 0
    _run: _TurnRun | None = None
    _pending_t0: tuple[float, float] | None = None  # (server-mapped, client ms)
    _buffered_finals: list[str] = field(default_factory=list)
    _held: list[str] = field(default_factory=list)  # trailing-off finals awaiting more
    _hold_task: asyncio.Task[None] | None = None
    _hold_started: float = 0.0
    _bg_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    _start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _stopping: bool = False  # shutting down: no new turns
    _backchannels: list[tuple[float, str]] = field(default_factory=list)  # (played at, text)
    _last_activity: float = 0.0
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

    async def _set_state(self, state: State, *, force: bool = False) -> None:
        if state == "listening":
            self._last_activity = self.clock()
        if force or state != self.state:
            self.state = state
            await self._send({"type": "state", "state": state})

    async def _error(self, code: str, message: str, *, fatal: bool = False) -> None:
        await self._send({"type": "error", "code": code, "message": message, "fatal": fatal})

    # ---------------------------------------------------------------- lifecycle

    async def run(self) -> None:
        await self._send(
            {
                "type": "hello",
                "barge_in": self.barge_in,
                "backchannel": self.backchannel,
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
            await self._close_providers()
            return
        await self._set_state("listening", force=True)
        tasks = {
            asyncio.create_task(self._recv_loop()),
            asyncio.create_task(self._stt_loop()),
            asyncio.create_task(self._idle_loop()),
        }
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._shutdown()

    async def _shutdown(self) -> None:
        # A held (trailing-off) utterance is dropped at shutdown; a release already
        # starting a turn is cancelled before the turn exists.
        self._stopping = True
        for task in list(self._bg_tasks):
            task.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        run = self._run
        if run is not None and run.running:
            self._request_stop(run, "shutdown")
            await self._await_run(run)
            run.timing.interrupted = True
        self._closed = True
        if run is not None:
            await self._finalize_metrics(run)
        if self._stt_stream is not None:
            with contextlib.suppress(Exception):
                await self._stt_stream.close()
        await self._close_providers()

    async def _close_providers(self) -> None:
        aclose = getattr(self.tts, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()

    async def _idle_loop(self) -> None:
        """A forgotten tab must not keep a (billed) STT stream open forever."""
        self._last_activity = self.clock()
        tick = min(1.0, self.idle_timeout_s / 4)
        while True:
            await asyncio.sleep(tick)
            busy = self._run is not None and self._run.running
            if busy or self.state != "listening":
                self._last_activity = self.clock()
                continue
            if self.clock() - self._last_activity >= self.idle_timeout_s:
                log.info("voice_idle_timeout", seconds=self.idle_timeout_s)
                await self._error(
                    "idle_timeout",
                    "Voice paused after a quiet stretch. Tap the orb to keep talking.",
                    fatal=True,
                )
                return

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
            elif kind == "backchannel":
                now = self.clock()
                self._backchannels = [
                    b for b in self._backchannels if now - b[0] < BACKCHANNEL_ECHO_S
                ]
                self._backchannels.append((now, str(msg.get("text") or "")[:40]))
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
        # STT endpointing can beat the client report: attach it to the turn it ended
        # (replacing an earlier, stale t0) if it falls shortly before that turn's t1.
        if run is not None and run.timing.t1 is not None and accept_t0(mapped[0], run.timing.t1):
            if run.timing.t0 is None or mapped[0] > run.timing.t0:
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
            if run.done:  # otherwise the end of _run_turn finalizes (turn_id known then)
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
        if ev.kind == "speech_started":
            self._last_activity = self.clock()
            return
        busy = self._busy()
        if ev.kind == "interim":
            self._last_activity = self.clock()
            if ev.text:
                self._extend_hold()  # still talking: don't start the held turn yet
            if not busy or self.barge_in:
                text = " ".join([*self._held, ev.text]) if not busy else ev.text
                await self._send({"type": "transcript_interim", "text": text, "during_reply": busy})
        elif ev.kind == "final":
            self._last_activity = self.clock()
            await self._on_final(ev.text)

    def _busy(self) -> bool:
        run = self._run
        return run is not None and run.running and run.cancel is None

    def _absorb_while_busy(self, text: str) -> bool:
        """A final heard while a reply is in flight. Before any reply audio (barge-in on),
        2+ words mean the student wasn't done: stop the reply and return False so the
        caller starts a new turn (the stopped turn's extraction is still saved). Otherwise
        keep the words for the next turn and return True."""
        run = self._run
        assert run is not None
        if self.barge_in and run.timing.t4 is None and word_count(text) >= CONTINUE_MIN_WORDS:
            log.info("voice_turn_restarted", words=word_count(text))
            run.last_played = -1
            self._request_stop(run, "interrupt")
            return False
        log.info("stt_final_buffered", state=self.state)
        self._buffered_finals.append(text)
        return True

    async def _on_final(self, text: str) -> None:
        """Start the turn, unless the student seems mid-thought: then hold briefly."""
        now = self.clock()
        recent = [t for at, t in self._backchannels if now - at < BACKCHANNEL_ECHO_S]
        if recent:
            cleaned = strip_echo(text, recent)
            if cleaned != text:
                log.info("backchannel_echo_dropped", kept_words=word_count(cleaned))
            if not cleaned:
                return
            text = cleaned
        if self._busy() and self._absorb_while_busy(text):
            return
        self._held.append(text)
        if trails_off(text):
            if self._hold_task is None or self._hold_task.done():
                self._hold_started = self.clock()
            self._cancel_hold()
            self._arm_hold()
            return
        self._cancel_hold()
        await self._release_held()

    def _cancel_hold(self) -> None:
        if self._hold_task is not None and not self._hold_task.done():
            self._hold_task.cancel()
        self._hold_task = None

    def _extend_hold(self) -> None:
        """More speech is coming: restart the hold clock (if a turn is being held), but
        never past ``TRAILING_HOLD_MAX_S`` from the start of the hold."""
        if self._hold_task is not None and not self._hold_task.done():
            self._cancel_hold()
            self._arm_hold()

    def _arm_hold(self) -> None:
        remaining = TRAILING_HOLD_MAX_S - (self.clock() - self._hold_started)
        delay = max(0.0, min(TRAILING_HOLD_S, remaining))

        async def release_later() -> None:
            await asyncio.sleep(delay)
            self._hold_task = None  # from here on a new final can't cancel the release
            await self._release_held()

        task = asyncio.create_task(release_later())
        self._hold_task = task
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _release_held(self) -> None:
        """Start one turn from the held text. Serialized: a final arriving while another
        release is starting a turn waits, then sees that turn as busy."""
        async with self._start_lock:
            if not self._held or self._closed or self._stopping:
                return
            text = " ".join(self._held)
            self._held.clear()
            if self._busy() and self._absorb_while_busy(text):
                return
            await self._start_turn(text)

    # ---------------------------------------------------------------- the turn

    async def _start_turn(self, text: str) -> None:
        t1 = self.clock()
        prev = self._run
        if prev is not None:
            if prev.running:  # a stopped turn still persisting/truncating
                await self._await_run(prev)
            await self._finalize_metrics(prev)  # previous turn never reported t5
        if self._buffered_finals:
            text = " ".join([*self._buffered_finals, text])
            self._buffered_finals.clear()
        self._turn_no += 1
        timing = TurnTiming(turn=self._turn_no, t1=t1)
        if self._pending_t0 is not None and accept_t0(self._pending_t0[0], t1):
            timing.t0, timing.t0_client_ms = self._pending_t0
        self._pending_t0 = None
        run = _TurnRun(timing=timing)
        self._run = run
        await self._send({"type": "transcript_final", "text": text, "turn": timing.turn})
        await self._set_state("thinking")
        run.task = asyncio.create_task(self._run_turn(run, text))

    def _request_stop(self, run: _TurnRun, kind: Literal["interrupt", "shutdown"]) -> None:
        if run.cancel is None:
            run.cancel = kind
        if run.tts_task is not None and not run.tts_task.done():
            run.tts_task.cancel()

    async def _await_run(self, run: _TurnRun) -> None:
        if run.task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(run.task), FINISH_TIMEOUT_S)
        except TimeoutError:
            log.error("voice_turn_stop_timeout", seconds=FINISH_TIMEOUT_S)
            run.task.cancel()
            with contextlib.suppress(BaseException):
                await run.task
        except asyncio.CancelledError:
            if not run.task.cancelled():
                raise
        except Exception:  # the task reports its own failures
            pass

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
        run.tts_task = asyncio.create_task(self._tts_worker(run, queue))
        chunker = SentenceChunker()
        failed = False
        assistant_text = ""
        try:
            run.baseline_idx = await self._max_idx()
            agen = self.orch.handle_turn(self.session_id, text, "voice")
            try:
                async for ev in agen:
                    if ev.event == "token" and run.cancel is not None:
                        break  # closing the generator persists the partial reply
                    failed = await self._on_turn_event(run, ev, chunker, queue) or failed
                    if ev.event == "done":
                        assistant_text = str(ev.data.get("assistant_text", ""))
            finally:
                await agen.aclose()
            if run.cancel is None:
                rest = chunker.flush()
                if rest:
                    queue.put_nowait(rest)
                queue.put_nowait(None)
                try:
                    await run.tts_task
                except asyncio.CancelledError:
                    task = asyncio.current_task()
                    if task is not None and task.cancelling():
                        raise  # we are being hard-cancelled, not just TTS
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failed = True
            log.error("voice_turn_failed", error=type(exc).__name__)
            await self._error("turn_failed", "Something went wrong. Please try again.")
        finally:
            if not run.tts_task.done():
                run.tts_task.cancel()
                with contextlib.suppress(BaseException):
                    await run.tts_task
        timing.audio = not run.tts_failed and timing.t4 is not None
        if run.cancel == "interrupt":
            await self._finish_interrupt(run)
        elif run.cancel is None:
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
            if not timing.audio or timing.t5 is not None:
                await self._finalize_metrics(run)  # else: on playback_start
        run.done = True

    async def _on_turn_event(
        self,
        run: _TurnRun,
        ev: TurnEvent,
        chunker: SentenceChunker,
        queue: asyncio.Queue[str | None],
    ) -> bool:
        """Forward one orchestrator event; returns True if it was an error."""
        timing = run.timing
        if ev.event == "token":
            delta = str(ev.data.get("text", ""))
            if timing.t2 is None:
                timing.t2 = self.clock()
            await self._send({"type": "assistant_text", "delta": delta, "turn": timing.turn})
            for sentence in chunker.push(delta):
                queue.put_nowait(sentence)
        elif ev.event in ("profile", "ready"):
            await self._send({"type": ev.event, **ev.data})
        elif ev.event == "done":
            run.turn_id = timing.turn_id = str(ev.data.get("turn_id"))
        elif ev.event == "error":
            await self._error(
                "llm_failed", str(ev.data.get("message") or "The counselor couldn't reply.")
            )
            return True
        return False

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
                async with contextlib.aclosing(self.tts.synthesize(sentence)) as audio:
                    async for pcm in audio:
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
        if run.cancel is not None or run.timing.interrupted:
            return  # already stopping / stopped
        try:
            run.last_played = int(msg.get("last_played", -1))
        except (TypeError, ValueError):
            run.last_played = -1
        if run.running:
            # Stop speaking now; the turn loop persists, truncates and reports.
            self._request_stop(run, "interrupt")
            await self._set_state("listening", force=True)
        else:
            run.cancel = "interrupt"
            await self._finish_interrupt(run)

    async def _finish_interrupt(self, run: _TurnRun) -> None:
        played = run.sentences[: max(0, run.last_played + 1)]
        text = " ".join(played) or NOTHING_PLAYED
        turn_id = await self._truncate_assistant_turn(run, text)
        run.turn_id = run.timing.turn_id = turn_id or run.turn_id
        run.timing.interrupted = True
        await self._send(
            {
                "type": "interrupted",
                "turn": run.timing.turn,
                "turn_id": run.turn_id,
                "played_through": run.last_played,
                "assistant_text": text,
            }
        )
        await self._set_state("listening", force=self.state != "listening")
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
                return None  # no reply text was persisted (nothing streamed yet)
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
