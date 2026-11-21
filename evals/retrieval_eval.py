"""Retrieval evals: top-k per mode on the GOLD and the END-TO-END profile (SPEC §10).

* **gold** — the persona's ``hidden_profile`` straight into the retriever
  (:func:`evals.common.gold_profile`, same as ``evals/ablation.py``).
* **e2e** — the profile the counselor extracted in ``run.py`` (``final_profile``).

:func:`evaluate_run` (needs the DB) writes ``retrieval.json``::

    {"k": 10, "modes": [...], "not_implemented": [...],
     "personas": {pid: {"gold": {mode: [unitid, ...]}, "e2e": {...}}}}

These top-k lists are also the system half of the TREC pool (``labels/pool.py``).
:func:`score_retrieval` (pure) scores them against ``labels.yaml`` with
``app.retrieval.metrics`` — recall@k, nDCG@k, judged-P@k, unjudged@k — using the
criteria.md rules (unjudged = non-hit; personas with no/empty labels skipped).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import TurnLogger
from app.retrieval.metrics import (
    judged_precision_at_k,
    ndcg_at_k,
    recall_at_k,
    unjudged_at_k,
)
from app.retrieval.retriever import Retriever
from app.schemas import RetrievalMode, StudentProfile
from evals.ablation import DEFAULT_MODES, Label
from evals.common import Persona, gold_profile

PROFILE_KINDS = ("gold", "e2e")


async def topk(
    session: AsyncSession,
    retriever: Retriever,
    profile: StudentProfile,
    modes: tuple[RetrievalMode, ...],
    k: int,
) -> tuple[dict[str, list[int]], list[str]]:
    out: dict[str, list[int]] = {}
    missing: list[str] = []
    quiet = TurnLogger()
    for mode in modes:
        try:
            cands = await retriever.retrieve(session, profile, k=k, mode=mode, logger=quiet)
        except NotImplementedError:
            missing.append(mode)
            continue
        out[mode] = [c.unitid for c in cands]
    return out, missing


async def evaluate_run(
    results: list[dict[str, Any]],
    personas: list[Persona],
    sessionmaker: async_sessionmaker[AsyncSession],
    embedder: Any,
    *,
    k: int = 10,
    modes: tuple[RetrievalMode, ...] = DEFAULT_MODES,
) -> dict[str, Any]:
    retriever = Retriever(embedder=embedder)
    by_id = {r["persona"]: r for r in results}
    doc: dict[str, Any] = {"k": k, "modes": [], "not_implemented": [], "personas": {}}
    not_impl: set[str] = set()
    async with sessionmaker() as session:
        for p in personas:
            entry: dict[str, Any] = {}
            gold, miss = await topk(session, retriever, gold_profile(p.hidden), modes, k)
            entry["gold"] = gold
            not_impl.update(miss)
            res = by_id.get(p.id)
            if res and res.get("final_profile") is not None:
                e2e_profile = StudentProfile.model_validate(res["final_profile"])
                entry["e2e"], miss = await topk(session, retriever, e2e_profile, modes, k)
                not_impl.update(miss)
            doc["personas"][p.id] = entry
    doc["modes"] = [m for m in modes if m not in not_impl]
    doc["not_implemented"] = sorted(not_impl)
    return doc


def score_retrieval(retrieval: dict[str, Any], labels: dict[str, Label]) -> list[dict[str, Any]]:
    """One row per (mode, profile kind): recall/nDCG/judged-P means, unjudged total, n."""
    k = int(retrieval.get("k", 10))
    rows: list[dict[str, Any]] = []
    personas = retrieval.get("personas", {})
    for mode in retrieval.get("modes", []):
        for kind in PROFILE_KINDS:
            recalls: list[float] = []
            ndcgs: list[float] = []
            precisions: list[float] = []
            unjudged = 0
            for pid, entry in sorted(personas.items()):
                lab = labels.get(pid)
                ranked = (entry.get(kind) or {}).get(mode)
                if lab is None or not lab.acceptable or ranked is None:
                    continue
                recalls.append(recall_at_k(ranked, lab.acceptable, k))
                ndcgs.append(ndcg_at_k(ranked, lab.acceptable, k))
                jp = judged_precision_at_k(ranked, lab.acceptable, lab.judged, k)
                if jp is not None:
                    precisions.append(jp)
                unjudged += unjudged_at_k(ranked, lab.judged, k)
            n = len(recalls)
            rows.append(
                {
                    "mode": mode,
                    "profile": kind,
                    "recall": sum(recalls) / n if n else None,
                    "ndcg": sum(ndcgs) / n if n else None,
                    "judged_precision": sum(precisions) / len(precisions) if precisions else None,
                    "unjudged": unjudged,
                    "n": n,
                }
            )
    for mode in retrieval.get("not_implemented", []):
        rows.append({"mode": mode, "profile": "-", "note": "not implemented", "n": 0})
    return rows
