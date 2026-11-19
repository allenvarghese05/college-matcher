"""Retrieval ablation (SPEC §10): recall@k / nDCG@k per retrieval mode on GOLD profiles.

Each persona's ``hidden_profile`` is fed straight to the retriever (no extraction), so
this measures retrieval alone. The persona's ``meta:`` block (eval bookkeeping) is
stripped and never reaches the profile.

Labels (``evals/labels/criteria.md``)::

    _meta: {...}                       # ignored
    persona-id:
      acceptable_unitids: [...]        # required
      judged_unitids: [...]            # required, superset of acceptable

Usage (from ``backend/``)::

    uv run python ../evals/ablation.py \
        --personas '../evals/personas/*.yaml' --labels ../evals/labels/labels.yaml

Prints a markdown table: mode | recall@10 | nDCG@10 | judged-P@10 | unjudged@10 | n.

* Unjudged top-k schools count as non-hits in recall/nDCG; ``unjudged@10`` is the total
  number of unjudged top-k schools across scored personas.
* judged-P@10 averages only over personas with ≥ 1 judged school in the top k
  ("n/a" if none).
* Personas without labels, or with an empty acceptable list, are skipped (criteria:
  "reported separately"); ``n`` is the number of personas scored for that mode.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.retrieval.major_match import Embedder, FunctionEmbedder  # noqa: E402
from app.retrieval.metrics import (  # noqa: E402
    judged_precision_at_k,
    ndcg_at_k,
    recall_at_k,
    unjudged_at_k,
)
from app.retrieval.retriever import Retriever  # noqa: E402
from app.schemas import RetrievalMode, StudentProfile  # noqa: E402

log = get_logger(__name__)

DEFAULT_MODES: tuple[RetrievalMode, ...] = (
    "sql_only",
    "hybrid",
    "hybrid_rerank",
    "hybrid_riasec_rerank",
)


@dataclass
class Persona:
    id: str
    profile: StudentProfile


@dataclass
class Label:
    acceptable: set[int]
    judged: set[int]


@dataclass
class ModeResult:
    mode: str
    recall: float | None
    ndcg: float | None
    n: int
    note: str = ""
    judged_precision: float | None = None
    unjudged: int = 0


def profile_from_hidden(hidden: dict[str, Any]) -> StudentProfile:
    """Gold profile: every hidden field becomes a ProfileField with confidence 1.0."""
    data: dict[str, Any] = {}
    for key, value in (hidden or {}).items():
        if key == "meta":
            continue
        if key not in StudentProfile.model_fields:
            log.warning("unknown_profile_field", field=key)
            continue
        data[key] = {"value": value, "confidence": 1.0}
    return StudentProfile.model_validate(data)


def load_personas(pattern: str) -> list[Persona]:
    out = []
    for path in sorted(glob.glob(pattern)):
        doc = yaml.safe_load(Path(path).read_text()) or {}
        doc.pop("meta", None)  # eval bookkeeping, never part of the gold profile
        pid = str(doc.get("id") or Path(path).stem)
        out.append(Persona(pid, profile_from_hidden(doc.get("hidden_profile") or {})))
    return out


def load_labels(path: str | Path) -> dict[str, Label]:
    """Parse labels.yaml; ``judged_unitids`` is required (ValueError if missing)."""
    doc = yaml.safe_load(Path(path).read_text()) or {}
    out: dict[str, Label] = {}
    for pid, entry in doc.items():
        if str(pid).startswith("_"):
            continue
        entry = entry or {}
        if "judged_unitids" not in entry:
            raise ValueError(f"labels for {pid!r} are missing required 'judged_unitids'")
        acceptable = {int(u) for u in entry.get("acceptable_unitids") or []}
        judged = {int(u) for u in entry.get("judged_unitids") or []}
        if not acceptable <= judged:
            log.warning("acceptable_not_in_judged", persona=str(pid))
        out[str(pid)] = Label(acceptable, judged | acceptable)
    return out


async def run_ablation(
    session: AsyncSession,
    personas: list[Persona],
    labels: dict[str, Label],
    embedder: Embedder | None,
    modes: tuple[RetrievalMode, ...] = DEFAULT_MODES,
    k: int = 10,
) -> list[ModeResult]:
    retriever = Retriever(embedder=embedder)
    scored = [p for p in personas if p.id in labels and labels[p.id].acceptable]
    results: list[ModeResult] = []
    for mode in modes:
        recalls: list[float] = []
        ndcgs: list[float] = []
        precisions: list[float] = []
        unjudged = 0
        note = ""
        for p in scored:
            try:
                cands = await retriever.retrieve(session, p.profile, k=k, mode=mode)
            except NotImplementedError:
                note = "not implemented"
                break
            ranked = [c.unitid for c in cands]
            lab = labels[p.id]
            recalls.append(recall_at_k(ranked, lab.acceptable, k))
            ndcgs.append(ndcg_at_k(ranked, lab.acceptable, k))
            jp = judged_precision_at_k(ranked, lab.acceptable, lab.judged, k)
            if jp is not None:
                precisions.append(jp)
            unjudged += unjudged_at_k(ranked, lab.judged, k)
        if note or not recalls:
            results.append(ModeResult(mode, None, None, 0, note or "no labelled personas"))
        else:
            results.append(
                ModeResult(
                    mode,
                    sum(recalls) / len(recalls),
                    sum(ndcgs) / len(ndcgs),
                    len(recalls),
                    judged_precision=sum(precisions) / len(precisions) if precisions else None,
                    unjudged=unjudged,
                )
            )
    return results


def format_table(results: list[ModeResult], k: int = 10) -> str:
    lines = [
        f"| mode | recall@{k} | nDCG@{k} | judged-P@{k} | unjudged@{k} | n |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.recall is None or r.ndcg is None:
            lines.append(f"| {r.mode} | – | – | – | – | 0 ({r.note}) |")
        else:
            jp = "n/a" if r.judged_precision is None else f"{r.judged_precision:.3f}"
            lines.append(
                f"| {r.mode} | {r.recall:.3f} | {r.ndcg:.3f} | {jp} | {r.unjudged} | {r.n} |"
            )
    return "\n".join(lines)


def default_embedder() -> Embedder:
    """The loader's real embedder (``app.retrieval.embedder``), adapted to ``Embedder``."""
    mod = importlib.import_module("app.retrieval.embedder")
    if hasattr(mod, "get_embedder"):
        obj = mod.get_embedder()
        if hasattr(obj, "embed"):
            return obj  # type: ignore[no-any-return]
        if hasattr(obj, "embed_texts"):
            return FunctionEmbedder(obj.embed_texts)
    return FunctionEmbedder(mod.embed_texts)


async def _main(args: argparse.Namespace) -> None:
    personas = load_personas(args.personas)
    labels = load_labels(args.labels)
    modes = tuple(args.modes.split(",")) if args.modes else DEFAULT_MODES
    engine = create_async_engine(args.database_url or get_settings().DATABASE_URL)
    try:
        async with AsyncSession(engine) as session:
            results = await run_ablation(
                session,
                personas,
                labels,
                default_embedder(),
                modes,
                args.k,  # type: ignore[arg-type]
            )
    finally:
        await engine.dispose()
    print(format_table(results, args.k))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--personas", default=str(REPO / "evals" / "personas" / "*.yaml"))
    ap.add_argument("--labels", default=str(REPO / "evals" / "labels" / "labels.yaml"))
    ap.add_argument("--modes", default="", help="comma-separated; default all four")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--database-url", default="")
    asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    main()
