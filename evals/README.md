# Eval harness

SPEC §10. Everything runs from `backend/` with `uv run`, or through `make`.

| Command | What it does | Cost |
|---|---|---|
| `make eval-replay` | 3 personas, scripted student, committed cassettes (`backend/tests/cassettes/evals`), fixture DB `matcher_evalsmoke_test`. Fails if a persona errors (incl. a stale cassette) or groundedness < 0.95. Runs in CI. | $0 |
| `make eval-record-smoke` | Rebuilds those cassettes offline (`--transport fake`, a heuristic stand-in for Claude). Re-run after any prompt / request / retrieval change. | $0 |
| `CONFIRM=1 make eval-live` | All personas against real Claude, Ollama student by default, recorded to `evals/recordings` (replayable). Prints a cost estimate first; budget guard `EVAL_MAX_COST` (default $8). Uses the dev DB (`--allow-dev-db`). Writes `docs/results.md`. | ~$7.5 |
| `make pool RUNS=<run_id>` | Candidate pools for labeling (`evals/labels/pools/`). Needs `evals/labels/major_sets.yaml` (criteria pass 1). | $0 |
| `make label` | Terminal labeling tool -> `evals/labels/labels.yaml`. | $0 |
| `uv run python ../evals/report.py --run <id>` | Aggregates a run into `docs/results.md`. | $0 |

Modules: `simulator.py` (student: ollama / claude / scripted + leak guard), `run.py`
(personas through the real orchestrator), `metrics_extraction.py`, `retrieval_eval.py`,
`topics.py` (question-topic heuristics), `labels/pool.py`, `labels/label.py`,
`report.py`, `fake_counselor.py` (offline cassette builder), `db_setup.py`.

## Known approximations

- **H3 home location.** There is no ZIP geocoding table in the project, so `pool.py`
  places the student at the mean lat/long of Scorecard institutions in the same ZIP5,
  else the same ZIP3, else the home state's population centre (`app.retrieval.geo`).
  Distances near the `max_distance_miles × 1.10` cutoff can be off by tens of miles
  (more in large rural states). The retriever measures from the state centre, so the
  two can disagree near the cutoff.
- **H2 tuition** comes from the raw Scorecard CSV (`data/raw/scorecard/`), falling back to
  the DB's `tuition_in_state` / `tuition_out_of_state` when the CSV is absent.
  Reciprocity prices are applied by hand.
- **Questions-asked coverage** is keyword matching on the counselor's question
  sentences (`topics.py`), not NLU.
