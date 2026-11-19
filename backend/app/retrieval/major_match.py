"""Stage A: student interests → majors (CIP 4-digit codes), SPEC §9.

* **Embedding path**: embed ``interests + dream_without_money + strengths (+ intended
  majors)`` as one query and take the cosine top-k over ``cip_code.embedding`` with
  pgvector's ``<=>`` operator (cosine distance). Only CIPs with at least one bachelor's
  program are searched. Similarity = ``1 - distance`` clipped to 0..1.
* **Intended majors**: each stated major is fuzzy-matched to CIP titles (token overlap
  + ``difflib`` ratio, with a small alias table for "CS", "pre-med", ...). A matched
  title gets similarity = its match score (exact title ≈ 1.0).
* The two lists are unioned by ``cip4``, keeping the max similarity.

The embedder is any object with ``embed(texts) -> list[list[float]]`` (``Embedder``
protocol); wrap a plain function with ``FunctionEmbedder``.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import StudentProfile

BACHELORS = 3
FUZZY_THRESHOLD = 0.6


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FunctionEmbedder:
    """Adapter: ``FunctionEmbedder(embed_texts)`` satisfies ``Embedder``."""

    def __init__(self, fn: Callable[[list[str]], list[list[float]]]):
        self._fn = fn

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._fn(texts)


@dataclass(frozen=True)
class CipScore:
    cip4: str
    title: str
    similarity: float  # 0..1
    source: Literal["embedding", "intended", "both"] = "embedding"


# ------------------------------------------------------------------ query text


def query_text(profile: StudentProfile) -> str:
    """The text embedded for Stage A ("" when the profile has no interest signal)."""
    parts: list[str] = []
    parts += profile.interests.value or []
    if profile.dream_without_money.value:
        parts.append(profile.dream_without_money.value)
    parts += profile.strengths.value or []
    parts += profile.intended_majors.value or []
    return ". ".join(p.strip() for p in parts if p and p.strip())


def vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


# ------------------------------------------------------------------ fuzzy match

ALIASES: dict[str, str] = {
    "cs": "computer science",
    "comp sci": "computer science",
    "compsci": "computer science",
    "pre med": "biology",
    "premed": "biology",
    "pre-med": "biology",
    "pre law": "political science",
    "prelaw": "political science",
    "pre-law": "political science",
    "econ": "economics",
    "psych": "psychology",
    "poli sci": "political science",
    "polisci": "political science",
    "bio": "biology",
    "chem": "chemistry",
    "math": "mathematics",
    "maths": "mathematics",
    "stats": "statistics",
    "business": "business administration management",
    "nursing": "registered nursing",
    "engineering": "engineering general",
}

_STOP = {"and", "of", "the", "in", "for", "other", "a", "an", "&", "studies", "major"}


def _tokens(s: str) -> list[str]:
    out = []
    for t in re.findall(r"[a-z0-9]+", s.lower()):
        if t in _STOP:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


def fuzzy_score(query: str, title: str) -> float:
    """0..1 match score of a stated major against a CIP title."""
    q = _tokens(query)
    t = _tokens(title)
    if not q or not t:
        return 0.0
    tset = set(t)
    overlap = sum(1 for x in q if x in tset) / len(q)
    ratio = difflib.SequenceMatcher(None, " ".join(q), " ".join(t)).ratio()
    return 0.7 * overlap + 0.3 * ratio


def match_titles(majors: list[str], titles: dict[str, str]) -> list[CipScore]:
    """Map each stated major to its best CIP title (plus near-perfect extra matches)."""
    found: dict[str, CipScore] = {}
    for major in majors:
        key = major.strip().lower()
        if not key:
            continue
        q = ALIASES.get(key, key)
        scored = sorted(
            ((fuzzy_score(q, title), cip4, title) for cip4, title in titles.items()),
            key=lambda x: (-x[0], x[1]),
        )
        if not scored or scored[0][0] < FUZZY_THRESHOLD:
            continue
        best = scored[0][0]
        for score, cip4, title in scored:
            if score < FUZZY_THRESHOLD or (score < best and score < 0.9):
                break
            sim = round(min(1.0, score), 4)
            prev = found.get(cip4)
            if prev is None or prev.similarity < sim:
                found[cip4] = CipScore(cip4, title, sim, "intended")
    return sorted(found.values(), key=lambda c: (-c.similarity, c.cip4))


async def bachelor_cip_titles(session: AsyncSession) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT c.cip4, c.title FROM cip_code c WHERE EXISTS ("
            " SELECT 1 FROM program p WHERE p.cip4 = c.cip4 AND p.credential_level = :lvl)"
        ),
        {"lvl": BACHELORS},
    )
    return {r.cip4: r.title for r in rows}


async def by_intended_majors(session: AsyncSession, profile: StudentProfile) -> list[CipScore]:
    majors = profile.intended_majors.value or []
    if not majors:
        return []
    return match_titles(majors, await bachelor_cip_titles(session))


# ------------------------------------------------------------------ embedding


async def by_vector(
    session: AsyncSession, embedder: Embedder, query: str, k: int = 8
) -> list[CipScore]:
    if not query:
        return []
    # off the event loop: the model call is CPU-bound (and loads the model if cold)
    [vec] = await asyncio.to_thread(embedder.embed, [query])
    rows = await session.execute(
        text(
            "SELECT c.cip4, c.title, 1 - (c.embedding <=> CAST(:q AS vector)) AS sim"
            " FROM cip_code c"
            " WHERE c.embedding IS NOT NULL AND EXISTS ("
            "  SELECT 1 FROM program p WHERE p.cip4 = c.cip4 AND p.credential_level = :lvl)"
            " ORDER BY c.embedding <=> CAST(:q AS vector), c.cip4"
            " LIMIT :k"
        ),
        {"q": vector_literal(vec), "lvl": BACHELORS, "k": k},
    )
    return [
        CipScore(r.cip4, r.title, round(max(0.0, min(1.0, float(r.sim))), 4), "embedding")
        for r in rows
    ]


def union(*lists: list[CipScore]) -> list[CipScore]:
    best: dict[str, CipScore] = {}
    for lst in lists:
        for c in lst:
            prev = best.get(c.cip4)
            if prev is None:
                best[c.cip4] = c
            else:
                src: Literal["embedding", "intended", "both"] = (
                    prev.source if prev.source == c.source else "both"
                )
                best[c.cip4] = CipScore(c.cip4, c.title, max(prev.similarity, c.similarity), src)
    return sorted(best.values(), key=lambda c: (-c.similarity, c.cip4))


async def by_embedding(
    session: AsyncSession, embedder: Embedder, profile: StudentProfile, k: int = 8
) -> list[CipScore]:
    """Stage A (tier 1): vector top-k ∪ fuzzy-matched intended majors."""
    vec = await by_vector(session, embedder, query_text(profile), k)
    intended = await by_intended_majors(session, profile)
    return union(vec, intended)
