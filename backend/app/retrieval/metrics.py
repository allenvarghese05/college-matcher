"""Ranking metrics for the retrieval eval (SPEC §10), binary relevance.

* ``recall_at_k`` = |top-k ∩ relevant| / min(|relevant|, k). Capping the denominator at
  ``k`` keeps a perfect top-k at 1.0 even when a persona has more than ``k`` acceptable
  schools (labels come from a hand-marked pool, often larger than 10).
* ``ndcg_at_k`` = DCG / IDCG with gain 1 for relevant items and discount
  ``1/log2(rank + 1)`` (rank starting at 1); IDCG places min(|relevant|, k) hits first.

* ``judged_precision_at_k`` = |relevant ∩ top-k| / |judged ∩ top-k| (None if nothing in
  the top-k was judged); ``unjudged_at_k`` = top-k items outside the judged set.
  Unjudged items count as non-hits in recall and nDCG (evals/labels/criteria.md).

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


def judged_precision_at_k[H: Hashable](
    ranked: Sequence[H], relevant: Iterable[H], judged: Iterable[H], k: int
) -> float | None:
    """|relevant ∩ top-k| / |judged ∩ top-k|; None when nothing in the top-k was judged.

    ``judged`` should be a superset of ``relevant`` (criteria.md); relevant items count as
    judged regardless, so a malformed label file can't push this above 1.
    """
    rel = set(relevant)
    jud = set(judged) | rel
    top = _dedupe(ranked)[:k]
    n_judged = sum(1 for x in top if x in jud)
    if n_judged == 0:
        return None
    return sum(1 for x in top if x in rel) / n_judged


def unjudged_at_k[H: Hashable](ranked: Sequence[H], judged: Iterable[H], k: int) -> int:
    """Top-k items nobody judged (they count as non-hits in recall and nDCG)."""
    jud = set(judged)
    return sum(1 for x in _dedupe(ranked)[:k] if x not in jud)
