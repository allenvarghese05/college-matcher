"""A deterministic stand-in for the Anthropic API, used to BUILD eval cassettes offline.

``run.py --mode record --transport fake`` plays personas through the real orchestrator
with this object as the ``anthropic_client`` of :class:`~app.core.llm.LLMClient`. Every
request the app makes is answered heuristically and saved as a normal cassette, so the
same run can then be replayed (``--mode replay``) with no network and no key. This is
how ``backend/tests/cassettes/evals/`` (the CI smoke) is produced.

It is NOT a model and its outputs are NOT a quality signal:

* **counselor reply** — asks the next topic in a fixed intake order (one question);
* **extraction** — parses the scripted simulator's sentence templates
  (:func:`evals.simulator.scripted_answer`) with regexes, quoting the exact span;
* **recommendation** — the first ``k`` candidates in retrieval order, citing their
  DB facts formatted exactly as the groundedness checker formats them.

Token usage is a rough ``len/4`` estimate so cost accounting and the budget guard have
non-zero numbers to work with.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from app.counselor.groundedness import format_fact
from evals.topics import asked_topics

# Fallback order without a planner note (and the extractor's logged next_topic). The
# planner's combined classes/strengths question is persisted as "strengths".
INTAKE_ORDER: tuple[str, ...] = (
    "interests",
    "dream_without_money",
    "strengths",
    "activities",
    "location",
    "size_setting",
    "priorities",
    "money",
    "academics",
    "work_values",
)

COMBINED_QUESTION = "Which classes do you like most, and what do you feel you're good at?"
QUESTIONS: dict[str, str] = {
    "follow_up": "Oh, that's cool. What is it about that that you enjoy most?",
    "interests": "Nice to meet you! What do you like doing in your free time?",
    "dream_without_money": (
        "If money weren't involved and you weren't getting paid, what would you happily do "
        "for the rest of your life?"
    ),
    "academics": "Totally optional, but do you know your GPA, and have you taken the SAT or ACT?",
    "money": "Roughly what income range is your family in, and how much could they pay per year?",
    "location": "What state do you live in, and how far from home would you go?",
    "size_setting": (
        "Do you picture a small, medium or large school, in a city, suburb, town or rural area?"
    ),
    # one combined question (planner key "strengths_subjects", persisted as "strengths")
    "strengths": COMBINED_QUESTION,
    "strengths_subjects": COMBINED_QUESTION,
    "favorite_subjects": "Which classes or subjects do you like most?",
    "activities": "What clubs, sports or teams are you part of outside of school?",
    "work_values": "In a future job, what would you want, like stability, freedom or recognition?",
    "priorities": "When you picture choosing a college, what's most important to you overall?",
}
CLOSING = (
    "Thanks, that's really helpful. You can ask to see your college matches whenever you like."
)

_ITEMS = r"(?P<v>[^.]+)"
# (field, regex, kind) — kinds: items | text | number | activities | const:<value>
TEMPLATES: list[tuple[str, str, str]] = [
    ("interests", rf"i'm into {_ITEMS}", "items"),
    ("intended_majors", rf"i'm thinking of majoring in {_ITEMS}", "items"),
    ("dream_without_money", r"my dream: (?P<v>.+?)(?=, honestly\b)", "text"),
    ("strengths", rf"i'm good at {_ITEMS}", "items"),
    ("favorite_subjects", rf"my favorite classes are {_ITEMS}", "items"),
    ("activities", rf"outside school i do {_ITEMS}", "activities"),
    ("work_values", rf"in a job i care about {_ITEMS}", "items"),
    ("gpa", r"my gpa is (?P<v>\d(?:\.\d+)?)", "number"),
    ("sat", r"i got (?P<v>\d+) on the sat", "number"),
    ("act", r"i got (?P<v>\d+) on the act", "number"),
    ("income_bracket", r"my family makes (?P<v>[\d\-k+]+) a year", "text"),
    ("budget_cap", r"they can pay about \$(?P<v>[\d,]+) a year", "number"),
    ("home_state", r"i live in (?P<v>[a-z .]+?)(?=\.(?:\s|$))", "text"),
    ("home_zip", r"zip is (?P<v>\d{5})", "text"),
    ("max_distance_miles", r"i'd go up to (?P<v>\d+) miles from home", "number"),
    ("regions", rf"i'd like to go to school in {_ITEMS}", "items"),
    ("size_pref", r"a (?P<v>small|medium|large) school is good", "text"),
    ("size_pref", r"size doesn't matter", "const:any"),
    ("setting_pref", r"(?P<v>city|suburb|town|rural) would be nice", "text"),
    ("setting_pref", r"any setting is fine", "const:any"),
    ("priorities", rf"what matters most is {_ITEMS}", "items"),
]
_COMPILED = [(f, re.compile(p), k) for f, p, k in TEMPLATES]


def _tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", text, re.S)
    return m.group(1) if m else ""


def _update(field: str, quote: str, **values: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "field": field,
        "text": "",
        "number": 0,
        "items": [],
        "activities": [],
        "confidence": 0.9,
        "quote": quote,
    }
    base.update(values)
    return base


def fake_extraction(latest: str, recent: str = "") -> dict[str, Any]:
    """ExtractionWire JSON for a scripted-simulator message."""
    updates: list[dict[str, Any]] = []
    for field, rx, kind in _COMPILED:
        m = rx.search(latest)
        if not m:
            continue
        quote = m.group(0)
        if kind.startswith("const:"):
            updates.append(_update(field, quote, text=kind.split(":", 1)[1]))
            continue
        raw = m.group("v").strip()
        if kind == "items":
            updates.append(_update(field, quote, items=[x.strip() for x in raw.split(",")]))
        elif kind == "activities":
            acts = [
                {"name": x.strip(), "role": "", "years": 0, "hours_per_week": 0}
                for x in raw.split(",")
                if x.strip()
            ]
            updates.append(_update(field, quote, activities=acts))
        elif kind == "number":
            updates.append(_update(field, quote, number=float(raw.replace(",", ""))))
        else:
            updates.append(_update(field, quote, text=raw))
    last_counselor = ""
    for line in recent.splitlines():
        if line.startswith("counselor: "):
            last_counselor = line[len("counselor: ") :]
    asked = [t for t in INTAKE_ORDER if t in asked_topics(last_counselor)]
    nxt = "interests"
    if asked:
        i = INTAKE_ORDER.index(asked[-1]) + 1
        nxt = INTAKE_ORDER[i] if i < len(INTAKE_ORDER) else "ready_to_recommend"
    return {"updates": updates, "next_topic": nxt}


LOCATION_PREF_QUESTION = (
    "How far from home would you go, or is there a part of the country you'd like?"
)
STATE_QUESTION = "What state do you live in?"
_NOTE_TOPIC = re.compile(r"^Suggested next topic: (?P<t>[a-z_]+)(?: \((?P<d>[^)]*)\))?", re.M)


def fake_reply(messages: list[dict[str, Any]]) -> str:
    """Follows the planner's note: asks the suggested topic (one question), and the
    closing line when the note says "Offer matches now: yes". Without a planner note it
    falls back to a fixed INTAKE_ORDER."""
    note = messages[-1]["content"] if messages and messages[-1]["role"] == "system" else ""
    ready = "Ready for recommendations: yes" in note
    n = sum(1 for m in messages if m["role"] == "assistant")
    m = _NOTE_TOPIC.search(note)
    if m:
        prefix = "Got it, thanks. " if n else ""
        topic, desc = m.group("t"), m.group("d") or ""
        if "Offer matches now: yes" in note or topic == "ready_to_recommend":
            return CLOSING if ready else prefix + QUESTIONS["interests"]
        if topic == "location":
            return prefix + (LOCATION_PREF_QUESTION if "how far" in desc else STATE_QUESTION)
        return prefix + QUESTIONS.get(topic, QUESTIONS["interests"])
    if n < len(INTAKE_ORDER):
        return ("Got it, thanks. " if n else "") + QUESTIONS[INTAKE_ORDER[n]]
    return CLOSING if ready else QUESTIONS["interests"]


_DIGITS = re.compile(r"\d")


def fake_recommendations(user: str) -> dict[str, Any]:
    cands = json.loads(_tag(user, "candidates") or "[]")
    m = re.search(r"Choose the best (\d+)", user)
    k = int(m.group(1)) if m else 10
    recs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for c in cands:
        if c["unitid"] in seen:
            continue
        seen.add(c["unitid"])
        claims = []
        for f in ("net_price", "admission_rate", "completion_rate", "program_median_earnings"):
            v = (c.get("facts") or {}).get(f)
            shown = format_fact(f, v)
            if shown is not None:
                claims.append({"field": f, "value": shown})
        major = _DIGITS.sub("", str(c.get("major") or "a program")).strip() or "a program"
        recs.append(
            {
                "unitid": c["unitid"],
                "cip4": c.get("cip4") or "",
                "reasons": [f"Offers {major}, which lines up with what you described."],
                "claims": claims,
            }
        )
        if len(recs) >= k:
            break
    return {"recommendations": recs}


def _usage(request: dict[str, Any], text: str) -> SimpleNamespace:
    size = len(json.dumps(request, default=str))
    return SimpleNamespace(
        input_tokens=max(1, size // 4),
        output_tokens=max(1, len(text) // 4),
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


class _CM:
    def __init__(self, kwargs: dict[str, Any]):
        self.kwargs = kwargs
        fmt = (kwargs.get("output_config") or {}).get("format")
        msgs = kwargs.get("messages") or []
        user = msgs[-1]["content"] if msgs else ""
        if fmt is None:
            self.text = fake_reply(msgs)
        elif fmt["schema"].get("title") == "ExtractionWire" or "updates" in json.dumps(
            fmt["schema"].get("properties", {})
        ):
            wire = fake_extraction(
                _tag(user, "latest_student_message"), _tag(user, "recent_conversation")
            )
            self.text = json.dumps(wire)
        else:
            self.text = json.dumps(fake_recommendations(user))

    async def __aenter__(self) -> _CM:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            words = self.text.split(" ")
            for i, w in enumerate(words):
                await asyncio.sleep(0)
                yield w if i == len(words) - 1 else w + " "

        return gen()

    async def get_final_message(self) -> Any:
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            stop_reason="end_turn",
            stop_details=None,
            usage=_usage(self.kwargs, self.text),
        )


class _Messages:
    def __init__(self, owner: FakeCounselorAnthropic):
        self.owner = owner

    def stream(self, **kwargs: Any) -> _CM:
        self.owner.calls += 1
        return _CM(kwargs)


class FakeCounselorAnthropic:
    """Duck-typed ``anthropic.AsyncAnthropic`` (only ``messages.stream`` is used)."""

    def __init__(self) -> None:
        self.calls = 0
        self.messages = _Messages(self)
