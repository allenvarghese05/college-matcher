"""Versioned system prompts stored as text files: ``<name>.v<N>.txt``.

Add a new version file rather than editing a prompt in place once cassettes or eval
results depend on it; the active version per prompt is pinned in ``ACTIVE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

ACTIVE: dict[str, int] = {
    "counselor_reply": 1,
    "extractor": 2,
    "recommender": 2,
}


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str

    @property
    def id(self) -> str:
        return f"{self.name}.v{self.version}"


@cache
def load_prompt(name: str, version: int | None = None) -> Prompt:
    v = ACTIVE[name] if version is None else version
    text = (PROMPT_DIR / f"{name}.v{v}.txt").read_text(encoding="utf-8").strip()
    return Prompt(name=name, version=v, text=text)
