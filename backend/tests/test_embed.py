"""Embedder module tests. Never downloads the real model."""

from __future__ import annotations

import math

import pytest

from app.retrieval import embedder as emb_mod
from app.retrieval.embedder import (
    EMBED_DIM,
    FakeEmbedder,
    FastEmbedder,
    embed_query,
    embed_texts,
    get_embedder,
    set_embedder,
)
from ingest.embed import embedding_text


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.fixture(autouse=True)
def _reset_embedder(monkeypatch: pytest.MonkeyPatch):
    set_embedder(None)
    monkeypatch.setattr(emb_mod, "_default", None)
    yield
    set_embedder(None)


def test_fake_embedder_shape_and_norm() -> None:
    vecs = FakeEmbedder().embed(["Automobile mechanics", "", "Graphic design."])
    assert len(vecs) == 3
    for v in vecs:
        assert len(v) == EMBED_DIM
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)


def test_fake_embedder_deterministic_and_lexical() -> None:
    e = FakeEmbedder()
    a, a2, b, c = e.embed(
        [
            "vehicle maintenance and repair",
            "vehicle maintenance and repair",
            "vehicle repair technology",
            "medieval poetry",
        ]
    )
    assert a == a2
    assert _cos(a, b) > _cos(a, c)
    assert _cos(a, b) > 0.3


def test_set_embedder_overrides_and_resets() -> None:
    fake = FakeEmbedder()
    set_embedder(fake)
    assert get_embedder() is fake
    assert embed_texts(["x"]) == fake.embed(["x"])
    assert embed_query("x") == fake.embed(["x"])[0]
    set_embedder(None)
    assert get_embedder() is not fake


def test_env_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDER", "fake")
    assert isinstance(get_embedder(), FakeEmbedder)


def test_default_is_lazy_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBEDDER", raising=False)
    e = get_embedder()
    assert isinstance(e, FastEmbedder)
    assert e._model is None  # nothing loaded / downloaded until first embed
    assert get_embedder() is e  # singleton
    assert e.embed([]) == []  # empty input never loads the model
    assert e._model is None


def test_fastembed_normalises_and_checks_dim() -> None:
    class Stub:
        def embed(self, texts, batch_size=0):
            for _ in texts:
                yield [3.0, 4.0] + [0.0] * (EMBED_DIM - 2)

    e = FastEmbedder()
    e._model = Stub()
    (v,) = e.embed(["a"])
    assert v[:2] == pytest.approx([0.6, 0.8])

    class Bad:
        def embed(self, texts, batch_size=0):
            yield [1.0, 0.0]

    e._model = Bad()
    with pytest.raises(ValueError, match="dim"):
        e.embed(["a"])


@pytest.mark.parametrize(
    ("title", "definition", "expected"),
    [
        ("Animal Sciences", "A group of programs.", "Animal Sciences. A group of programs."),
        ("Animal Sciences.", None, "Animal Sciences."),
        ("Animal Sciences", "  ", "Animal Sciences."),
    ],
)
def test_embedding_text(title: str, definition: str | None, expected: str) -> None:
    assert embedding_text(title, definition) == expected
