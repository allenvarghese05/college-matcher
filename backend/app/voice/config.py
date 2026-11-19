"""Voice settings. Kept separate from ``app.core.config`` so the voice package owns them.

``DEEPGRAM_API_KEY`` lives in the core settings (``backend/.env``); everything here has a
safe default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

VoiceProviderMode = Literal["auto", "deepgram", "fake", "off"]


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # auto: Deepgram when DEEPGRAM_API_KEY is set, otherwise voice is unavailable.
    # fake: scripted STT + tone TTS (UI development without a key). off: always unavailable.
    VOICE_PROVIDER: VoiceProviderMode = "auto"
    # Tier 3: client VAD during playback -> interrupt -> cancel LLM + TTS, truncate turn.
    VOICE_BARGE_IN: bool = False

    # Deepgram live STT (wss://api.deepgram.com/v1/listen)
    DEEPGRAM_STT_MODEL: str = "nova-3"
    DEEPGRAM_STT_LANGUAGE: str = "en-US"
    DEEPGRAM_ENDPOINTING_MS: int = 300
    DEEPGRAM_UTTERANCE_END_MS: int = 1000  # docs: >= 1000 ms and needs interim_results

    # Deepgram TTS (POST https://api.deepgram.com/v1/speak)
    DEEPGRAM_TTS_MODEL: str = "aura-2-thalia-en"
    TTS_SAMPLE_RATE: int = 24000

    INPUT_SAMPLE_RATE: int = 16000


@lru_cache
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()
