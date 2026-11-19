"""Ranking metrics for the retrieval eval (SPEC §10), binary relevance.

* ``recall_at_k`` = |top-k ∩ relevant| / min(|relevant|, k). Capping the denominator at
  ``k`` keeps a perfect top-k at 1.0 even when a persona has more than ``k`` acceptable
  schools (labels come from a hand-marked pool, often larger than 10).
* ``ndcg_at_k`` = DCG / IDCG with gain 1 for relevant items and discount
  ``1/log2(rank + 1)`` (rank starting at 1); IDCG places min(|relevant|, k) hits first.

Duplicate ids in the ranking count once (first occurrence). An empty relevant set
returns 0.0 — callers should skip such personas rather than average them in.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Sequence


def _dedupe[H: Hashable](ranked: Iterable[H]) -> list[H]:
    seen: set[H] = set()
    out: list[H] = []
    for x in ranked:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def recall_at_k[H: Hashable](ranked: Sequence[H], relevant: Iterable[H], k: int) -> float:
    rel = set(relevant)
    if not rel or k <= 0:
        return 0.0
    top = _dedupe(ranked)[:k]
    hits = sum(1 for x in top if x in rel)
    return hits / min(len(rel), k)


def ndcg_at_k[H: Hashable](ranked: Sequence[H], relevant: Iterable[H], k: int) -> float:
    rel = set(relevant)
    if not rel or k <= 0:
        return 0.0
    top = _dedupe(ranked)[:k]
    dcg = sum(1.0 / math.log2(i + 2) for i, x in enumerate(top) if x in rel)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(rel), k)))
    return dcg / idcg
