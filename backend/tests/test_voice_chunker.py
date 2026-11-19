"""Sentence chunker: streamed tokens -> TTS-sized chunks (first chunk ASAP)."""

from __future__ import annotations

from app.voice.chunker import SentenceChunker


def _feed(tokens: list[str], **kw: int) -> tuple[list[list[str]], str | None]:
    c = SentenceChunker(**kw)
    per_token = [c.push(t) for t in tokens]
    return per_token, c.flush()


def _all(tokens: list[str], **kw: int) -> list[str]:
    per, rest = _feed(tokens, **kw)
    out = [s for chunk in per for s in chunk]
    return out + ([rest] if rest else [])


def test_first_sentence_emitted_as_soon_as_boundary_is_confirmed() -> None:
    per, rest = _feed(["That's ", "awesome!", " Where do", " you live?"])
    assert per[1] == []  # "awesome!" not confirmed until whitespace follows
    assert per[2] == ["That's awesome!"]
    assert rest == "Where do you live?"


def test_char_by_char_stream_matches_word_stream() -> None:
    text = "Great question. Nursing is a strong fit! Do you want to stay in Ohio? Tell me."
    words = [w + " " for w in text.split(" ")]
    assert _all(list(text)) == _all(words)
    assert _all(list(text)) == [
        "Great question.",
        "Nursing is a strong fit!",
        "Do you want to stay in Ohio?",
        "Tell me.",
    ]


def test_decimals_and_abbreviations_do_not_split() -> None:
    text = "A 3.7 GPA is solid. Dr. Lee at the U.S. Naval Academy agrees, e.g. on math. Next."
    assert _all(list(text)) == [
        "A 3.7 GPA is solid.",
        "Dr. Lee at the U.S. Naval Academy agrees, e.g. on math.",
        "Next.",
    ]


def test_closing_quote_and_ellipsis_stay_with_sentence() -> None:
    assert _all(list('She said "go for it." Then... we talked! Okay')) == [
        'She said "go for it."',
        "Then...",
        "we talked!",
        "Okay",
    ]


def test_first_chunk_cut_at_word_limit_without_boundary() -> None:
    words = [f"w{i} " for i in range(20)]
    per, _ = _feed(words, first_max_words=12)
    emitted = [(i, s) for i, chunk in enumerate(per) for s in chunk]
    # 12th word is confirmed when the 12th token (with its trailing space) arrives
    assert emitted[0][0] == 11
    assert emitted[0][1].split() == [f"w{i}" for i in range(12)]


def test_first_chunk_prefers_clause_break() -> None:
    text = "If money were no object and you could do anything at all, what would you pick "
    per, _ = _feed(list(text), first_max_words=12)
    first = next(s for chunk in per for s in chunk)
    assert first == "If money were no object and you could do anything at all,"


def test_later_chunks_use_sentence_boundaries_not_first_limit() -> None:
    sentence2 = " ".join(f"x{i}" for i in range(20)) + "."
    out = _all(list("Hi there. " + sentence2 + " Done."))
    assert out == ["Hi there.", sentence2, "Done."]


def test_run_on_sentence_split_at_max_words() -> None:
    long = " ".join(f"y{i}" for i in range(50)) + " "
    out = _all(list("Okay. " + long), max_words=40)
    assert out[0] == "Okay."
    assert len(out[1].split()) == 40
    assert len(out[2].split()) == 10


def test_flush_empty_and_whitespace() -> None:
    c = SentenceChunker()
    assert c.push("   ") == []
    assert c.flush() is None
    assert c.emitted == 0
