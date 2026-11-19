"""Regenerate ``tests/cassettes/*.json`` from the hand-written scenario (no network).

The Claude responses are hand-written in ``tests/counselor_fixtures.py``; this script
plays the scenario through the real API + orchestrator with ``LLM_MODE=record`` and a
scripted fake Anthropic transport, so every cassette is keyed by the exact request the
app sends. Re-run after changing a prompt or request shape:

    cd backend && DATABASE_URL=postgresql+asyncpg://...:5433/matcher_counselor \
        uv run python -m tests.cassettes.build
"""

from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

from app.core.llm import LLMClient
from app.db.session import dispose_engine
from tests.counselor_fixtures import (
    CASSETTE_DIR,
    SCENARIO_K,
    FakeRetriever,
    ScriptedAnthropic,
    make_app,
    run_api_scenario,
    scenario_profile,
    script_recommendation,
    script_scenario,
)


async def main() -> None:
    for old in CASSETTE_DIR.glob("*.json"):
        old.unlink()
    fake = ScriptedAnthropic()
    script_scenario(fake)
    script_recommendation(fake, scenario_profile(), SCENARIO_K)
    llm = LLMClient(mode="record", cassette_dir=CASSETTE_DIR, anthropic_client=fake)
    app = make_app(llm, FakeRetriever())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        run = await run_api_scenario(c)
    await dispose_engine()
    written = sorted(p.name for p in CASSETTE_DIR.glob("*.json"))
    print(f"groundedness={run.recommendations['groundedness']} cassettes={written}")


if __name__ == "__main__":
    asyncio.run(main())
