"""Simulated student: plays one persona against the counselor (SPEC §10).

The simulator sees only ``summary``, ``hidden_profile``, ``style``, ``reveal`` and
``quirks`` — ``meta`` is stripped in :func:`evals.common.persona_from_doc` and never
rendered. The hidden profile is rendered as plain-English private facts, never as YAML.

Backends (``make_simulator(kind, ...)``):

``ollama``   local model over ``http://localhost:11434/api/chat`` (default
             ``qwen2.5:7b-instruct``; free). Exchanges are cached as
             ``ollama-<hash>.json`` cassettes next to the Claude cassettes, so
             ``--mode replay`` reproduces a recorded run with no Ollama server.
``claude``   Sonnet through the app's :class:`~app.core.llm.LLMClient` (records /
             replays like every other Claude call; its cost counts toward the budget).
``scripted`` deterministic templates (tests, CI, cassette building). Answers exactly
             the topics the counselor asked about (see :mod:`evals.topics`).

The **leak guard** (:class:`LeakGuard`) checks every student message: which hidden
facts it reveals, which of those the counselor had not asked about, whether it leaked
two or more unasked facts at once (``multi_leak``), and whether it broke character
(mentions being an AI / a simulation, field names, YAML-looking lines). Events are
logged and counted in the run summary; they don't stop the run.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.core.llm import LLMClient, ReplayMissError  # noqa: E402
from app.core.logging import Stage, get_logger  # noqa: E402
from app.counselor.context import STATE_NAMES  # noqa: E402
from evals.common import Persona
from evals.topics import FIELD_TOPIC, asked_topics

log = get_logger(__name__)

# The web app's opening line (web/src/mocks/profile.ts); the student answers it first.
COUNSELOR_GREETING = (
    "Hi. I'm here to help you think through college, at whatever pace feels right. "
    "What's on your mind about it right now?"
)
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
OLLAMA_URL = "http://localhost:11434"
CODE_TO_STATE: dict[str, str] = {}
for _name, _code in STATE_NAMES.items():  # first name per code ("district of columbia")
    CODE_TO_STATE.setdefault(_code, _name)

# ------------------------------------------------------------------ spoken numbers

_UNITS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
}
_TENS = {
    w: 10 * i
    for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split())
    if w != "_"
}
_NUMWORD = set(_UNITS) | set(_TENS) | {"hundred", "thousand", "point", "oh", "k", "grand"}


def _words_value(words: list[str]) -> float | None:
    """'three point six' -> 3.6, 'thirteen ten' -> 1310, 'twenty two thousand' -> 22000."""
    if not words:
        return None
    if "point" in words:
        i = words.index("point")
        whole = _words_value(words[:i]) if i else 0.0
        frac = "".join(str(_UNITS[w]) for w in words[i + 1 :] if w in _UNITS and _UNITS[w] < 10)
        if whole is None or not frac:
            return whole
        return float(f"{int(whole)}.{frac}")
    # year-style pairs: "thirteen ten", "eleven eighty", "fourteen fifty"
    if len(words) in (2, 3) and words[0] in _UNITS and 10 <= _UNITS[words[0]] <= 19:
        rest = _words_value(words[1:])
        if rest is not None and 0 < rest < 100 and words[1] not in ("hundred", "thousand"):
            return _UNITS[words[0]] * 100 + rest
    total, cur = 0.0, 0.0
    for w in words:
        if w in _UNITS:
            cur += _UNITS[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w in ("thousand", "k", "grand"):
            total += (cur or 1) * 1000
            cur = 0
        elif w == "oh":
            continue
    return total + cur


def numbers_in(text: str) -> list[float]:
    """Numbers written as digits ('3.6', '1,310', '$22k', '50 thousand') or words."""
    low = text.lower().replace("–", "-")
    out: list[float] = []
    for m in re.finditer(r"\$?(\d[\d,]*(?:\.\d+)?)\s*(k|grand|thousand)?\b", low):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            v *= 1000
        out.append(v)
    run: list[str] = []
    for tok in re.split(r"[\s\-,]+", low) + [""]:
        t = tok.strip(".!?;:'\"()")
        if t in _NUMWORD and not (t in ("k", "grand", "point", "oh") and not run):
            run.append(t)
            continue
        if run:
            v = _words_value(run)
            if v is not None and any(
                w in _UNITS or w in _TENS or w in ("hundred", "thousand") for w in run
            ):
                out.append(v)
            run = []
    return out


# ---------------------------------------------------------------------- leak guard

_STOP = set(
    "a an the and or of to in on for with my i me at by from about stuff things thing "
    "people every day really like just being be do get make some all".split()
)
_CHARACTER_BREAK = [
    re.compile(p, re.I | re.M)
    for p in (
        r"\bas an ai\b",
        r"\blanguage model\b",
        r"\bsimulat",
        r"\bpersona\b",
        r"\bhidden[_ ]profile\b",
        r"\b(budget_cap|income_bracket|home_zip|home_state|max_distance_miles|"
        r"dream_without_money|intended_majors|favorite_subjects|work_values|size_pref|"
        r"setting_pref)\b",
        r"\briasec\b",
        r"^\s*-?\s*[a-z_]{3,}:\s+\S",
        r"\bi('m| am) (an? )?(ai|assistant|chatbot)\b",
        r"\bhow can i (help|assist) you\b",
        r"\b(private facts|these instructions|my instructions)\b",
    )
]


def _stem(w: str) -> str:
    w = w.lower().strip(".,!?;:'\"()")
    for suf in ("ing", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _content(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-zA-Z']+", text) if w.lower() not in _STOP}


def _mentions(item: str, msg_stems: set[str]) -> bool:
    words = [w for w in _content(item) if len(w) >= 3]
    if not words:
        return False
    hit = sum(1 for w in words if w in msg_stems)
    return hit / len(words) >= 0.6


@dataclass
class GuardResult:
    revealed: list[str] = field(default_factory=list)
    unasked: list[str] = field(default_factory=list)
    multi_leak: bool = False
    character_break: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revealed": self.revealed,
            "unasked": self.unasked,
            "multi_leak": self.multi_leak,
            "character_break": self.character_break,
        }


class LeakGuard:
    """Detect hidden facts in a student message and flag unasked reveals / breaks."""

    def __init__(self, hidden: dict[str, Any]):
        self.hidden = hidden

    def revealed(self, msg: str, exclude_stems: frozenset[str] = frozenset()) -> list[str]:
        """Hidden fields whose value appears in ``msg``. Words in ``exclude_stems`` are
        ignored for the text fields (values shared with an asked-about field)."""
        h = self.hidden
        nums = numbers_in(msg)
        low = msg.lower()
        stems = _content(msg) - exclude_stems
        out: list[str] = []

        def near(target: float, tol: float, lo: float = float("-inf")) -> bool:
            return any(abs(n - target) <= tol and n >= lo for n in nums)

        if h.get("home_state"):
            code = str(h["home_state"]).upper()
            name = CODE_TO_STATE.get(code, "")
            amb = {"OK", "IN", "ME", "OR", "HI", "AL", "PA", "MA", "DE", "CO", "OH", "LA", "ID"}
            if (name and re.search(rf"\b{re.escape(name)}\b", low)) or (
                code not in amb and re.search(rf"\b{code}\b", msg)
            ):
                out.append("home_state")
        if h.get("home_zip") and re.search(rf"\b{h['home_zip']}\b", msg):
            out.append("home_zip")
        if h.get("gpa") is not None and near(float(h["gpa"]), 0.051):
            out.append("gpa")
        if h.get("sat") is not None and near(float(h["sat"]), 10.1):
            out.append("sat")
        if h.get("act") is not None and re.search(r"\bact\b", low) and near(float(h["act"]), 0):
            out.append("act")
        if h.get("budget_cap") and near(float(h["budget_cap"]), 0.1 * float(h["budget_cap"]), 500):
            out.append("budget_cap")
        if h.get("max_distance_miles") and re.search(r"\b(mile|hour)", low):
            d = float(h["max_distance_miles"])
            if near(d, 0.1 * d):
                out.append("max_distance_miles")
        for f in ("interests", "strengths", "favorite_subjects", "intended_majors"):
            if any(_mentions(str(x), stems) for x in h.get(f) or []):
                out.append(f)
        if any(_mentions(str(a.get("name", "")), stems) for a in h.get("activities") or []):
            out.append("activities")
        dream = h.get("dream_without_money")
        if dream and len([w for w in _content(dream) if len(w) >= 3]) >= 2:
            if _mentions(str(dream), stems):
                out.append("dream_without_money")
        return out

    def check(self, msg: str, counselor_msg: str | None) -> GuardResult:
        revealed = self.revealed(msg)
        allowed = (
            asked_topics(counselor_msg, questions_only=False)
            if counselor_msg is not None
            else set()
        )
        # Words that belong to an asked-about field's value don't count as leaking another
        # field that shares them (e.g. "drawing" is both an interest and a strength).
        shared: set[str] = set()
        for f, topic in FIELD_TOPIC.items():
            if topic in allowed and f in self.hidden:
                shared |= _content(json.dumps(self.hidden[f]))
        strict = set(self.revealed(msg, frozenset(shared)))
        unasked = [f for f in revealed if FIELD_TOPIC.get(f) not in allowed and f in strict]
        # several fields of one topic answered together count as one fact
        unasked_topics = {FIELD_TOPIC.get(f) for f in unasked}
        breaks = [p.pattern for p in _CHARACTER_BREAK if p.search(msg)]
        res = GuardResult(revealed, unasked, len(unasked_topics) >= 2, breaks)
        if res.multi_leak or res.character_break:
            log.warning(
                "sim_guard",
                multi_leak=res.multi_leak,
                unasked=unasked,
                character_break=bool(breaks),
            )
        return res


# --------------------------------------------------------------- persona rendering


def _join(items: list[Any]) -> str:
    return ", ".join(str(x) for x in items)


def _region_words(regions: list[str]) -> str:
    words = []
    for r in regions:
        if r == "out_of_state":
            words.append("anywhere outside your home state")
        elif len(r) == 2:
            words.append(CODE_TO_STATE.get(r.upper(), r).title())
        else:
            words.append(r.replace("_", " "))
    return ", ".join(words)


def render_facts(hidden: dict[str, Any]) -> list[str]:
    """Plain-English private facts (no field names, no YAML, no RIASEC)."""
    h = hidden
    lines: list[str] = []
    if h.get("home_state"):
        st = CODE_TO_STATE.get(str(h["home_state"]).upper(), h["home_state"]).title()
        zip_part = f" (zip code {h['home_zip']})" if h.get("home_zip") else ""
        lines.append(f"You live in {st}{zip_part}.")
    lines.append(
        f"Your unweighted GPA is {h['gpa']}." if "gpa" in h else "You don't have a GPA to share."
    )
    tests = []
    if "sat" in h:
        tests.append(f"you scored {h['sat']} on the SAT")
    if "act" in h:
        tests.append(f"you scored {h['act']} on the ACT")
    lines.append(
        ("Tests: " + " and ".join(tests) + ".") if tests else "You haven't taken the SAT or ACT."
    )
    if h.get("income_bracket"):
        lines.append(f"Your family's income is roughly ${h['income_bracket']} a year.")
    if h.get("budget_cap"):
        lines.append(f"Your family could pay about ${int(h['budget_cap']):,} a year for college.")
    else:
        lines.append("You don't know how much your family could pay per year.")
    if h.get("interests"):
        lines.append(f"Things you're into: {_join(h['interests'])}.")
    if h.get("dream_without_money"):
        lines.append(f"If money didn't matter, you'd want to: {h['dream_without_money']}.")
    if "intended_majors" in h:
        im = h["intended_majors"]
        lines.append(
            f"Majors you're considering: {_join(im)}." if im else "You have no major in mind yet."
        )
    if h.get("strengths"):
        lines.append(f"You're good at: {_join(h['strengths'])}.")
    if h.get("favorite_subjects"):
        lines.append(f"Favorite subjects: {_join(h['favorite_subjects'])}.")
    acts = []
    for a in h.get("activities") or []:
        bits = [b for b in (a.get("role"), f"{a['years']} years" if a.get("years") else None) if b]
        acts.append(a["name"] + (f" ({', '.join(bits)})" if bits else ""))
    if acts:
        lines.append(f"Activities: {'; '.join(acts)}.")
    if h.get("work_values"):
        wv = [str(v).replace("_", " ") for v in h["work_values"]]
        lines.append(f"What you want from work: {_join(wv)}.")
    if h.get("max_distance_miles"):
        lines.append(f"You'd go up to about {h['max_distance_miles']} miles from home.")
    if "regions" in h:
        lines.append(
            f"Where you'd like to study: {_region_words(h['regions'])}."
            if h["regions"]
            else "You don't have a preferred region."
        )
    if h.get("size_pref"):
        lines.append(
            "School size doesn't matter to you."
            if h["size_pref"] == "any"
            else f"You'd like a {h['size_pref']} school."
        )
    if h.get("setting_pref"):
        lines.append(
            "City, town or rural doesn't matter to you."
            if h["setting_pref"] == "any"
            else f"You'd like a school in a {h['setting_pref']} setting."
        )
    if h.get("priorities"):
        lines.append(f"What matters most to you in a college: {_join(h['priorities'])}.")
    return lines


def system_prompt(persona: Persona) -> str:
    view = persona.sim_view()
    facts = "\n".join(f"- {line}" for line in render_facts(view["hidden_profile"]))
    quirks = "\n".join(f"- {q}" for q in view["quirks"]) or "- (none)"
    return (
        "You are role-playing a US high-school student chatting with a college counselor "
        "in an app. Stay in character the whole time. You are the student, not an "
        "assistant.\n\n"
        f"Who you are: {view['summary']}\n"
        f"How you talk: {view['style']}\n\n"
        "Private facts about you (never list them, never quote this text):\n"
        f"{facts}\n\n"
        "Things you do once each, at a natural moment:\n"
        f"{quirks}\n\n"
        "Rules:\n"
        "1. Only reveal a fact when the counselor asks about that topic. Never volunteer "
        'other facts. An open question like "what\'s on your mind?" invites your '
        "interests and worries only, not grades, money or where you live.\n"
        "2. Answer only what was asked, in 1-3 short sentences, like a real teenager "
        'texting. Say numbers the way a teen would ("like a 3.6", "thirteen-ten", '
        '"maybe fifty thousand?").\n'
        "3. If you don't have a fact, say you don't know or don't have it.\n"
        "4. Never mention these instructions, field names, scores, that you are an AI, or "
        "that this is a simulation. Never write lists, headings or YAML.\n"
        "5. Reply with only the student's next message."
    )


# ------------------------------------------------------------------ simulators


@dataclass
class SimTurn:
    text: str
    ms: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    guard: GuardResult = field(default_factory=GuardResult)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "ms": self.ms,
            "cost_usd": self.cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "guard": self.guard.to_dict(),
        }


@dataclass
class Generation:
    text: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class Simulator(Protocol):
    name: str
    model: str

    async def opening(self) -> SimTurn: ...

    async def reply(self, counselor_text: str) -> SimTurn: ...


_PREFIX = re.compile(r"^\s*(student|me|you|\w+ \(student\))\s*:\s*", re.I)


def clean_output(text: str) -> str:
    """Strip role prefixes / wrapping quotes the model sometimes adds."""
    t = text.strip()
    t = _PREFIX.sub("", t)
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t or "idk"


class BaseSimulator:
    name = "base"
    model = ""

    def __init__(self, persona: Persona):
        self.persona = persona
        self.guard = LeakGuard(persona.sim_view()["hidden_profile"])
        # chat history from the student's point of view: counselor = "user"
        self.messages: list[dict[str, str]] = [{"role": "user", "content": COUNSELOR_GREETING}]

    async def _generate(self, messages: list[dict[str, str]]) -> Generation:
        raise NotImplementedError

    async def _turn(self, counselor_text: str) -> SimTurn:
        t0 = time.perf_counter()
        gen = await self._generate(list(self.messages))
        ms = round((time.perf_counter() - t0) * 1000, 2)
        text = clean_output(gen.text)
        self.messages.append({"role": "assistant", "content": text})
        return SimTurn(
            text=text,
            ms=ms,
            cost_usd=gen.cost_usd,
            input_tokens=gen.input_tokens,
            output_tokens=gen.output_tokens,
            guard=self.guard.check(text, counselor_text),
        )

    async def opening(self) -> SimTurn:
        return await self._turn(COUNSELOR_GREETING)

    async def reply(self, counselor_text: str) -> SimTurn:
        self.messages.append({"role": "user", "content": counselor_text})
        return await self._turn(counselor_text)


# -- scripted ----------------------------------------------------------------------


def _items(xs: list[Any]) -> str:
    return ", ".join(str(x).replace("_", " ") for x in xs)


def scripted_answer(hidden: dict[str, Any], topic: str) -> str:
    """Deterministic teen-ish sentence(s) answering ``topic`` from the hidden profile.

    The templates are parsed back by :mod:`evals.fake_counselor` (cassette building).
    """
    h = hidden
    parts: list[str] = []
    if topic == "interests":
        parts.append(
            f"i'm into {_items(h['interests'])}." if h.get("interests") else "idk, nothing really."
        )
        if "intended_majors" in h:
            im = h["intended_majors"]
            parts.append(
                f"i'm thinking of majoring in {_items(im)}." if im else "no idea what to major in."
            )
    elif topic == "dream_without_money":
        d = h.get("dream_without_money")
        parts.append(f"my dream: {str(d).rstrip('.')}, honestly." if d else "honestly no idea.")
    elif topic == "strengths":
        s = h.get("strengths")
        parts.append(f"i'm good at {_items(s)}." if s else "not sure what i'm good at.")
    elif topic == "favorite_subjects":
        s = h.get("favorite_subjects")
        parts.append(f"my favorite classes are {_items(s)}." if s else "no favorite class.")
    elif topic == "activities":
        a = [x["name"] for x in h.get("activities") or []]
        parts.append(f"outside school i do {_items(a)}." if a else "i don't do much after school.")
    elif topic == "work_values":
        w = h.get("work_values")
        parts.append(f"in a job i care about {_items(w)}." if w else "idk what i want from a job.")
    elif topic == "academics":
        parts.append(f"my gpa is {h['gpa']}." if "gpa" in h else "i don't really have a gpa.")
        if "sat" in h:
            parts.append(f"i got {h['sat']} on the sat.")
        if "act" in h:
            parts.append(f"i got {h['act']} on the act.")
        if "sat" not in h and "act" not in h:
            parts.append("haven't taken the sat or act.")
    elif topic == "money":
        if h.get("income_bracket"):
            parts.append(f"my family makes {h['income_bracket']} a year.")
        parts.append(
            f"they can pay about ${int(h['budget_cap']):,} a year."
            if h.get("budget_cap")
            else "not sure how much they can pay."
        )
    elif topic == "location":
        if h.get("home_state"):
            st = CODE_TO_STATE.get(str(h["home_state"]).upper(), h["home_state"])
            parts.append(f"i live in {st}.")
        if h.get("home_zip"):
            parts.append(f"zip is {h['home_zip']}.")
        if h.get("max_distance_miles"):
            parts.append(f"i'd go up to {h['max_distance_miles']} miles from home.")
        if "regions" in h:
            r = h["regions"]
            parts.append(f"i'd like to go to school in {_items(r)}." if r else "anywhere is fine.")
    elif topic == "size_setting":
        size, setting = h.get("size_pref"), h.get("setting_pref")
        if size:
            parts.append("size doesn't matter." if size == "any" else f"a {size} school is good.")
        if setting:
            parts.append(
                "any setting is fine." if setting == "any" else f"{setting} would be nice."
            )
        if not parts:
            parts.append("no preference.")
    elif topic == "priorities":
        p = h.get("priorities")
        parts.append(f"what matters most is {_items(p)}." if p else "idk what matters most.")
    return " ".join(parts)


TOPIC_ORDER = (
    "interests",
    "dream_without_money",
    "strengths",
    "favorite_subjects",
    "activities",
    "work_values",
    "academics",
    "money",
    "location",
    "size_setting",
    "priorities",
)


class ScriptedSimulator(BaseSimulator):
    """Deterministic: answers each topic the last counselor message asked about."""

    name = "scripted"
    model = "scripted-v1"

    async def _generate(self, messages: list[dict[str, str]]) -> Generation:
        last = messages[-1]["content"] if messages and messages[-1]["role"] == "user" else ""
        hidden = self.persona.sim_view()["hidden_profile"]
        if last == COUNSELOR_GREETING:
            return Generation("hi. idk where to start with college stuff. " + scripted_answer(
                hidden, "interests"
            ))  # fmt: skip
        topics = asked_topics(last)
        if not topics:
            low = last.lower()
            if any(w in low for w in ("match", "recommend", "college list", "see your")):
                return Generation("cool, can i see my matches?")
            return Generation("ok")
        return Generation(" ".join(scripted_answer(hidden, t) for t in TOPIC_ORDER if t in topics))


# -- ollama ------------------------------------------------------------------------


class OllamaSimulator(BaseSimulator):
    """Local model via Ollama's /api/chat, with record/replay cassettes."""

    name = "ollama"

    def __init__(
        self,
        persona: Persona,
        *,
        mode: str = "live",
        cassette_dir: Path | None = None,
        model: str = DEFAULT_OLLAMA_MODEL,
        base_url: str = OLLAMA_URL,
        temperature: float = 0.7,
        seed: int = 7,
        timeout_s: float = 120.0,
        transport: Any = None,
    ):
        super().__init__(persona)
        self.mode = mode
        self.cassette_dir = cassette_dir
        self.model = model
        self.base_url = base_url
        self.options = {"temperature": temperature, "seed": seed, "num_predict": 200}
        self.timeout_s = timeout_s
        self.transport = transport
        self.system = system_prompt(persona)

    def _key(self, body: dict[str, Any]) -> str:
        canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canon.encode()).hexdigest()[:24]

    async def _generate(self, messages: list[dict[str, str]]) -> Generation:
        import httpx

        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system}, *messages],
            "stream": False,
            "options": self.options,
        }
        key = self._key(body)
        path = (self.cassette_dir / f"ollama-{key}.json") if self.cassette_dir else None
        if self.mode == "replay":
            if path is None or not path.exists():
                raise ReplayMissError(key, "ollama", self.model, self.cassette_dir or Path("."))
            return Generation(json.loads(path.read_text())["response"]["text"])
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_s, transport=self.transport
        ) as client:
            r = await client.post("/api/chat", json=body)
            r.raise_for_status()
            data = r.json()
        text = str((data.get("message") or {}).get("content") or "")
        gen = Generation(
            text,
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )
        if self.mode == "record" and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"key": key, "kind": "ollama", "request": body, "response": {"text": text}},
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n"
            )
        return gen


# -- claude ------------------------------------------------------------------------


class ClaudeSimulator(BaseSimulator):
    """Sonnet plays the student through LLMClient (record/replay, cost accounted)."""

    name = "claude"

    def __init__(self, persona: Persona, llm: LLMClient, model: str | None = None):
        super().__init__(persona)
        from app.core.config import get_settings

        self.llm = llm
        self.model = model or get_settings().MODEL_FAST
        self.system = system_prompt(persona)

    async def _generate(self, messages: list[dict[str, str]]) -> Generation:
        st = Stage(name="sim")
        stream = self.llm.stream_text(
            self.model, self.system, messages, effort="low", max_tokens=400, stage=st
        )
        parts = [chunk async for chunk in stream]
        return Generation(
            "".join(parts),
            cost_usd=st.cost_usd or 0.0,
            input_tokens=st.input_tokens + st.cache_read_tokens + st.cache_creation_tokens,
            output_tokens=st.output_tokens,
        )


def make_simulator(
    kind: str,
    persona: Persona,
    *,
    mode: str = "replay",
    llm: LLMClient | None = None,
    cassette_dir: Path | None = None,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
) -> Simulator:
    if kind == "scripted":
        return ScriptedSimulator(persona)
    if kind == "ollama":
        return OllamaSimulator(persona, mode=mode, cassette_dir=cassette_dir, model=ollama_model)
    if kind == "claude":
        if llm is None:
            raise ValueError("claude simulator needs an LLMClient")
        return ClaudeSimulator(persona, llm)
    raise ValueError(f"unknown simulator {kind!r}")
