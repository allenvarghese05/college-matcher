"""Report aggregation (evals/report.py) on a synthetic run directory."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.ablation import Label  # noqa: E402
from evals.report import build_report, check_gates, resolve_run  # noqa: E402
from evals.retrieval_eval import score_retrieval  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MAYA = str(REPO / "evals" / "personas" / "maya-oh.yaml")


def _stage(ms: float, cost: float) -> dict[str, object]:
    return {"ms": ms, "cost_usd": cost, "model": "m", "input_tokens": 1, "output_tokens": 1}


def _persona_result(pid: str, n_claims: int, n_verified: int, status: str = "ok") -> dict:
    return {
        "persona": pid,
        "persona_path": MAYA,
        "status": status,
        "n_turns": 2,
        "turns": [
            {
                "counselor": "What state do you live in?",
                "sim": {"ms": 50.0, "cost_usd": 0.0, "guard": {}},
                "stages": {"extract": _stage(100, 0.004), "reply_total": _stage(300, 0.006)},
            },
            {
                "counselor": "Do you know your GPA?",
                "sim": {"ms": 70.0, "cost_usd": 0.0, "guard": {}},
                "stages": {"extract": _stage(200, 0.004), "reply_total": _stage(500, 0.006)},
            },
        ],
        "final_profile": {
            "home_state": {"value": "OH", "confidence": 0.9, "evidence": []},
            "gpa": {"value": 3.6, "confidence": 0.9, "evidence": []},
        },
        "next_topics": ["location", "academics"],
        "recommendations": [{"unitid": 1}, {"unitid": 2}],
        "groundedness": {"n_claims": n_claims, "n_verified": n_verified, "groundedness": 0.9},
        "hallucinated_schools": 0,
        "recommend_stages": {"retrieve": _stage(40, 0), "recommend": _stage(9000, 0.13)},
        "totals": {"cost_usd": 0.15},
    }


def _run_dir(tmp: Path) -> Path:
    d = tmp / "results" / "r1"
    d.mkdir(parents=True)
    (d / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "r1",
                "mode": "replay",
                "transport": "anthropic",
                "statuses": {"ok": 2},
                "cost_usd": 0.30,
                "guard": {"messages": 4, "multi_leaks": 1},
                "cassette_provenance": {"transport": "fake"},
                "models": {"reply": "claude-sonnet-5-5", "recommend": "claude-opus-5-5"},
            }
        )
    )
    (d / "maya-oh.json").write_text(json.dumps(_persona_result("maya-oh", 10, 10)))
    other = _persona_result("other-oh", 10, 8)
    (d / "other-oh.json").write_text(json.dumps(other))
    (d / "retrieval.json").write_text(
        json.dumps(
            {
                "k": 10,
                "modes": ["sql_only", "hybrid_rerank"],
                "not_implemented": ["hybrid_riasec_rerank"],
                "personas": {
                    "maya-oh": {
                        "gold": {"sql_only": [1, 2, 3], "hybrid_rerank": [4, 1, 9]},
                        "e2e": {"sql_only": [3], "hybrid_rerank": [9, 8]},
                    }
                },
            }
        )
    )
    return d


def test_score_retrieval_rows() -> None:
    doc = {
        "k": 10,
        "modes": ["hybrid_rerank"],
        "personas": {"p": {"gold": {"hybrid_rerank": [1, 2, 5]}, "e2e": {"hybrid_rerank": [5]}}},
    }
    rows = score_retrieval(doc, {"p": Label(acceptable={1, 2}, judged={1, 2, 3})})
    gold = next(r for r in rows if r["profile"] == "gold")
    e2e = next(r for r in rows if r["profile"] == "e2e")
    assert gold["recall"] == 1.0 and gold["unjudged"] == 1 and gold["judged_precision"] == 1.0
    assert e2e["recall"] == 0.0 and e2e["judged_precision"] is None and e2e["n"] == 1


def test_build_report_aggregates(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    labels = tmp_path / "labels.yaml"
    labels.write_text(
        yaml.safe_dump(
            {
                "_meta": {"criteria_commit": "x"},
                "maya-oh": {
                    "acceptable_unitids": [1, 4],
                    "judged_unitids": [1, 2, 3, 4],
                    "notes": "",
                    "labeled_at": "2026-11-21",
                },
            }
        )
    )
    md, m = build_report(run, labels)
    assert m["groundedness"]["n_claims"] == 20 and m["groundedness"]["value"] == 0.9
    assert m["hallucinated"]["rate"] == 0.0
    assert m["latency_ms"]["extract"]["p50"] == 150.0  # [100, 100, 200, 200]
    assert m["latency_ms"]["reply_total"]["p95"] == 500.0
    assert m["latency_ms"]["recommend"]["n"] == 2
    assert m["cost"]["per_session_mean"] == 0.15
    assert abs(m["cost"]["per_turn_mean"] - 0.01) < 1e-9
    assert m["labeled_personas"] == ["maya-oh"]
    hr = {(r["mode"], r["profile"]): r for r in m["retrieval"]}
    assert hr[("hybrid_rerank", "gold")]["recall"] == 1.0
    assert hr[("hybrid_rerank", "e2e")]["recall"] == 0.0
    assert hr[("sql_only", "gold")]["recall"] == 0.5
    assert m["extraction"]["overall"]["tp"] == 4  # home_state + gpa, twice
    assert "**0.900** (18/20)" in md
    assert "offline fake counselor" in md  # replayed fake cassettes are flagged
    assert "hybrid_riasec_rerank | – " in md
    assert "Internal benchmark, not ground truth" in md
    assert "Single labeler" in md
    assert check_gates(m, 0.95, True) == ["groundedness 0.900 < 0.95"]
    assert check_gates(m, 0.85, True) == []
    assert resolve_run("latest", tmp_path / "results") == run


def test_gates_require_claims_and_completion(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    (run / "maya-oh.json").write_text(json.dumps(_persona_result("maya-oh", 0, 0, "error")))
    (run / "other-oh.json").write_text(json.dumps(_persona_result("other-oh", 0, 0, "error")))
    summary = json.loads((run / "summary.json").read_text())
    summary["statuses"] = {"error": 2}
    summary["aborted"] = "budget guard: ..."
    (run / "summary.json").write_text(json.dumps(summary))
    _, m = build_report(run, None)
    fails = check_gates(m, 0.95, True)
    assert "no claims to check groundedness on" in fails
    assert any("aborted" in f for f in fails) and any("errored" in f for f in fails)
