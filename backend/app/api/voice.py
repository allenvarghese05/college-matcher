"""Voice routes: ``WS /api/sessions/{id}/voice`` (protocol: ``app.voice.gateway``) and
``GET /api/voice/status`` (lets the UI show "Voice isn't connected yet" without a socket).

Dependencies (override in tests via ``app.dependency_overrides``):
``get_voice_config`` (STT/TTS providers + barge-in flag; ``None`` = voice unavailable)
and ``app.api.sessions.get_orchestrator``.

Close codes: 4404 unknown session, 4503 voice not configured (no ``DEEPGRAM_API_KEY``).
Inbound limits: binary frames > 64 KB and text frames > 4 KB are dropped.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, WebSocket

from app.api.sessions import get_orchestrator
from app.core.config import get_settings
from app.core.logging import get_logger
from app.counselor.orchestrator import CounselorOrchestrator, SessionNotFound, get_chat_session
from app.voice.config import get_voice_settings
from app.voice.gateway import VoiceGateway
from app.voice.stt import DeepgramSTT, FakeSTT, STTProvider
from app.voice.tts import DeepgramTTS, FakeTTS, TTSError, TTSProvider

router = APIRouter(tags=["voice"])
log = get_logger(__name__)

FAKE_UTTERANCES = [
    "I really like building things and I have been coding since middle school.",
    "I live in Ohio and my family makes around sixty thousand a year.",
]


@dataclass
class VoiceConfig:
    stt: STTProvider
    tts: TTSProvider
    provider: str
    barge_in: bool = False
    backchannel: bool = False
    input_sample_rate: int = 16000
    idle_timeout_s: float = 90.0


def get_voice_config() -> VoiceConfig | None:
    vs = get_voice_settings()
    if vs.VOICE_PROVIDER == "off":
        return None
    if vs.VOICE_PROVIDER == "fake":
        return VoiceConfig(
            stt=FakeSTT(utterances=FAKE_UTTERANCES),
            tts=FakeTTS(sample_rate=vs.TTS_SAMPLE_RATE, chunks_per_sentence=10, chunk_ms=50),
            provider="fake",
            barge_in=vs.VOICE_BARGE_IN,
            backchannel=vs.VOICE_BACKCHANNEL,
            input_sample_rate=vs.INPUT_SAMPLE_RATE,
            idle_timeout_s=vs.VOICE_IDLE_TIMEOUT_S,
        )
    key = get_settings().DEEPGRAM_API_KEY
    if key is None or not key.get_secret_value():
        return None
    secret = key.get_secret_value()
    return VoiceConfig(
        stt=DeepgramSTT(
            api_key=secret,
            model=vs.DEEPGRAM_STT_MODEL,
            language=vs.DEEPGRAM_STT_LANGUAGE,
            sample_rate=vs.INPUT_SAMPLE_RATE,
            endpointing_ms=vs.DEEPGRAM_ENDPOINTING_MS,
            utterance_end_ms=vs.DEEPGRAM_UTTERANCE_END_MS,
        ),
        tts=DeepgramTTS(
            api_key=secret, model=vs.DEEPGRAM_TTS_MODEL, sample_rate=vs.TTS_SAMPLE_RATE
        ),
        provider="deepgram",
        barge_in=vs.VOICE_BARGE_IN,
        backchannel=vs.VOICE_BACKCHANNEL,
        input_sample_rate=vs.INPUT_SAMPLE_RATE,
        idle_timeout_s=vs.VOICE_IDLE_TIMEOUT_S,
    )


MAX_AUDIO_FRAME_BYTES = 64 * 1024  # 20 ms of 16 kHz PCM16 is 640 bytes
MAX_TEXT_FRAME_CHARS = 4 * 1024


class StarletteTransport:
    """Oversized frames are dropped (returned as an empty control message)."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def send_json(self, data: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(data, ensure_ascii=False))

    async def send_bytes(self, data: bytes) -> None:
        await self.ws.send_bytes(data)

    async def receive(self) -> bytes | dict[str, Any] | None:
        msg = await self.ws.receive()
        if msg["type"] == "websocket.disconnect":
            return None
        if msg.get("bytes") is not None:
            if len(msg["bytes"]) > MAX_AUDIO_FRAME_BYTES:
                log.warning("voice_frame_dropped", kind="binary", size=len(msg["bytes"]))
                return {}
            return bytes(msg["bytes"])
        text = msg.get("text") or ""
        if len(text) > MAX_TEXT_FRAME_CHARS:
            log.warning("voice_frame_dropped", kind="text", size=len(text))
            return {}
        try:
            data = json.loads(text)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}


@router.get("/api/voice/status")
async def voice_status(config: VoiceConfig | None = Depends(get_voice_config)) -> dict[str, Any]:
    if config is None:
        return {"available": False, "provider": None, "barge_in": False}
    return {"available": True, "provider": config.provider, "barge_in": config.barge_in}


BACKCHANNEL_TEXTS = ("Mhm.", "Yeah.", "Right.", "Okay.", "Mm, I see.")
_backchannel_cache: dict[str, dict[str, Any]] = {}
_backchannel_lock = asyncio.Lock()


async def synthesize_backchannels(tts: TTSProvider, cache_key: str) -> dict[str, Any]:
    """Short listening sounds, synthesized once per voice model and cached in memory."""
    async with _backchannel_lock:  # concurrent first requests synthesize once
        if cache_key in _backchannel_cache:
            return _backchannel_cache[cache_key]
        clips = []
        for text in BACKCHANNEL_TEXTS:
            pcm = b"".join([chunk async for chunk in tts.synthesize(text)])
            clips.append({"text": text, "pcm16_b64": base64.b64encode(pcm).decode("ascii")})
        out = {"sample_rate": tts.sample_rate, "clips": clips}
        _backchannel_cache[cache_key] = out
        return out


@router.get("/api/voice/backchannels")
async def voice_backchannels(
    config: VoiceConfig | None = Depends(get_voice_config),
) -> dict[str, Any]:
    """PCM16 mono clips for the client's mid-answer "mhm"s (empty when disabled)."""
    if config is None or not config.backchannel:
        return {"sample_rate": 24000, "clips": []}
    key = f"{config.provider}:{getattr(config.tts, 'model', '')}:{config.tts.sample_rate}"
    try:
        return await synthesize_backchannels(config.tts, key)
    except TTSError as exc:
        log.warning("backchannel_synth_failed", error=str(exc))
        return {"sample_rate": config.tts.sample_rate, "clips": []}
    finally:
        aclose = getattr(config.tts, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()


async def _fatal(ws: WebSocket, code: str, message: str, close_code: int) -> None:
    await ws.send_text(json.dumps({"type": "error", "code": code, "message": message,
                                   "fatal": True}))  # fmt: skip
    await ws.close(code=close_code)


@router.websocket("/api/sessions/{session_id}/voice")
async def voice_socket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    orch: CounselorOrchestrator = Depends(get_orchestrator),
    config: VoiceConfig | None = Depends(get_voice_config),
) -> None:
    await websocket.accept()
    if config is None:
        await _fatal(websocket, "voice_unavailable", "Voice isn't connected yet.", 4503)
        return
    try:
        async with orch.sessionmaker() as db:
            await get_chat_session(db, session_id)
    except SessionNotFound:
        await _fatal(websocket, "session_not_found", "This conversation no longer exists.", 4404)
        return
    gateway = VoiceGateway(
        transport=StarletteTransport(websocket),
        orch=orch,
        session_id=session_id,
        stt=config.stt,
        tts=config.tts,
        barge_in=config.barge_in,
        backchannel=config.backchannel,
        provider_name=config.provider,
        input_sample_rate=config.input_sample_rate,
        idle_timeout_s=config.idle_timeout_s,
    )
    try:
        await gateway.run()
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
