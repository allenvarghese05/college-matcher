"""Voice WebSocket: ``WS /api/sessions/{id}/voice`` (protocol: ``app.voice.gateway``).

Dependencies (override in tests via ``app.dependency_overrides``):
``get_voice_config`` (STT/TTS providers + barge-in flag; ``None`` = voice unavailable)
and ``app.api.sessions.get_orchestrator``.

Close codes: 4404 unknown session, 4503 voice not configured (no ``DEEPGRAM_API_KEY``).
"""

from __future__ import annotations

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
from app.voice.tts import DeepgramTTS, FakeTTS, TTSProvider

router = APIRouter(prefix="/api/sessions", tags=["voice"])
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
    input_sample_rate: int = 16000


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
            input_sample_rate=vs.INPUT_SAMPLE_RATE,
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
        input_sample_rate=vs.INPUT_SAMPLE_RATE,
    )


class StarletteTransport:
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
            return bytes(msg["bytes"])
        try:
            data = json.loads(msg.get("text") or "")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}


async def _fatal(ws: WebSocket, code: str, message: str, close_code: int) -> None:
    await ws.send_text(json.dumps({"type": "error", "code": code, "message": message,
                                   "fatal": True}))  # fmt: skip
    await ws.close(code=close_code)


@router.websocket("/{session_id}/voice")
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
        provider_name=config.provider,
        input_sample_rate=config.input_sample_rate,
    )
    try:
        await gateway.run()
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
