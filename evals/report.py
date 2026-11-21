"""Aggregate one eval run into ``docs/results.md`` (the README results table).

Pure file aggregation (no DB, no network): reads ``evals/results/<run_id>/*.json``,
``retrieval.json`` and ``evals/labels/labels.yaml`` (if present), writes the markdown
report plus ``metrics.json`` into the run directory.

    uv run python ../evals/report.py --run latest            # newest run
    uv run python ../evals/report.py --run <run_id> --out ../docs/results.md \
        --min-groundedness 0.95 --require-complete           # CI gate

Exit status 1 when a gate fails: groundedness below ``--min-groundedness`` (or no
claims at all), or with ``--require-complete`` any persona errored / the run aborted.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [p for p in (str(_REPO), str(_REPO / "backend")) if p not in sys.path]

import argparse  # noqa: E402
import json  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402

import yaml  # noqa: E402

from evals.ablation import Label, load_labels  # noqa: E402
from evals.common import (  # noqa: E402
    DEFAULT_LABELS,
    REPO,
    RESULTS_DIR,
    load_persona,
    percentile,
)
from evals.metrics_extraction import aggregate_extraction  # noqa: E402
from evals.retrieval_eval import score_retrieval  # noqa: E402

STAGE_ORDER = (
    "sim",
    "extract",
    "reply_ttft",
    "reply_total",
    "retrieve",
    "retrieve.major_match",
    "retrieve.sql_filter",
    "retrieve.rerank",
    "recommend",
    "groundedness",
)
HEADLINE_MODE = "hybrid_rerank"


@dataclass
class RunData:
    run_dir: Path
    summary: dict[str, Any]
    results: list[dict[str, Any]]
    retrieval: dict[str, Any] | None


def resolve_run(run: str, results_dir: Path = RESULTS_DIR) -> Path:
    p = Path(run)
    if p.is_dir():
        return p
    if run == "latest":
        runs = sorted(
            (d for d in results_dir.iterdir() if (d / "summary.json").exists()),
            key=lambda d: (d / "summary.json").stat().st_mtime,
        )
        if not runs:
            raise SystemExit(f"no runs in {results_dir}")
        return runs[-1]
    if (results_dir / run).is_dir():
        return results_dir / run
    raise SystemExit(f"run not found: {run}")


def load_run(run_dir: Path) -> RunData:
    summary = json.loads((run_dir / "summary.json").read_text())
    results = []
    for p in sorted(run_dir.glob("*.json")):
        if p.name in ("summary.json", "retrieval.json", "metrics.json"):
            continue
        results.append(json.loads(p.read_text()))
    rpath = run_dir / "retrieval.json"
    retrieval = json.loads(rpath.read_text()) if rpath.exists() else None
    return RunData(run_dir, summary, results, retrieval)


def _hidden(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for r in results:
        path = r.get("persona_path")
        if path and Path(path).exists():
            out[r["persona"]] = load_persona(path).hidden
        else:
            guess = REPO / "evals" / "personas" / f"{r['persona']}.yaml"
            if guess.exists():
                out[r["persona"]] = load_persona(guess).hidden
    return out


def compute_metrics(data: RunData, labels: dict[str, Label]) -> dict[str, Any]:
    res = data.results
    ok = [r for r in res if r.get("status") == "ok"]
    n_claims = sum((r.get("groundedness") or {}).get("n_claims", 0) for r in ok)
    n_verified = sum((r.get("groundedness") or {}).get("n_verified", 0) for r in ok)
    n_recs = sum(len(r.get("recommendations") or []) for r in ok)
    halluc = sum(r.get("hallucinated_schools", 0) for r in ok)
    digit_viol = sum((r.get("groundedness") or {}).get("reason_digit_violations", 0) for r in ok)

    stages: dict[str, list[float]] = {}
    turn_costs: list[float] = []
    rec_costs: list[float] = []
    for r in res:
        for t in r.get("turns", []):
            if t.get("sim", {}).get("ms") is not None:
                stages.setdefault("sim", []).append(float(t["sim"]["ms"]))
            for name, s in (t.get("stages") or {}).items():
                stages.setdefault(name, []).append(float(s["ms"]))
            turn_costs.append(sum((s.get("cost_usd") or 0.0) for s in t.get("stages", {}).values()))
        if r.get("recommend_stages"):
            for name, s in r["recommend_stages"].items():
                stages.setdefault(name, []).append(float(s["ms"]))
            rec_costs.append(
                sum((s.get("cost_usd") or 0.0) for s in r["recommend_stages"].values())
            )
    latency = {
        name: {
            "n": len(v),
            "p50": percentile(v, 50),
            "p95": percentile(v, 95),
        }
        for name, v in sorted(
            stages.items(),
            key=lambda kv: (
                STAGE_ORDER.index(kv[0]) if kv[0] in STAGE_ORDER else len(STAGE_ORDER),
                kv[0],
            ),
        )
    }
    sessions = [r for r in res if r.get("totals")]
    costs = [r["totals"]["cost_usd"] for r in sessions]
    turns = [r.get("n_turns", len(r.get("turns", []))) for r in sessions]
    extraction = aggregate_extraction(res, _hidden(res))
    retrieval_rows = score_retrieval(data.retrieval, labels) if data.retrieval else []
    labeled = sorted(
        pid
        for pid in (data.retrieval or {}).get("personas", {})
        if pid in labels and labels[pid].acceptable
    )
    return {
        "run_id": data.summary.get("run_id"),
        "n_personas": len(res),
        "statuses": data.summary.get("statuses", {}),
        "aborted": data.summary.get("aborted"),
        "groundedness": {
            "value": (n_verified / n_claims) if n_claims else None,
            "n_claims": n_claims,
            "n_verified": n_verified,
            "per_session_min": min(
                ((r.get("groundedness") or {}).get("groundedness", 1.0) for r in ok), default=None
            ),
            "reason_digit_violations": digit_viol,
        },
        "hallucinated": {
            "n": halluc,
            "n_recs": n_recs,
            "rate": halluc / n_recs if n_recs else None,
        },
        "extraction": extraction.to_dict(),
        "retrieval": retrieval_rows,
        "labeled_personas": labeled,
        "cost": {
            "total_usd": data.summary.get("cost_usd", sum(costs)),
            "counselor_usd": data.summary.get("counselor_cost_usd"),
            "sim_usd": data.summary.get("sim_cost_usd"),
            "per_session_mean": sum(costs) / len(costs) if costs else None,
            "per_turn_mean": sum(turn_costs) / len(turn_costs) if turn_costs else None,
            "per_recommendation_mean": sum(rec_costs) / len(rec_costs) if rec_costs else None,
        },
        "turns": {
            "mean": sum(turns) / len(turns) if turns else None,
            "max": max(turns) if turns else None,
        },
        "latency_ms": latency,
        "guard": data.summary.get("guard", {}),
    }


# ------------------------------------------------------------------ markdown


def _f(v: Any, nd: int = 3) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _usd(v: Any, nd: int = 4) -> str:
    return "–" if v is None else f"${v:.{nd}f}"


def _model_labeled(m: dict[str, Any]) -> bool:
    return m.get("labeler", "project owner") != "project owner"


def _labeler_short(m: dict[str, Any]) -> str:
    if _model_labeled(m):
        return "relevance labels judged by an LLM (not a human)"
    return "a single labeler who also built the system"


def _labeler_caveat(m: dict[str, Any]) -> str:
    if _model_labeled(m):
        return (
            f"- **LLM-judged labels** — {m['labeler']}. Pass 1 major sets were drafted by the "
            "assistant from each persona file and reviewed by the project owner; pass 2 fit "
            "scores (S1) were assigned by the model blind (shuffled pool, no source, rank or "
            "score) under the frozen rubric, with a one-line rationale per school in "
            "`evals/labels/rationales/`. The judge is the same model family as the "
            "recommender, so self-preference bias is possible; no human agreement is reported."
        )
    return (
        "- **Single labeler** — the project owner, who also built the system; no inter-rater "
        "agreement unless reported separately."
    )


def render(m: dict[str, Any], summary: dict[str, Any]) -> str:
    g = m["groundedness"]
    ex = m["extraction"]
    prov = summary.get("cassette_provenance") or {}
    fake = summary.get("transport") == "fake" or (
        summary.get("mode") == "replay" and prov.get("transport") == "fake"
    )
    replay = summary.get("mode") == "replay"
    lines: list[str] = []
    a = lines.append
    a("# College Matcher v2 — eval results")
    a("")
    a(
        "> **Internal benchmark, not ground truth.** Simulated students (made-up personas), "
        f"{_labeler_short(m)}, and Scorecard data limits. See Caveats."
    )
    a("")
    models = summary.get("models", {})
    a(
        f"Run `{m['run_id']}` · mode **{summary.get('mode')}** · transport "
        f"`{summary.get('transport')}` · simulator `{summary.get('sim_model')}` · reply/extract "
        f"`{models.get('reply')}` · recommend `{models.get('recommend')}` · embedder "
        f"`{summary.get('embedder')}` · git `{str(summary.get('git_sha', ''))[:10]}` · "
        f"{str(summary.get('finished_at', ''))[:10]}"
    )
    a("")
    st = ", ".join(f"{k} {v}" for k, v in sorted(m["statuses"].items()))
    a(
        f"Personas: **{m['n_personas']}** ({st})"
        + (f" — **ABORTED**: {m['aborted']}" if m["aborted"] else "")
    )
    a("")
    if fake:
        a(
            "> **Note:** this run used the **offline fake counselor** (`--transport fake`, "
            "directly or via cassettes recorded with it). It "
            "exercises the harness end to end; the numbers say nothing about Claude's quality."
        )
        a("")

    head = next(
        (r for r in m["retrieval"] if r.get("mode") == HEADLINE_MODE and r["profile"] == "gold"),
        None,
    )
    head_e2e = next(
        (r for r in m["retrieval"] if r.get("mode") == HEADLINE_MODE and r["profile"] == "e2e"),
        None,
    )
    a("## Headline")
    a("")
    a("| Metric | Value |")
    a("|---|---|")
    a(
        f"| **Groundedness** (verified claims / all claims) — lead metric | "
        f"**{_f(g['value'])}** ({g['n_verified']}/{g['n_claims']}) |"
    )
    h = m["hallucinated"]
    a(
        f"| Hallucinated-school rate (recs not in retrieved set) | {_f(h['rate'])} "
        f"({h['n']}/{h['n_recs']}) |"
    )
    o = ex["overall"]
    a(
        f"| Extraction precision / recall (micro, all fields) | {_f(o['precision'])} / "
        f"{_f(o['recall'])} |"
    )
    osig = ex.get("overall_interest_signal")
    if osig:
        a(
            "| Extraction precision / recall (micro, `interests` scored as interest signal "
            f"across fields — see Caveats) | {_f(osig['precision'])} / {_f(osig['recall'])} |"
        )
    a(
        f"| Questions-asked coverage (planned via next_topic) | {_f(ex['coverage'])} "
        f"({_f(ex['planned_coverage'])}) |"
    )
    if head and head.get("n"):
        a(
            f"| recall@10 gold / e2e ({HEADLINE_MODE}) | {_f(head['recall'])} / "
            f"{_f(head_e2e['recall'] if head_e2e else None)} |"
        )
    else:
        a(f"| recall@10 gold / e2e ({HEADLINE_MODE}) | – (no labels yet) |")
    ok = m["statuses"].get("ok", 0)
    a(f"| Sessions reaching recommendations | {ok}/{m['n_personas']} |")
    a(f"| Turns per session (mean / max) | {_f(m['turns']['mean'], 1)} / {_f(m['turns']['max'])} |")
    c = m["cost"]
    a(f"| Cost per session (mean) | {_usd(c['per_session_mean'])} |")
    gd = m["guard"]
    a(
        f"| Simulator guard: multi-leak messages / character breaks / unasked reveals | "
        f"{gd.get('multi_leaks', 0)} / {gd.get('character_breaks', 0)} / "
        f"{gd.get('unasked_reveals', 0)} (of {gd.get('messages', 0)} messages) |"
    )
    a("")

    a("## Retrieval: gold profile vs end-to-end (ablation)")
    a("")
    n_lab = len(m["labeled_personas"])
    a(
        f"Scored against `evals/labels/labels.yaml` ({n_lab} labeled persona(s) with a "
        "non-empty acceptable set). Unjudged top-10 schools count as non-hits; judged-P@10 "
        "is precision among judged schools only. The gold − e2e gap is what extraction loses."
    )
    a("")
    a(
        "| mode | recall@10 gold | recall@10 e2e | nDCG@10 gold | nDCG@10 e2e | "
        "judged-P@10 gold | judged-P@10 e2e | unjudged@10 gold / e2e | n |"
    )
    a("|---|---|---|---|---|---|---|---|---|")
    by_mode: dict[str, dict[str, dict[str, Any]]] = {}
    for r in m["retrieval"]:
        by_mode.setdefault(r["mode"], {})[r["profile"]] = r
    for mode, rows in by_mode.items():
        if "-" in rows:
            a(f"| {mode} | – | – | – | – | – | – | – | 0 (not implemented) |")
            continue
        gr, er = rows.get("gold", {}), rows.get("e2e", {})
        a(
            f"| {mode} | {_f(gr.get('recall'))} | {_f(er.get('recall'))} | {_f(gr.get('ndcg'))} | "
            f"{_f(er.get('ndcg'))} | {_f(gr.get('judged_precision'))} | "
            f"{_f(er.get('judged_precision'))} | {gr.get('unjudged', 0)} / "
            f"{er.get('unjudged', 0)} | "
            f"{gr.get('n', 0)} / {er.get('n', 0)} |"
        )
    if not by_mode:
        a("| (no retrieval.json in this run) | | | | | | | | |")
    a("")

    a("## Extraction per field")
    a("")
    a("| field | precision | recall | TP | FP | FN |")
    a("|---|---|---|---|---|---|")
    rows = list(ex["per_field"].items())
    if ex.get("interest_signal"):
        i = next((n for n, (name, _) in enumerate(rows) if name == "interests"), len(rows) - 1)
        rows.insert(i + 1, ("interests (any field)", ex["interest_signal"]))
    for name, cnt in rows:
        if cnt["tp"] or cnt["fp"] or cnt["fn"]:
            a(
                f"| {name} | {_f(cnt['precision'])} | {_f(cnt['recall'])} | {cnt['tp']} | "
                f"{cnt['fp']} | {cnt['fn']} |"
            )
    if ex.get("interest_signal"):
        a("")
        a(
            "`interests (any field)`: a hidden interest counts as recovered if it fuzzy-matches "
            "an extracted item in interests, strengths, activity names, the dream answer or "
            'favorite subjects (the extractor often files "good at drawing" under strengths). '
            "The strict `interests` row above is unchanged."
        )
    a("")

    a("## Cost and latency")
    a("")
    a(
        f"Total {_usd(c['total_usd'])} (counselor {_usd(c['counselor_usd'])}, simulator "
        f"{_usd(c['sim_usd'])}); per turn {_usd(c['per_turn_mean'])} (Sonnet reply + "
        f"extraction); per recommendation {_usd(c['per_recommendation_mean'])} (Opus + "
        "retrieval + groundedness)."
    )
    a("")
    a("| stage | n | p50 ms | p95 ms |")
    a("|---|---|---|---|")
    for name, v in m["latency_ms"].items():
        a(f"| {name} | {v['n']} | {_f(v['p50'], 1)} | {_f(v['p95'], 1)} |")
    a("")
    if replay:
        a(
            "> Replay mode: Claude latencies above are cassette playback, not API timings, and "
            "costs are the token usage recorded in the cassettes."
        )
        a("")

    a("## Per persona")
    a("")
    a("| persona | status | turns | groundedness | extraction P / R | coverage | cost |")
    a("|---|---|---|---|---|---|---|")
    pp = ex["per_persona"]
    for r in m.get("_results", []):
        pid = r["persona"]
        e = pp.get(pid, {})
        ov = e.get("overall", {})
        qa = e.get("questions_asked", {})
        gr = (r.get("groundedness") or {}).get("groundedness")
        a(
            f"| {pid} | {r.get('status')} | {r.get('n_turns', len(r.get('turns', [])))} | "
            f"{_f(gr)} | {_f(ov.get('precision'))} / {_f(ov.get('recall'))} | "
            f"{_f(qa.get('coverage'))} | {_usd((r.get('totals') or {}).get('cost_usd'))} |"
        )
    a("")

    a("## Caveats")
    a("")
    a(
        "- **Internal benchmark, not ground truth.** Labels follow the frozen protocol in "
        "`evals/labels/criteria.md` (TREC-style pooling, hard criteria H1–H4, soft rubric S1)."
    )
    a(_labeler_caveat(m))
    a(f"- **Simulated students.** Personas are invented. {sim_caveat(summary)}")
    a(
        "- **Heuristic coverage.** Questions-asked coverage uses keyword matching on the "
        "counselor's question sentences (`evals/topics.py`)."
    )
    a(
        "- **Interest signal is a lenient, secondary score.** `interests (any field)` and the "
        "matching micro totals credit a hidden interest found in strengths, activities, the "
        "dream answer or favorite subjects; strict per-field scoring stays the headline. "
        "Rule: `evals/README.md` (Extraction metrics)."
    )
    a(
        "- **Data limits.** Scorecard public net price is in-state; program earnings are "
        "missing for many programs; SAT/ACT ranges exist for under half of schools."
    )
    a("- **Small n.** Edge cases with n = 1 (hannah, megan, bella) are anecdotes, not rates.")
    a("")
    return "\n".join(lines) + "\n"


def sim_caveat(summary: dict[str, Any]) -> str:
    sim = summary.get("sim")
    model = summary.get("sim_model")
    guard = " The leak guard counts simulator slips (Headline)."
    if sim == "ollama":
        return (
            f"The student is played by a local model (`{model}` via Ollama), a different "
            "model family from the Claude counselor, which makes self-flattering scores less "
            "likely." + guard
        )
    if sim == "claude":
        return (
            "The student is played by Claude (Sonnet), the **same model family** as the "
            "counselor, so scores may be flattering; prefer an Ollama-simulated run." + guard
        )
    return (
        "The student is a deterministic scripted template (no model): it answers exactly "
        "what is asked, so extraction and coverage numbers are upper bounds." + guard
    )


def check_gates(
    m: dict[str, Any], min_groundedness: float | None, require_complete: bool
) -> list[str]:
    failures: list[str] = []
    g = m["groundedness"]
    if min_groundedness is not None:
        if not g["n_claims"]:
            failures.append("no claims to check groundedness on")
        elif g["value"] < min_groundedness:
            failures.append(f"groundedness {g['value']:.3f} < {min_groundedness}")
    if require_complete:
        if m["aborted"]:
            failures.append(f"run aborted: {m['aborted']}")
        if m["statuses"].get("error"):
            failures.append(f"{m['statuses']['error']} persona(s) errored")
    return failures


def _labeler(labels_path: Path | None) -> str:
    """Who labeled (``_meta.labeler`` in labels.yaml); the project owner by default."""
    if not labels_path or not Path(labels_path).exists():
        return "project owner"
    doc = yaml.safe_load(Path(labels_path).read_text()) or {}
    return str((doc.get("_meta") or {}).get("labeler") or "project owner")


def build_report(
    run_dir: Path, labels_path: Path | None = DEFAULT_LABELS
) -> tuple[str, dict[str, Any]]:
    data = load_run(run_dir)
    labels = load_labels(labels_path) if labels_path and Path(labels_path).exists() else {}
    m = compute_metrics(data, labels)
    m["labeler"] = _labeler(labels_path)
    m["_results"] = data.results
    md = render(m, data.summary)
    m.pop("_results")
    return md, m


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default="latest", help="run dir, run id, or 'latest'")
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "results.md")
    ap.add_argument("--min-groundedness", type=float, default=None)
    ap.add_argument("--require-complete", action="store_true")
    a = ap.parse_args(argv)
    run_dir = resolve_run(a.run, a.results_dir)
    md, m = build_report(run_dir, a.labels)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(md)
    (run_dir / "metrics.json").write_text(json.dumps(m, indent=2, default=str) + "\n")
    g = m["groundedness"]
    print(f"wrote {a.out} (groundedness={_f(g['value'])} claims={g['n_claims']})")
    failures = check_gates(m, a.min_groundedness, a.require_complete)
    for f in failures:
        print(f"GATE FAILED: {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
