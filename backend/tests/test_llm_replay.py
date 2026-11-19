from __future__ import annotations

import json
from pathlib import Path

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from app.core.llm import (
    LLMClient,
    LLMOutputError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMRequestError,
    LLMUnavailableError,
    ReplayMissError,
    request_key,
    use_stage,
)
from app.core.logging import Stage
from tests.counselor_fixtures import ScriptedAnthropic, ScriptedParse, ScriptedStream, usage

SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"
SYSTEM = "You are a test system prompt."
MSGS = [{"role": "user", "content": "hello"}]


class Pet(BaseModel):
    name: str
    legs: int


SCHEMA = {
    "type": "object",
    "properties": {"ids": {"type": "array", "items": {"type": "integer", "enum": [1, 2]}}},
    "required": ["ids"],
    "additionalProperties": False,
}


def _req() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


async def _drain(client: LLMClient, **kw: object) -> tuple[list[str], object]:
    stream = client.stream_text(SONNET, SYSTEM, MSGS, effort="low", max_tokens=256, **kw)  # type: ignore[arg-type]
    return [c async for c in stream], stream


async def test_stream_record_then_replay_roundtrip(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["Hel", "lo ", "there"], usage=usage(10, 3, 100, 20)))
    rec = LLMClient(mode="record", cassette_dir=tmp_path, anthropic_client=fake)
    st = Stage("reply")
    chunks, stream = await _drain(rec, stage=st)
    assert chunks == ["Hel", "lo ", "there"]
    assert stream.text == "Hello there"  # type: ignore[attr-defined]
    assert stream.ttft_ms is not None  # type: ignore[attr-defined]
    files = list(tmp_path.glob("stream-*.json"))
    assert len(files) == 1
    cas = json.loads(files[0].read_text())
    assert cas["response"]["chunks"] == ["Hel", "lo ", "there"]
    assert cas["request"]["params"] == {"effort": "low", "max_tokens": 256}
    assert st.input_tokens == 10 and st.output_tokens == 3 and st.cache_read_tokens == 100
    assert st.extra["cache_creation_tokens"] == 20

    # replay: no transport at all, same chunks and usage
    rep = LLMClient(mode="replay", cassette_dir=tmp_path)
    st2 = Stage("reply")
    chunks2, stream2 = await _drain(rep, stage=st2)
    assert chunks2 == chunks
    assert stream2.usage.output_tokens == 3  # type: ignore[attr-defined]
    assert st2.cost_usd == pytest.approx(st.cost_usd)


async def test_stream_api_params_cache_effort_no_prefill(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(ScriptedStream(chunks=["ok"]))
    client = LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)
    await _drain(client)
    kind, kw = fake.calls[0]
    assert kind == "stream"
    assert kw["model"] == SONNET and kw["max_tokens"] == 256
    assert kw["system"] == [
        {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]
    assert kw["output_config"] == {"effort": "low"}
    assert "thinking" not in kw and "tool_choice" not in kw and "temperature" not in kw
    assert kw["messages"][-1]["role"] != "assistant"  # no prefill
    assert not list(tmp_path.glob("*.json"))  # live mode doesn't write cassettes


async def test_parse_pydantic_record_replay(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse("Pet", ScriptedParse(output=Pet(name="Rex", legs=4)))
    rec = LLMClient(mode="record", cassette_dir=tmp_path, anthropic_client=fake)
    pet = await rec.parse(SONNET, SYSTEM, MSGS, Pet, effort="medium", max_tokens=1000)
    assert pet == Pet(name="Rex", legs=4)
    _, kw = fake.calls[0]
    assert kw["output_format"] is Pet
    assert kw["output_config"] == {"effort": "medium"}
    rep = LLMClient(mode="replay", cassette_dir=tmp_path)
    assert await rep.parse(SONNET, SYSTEM, MSGS, Pet, effort="medium", max_tokens=1000) == pet


async def test_parse_json_schema_uses_output_config_format(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse("json_schema", ScriptedParse(output={"ids": [2]}))
    rec = LLMClient(mode="record", cassette_dir=tmp_path, anthropic_client=fake)
    out = await rec.parse(OPUS, SYSTEM, MSGS, SCHEMA, effort="high")
    assert out == {"ids": [2]}
    _, kw = fake.calls[0]
    assert kw["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": SCHEMA},
    }
    assert "output_format" not in kw
    rep = LLMClient(mode="replay", cassette_dir=tmp_path)
    assert await rep.parse(OPUS, SYSTEM, MSGS, SCHEMA, effort="high") == {"ids": [2]}


async def test_replay_miss_names_hash(tmp_path: Path) -> None:
    rep = LLMClient(mode="replay", cassette_dir=tmp_path)
    req = {
        "model": SONNET,
        "system": SYSTEM,
        "messages": MSGS,
        "schema": Pet.model_json_schema(),
        "params": {"effort": "low", "max_tokens": 16000},
    }
    key = request_key("parse", req)
    with pytest.raises(ReplayMissError) as ei:
        await rep.parse(SONNET, SYSTEM, MSGS, Pet, effort="low")
    assert ei.value.key == key and key in str(ei.value)
    with pytest.raises(ReplayMissError):
        await _drain(rep)


def test_request_key_is_stable_and_sensitive() -> None:
    base = {"model": SONNET, "system": SYSTEM, "messages": MSGS, "schema": None, "params": {}}
    assert request_key("stream", base) == request_key("stream", dict(reversed(base.items())))
    assert request_key("stream", base) != request_key("parse", base)
    assert request_key("stream", base) != request_key("stream", {**base, "system": "x"})
    assert request_key("stream", base) != request_key("stream", {**base, "model": OPUS})


async def test_replay_mode_never_builds_api_client(tmp_path: Path) -> None:
    rep = LLMClient(mode="replay", cassette_dir=tmp_path)
    with pytest.raises(RuntimeError):
        rep._api()


async def test_refusal_stream_and_parse(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_stream(
        ScriptedStream(chunks=[], stop_reason="refusal", refusal_category="general_harms")
    )
    fake.add_parse("Pet", ScriptedParse(output="", stop_reason="refusal", refusal_category="cyber"))
    rec = LLMClient(mode="record", cassette_dir=tmp_path, anthropic_client=fake)
    with pytest.raises(LLMRefusalError) as ei:
        await _drain(rec)
    assert ei.value.category == "general_harms"
    with pytest.raises(LLMRefusalError):
        await rec.parse(SONNET, SYSTEM, MSGS, Pet, effort="low")
    # refusals replay as refusals
    rep = LLMClient(mode="replay", cassette_dir=tmp_path)
    with pytest.raises(LLMRefusalError):
        await _drain(rep)
    with pytest.raises(LLMRefusalError):
        await rep.parse(SONNET, SYSTEM, MSGS, Pet, effort="low")


async def test_truncated_or_invalid_structured_output(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse("Pet", ScriptedParse(output='{"name": "Re', stop_reason="max_tokens"))
    fake.add_parse("Pet", ScriptedParse(output='{"name": "Rex"}'))
    client = LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)
    with pytest.raises(LLMOutputError, match="max_tokens"):
        await client.parse(SONNET, SYSTEM, MSGS, Pet, effort="low")
    with pytest.raises(LLMOutputError):
        await client.parse(SONNET, SYSTEM, MSGS, Pet, effort="low")


@pytest.mark.parametrize(
    ("exc", "expected", "retryable"),
    [
        (
            anthropic.RateLimitError(
                "slow down", response=httpx2.Response(429, request=_req()), body=None
            ),
            LLMRateLimitError,
            True,
        ),
        (
            anthropic.InternalServerError(
                "oops", response=httpx2.Response(500, request=_req()), body=None
            ),
            LLMUnavailableError,
            True,
        ),
        (
            anthropic.BadRequestError(
                "bad", response=httpx2.Response(400, request=_req()), body=None
            ),
            LLMRequestError,
            False,
        ),
        (anthropic.APIConnectionError(request=_req()), LLMUnavailableError, True),
        (anthropic.APITimeoutError(request=_req()), LLMUnavailableError, True),
    ],
)
async def test_sdk_errors_are_translated(
    tmp_path: Path, exc: Exception, expected: type[Exception], retryable: bool
) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse("Pet", exc)
    fake.add_stream(exc)
    client = LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)
    with pytest.raises(expected) as ei:
        await client.parse(SONNET, SYSTEM, MSGS, Pet, effort="low")
    assert ei.value.retryable is retryable  # type: ignore[attr-defined]
    with pytest.raises(expected):
        await _drain(client)


async def test_usage_cost_includes_cache_write_and_binds_via_contextvar(tmp_path: Path) -> None:
    fake = ScriptedAnthropic()
    fake.add_parse(
        "Pet", ScriptedParse(output=Pet(name="a", legs=1), usage=usage(1000, 100, 10_000, 2000))
    )
    client = LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)
    st = Stage("extract")
    with use_stage(st):
        await client.parse(SONNET, SYSTEM, MSGS, Pet, effort="low")
    # sonnet: $2 in, $10 out, $0.10 cache read; cache write 1.25 x $2
    expected = (1000 * 2 + 100 * 10 + 10_000 * 0.10 + 2000 * 2 * 1.25) / 1_000_000
    assert st.cost_usd == pytest.approx(expected)
    assert st.model == SONNET
    assert st.cache_read_tokens == 10_000
