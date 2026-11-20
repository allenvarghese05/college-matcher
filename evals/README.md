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
- **Planned coverage** reads `profile_snapshot.next_topic`, which (since
  `counselor_reply.v2`) is the topic the deterministic planner steered each reply to
  (`app.counselor.context.plan_next_topic`), not the extractor's suggestion.

## Extraction metrics

Strict per-field scoring is the headline (`metrics_extraction.py` docstring: scalar
tolerances, one-to-one fuzzy matching for free-text lists, exact enum lists).

**Interest signal** (secondary, clearly labelled). Strict `interests` undercounts: the
extractor reasonably files "i'm good at drawing" under `strengths` and "fixing bikes"
under `activities`. The report therefore adds a row `interests (any field)`:

- a hidden `interests` item is **recovered** (TP) if it fuzzy-matches (same rule as other
  free-text lists, one-to-one) any extracted item in `interests` ∪ `strengths` ∪
  `activities[].name` ∪ `dream_without_money` ∪ `favorite_subjects`; otherwise FN;
- an extracted `interests` item left unmatched is an FP only if it also matches nothing
  in the hidden profile's same five fields;
- hidden `interests` absent or `[]`: strict rule.

It also reports micro totals with that row substituted for strict `interests`
("interests scored as interest signal"). The strict `interests` row and the strict
micro totals are unchanged. Example (live-pilot-1, maya-oh): hidden
[drawing, fixing bikes, how things are built]; extracted interests [designing things,
art], strengths [drawing, figuring out how stuff works], activities [robotics club,
part-time job at a bike shop fixing bikes] -> strict TP 0 / FP 2 / FN 3, interest
signal TP 2 / FP 0 / FN 1 ("how things are built" is not recovered).
