"""Which intake topics a counselor message asks about (keyword heuristics).

Used in three places, so they agree by construction:

* the scripted simulator decides what to answer;
* the leak guard decides which facts the student was *allowed* to reveal;
* ``metrics_extraction.questions_asked`` decides which hidden fields the counselor asked
  about (questions-asked coverage).

Method: split the counselor text into sentences, keep the **question sentences** (ending
in ``?``), drop the canonical dream question's money wording, then match each topic's
regexes (case-insensitive; ``ACT`` must be upper-case). An open invitation ("what's on
your mind about college?") counts as asking about interests and the dream, as the
persona README specifies. Heuristics, not NLU: documented as such in the report.
"""

from __future__ import annotations

import re

# Field -> intake topic (NextTopic vocabulary). riasec is never asked directly.
FIELD_TOPIC: dict[str, str] = {
    "home_state": "location",
    "home_zip": "location",
    "max_distance_miles": "location",
    "regions": "location",
    "gpa": "academics",
    "sat": "academics",
    "act": "academics",
    "income_bracket": "money",
    "budget_cap": "money",
    "interests": "interests",
    "intended_majors": "interests",
    "dream_without_money": "dream_without_money",
    "strengths": "strengths",
    "favorite_subjects": "favorite_subjects",
    "activities": "activities",
    "work_values": "work_values",
    "size_pref": "size_setting",
    "setting_pref": "size_setting",
    "priorities": "priorities",
}

TOPICS: tuple[str, ...] = (
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

_DREAM_PHRASES = [
    r"if money (weren't|wasn't|were not|was not|isn't|is not) (involved|an issue|a factor|"
    r"a concern|in the picture)",
    r"(weren't|wasn't|not) getting paid",
    r"\bdream\b",
    r"rest of your life",
    r"\bif money\b",
    r"\bideal (job|career|day|life)\b",
    r"\bwhat would you (happily )?do\b",
]

PATTERNS: dict[str, list[str]] = {
    "dream_without_money": _DREAM_PHRASES,
    "interests": [
        r"\binterest", r"\binto\b", r"\benjoy", r"\bfree time\b", r"\bhobb", r"\bfor fun\b",
        r"\blike (to do|doing)\b", r"\bpassion", r"\bexcite", r"\bmajors?\b", r"\bstudy\b",
        r"\bcurious\b", r"\blove (to|doing)\b", r"\bcareers?\b",
    ],
    "strengths": [
        r"\bgood at\b", r"\bstrengths?\b", r"\bgreat at\b", r"\bskills?\b", r"\btalent",
        r"\bcomes? easy\b", r"\bnatural at\b",
    ],
    "favorite_subjects": [
        r"\bsubjects?\b", r"\bclass(es)?\b", r"\bcourses?\b",
    ],
    "activities": [
        r"\bactivit", r"\bclubs?\b", r"\bsports?\b", r"\bteams?\b", r"\bafter school\b",
        r"\bextracurricular", r"\bvolunteer", r"\boutside (of )?(school|class)",
        r"\b(have|had|work) a (part-time )?job\b", r"\bpart-time\b", r"\bleadership\b",
    ],
    "work_values": [
        r"\bin (a|your) (future )?(job|career|work)\b",
        r"\bwork(ing)? with (people|things|your hands)\b", r"\bstability\b", r"\bfreedom\b",
        r"\brecognition\b", r"\bwhat (do )?you want (out of|from) (work|a job|a career)\b",
        r"\bkind of work\b", r"\bwork environment\b",
    ],
    "academics": [
        r"\bgpa\b", r"\bgrades?\b", r"\bsat\b", r"\btest scores?\b", r"\btests?\b",
        r"\bstandardi[sz]ed\b", r"\bacademic",
    ],
    "money": [
        r"\bincome\b", r"\bafford", r"\bbudget", r"\bpay\b", r"\bcosts?\b", r"\bfinancial",
        r"\bmoney\b", r"\bhousehold\b", r"\bparents make\b", r"\bper year\b", r"\bprice",
        r"\bfinancial aid\b", r"\bspend\b",
    ],
    "location": [
        r"\bwhere (do )?you live\b", r"\bhome state\b", r"\bwhat state\b", r"\bwhich state\b",
        r"\bfrom home\b", r"\bhow far\b", r"\bdistance\b", r"\bmiles?\b", r"\bzip\b",
        r"\bregions?\b", r"\bpart of the country\b", r"\bmove away\b", r"\bstay (close|near)",
        r"\bwhere are you (from|based|located)\b", r"\bclose to home\b", r"\bout of state\b",
        r"\bin-state\b", r"\bwhere .*\b(live|located)\b", r"\bnear home\b",
    ],
    "size_setting": [
        r"\bsize\b", r"\bbig\b", r"\bsmall\b", r"\blarge\b", r"\bcampus\b", r"\bcity\b",
        r"\bsuburb", r"\btown\b", r"\brural\b", r"\bsetting\b", r"\burban\b",
    ],
    "priorities": [
        r"\bmost important\b", r"\bpriorit", r"\bmatters? most\b", r"\bprestige\b",
        r"\bcareer outcomes?\b", r"\boverall fit\b", r"\bbiggest factor\b",
    ],
}  # fmt: skip

_COMPILED = {t: [re.compile(p, re.I) for p in ps] for t, ps in PATTERNS.items()}
_ACT = re.compile(r"\bACTs?\b")
_DREAM_STRIP = re.compile("|".join(_DREAM_PHRASES[:3]), re.I)
_OPEN_INVITES = [
    re.compile(p, re.I)
    for p in (
        r"what'?s on your mind",
        r"tell me (a (little|bit) )?about (yourself|you)\b",
        r"what brings you",
        r"how are you feeling about college",
        r"where would you like to start",
        r"what('?s| is) been on your mind",
    )
]
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def question_sentences(text: str) -> list[str]:
    """Sentences that end with a question mark (the counselor asks one per reply)."""
    return [s.strip() for s in _SENT.split(text or "") if s.strip().endswith("?")]


def topics_in(sentence: str) -> set[str]:
    found: set[str] = set()
    for p in _COMPILED["dream_without_money"]:
        if p.search(sentence):
            found.add("dream_without_money")
            break
    rest = _DREAM_STRIP.sub(" ", sentence)  # "if money weren't involved" is not money
    for topic, pats in _COMPILED.items():
        if topic == "dream_without_money":
            continue
        if any(p.search(rest) for p in pats):
            found.add(topic)
    if _ACT.search(sentence):
        found.add("academics")
    if any(p.search(sentence) for p in _OPEN_INVITES):
        found |= {"interests", "dream_without_money"}
    return found


def asked_topics(text: str, questions_only: bool = True) -> set[str]:
    """Topics the counselor asks about in ``text`` (question sentences by default)."""
    sents = question_sentences(text) if questions_only else [text or ""]
    out: set[str] = set()
    for s in sents:
        out |= topics_in(s)
    return out


def asked_fields(text: str) -> set[str]:
    topics = asked_topics(text)
    return {f for f, t in FIELD_TOPIC.items() if t in topics}
