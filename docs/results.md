# College Matcher v2 — eval results

> **Internal benchmark, not ground truth.** Simulated students (made-up personas), a single labeler who also built the system, and Scorecard data limits. See Caveats.

Run `replay-smoke` · mode **replay** · transport `anthropic` · simulator `scripted` · reply/extract `claude-sonnet-5-5` · recommend `claude-opus-5-5` · embedder `fake-hash-bow-v1` · git `a92395eef8` · 2026-11-20

Personas: **3** (ok 3)

> **Note:** this run used the **offline fake counselor** (`--transport fake`, directly or via cassettes recorded with it). It exercises the harness end to end; the numbers say nothing about Claude's quality.

## Headline

| Metric | Value |
|---|---|
| **Groundedness** (verified claims / all claims) — lead metric | **1.000** (76/76) |
| Hallucinated-school rate (recs not in retrieved set) | 0.000 (0/26) |
| Extraction precision / recall (micro, all fields) | 1.000 / 0.694 |
| Questions-asked coverage (planned via next_topic) | 0.826 (0.826) |
| recall@10 gold / e2e (hybrid_rerank) | – (no labels yet) |
| Sessions reaching recommendations | 3/3 |
| Turns per session (mean / max) | 8.0 / 8 |
| Cost per session (mean) | $0.1120 |
| Simulator guard: multi-leak messages / character breaks / unasked reveals | 0 / 0 / 0 (of 24 messages) |

## Retrieval: gold profile vs end-to-end (ablation)

Scored against `evals/labels/labels.yaml` (0 labeled persona(s) with a non-empty acceptable set). Unjudged top-10 schools count as non-hits; judged-P@10 is precision among judged schools only. The gold − e2e gap is what extraction loses.

| mode | recall@10 gold | recall@10 e2e | nDCG@10 gold | nDCG@10 e2e | judged-P@10 gold | judged-P@10 e2e | unjudged@10 gold / e2e | n |
|---|---|---|---|---|---|---|---|---|
| sql_only | – | – | – | – | – | – | 0 / 0 | 0 / 0 |
| hybrid | – | – | – | – | – | – | 0 / 0 | 0 / 0 |
| hybrid_rerank | – | – | – | – | – | – | 0 / 0 | 0 / 0 |
| hybrid_riasec_rerank | – | – | – | – | – | – | – | 0 (not implemented) |

## Extraction per field

| field | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| home_state | 1.000 | 1.000 | 3 | 0 | 0 |
| home_zip | 1.000 | 1.000 | 3 | 0 | 0 |
| gpa | 1.000 | 1.000 | 2 | 0 | 0 |
| sat | 1.000 | 1.000 | 2 | 0 | 0 |
| income_bracket | 1.000 | 1.000 | 3 | 0 | 0 |
| budget_cap | 1.000 | 1.000 | 3 | 0 | 0 |
| interests | 1.000 | 1.000 | 12 | 0 | 0 |
| dream_without_money | 1.000 | 1.000 | 3 | 0 | 0 |
| intended_majors | 1.000 | 1.000 | 4 | 0 | 0 |
| strengths | 1.000 | 1.000 | 9 | 0 | 0 |
| favorite_subjects | – | 0.000 | 0 | 0 | 6 |
| activities | – | 0.000 | 0 | 0 | 8 |
| work_values | – | 0.000 | 0 | 0 | 6 |
| max_distance_miles | 1.000 | 1.000 | 3 | 0 | 0 |
| regions | 1.000 | 1.000 | 6 | 0 | 0 |
| size_pref | 1.000 | 1.000 | 3 | 0 | 0 |
| setting_pref | 1.000 | 1.000 | 3 | 0 | 0 |
| priorities | – | 0.000 | 0 | 0 | 6 |

## Cost and latency

Total $0.3361 (counselor $0.3361, simulator $0.0000); per turn $0.0091 (Sonnet reply + extraction); per recommendation $0.0395 (Opus + retrieval + groundedness).

| stage | n | p50 ms | p95 ms |
|---|---|---|---|
| sim | 24 | 0.1 | 0.1 |
| extract | 24 | 1.3 | 2.3 |
| reply_ttft | 24 | 1.7 | 2.7 |
| reply_total | 24 | 2.0 | 2.9 |
| retrieve | 3 | 32.0 | 53.7 |
| retrieve.major_match | 3 | 19.9 | 42.5 |
| retrieve.sql_filter | 3 | 11.0 | 11.4 |
| retrieve.rerank | 3 | 0.6 | 0.8 |
| recommend | 3 | 1.1 | 1.2 |
| groundedness | 3 | 9.9 | 10.4 |

> Replay mode: Claude latencies above are cassette playback, not API timings, and costs are the token usage recorded in the cassettes.

## Per persona

| persona | status | turns | groundedness | extraction P / R | coverage | cost |
|---|---|---|---|---|---|---|
| aaliyah-ga | ok | 8 | 1.000 | 1.000 / 0.700 | 0.833 | $0.0928 |
| maya-oh | ok | 8 | 1.000 | 1.000 / 0.667 | 0.833 | $0.1204 |
| zoe-co | ok | 8 | 1.000 | 1.000 / 0.710 | 0.812 | $0.1229 |

## Caveats

- **Internal benchmark, not ground truth.** Labels follow the frozen protocol in `evals/labels/criteria.md` (TREC-style pooling, hard criteria H1–H4, soft rubric S1).
- **Single labeler** — the project owner, who also built the system; no inter-rater agreement unless reported separately.
- **Simulated students.** Personas are invented. The student is a deterministic scripted template (no model): it answers exactly what is asked, so extraction and coverage numbers are upper bounds. The leak guard counts simulator slips (Headline).
- **Heuristic coverage.** Questions-asked coverage uses keyword matching on the counselor's question sentences (`evals/topics.py`).
- **Data limits.** Scorecard public net price is in-state; program earnings are missing for many programs; SAT/ACT ranges exist for under half of schools.
- **Small n.** Edge cases with n = 1 (hannah, megan, bella) are anecdotes, not rates.

