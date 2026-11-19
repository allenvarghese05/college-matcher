"""Text-to-speech: Deepgram Aura-2 (chunked REST, streamed body) plus ``FakeTTS`` for tests.

One request per sentence chunk. REST is used rather than the TTS WebSocket because the
WebSocket's ``Flush`` is limited to 20 per 60 s (one per sentence would hit it in a long
conversation), and per-sentence requests make cancellation on barge-in trivial.

Deepgram (docs: https://developers.deepgram.com/reference/text-to-speech/speak-request):
``POST https://api.deepgram.com/v1/speak?model=aura-2-thalia-en&encoding=linear16
&sample_rate=24000&container=none`` with JSON ``{"text": ...}`` and header
``Authorization: Token <key>``. ``container=none`` returns raw little-endian PCM16 (the
default container for linear16 is a WAV header). Max 2000 characters per request.

Output contract for every provider: an async iterator of PCM16 mono byte chunks at
``sample_rate``, each chunk an even number of bytes.
"""

from __future__ import annotations

import asyncio
import math
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

import httpx

DEEPGRAM_SPEAK_URL = "https://api.deepgram.com/v1/speak"
MAX_CHARS = 2000


class TTSError(Exception):
    """TTS request failed."""


class TTSProvider(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> AsyncIterator[bytes]: ...


async def _even_chunks(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Re-frame a byte stream so no chunk splits a 16-bit sample."""
    carry = b""
    async for chunk in chunks:
        data = carry + chunk
        cut = len(data) - (len(data) % 2)
        carry = data[cut:]
        if cut:
            yield data[:cut]


@dataclass
class DeepgramTTS:
    api_key: str
    model: str = "aura-2-thalia-en"
    sample_rate: int = 24000
    timeout_s: float = 15.0
    client: httpx.AsyncClient | None = None

    def _params(self) -> dict[str, str | int]:
        return {
            "model": self.model,
            "encoding": "linear16",
            "sample_rate": self.sample_rate,
            "container": "none",
        }

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        client = self.client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            async with client.stream(
                "POST",
                DEEPGRAM_SPEAK_URL,
                params=self._params(),
                headers={"Authorization": f"Token {self.api_key}"},
                json={"text": text[:MAX_CHARS]},
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise TTSError(f"deepgram speak HTTP {resp.status_code}")
                async for chunk in _even_chunks(resp.aiter_bytes()):
                    yield chunk
        except httpx.HTTPError as exc:
            raise TTSError(f"deepgram speak failed: {type(exc).__name__}") from exc
        finally:
            if self.client is None:
                await client.aclose()


def tone_pcm(n_samples: int, sample_rate: int, freq: float = 220.0, amp: float = 0.08) -> bytes:
    """A soft sine tone, PCM16 LE — audible stand-in for speech in fake mode."""
    return b"".join(
        struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / sample_rate)))
        for i in range(n_samples)
    )


@dataclass
class FakeTTS:
    """Emits ``chunks_per_sentence`` PCM chunks of ``chunk_ms`` each per sentence.

    ``fail_on`` — 0-based sentence indices (counted across the provider's lifetime) that
    raise ``TTSError`` before any audio. ``first_chunk_delay_s`` simulates TTS latency.
    """

    sample_rate: int = 24000
    chunks_per_sentence: int = 2
    chunk_ms: int = 40
    first_chunk_delay_s: float = 0.0
    chunk_delay_s: float = 0.0
    fail_on: set[int] = field(default_factory=set)
    requests: list[str] = field(default_factory=list)

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        n = len(self.requests)
        self.requests.append(text)
        if n in self.fail_on:
            raise TTSError("fake tts failure")
        if self.first_chunk_delay_s:
            await asyncio.sleep(self.first_chunk_delay_s)
        samples = self.sample_rate * self.chunk_ms // 1000
        pcm = tone_pcm(samples, self.sample_rate)
        for i in range(self.chunks_per_sentence):
            if i and self.chunk_delay_s:
                await asyncio.sleep(self.chunk_delay_s)
            yield pcm
