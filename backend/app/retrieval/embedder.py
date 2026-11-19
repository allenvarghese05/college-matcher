"""Text embeddings for CIP definitions and student queries (SPEC §9 stage A, P3).

One model everywhere: fastembed ``BAAI/bge-small-en-v1.5`` (384-dim). Vectors are
L2-normalised, so cosine similarity == dot product == ``1 - (a <=> b)`` in pgvector.

Usage::

    from app.retrieval.embedder import embed_texts, embed_query
    vecs = embed_texts(["fixing cars and engines"])  # list[list[float]], len 384 each

The real model is loaded lazily on first use (first call downloads ~70 MB from
Hugging Face into ``FASTEMBED_CACHE_PATH`` or fastembed's temp-dir default).

Tests / CI / replay never need the model:

* ``set_embedder(FakeEmbedder())`` (and ``set_embedder(None)`` to reset), or
* env ``EMBEDDER=fake`` to make ``get_embedder()`` return a FakeEmbedder.

FakeEmbedder is deterministic (hashed bag of words) so lexically similar texts get
similar vectors; it is only for tests and must never populate a real database.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from typing import Any, Protocol

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
FAKE_MODEL = "fake-hash-bow-v1"


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalised EMBED_DIM vector per text, in order."""
        ...


def normalise(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return vec if n == 0 else [x / n for x in vec]


class FastEmbedder:
    """fastembed TextEmbedding, loaded on first ``embed`` call (thread-safe)."""

    model_name = EMBED_MODEL

    def __init__(self, model_name: str = EMBED_MODEL, batch_size: int = 64) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    self._model = TextEmbedding(
                        self.model_name, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH")
                    )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        out = [
            normalise([float(x) for x in v]) for v in model.embed(texts, batch_size=self.batch_size)
        ]
        for v in out:
            if len(v) != EMBED_DIM:
                raise ValueError(f"{self.model_name} returned dim {len(v)}, want {EMBED_DIM}")
        return out


_TOKEN = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic test double: hashed bag of words (+ char trigrams), normalised.

    Shared words -> positive cosine; disjoint texts -> ~0. Stable across processes
    (uses blake2b, not ``hash()``).
    """

    model_name = FAKE_MODEL

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % self.dim
        sign = 1.0 if h[4] & 1 else -1.0
        return idx, sign

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in _TOKEN.findall(text.lower()):
                i, s = self._bucket("w:" + tok)
                vec[i] += s
                padded = f"#{tok}#"
                for k in range(len(padded) - 2):
                    i, s = self._bucket("c:" + padded[k : k + 3])
                    vec[i] += 0.25 * s
            if not any(vec):
                vec[0] = 1.0  # empty text: a fixed unit vector rather than zeros
            out.append(normalise(vec))
        return out


_override: Embedder | None = None
_default: Embedder | None = None
_default_lock = threading.Lock()


def set_embedder(embedder: Embedder | None) -> None:
    """Override the process-wide embedder (tests). ``None`` restores the default."""
    global _override
    _override = embedder


def get_embedder() -> Embedder:
    """The override if set, else a lazily created singleton (FakeEmbedder if EMBEDDER=fake)."""
    global _default
    if _override is not None:
        return _override
    if _default is None:
        with _default_lock:
            if _default is None:
                fake = os.environ.get("EMBEDDER", "").lower() == "fake"
                _default = FakeEmbedder() if fake else FastEmbedder()
    return _default


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed documents or queries with the current embedder (normalised, 384-dim)."""
    return get_embedder().embed(list(texts))


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
