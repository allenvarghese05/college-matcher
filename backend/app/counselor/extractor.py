"""Per-turn profile extractor (Sonnet, structured output ``schemas.ExtractionResult``).

The model returns a ``ProfileDelta`` (only fields the latest student message states)
plus ``next_topic``. Deterministic guards then drop anything the contract forbids:

* updates whose ``quote`` is not an exact span of the latest message (no paraphrase,
  no carrying over earlier turns);
* ``regions`` values outside the fixed vocabulary / USPS codes;
* ``riasec`` (comes from the quiz, never from chat).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.llm import Effort, LLMClient
from app.core.logging import Stage, get_logger
from app.counselor.context import (
    REGION_VOCAB,
    US_STATES,
    HistoryTurn,
    profile_json,
    render_transcript,
)
from app.counselor.prompts import load_prompt
from app.schemas import ExtractionResult, ProfileDelta, StudentProfile, Update

log = get_logger(__name__)


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in(quote: str, message: str) -> bool:
    q = _norm(quote).strip(" .,!?;:\"'")
    return bool(q) and q in _norm(message)


def build_user_message(profile: StudentProfile, context: list[HistoryTurn], latest: str) -> str:
    return (
        "<current_profile>\n"
        f"{profile_json(profile)}\n"
        "</current_profile>\n\n"
        "<recent_conversation>\n"
        f"{render_transcript(context) or '(start of conversation)'}\n"
        "</recent_conversation>\n\n"
        "<latest_student_message>\n"
        f"{latest}\n"
        "</latest_student_message>\n\n"
        "Extract only what the latest student message states, then choose next_topic."
    )


def sanitize(delta: ProfileDelta, latest: str) -> tuple[ProfileDelta, list[str]]:
    """Return a cleaned delta and the names of dropped fields (for metrics/logs)."""
    data = delta.model_copy(deep=True)
    dropped: list[str] = []
    for name in ProfileDelta.model_fields:
        upd: Update | None = getattr(data, name)  # type: ignore[type-arg]
        if upd is None:
            continue
        if name == "riasec" or not quote_in(upd.quote, latest):
            setattr(data, name, None)
            dropped.append(name)
            continue
        if name == "regions":
            kept = []
            for r in upd.value:
                r_clean = r.strip()
                if r_clean.lower() in REGION_VOCAB:
                    kept.append(r_clean.lower())
                elif r_clean.upper() in US_STATES and len(r_clean) == 2:
                    kept.append(r_clean.upper())
            if kept:
                upd.value = kept
            else:
                setattr(data, name, None)
                dropped.append(name)
        elif name == "home_state":
            code = upd.value.strip().upper()
            if code in US_STATES:
                upd.value = code
            else:
                setattr(data, name, None)
                dropped.append(name)
    return data, dropped


@dataclass
class Extractor:
    llm: LLMClient
    model: str = field(default_factory=lambda: get_settings().MODEL_FAST)
    effort: Effort = "medium"
    max_tokens: int = 8000
    context_turns: int = 6

    async def extract(
        self,
        history: list[HistoryTurn],
        latest: str,
        profile: StudentProfile,
        *,
        stage: Stage | None = None,
    ) -> ExtractionResult:
        """``history`` = turns before the latest student message (oldest first)."""
        context = history[-self.context_turns :]
        prompt = load_prompt("extractor")
        result = await self.llm.parse(
            self.model,
            prompt.text,
            [{"role": "user", "content": build_user_message(profile, context, latest)}],
            ExtractionResult,
            effort=self.effort,
            max_tokens=self.max_tokens,
            stage=stage,
        )
        delta, dropped = sanitize(result.delta, latest)
        if stage is not None:
            stage.set(prompt=prompt.id, dropped_fields=dropped, next_topic=result.next_topic)
        if dropped:
            log.info("extract_dropped_fields", fields=dropped)
        return ExtractionResult(delta=delta, next_topic=result.next_topic)
