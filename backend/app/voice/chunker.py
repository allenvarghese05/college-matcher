"""Sentence-level chunking of a streamed LLM reply for TTS (SPEC §11).

Tokens arrive in arbitrary fragments. A chunk is emitted as soon as a sentence boundary
is *confirmed* — terminal punctuation (``. ! ? …``, optionally followed by a closing
quote/bracket) followed by whitespace — so ``3.7`` or a half-streamed ``U.S.`` never split.

The first chunk is latency-critical (it gates time-to-first-audio): if no boundary has
appeared by ``first_max_words`` words it is cut at the last clause break (``, ; : —``) or
word boundary. Later chunks are cut at ``max_words`` only for run-on sentences.
"""

from __future__ import annotations

import re

_TERMINAL = ".!?…"
_CLOSERS = "\"'”’)]"
_CLAUSE = ",;:—–"
# Abbreviations that end in a period but rarely end a sentence.
_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "u.s", "u.k", "a.m", "p.m", "approx", "no", "dept", "univ",
}  # fmt: skip
_WORD = re.compile(r"\S+")


def _is_abbreviation(text: str, dot_index: int) -> bool:
    start = dot_index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    word = text[start:dot_index].lower().lstrip("(\"'“‘")
    if not word:
        return False
    if word in _ABBREV:
        return True
    return len(word) == 1 and word.isalpha()  # initials: "J. R. R."


class SentenceChunker:
    def __init__(self, first_max_words: int = 12, max_words: int = 40) -> None:
        self.first_max_words = first_max_words
        self.max_words = max_words
        self._buf = ""
        self.emitted = 0

    def push(self, text: str) -> list[str]:
        """Add streamed text; return the chunks that are now complete (may be empty)."""
        self._buf += text
        out: list[str] = []
        while True:
            chunk = self._next_chunk()
            if chunk is None:
                break
            out.append(chunk)
        return out

    def flush(self) -> str | None:
        """End of stream: return whatever is left (or ``None``)."""
        rest = self._buf.strip()
        self._buf = ""
        if not rest:
            return None
        self.emitted += 1
        return rest

    # ------------------------------------------------------------------ internals

    def _take(self, end: int) -> str | None:
        chunk = self._buf[:end].strip()
        self._buf = self._buf[end:].lstrip()
        if not chunk:
            return None
        self.emitted += 1
        return chunk

    def _sentence_end(self) -> int | None:
        buf = self._buf
        for i, ch in enumerate(buf):
            if ch not in _TERMINAL:
                continue
            j = i + 1
            while j < len(buf) and (buf[j] in _TERMINAL or buf[j] in _CLOSERS):
                j += 1
            if j >= len(buf) or not buf[j].isspace():
                continue  # boundary not confirmed yet (or mid-token like "3.7")
            if ch == "." and _is_abbreviation(buf, i):
                continue
            return j
        return None

    def _word_limit_cut(self, limit: int) -> int | None:
        words = list(_WORD.finditer(self._buf))
        # need limit complete words: a following whitespace confirms the last one
        if len(words) < limit or (len(words) == limit and not self._buf[-1:].isspace()):
            return None
        end = words[limit - 1].end()
        # prefer the last clause break within the window
        for w in reversed(words[: limit - 1]):
            if w.group()[-1] in _CLAUSE and w.end() >= end // 3:
                return w.end()
        return end

    def _next_chunk(self) -> str | None:
        end = self._sentence_end()
        if end is not None:
            return self._take(end)
        limit = self.first_max_words if self.emitted == 0 else self.max_words
        cut = self._word_limit_cut(limit)
        if cut is not None:
            return self._take(cut)
        return None
