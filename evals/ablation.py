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

Re-score END-TO-END without re-running conversations (no LLM calls)::

    uv run python ../evals/ablation.py --from-run ../evals/results/live-full-1 \
        [--write-extra] [--json-out top10.json]

``--from-run`` re-runs every mode on each persona's gold profile AND on the
``final_profile`` saved in ``<run>/<persona>.json`` (``retrieval_eval.evaluate_run``),
and prints one row per mode × {gold, e2e}. ``--write-extra`` lists, per persona, the
top-10 picks (any mode, gold or e2e) outside ``judged_unitids``, checks them against
H1–H4 (``labels/pool.py``), and writes ``labels/pools/<id>.extra.csv`` (passing rows,
pool CSV format, for a blind top-up labeling pass) + ``<id>.extra.meta.yaml``.

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
for _p in (str(BACKEND), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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


async def _rescore(args: argparse.Namespace, database_url: str) -> None:
    """``--from-run``: gold + e2e (saved ``final_profile``) for every mode, no LLM."""
    import json

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from evals.common import load_personas as load_full_personas
    from evals.report import resolve_run
    from evals.retrieval_eval import evaluate_run, score_retrieval

    labels = load_labels(args.labels)
    raw_labels = yaml.safe_load(Path(args.labels).read_text()) or {}
    modes = tuple(args.modes.split(",")) if args.modes else DEFAULT_MODES
    personas = [
        p for p in load_full_personas(args.personas) if p.id in labels and labels[p.id].acceptable
    ]
    run_dir = resolve_run(args.from_run)
    results = []
    for p in personas:
        f = run_dir / f"{p.id}.json"
        if f.exists():
            doc = json.loads(f.read_text())
            results.append({"persona": p.id, "final_profile": doc.get("final_profile")})
        else:
            log.warning("no_saved_run", persona=p.id, run=str(run_dir))
    engine = create_async_engine(database_url)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        retrieval = await evaluate_run(
            results,
            personas,
            sm,
            default_embedder(),
            k=args.k,
            modes=modes,  # type: ignore[arg-type]
        )
        print(format_rescore(score_retrieval(retrieval, labels), args.k))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(retrieval, indent=1))
        if args.write_extra:
            async with AsyncSession(engine) as session:
                await _write_extras(session, personas, retrieval, labels, raw_labels, args)
    finally:
        await engine.dispose()


def format_rescore(rows: list[dict[str, Any]], k: int = 10) -> str:
    def f(v: float | None) -> str:
        return "–" if v is None else f"{v:.3f}"

    lines = [
        f"| mode | profile | recall@{k} | nDCG@{k} | judged-P@{k} | unjudged@{k} | n |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("note"):
            lines.append(f"| {r['mode']} | – | – | – | – | – | 0 ({r['note']}) |")
            continue
        lines.append(
            f"| {r['mode']} | {r['profile']} | {f(r['recall'])} | {f(r['ndcg'])} | "
            f"{f(r['judged_precision'])} | {r['unjudged']} | {r['n']} |"
        )
    return "\n".join(lines)


async def _write_extras(
    session: AsyncSession,
    personas: list[Any],
    retrieval: dict[str, Any],
    labels: dict[str, Label],
    raw_labels: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    from evals.labels.pool import (
        MAJOR_SETS,
        RAW_INSTITUTIONS,
        RawInstitutions,
        extra_rows,
        load_major_sets,
        write_extra,
    )

    raw = RawInstitutions.load(Path(args.raw_institutions or RAW_INSTITUTIONS))
    major_sets = load_major_sets(MAJOR_SETS)
    k = int(retrieval.get("k", args.k))
    print("\n### Top-10 picks outside judged_unitids (any mode, gold or e2e)\n")
    print("| persona | extra | pass H1–H4 | csv |")
    print("|---|---|---|---|")
    details: list[str] = []
    for p in personas:
        entry = retrieval["personas"].get(p.id, {})
        picked_by: dict[int, list[str]] = {}
        for kind in ("gold", "e2e"):
            for mode, ids in (entry.get(kind) or {}).items():
                for uid in ids[:k]:
                    if uid not in labels[p.id].judged:
                        picked_by.setdefault(int(uid), []).append(f"{mode}/{kind}")
        relaxed = "budget" in ((raw_labels.get(p.id) or {}).get("relaxed") or [])
        rows, failed = await extra_rows(
            p, major_sets.get(p.id, []), set(picked_by), relaxed, session, raw
        )
        names = {r["unitid"]: r["name"] for r in rows} | {x["unitid"]: x["name"] for x in failed}
        meta = {
            "persona": p.id,
            "n_extra": len(picked_by),
            "n_pass_h1_h4": len(rows),
            "relaxed": ["budget"] if relaxed else [],
            "passing": sorted(r["unitid"] for r in rows),
            "auto_judged": failed,
            "picked_by": {u: picked_by[u] for u in sorted(picked_by)},
        }
        path = write_extra(p.id, rows, meta)
        print(f"| {p.id} | {len(picked_by)} | {len(rows)} | {path.relative_to(REPO)} |")
        passing = {r["unitid"] for r in rows}
        for uid in sorted(picked_by):
            ok = "PASS" if uid in passing else "fail"
            details.append(f"- {p.id} {uid} {names.get(uid)} [{ok}] ({', '.join(picked_by[uid])})")
    print("\n" + "\n".join(details))


async def _main(args: argparse.Namespace) -> None:
    if args.from_run:
        await _rescore(args, args.database_url or get_settings().DATABASE_URL)
        return
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
    ap.add_argument("--from-run", default="", help="run dir/id with <persona>.json (e2e)")
    ap.add_argument("--write-extra", action="store_true", help="with --from-run")
    ap.add_argument("--json-out", default="", help="with --from-run: write top-k lists")
    ap.add_argument("--raw-institutions", default="", help="Scorecard CSV (for H2 tuition)")
    asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    main()
