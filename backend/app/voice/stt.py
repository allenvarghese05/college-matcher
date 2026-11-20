"""Streaming speech-to-text: Deepgram live STT over WebSocket, plus ``FakeSTT`` for tests.

Both expose the same normalized event stream so the gateway never sees vendor frames:

* ``STTEvent("interim", text)`` — running transcript of the current utterance
  (finalized segments + the latest interim hypothesis);
* ``STTEvent("final", text)`` — the utterance is complete; ``text`` is the full utterance;
* ``STTEvent("speech_started")`` — Deepgram VAD event (informational).

Deepgram (docs: https://developers.deepgram.com/reference/speech-to-text/listen-streaming,
https://developers.deepgram.com/docs/understanding-end-of-speech-detection):

* ``wss://api.deepgram.com/v1/listen?model=nova-3&encoding=linear16&sample_rate=16000
  &channels=1&interim_results=true&endpointing=300&utterance_end_ms=1000&vad_events=true
  &smart_format=true&punctuate=true``, header ``Authorization: Token <key>``;
* audio is sent as raw binary messages; control messages are JSON
  ``{"type": "KeepAlive" | "Finalize" | "CloseStream"}``;
* ``Results`` frames carry ``is_final`` / ``speech_final`` / ``from_finalize`` and
  ``channel.alternatives[0].transcript``. ``is_final`` segments are concatenated; the
  utterance ends on ``speech_final=true`` (endpointing), on ``from_finalize=true`` (we
  sent ``Finalize`` because the client VAD saw end of speech), or on ``UtteranceEnd``
  when no ``speech_final`` preceded it (Deepgram's recommended combination).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlencode

from app.core.logging import get_logger

log = get_logger(__name__)

DEEPGRAM_LISTEN_URL = "wss://api.deepgram.com/v1/listen"
KEEPALIVE_S = 5.0  # Deepgram closes idle streams after ~10 s without audio


class STTError(Exception):
    """The STT stream failed or disconnected."""


@dataclass(frozen=True)
class STTEvent:
    kind: Literal["interim", "final", "speech_started"]
    text: str = ""


class STTStream(Protocol):
    async def send_audio(self, chunk: bytes) -> None: ...

    async def finalize(self) -> None:
        """Client VAD saw end of speech: flush the current utterance now."""
        ...

    def events(self) -> AsyncIterator[STTEvent]: ...

    async def close(self) -> None: ...


class STTProvider(Protocol):
    async def connect(self) -> STTStream: ...


# ---------------------------------------------------------------- utterance assembly


@dataclass
class UtteranceAssembler:
    """Turns Deepgram ``Results`` / ``UtteranceEnd`` frames into normalized events."""

    segments: list[str] = field(default_factory=list)
    last_interim: str = ""
    speech_final_seen: bool = False

    def _current(self, interim: str = "") -> str:
        return " ".join(s for s in [*self.segments, interim] if s).strip()

    def _complete(self) -> list[STTEvent]:
        text = self._current()
        self.segments.clear()
        self.last_interim = ""
        return [STTEvent("final", text)] if text else []

    def feed(self, msg: dict[str, Any]) -> list[STTEvent]:
        kind = msg.get("type")
        if kind == "SpeechStarted":
            return [STTEvent("speech_started")]
        if kind == "UtteranceEnd":
            if self.speech_final_seen:  # already completed by endpointing
                self.speech_final_seen = False
                return []
            if self.last_interim:  # unfinalized tail after the finalized segments
                self.segments.append(self.last_interim)
            return self._complete()
        if kind != "Results":
            return []
        alts = (msg.get("channel") or {}).get("alternatives") or [{}]
        transcript = str(alts[0].get("transcript") or "").strip()
        if msg.get("is_final"):
            if transcript:
                self.segments.append(transcript)
            self.last_interim = ""
            if msg.get("speech_final") or msg.get("from_finalize"):
                self.speech_final_seen = bool(msg.get("speech_final"))
                return self._complete()
            return [STTEvent("interim", self._current())] if transcript else []
        self.speech_final_seen = False
        if not transcript:
            return []
        self.last_interim = transcript
        return [STTEvent("interim", self._current(transcript))]


# --------------------------------------------------------------------- Deepgram


def deepgram_listen_url(
    *,
    model: str,
    language: str,
    sample_rate: int,
    endpointing_ms: int,
    utterance_end_ms: int,
) -> str:
    params = {
        "model": model,
        "language": language,
        "encoding": "linear16",
        "sample_rate": sample_rate,
        "channels": 1,
        "interim_results": "true",
        "endpointing": endpointing_ms,
        "utterance_end_ms": utterance_end_ms,
        "vad_events": "true",
        "smart_format": "true",
        "punctuate": "true",
    }
    return f"{DEEPGRAM_LISTEN_URL}?{urlencode(params)}"


class DeepgramSTTStream:
    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._asm = UtteranceAssembler()
        self._last_send = time.monotonic()
        self._closed = False
        self._keepalive = asyncio.create_task(self._keepalive_loop())

    async def _keepalive_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(1.0)
            if time.monotonic() - self._last_send >= KEEPALIVE_S:
                with contextlib.suppress(Exception):
                    await self._ws.send(json.dumps({"type": "KeepAlive"}))
                self._last_send = time.monotonic()

    async def send_audio(self, chunk: bytes) -> None:
        try:
            await self._ws.send(chunk)
        except Exception as exc:
            raise STTError(f"send failed: {type(exc).__name__}") from exc
        self._last_send = time.monotonic()

    async def finalize(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.send(json.dumps({"type": "Finalize"}))

    async def events(self) -> AsyncIterator[STTEvent]:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                for ev in self._asm.feed(msg):
                    yield ev
        except Exception as exc:
            if not self._closed:
                raise STTError(f"stream failed: {type(exc).__name__}") from exc
        if not self._closed:
            raise STTError("stream closed by server")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._keepalive.cancel()
        with contextlib.suppress(Exception):
            await self._ws.send(json.dumps({"type": "CloseStream"}))
        with contextlib.suppress(Exception):
            await self._ws.close()


@dataclass
class DeepgramSTT:
    api_key: str
    model: str = "nova-3"
    language: str = "en-US"
    sample_rate: int = 16000
    endpointing_ms: int = 300
    utterance_end_ms: int = 1000

    async def connect(self) -> STTStream:
        from websockets.asyncio.client import connect

        url = deepgram_listen_url(
            model=self.model,
            language=self.language,
            sample_rate=self.sample_rate,
            endpointing_ms=self.endpointing_ms,
            utterance_end_ms=self.utterance_end_ms,
        )
        try:
            ws = await connect(
                url, additional_headers={"Authorization": f"Token {self.api_key}"}, max_size=None
            )
        except Exception as exc:
            raise STTError(f"connect failed: {type(exc).__name__}") from exc
        return DeepgramSTTStream(ws)


# ------------------------------------------------------------------------- fake


@dataclass
class FakeSTTStream:
    """Scripted STT. Each utterance is revealed one word per audio frame as ``interim``
    events, and completed as ``final`` on ``finalize()`` (client VAD end) or after
    ``auto_final_frames`` frames. ``fail_after_frames`` simulates a disconnect."""

    utterances: list[str]
    auto_final_frames: int | None = None
    fail_after_frames: int | None = None
    final_delay_s: float = 0.0
    frames: int = 0
    _queue: asyncio.Queue[STTEvent | Exception | None] = field(default_factory=asyncio.Queue)
    _idx: int = 0
    _words_shown: int = 0
    _frames_in_utt: int = 0
    closed: bool = False

    def _words(self) -> list[str]:
        return self.utterances[self._idx % len(self.utterances)].split() if self.utterances else []

    async def send_audio(self, chunk: bytes) -> None:
        if self.closed:
            raise STTError("closed")
        self.frames += 1
        if self.fail_after_frames is not None and self.frames >= self.fail_after_frames:
            await self._queue.put(STTError("fake disconnect"))
            return
        words = self._words()
        self._frames_in_utt += 1
        if self._words_shown < len(words):
            self._words_shown += 1
            await self._queue.put(STTEvent("interim", " ".join(words[: self._words_shown])))
        if self.auto_final_frames is not None and self._frames_in_utt >= self.auto_final_frames:
            await self.finalize()

    async def finalize(self) -> None:
        if self._frames_in_utt == 0:
            return
        words = self._words()
        self._idx += 1
        self._words_shown = 0
        self._frames_in_utt = 0
        if self.final_delay_s:
            await asyncio.sleep(self.final_delay_s)
        await self._queue.put(STTEvent("final", " ".join(words)))

    async def events(self) -> AsyncIterator[STTEvent]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            await self._queue.put(None)


@dataclass
class FakeSTT:
    utterances: list[str]
    auto_final_frames: int | None = None
    fail_after_frames: int | None = None
    fail_connect_after: int | None = None  # connect() raises after this many connections
    final_delay_s: float = 0.0
    connections: int = 0
    streams: list[FakeSTTStream] = field(default_factory=list)

    async def connect(self) -> STTStream:
        if self.fail_connect_after is not None and self.connections >= self.fail_connect_after:
            raise STTError("fake connect failure")
        self.connections += 1
        # only the first connection carries the injected failure
        stream = FakeSTTStream(
            utterances=self.utterances,
            auto_final_frames=self.auto_final_frames,
            fail_after_frames=self.fail_after_frames if self.connections == 1 else None,
            final_delay_s=self.final_delay_s,
        )
        self.streams.append(stream)
        return stream
