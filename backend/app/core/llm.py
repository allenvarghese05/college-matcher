"""Claude client with record / replay (SPEC §10 replay mode, §12 observability).

Every Claude call in the app goes through :class:`LLMClient`:

* ``stream_text`` — streamed text reply (``client.messages.stream``).
* ``parse`` — structured output: the schema (Pydantic model or JSON-schema dict) is
  passed through ``anthropic.transform_schema`` and sent as
  ``output_config.format = {"type": "json_schema", ...}`` on a streamed request
  (``messages.stream`` + ``get_final_message``, so large ``max_tokens`` never hits
  HTTP timeouts). No SDK-side eager validation: we record usage and the cassette,
  check ``stop_reason`` (refusal / max_tokens) first, and only then validate locally,
  raising :class:`LLMOutputError` on a schema mismatch.

Modes (``LLM_MODE``):

* ``live``   — call the Anthropic API.
* ``record`` — call the API and save each exchange as a JSON cassette.
* ``replay`` — never touch the network; answer from cassettes. A miss raises
  :class:`ReplayMissError` naming the request hash.

Cassettes live under ``Settings.LLM_CASSETTE_DIR`` (default ``<repo>/evals/recordings``)
as ``<kind>-<hash>.json``. The hash is a SHA-256 over the canonical JSON of
(kind, model, system, messages, schema, params), so any prompt change is a new key.

Usage (input, output, cache read, cache creation) and cost are recorded into the
:class:`~app.core.logging.Stage` passed in (or the one bound with :func:`use_stage`).
The stable system prompt is sent as a cached block (``cache_control: ephemeral``).
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar, overload

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.config import LLMMode, get_settings
from app.core.cost import cost_usd
from app.core.logging import Stage, get_logger

log = get_logger(__name__)

Effort = Literal["low", "medium", "high", "xhigh", "max"]
M = TypeVar("M", bound=BaseModel)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASSETTE_DIR = REPO_ROOT / "evals" / "recordings"

_current_stage: contextvars.ContextVar[Stage | None] = contextvars.ContextVar(
    "llm_stage", default=None
)


@contextmanager
def use_stage(stage: Stage) -> Iterator[Stage]:
    """Bind ``stage`` so LLM calls without an explicit ``stage=`` record into it."""
    token = _current_stage.set(stage)
    try:
        yield stage
    finally:
        _current_stage.reset(token)


# ---------------------------------------------------------------------- errors


class LLMError(Exception):
    """Base class. ``retryable`` tells callers whether a later retry may succeed."""

    retryable: bool = False


class ReplayMissError(LLMError):
    def __init__(self, key: str, kind: str, model: str, directory: Path):
        self.key = key
        super().__init__(
            f"replay miss: no cassette {kind}-{key}.json for model={model} in {directory}. "
            "Record it with LLM_MODE=record (live API) or add the cassette."
        )


class LLMRefusalError(LLMError):
    """The model declined (stop_reason == 'refusal')."""

    def __init__(self, category: str | None = None):
        self.category = category
        super().__init__(f"model refused the request (category={category})")


class LLMRateLimitError(LLMError):
    retryable = True


class LLMUnavailableError(LLMError):
    """Connection failure, timeout, or 5xx/529 after SDK retries."""

    retryable = True


class LLMRequestError(LLMError):
    """Non-retryable API error (400/401/403/404/...)."""


class LLMAccountError(LLMRequestError):
    """Account-level failure: usage/credit limit reached (400) or auth/permission
    (401/403). Not retryable until someone fixes the account; shown to the student as
    ``ACCOUNT_ERROR_MESSAGE`` rather than as a generic glitch."""


class LLMOutputError(LLMError):
    """Response could not be parsed into the requested schema (e.g. max_tokens)."""


ACCOUNT_ERROR_MESSAGE = (
    "The counselor is unavailable right now (API account limit). Please try again later."
)
# Lowercase fragments of Anthropic 400 messages that mean the account, not the request,
# is the problem ("You have reached your specified API usage limits...", "Your credit
# balance is too low to access the Anthropic API...").
_ACCOUNT_LIMIT_MARKERS = ("usage limit", "credit balance", "spend limit", "billing")


def is_account_error(status_code: int, message: str) -> bool:
    if status_code in (401, 403):
        return True
    text = message.lower()
    return status_code == 400 and any(m in text for m in _ACCOUNT_LIMIT_MARKERS)


def _translate(exc: Exception) -> LLMError:
    """Map SDK exceptions to app errors, most specific first."""
    if isinstance(exc, anthropic.RateLimitError):
        return LLMRateLimitError(f"rate limited: {exc.message}")
    if isinstance(exc, anthropic.APIStatusError):
        if is_account_error(exc.status_code, exc.message):
            # the API's own message text (never the key or request) so the owner can act
            log.error("llm_account_error", status=exc.status_code, api_message=exc.message)
            return LLMAccountError(f"API account error {exc.status_code}: {exc.message}")
        if exc.status_code >= 500:
            return LLMUnavailableError(f"API error {exc.status_code}: {exc.message}")
        return LLMRequestError(f"API error {exc.status_code}: {exc.message}")
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return LLMUnavailableError(f"connection error: {exc}")
    return LLMError(str(exc))


# ----------------------------------------------------------------------- usage


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @classmethod
    def from_api(cls, u: Any) -> Usage:
        return cls(
            input_tokens=int(getattr(u, "input_tokens", 0) or 0),
            output_tokens=int(getattr(u, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
            cache_creation_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Usage:
        return cls(
            input_tokens=int(d.get("input_tokens", 0)),
            output_tokens=int(d.get("output_tokens", 0)),
            cache_read_tokens=int(d.get("cache_read_input_tokens", 0)),
            cache_creation_tokens=int(d.get("cache_creation_input_tokens", 0)),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_tokens,
            "cache_creation_input_tokens": self.cache_creation_tokens,
        }

    def cost(self, model: str) -> float | None:
        try:
            return cost_usd(
                model,
                self.input_tokens,
                self.output_tokens,
                self.cache_read_tokens,
                self.cache_creation_tokens,
            )
        except KeyError:
            return None


def _record(stage: Stage | None, model: str, usage: Usage) -> None:
    st = stage or _current_stage.get()
    if st is None:
        return
    st.record_usage(
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        cost=usage.cost(model),
    )


# -------------------------------------------------------------------- cassettes


def request_key(kind: str, request: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"kind": kind, **request}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class CassetteStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def path(self, kind: str, key: str) -> Path:
        return self.directory / f"{kind}-{key}.json"

    def load(self, kind: str, key: str) -> dict[str, Any] | None:
        p = self.path(kind, key)
        if not p.exists():
            return None
        data: dict[str, Any] = json.loads(p.read_text())
        return data

    def save(self, kind: str, key: str, request: dict[str, Any], response: dict[str, Any]) -> Path:
        """Atomic write (temp file in the same dir + ``os.replace``)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        p = self.path(kind, key)
        payload = {"key": key, "kind": kind, "request": request, "response": response}
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=f".{p.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return p


# --------------------------------------------------------------------- streams


class TextStream:
    """Async iterator of text chunks; after exhaustion exposes text/usage/ttft."""

    def __init__(self, gen: AsyncIterator[str]):
        self._gen = gen
        self.text = ""
        self.usage = Usage()
        self.stop_reason: str | None = None
        self.ttft_ms: float | None = None
        self._t0 = time.perf_counter()

    def __aiter__(self) -> TextStream:
        return self

    async def __anext__(self) -> str:
        chunk = await self._gen.__anext__()
        if self.ttft_ms is None:
            self.ttft_ms = round((time.perf_counter() - self._t0) * 1000, 2)
        self.text += chunk
        return chunk

    async def aclose(self) -> None:
        """Close the underlying request (e.g. the client disconnected mid-reply)."""
        aclose = getattr(self._gen, "aclose", None)
        if aclose is not None:
            await aclose()


def _refusal_category(msg: Any) -> str | None:
    details = getattr(msg, "stop_details", None)
    return getattr(details, "category", None) if details is not None else None


def _first_text(msg: Any) -> str:
    return next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")


# ---------------------------------------------------------------------- client


@dataclass
class LLMClient:
    """Wraps ``anthropic.AsyncAnthropic`` with record/replay and usage accounting."""

    mode: LLMMode = "replay"
    cassette_dir: Path = field(default_factory=lambda: DEFAULT_CASSETTE_DIR)
    anthropic_client: Any = None  # AsyncAnthropic or a test double with .messages
    replay_chunk_delay_s: float = 0.0

    def __post_init__(self) -> None:
        self.store = CassetteStore(Path(self.cassette_dir))

    @classmethod
    def from_settings(cls) -> LLMClient:
        s = get_settings()
        return cls(mode=s.LLM_MODE, cassette_dir=s.LLM_CASSETTE_DIR or DEFAULT_CASSETTE_DIR)

    # -- plumbing

    def _api(self) -> Any:
        if self.mode == "replay":
            raise RuntimeError("LLMClient in replay mode must not call the API")
        if self.anthropic_client is None:
            key = get_settings().ANTHROPIC_API_KEY
            self.anthropic_client = anthropic.AsyncAnthropic(
                api_key=key.get_secret_value() if key else None
            )
        return self.anthropic_client

    @staticmethod
    def system_blocks(system: str) -> list[dict[str, Any]]:
        """Stable system prompt as one cached block (prefix caching, SPEC §12)."""
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    # -- streaming text

    def stream_text(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        *,
        effort: Effort,
        max_tokens: int,
        stage: Stage | None = None,
    ) -> TextStream:
        request = {
            "model": model,
            "system": system,
            "messages": messages,
            "schema": None,
            "params": {"effort": effort, "max_tokens": max_tokens},
        }
        key = request_key("stream", request)
        holder: list[TextStream] = []

        async def gen() -> AsyncIterator[str]:
            ts = holder[0]
            if self.mode == "replay":
                cas = self.store.load("stream", key)
                if cas is None:
                    raise ReplayMissError(key, "stream", model, self.store.directory)
                resp = cas["response"]
                for chunk in resp["chunks"]:  # partial chunks first, like live
                    await asyncio.sleep(self.replay_chunk_delay_s)
                    yield chunk
                ts.stop_reason = resp.get("stop_reason")
                ts.usage = Usage.from_dict(resp.get("usage", {}))
                _record(stage, model, ts.usage)
                if ts.stop_reason == "refusal":
                    raise LLMRefusalError(resp.get("refusal_category"))
                return

            chunks: list[str] = []
            try:
                async with self._api().messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=self.system_blocks(system),
                    messages=messages,
                    output_config={"effort": effort},
                ) as s:
                    async for text in s.text_stream:
                        chunks.append(text)
                        yield text
                    final = await s.get_final_message()
            except anthropic.APIError as exc:
                raise _translate(exc) from exc
            ts.stop_reason = final.stop_reason
            ts.usage = Usage.from_api(final.usage)
            _record(stage, model, ts.usage)
            category = _refusal_category(final)
            if self.mode == "record":
                self.store.save(
                    "stream",
                    key,
                    request,
                    {
                        "chunks": chunks,
                        "stop_reason": final.stop_reason,
                        "refusal_category": category,
                        "usage": ts.usage.to_dict(),
                    },
                )
            if final.stop_reason == "refusal":
                raise LLMRefusalError(category)

        ts = TextStream(gen())
        holder.append(ts)
        return ts

    # -- structured output

    @overload
    async def parse(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        output: type[M],
        *,
        effort: Effort,
        max_tokens: int = ...,
        stage: Stage | None = ...,
    ) -> M: ...

    @overload
    async def parse(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        output: dict[str, Any],
        *,
        effort: Effort,
        max_tokens: int = ...,
        stage: Stage | None = ...,
    ) -> dict[str, Any]: ...

    async def parse(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        output: type[BaseModel] | dict[str, Any],
        *,
        effort: Effort,
        max_tokens: int = 16000,
        stage: Stage | None = None,
    ) -> BaseModel | dict[str, Any]:
        """Structured output. ``output`` is a Pydantic model class or a JSON schema dict."""
        schema = wire_schema(output)
        request = {
            "model": model,
            "system": system,
            "messages": messages,
            "schema": schema,
            "params": {"effort": effort, "max_tokens": max_tokens},
        }
        key = request_key("parse", request)

        if self.mode == "replay":
            cas = self.store.load("parse", key)
            if cas is None:
                raise ReplayMissError(key, "parse", model, self.store.directory)
            resp = cas["response"]
            stop_reason, text = resp.get("stop_reason"), resp.get("text", "")
            usage = Usage.from_dict(resp.get("usage", {}))
            category = resp.get("refusal_category")
        else:
            try:
                async with self._api().messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=self.system_blocks(system),
                    messages=messages,
                    output_config={
                        "effort": effort,
                        "format": {"type": "json_schema", "schema": schema},
                    },
                ) as s:
                    msg = await s.get_final_message()
            except anthropic.APIError as exc:
                raise _translate(exc) from exc
            stop_reason = msg.stop_reason
            text = _first_text(msg)
            usage = Usage.from_api(msg.usage)
            category = _refusal_category(msg)
            if self.mode == "record":
                self.store.save(
                    "parse",
                    key,
                    request,
                    {
                        "text": text,
                        "stop_reason": stop_reason,
                        "refusal_category": category,
                        "usage": usage.to_dict(),
                    },
                )

        _record(stage, model, usage)
        if stop_reason == "refusal":
            raise LLMRefusalError(category)
        if stop_reason == "max_tokens":
            raise LLMOutputError("structured output truncated (stop_reason=max_tokens)")
        try:
            if isinstance(output, type):
                return output.model_validate_json(text)
            data: dict[str, Any] = json.loads(text)
            return data
        except (ValidationError, ValueError) as exc:
            raise LLMOutputError(f"structured output failed validation: {exc}") from exc


def wire_schema(output: type[BaseModel] | dict[str, Any]) -> dict[str, Any]:
    """The exact JSON schema sent as ``output_config.format.schema``."""
    return anthropic.transform_schema(output)


# Structured-outputs complexity limits (per request, across the whole schema).
MAX_OPTIONAL_PARAMS = 24
MAX_UNION_PARAMS = 16


@dataclass(frozen=True)
class SchemaComplexity:
    optional: int  # object properties not listed in ``required``
    unions: int  # nodes using anyOf/oneOf or a list-valued ``type`` (incl. nullable)


def schema_complexity(schema: dict[str, Any]) -> SchemaComplexity:
    """Walk a (transformed) JSON schema, including ``$defs``, and count limit-relevant
    constructs. ``$defs`` are counted once each, as the API compiles them once."""
    optional = unions = 0

    def walk(node: Any) -> None:
        nonlocal optional, unions
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        if "anyOf" in node or "oneOf" in node or isinstance(node.get("type"), list):
            unions += 1
        props = node.get("properties")
        if isinstance(props, dict):
            required = set(node.get("required") or [])
            optional += sum(1 for k in props if k not in required)
            for v in props.values():
                walk(v)
        for k in ("items", "anyOf", "oneOf", "allOf"):
            if k in node:
                walk(node[k])
        for v in (node.get("$defs") or {}).values():
            walk(v)

    walk(schema)
    return SchemaComplexity(optional=optional, unions=unions)


_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """FastAPI dependency / process-wide default client (override in tests)."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient.from_settings()
    return _default_client
