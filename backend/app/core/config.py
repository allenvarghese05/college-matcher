"""Application settings, loaded from environment variables (and `.env` if present)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMMode = Literal["live", "record", "replay"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://matcher:matcher@localhost:5432/matcher"

    ANTHROPIC_API_KEY: SecretStr | None = None
    DEEPGRAM_API_KEY: SecretStr | None = None

    # Never log raw student text unless explicitly enabled (SPEC §12).
    LOG_PII: bool = False
    LOG_LEVEL: str = "INFO"

    # live: call APIs; record: call APIs and save cassettes; replay: read cassettes only.
    LLM_MODE: LLMMode = "replay"

    MODEL_FAST: str = "claude-sonnet-5-5"
    MODEL_STRONG: str = "claude-opus-5-5"

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
