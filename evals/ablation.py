"""Retrieval ablation (SPEC §10): recall@k / nDCG@k per retrieval mode on GOLD profiles.

Each persona's ``hidden_profile`` is fed straight to the retriever (no extraction), so
this measures retrieval alone. Labels: ``{persona_id: {acceptable_unitids: [...]}}``.

Usage (from ``backend/``)::

    uv run python ../evals/ablation.py \
        --personas '../evals/personas/*.yaml' --labels ../evals/labels/labels.yaml

Prints a markdown table: mode | recall@10 | nDCG@10 | n. Personas without labels are
skipped; ``n`` is the number of personas scored for that mode.
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
from app.retrieval.metrics import ndcg_at_k, recall_at_k  # noqa: E402
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
class ModeResult:
    mode: str
    recall: float | None
    ndcg: float | None
    n: int
    note: str = ""


def profile_from_hidden(hidden: dict[str, Any]) -> StudentProfile:
    """Gold profile: every hidden field becomes a ProfileField with confidence 1.0."""
    data: dict[str, Any] = {}
    for key, value in (hidden or {}).items():
        if key not in StudentProfile.model_fields:
            log.warning("unknown_profile_field", field=key)
            continue
        data[key] = {"value": value, "confidence": 1.0}
    return StudentProfile.model_validate(data)


def load_personas(pattern: str) -> list[Persona]:
    out = []
    for path in sorted(glob.glob(pattern)):
        doc = yaml.safe_load(Path(path).read_text())
        pid = str(doc.get("id") or Path(path).stem)
        out.append(Persona(pid, profile_from_hidden(doc.get("hidden_profile") or {})))
    return out


def load_labels(path: str | Path) -> dict[str, set[int]]:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    return {
        str(pid): {int(u) for u in (entry or {}).get("acceptable_unitids", [])}
        for pid, entry in doc.items()
    }


async def run_ablation(
    session: AsyncSession,
    personas: list[Persona],
    labels: dict[str, set[int]],
    embedder: Embedder | None,
    modes: tuple[RetrievalMode, ...] = DEFAULT_MODES,
    k: int = 10,
) -> list[ModeResult]:
    retriever = Retriever(embedder=embedder)
    scored = [p for p in personas if labels.get(p.id)]
    results: list[ModeResult] = []
    for mode in modes:
        recalls: list[float] = []
        ndcgs: list[float] = []
        note = ""
        for p in scored:
            try:
                cands = await retriever.retrieve(session, p.profile, k=k, mode=mode)
            except NotImplementedError:
                note = "not implemented"
                break
            ranked = [c.unitid for c in cands]
            recalls.append(recall_at_k(ranked, labels[p.id], k))
            ndcgs.append(ndcg_at_k(ranked, labels[p.id], k))
        if note or not recalls:
            results.append(ModeResult(mode, None, None, 0, note or "no labelled personas"))
        else:
            results.append(
                ModeResult(mode, sum(recalls) / len(recalls), sum(ndcgs) / len(ndcgs), len(recalls))
            )
    return results


def format_table(results: list[ModeResult], k: int = 10) -> str:
    lines = [f"| mode | recall@{k} | nDCG@{k} | n |", "|---|---|---|---|"]
    for r in results:
        if r.recall is None or r.ndcg is None:
            lines.append(f"| {r.mode} | – | – | 0 ({r.note}) |")
        else:
            lines.append(f"| {r.mode} | {r.recall:.3f} | {r.ndcg:.3f} | {r.n} |")
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
