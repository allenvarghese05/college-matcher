# College Matcher v2 — eval results

> **Internal benchmark, not ground truth.** Simulated students (made-up personas), relevance labels judged by an LLM (not a human), and Scorecard data limits. See Caveats.

Run `live-full-1` · mode **record** · transport `anthropic` · simulator `qwen2.5:7b-instruct` · reply/extract `claude-sonnet-5-5` · recommend `claude-opus-5-5` · embedder `BAAI/bge-small-en-v1.5` · git `3f035e5d93` · 2026-11-20

Personas: **36** (ok 36)

## Headline

| Metric | Value |
|---|---|
| **Groundedness** (verified claims / all claims) — lead metric | **0.997** (1499/1504) |
| Hallucinated-school rate (recs not in retrieved set) | 0.000 (0/353) |
| Extraction precision / recall (micro, all fields) | 0.878 / 0.728 |
| Extraction precision / recall (micro, `interests` scored as interest signal across fields — see Caveats) | 0.904 / 0.767 |
| Questions-asked coverage (planned via next_topic) | 0.887 (0.808) |
| recall@10 gold / e2e (hybrid_rerank) | 0.337 / 0.352 |
| Sessions reaching recommendations | 36/36 |
| Turns per session (mean / max) | 10.3 / 12 |
| Cost per session (mean) | $0.2067 |
| Simulator guard: multi-leak messages / character breaks / unasked reveals | 2 / 0 / 30 (of 370 messages) |

## Retrieval: gold profile vs end-to-end (ablation)

Scored against `evals/labels/labels.yaml` (12 labeled persona(s) with a non-empty acceptable set). Unjudged top-10 schools count as non-hits; judged-P@10 is precision among judged schools only. The gold − e2e gap is what extraction loses.

| mode | recall@10 gold | recall@10 e2e | nDCG@10 gold | nDCG@10 e2e | judged-P@10 gold | judged-P@10 e2e | unjudged@10 gold / e2e | n |
|---|---|---|---|---|---|---|---|---|
| sql_only | 0.144 | 0.221 | 0.127 | 0.225 | 0.117 | 0.191 | 0 / 0 | 12 / 12 |
| hybrid | 0.164 | 0.295 | 0.133 | 0.226 | 0.117 | 0.175 | 0 / 0 | 12 / 12 |
| hybrid_rerank | 0.337 | 0.352 | 0.284 | 0.306 | 0.258 | 0.267 | 0 / 0 | 12 / 12 |
| hybrid_riasec_rerank | – | – | – | – | – | – | – | 0 (not implemented) |

## Retrieval after the retriever fix (re-scored offline)

The conversations above ran on the old retriever. After labeling, the benchmark showed that its top 10s broke stated constraints: it silently widened the distance limit, applied no budget when none was given, and let far reaches in. The fix stops silent distance/region widening (it returns fewer schools and says so), allows only one disclosed relaxation (budget, to the bracket default, when fewer than 3 schools fit an impossible cap), uses a bracket-default budget when there is no cap, prices out-of-state publics at the out-of-state estimate, caps far reaches at 1 of 10, and treats "out of state" as a hard home-state exclusion. Both columns below are scored against the **same, final** labels (pool topped up; criteria.md changelog 2026-11-20) by re-running retrieval on the gold profiles and on each session's saved extracted profile, with no LLM calls (`evals/ablation.py --from-run live-full-1`). Unjudged@10 is 0 everywhere.

| mode | recall@10 gold (before → after) | recall@10 e2e (before → after) | nDCG@10 gold | nDCG@10 e2e | judged-P@10 gold | judged-P@10 e2e |
|---|---|---|---|---|---|---|
| sql_only | 0.152 → 0.181 | 0.221 → 0.292 | 0.124 → 0.158 | 0.206 → 0.264 | 0.100 → 0.236 | 0.155 → 0.267 |
| hybrid | 0.164 → 0.441 | 0.295 → 0.589 | 0.133 → 0.436 | 0.226 → 0.540 | 0.117 → 0.433 | 0.175 → 0.492 |
| **hybrid_rerank** | **0.312 → 0.602** | **0.352 → 0.615** | 0.266 → 0.564 | 0.298 → 0.612 | 0.233 → 0.556 | 0.242 → 0.548 |

**Where the gain comes from (and a bias to disclose).** The reviewer ablated the fix on the pre-top-up labels (hybrid_rerank gold / e2e): before 0.337 / 0.352; no silent relaxation + out-of-state + leave-home only 0.479 / 0.468; + far-reach cap 0.515 / 0.504; + bracket-default budget 0.533 / 0.541; both 0.585 / 0.596. The bracket-default budget table is **identical to the labeling rule H2**, and the far-reach cap follows **H4's structure** with different thresholds. Both are defensible counselor defaults, but they make those hard criteria easier to pass by construction, so between a third and a half of the gain (about 36–43% on gold, 45–52% end-to-end, depending on how the two rules' overlap is counted) comes from aligning the system with the grader rather than from independent retrieval quality. The location-honesty changes, which the grader does not mirror, account for the largest single step.

**Caveats specific to this section.** Recommendations and groundedness in the headline come from the old retriever (they were not re-run). The pool top-up rows are all system picks, so the top-up labeler could tell they came from a system. kenji-hi's acceptable set shrank from 20 to 5 under the unchanged 10–25 rule once the top-up pushed it to 26 schools at S1 ≥ 1.

## Extraction per field

| field | precision | recall | TP | FP | FN |
|---|---|---|---|---|---|
| home_state | 1.000 | 1.000 | 36 | 0 | 0 |
| home_zip | 1.000 | 0.667 | 24 | 0 | 12 |
| gpa | 0.917 | 0.846 | 22 | 2 | 4 |
| sat | 1.000 | 0.846 | 11 | 0 | 2 |
| act | 1.000 | 0.917 | 11 | 0 | 1 |
| income_bracket | 1.000 | 1.000 | 36 | 0 | 0 |
| budget_cap | 0.714 | 0.714 | 10 | 4 | 4 |
| interests | 0.577 | 0.281 | 45 | 33 | 115 |
| interests (any field) | 0.857 | 0.525 | 84 | 14 | 76 |
| dream_without_money | 0.750 | 0.750 | 27 | 9 | 9 |
| intended_majors | 0.821 | 0.727 | 32 | 7 | 12 |
| strengths | 0.898 | 0.807 | 88 | 10 | 21 |
| favorite_subjects | 0.986 | 1.000 | 72 | 1 | 0 |
| activities | 0.902 | 0.856 | 83 | 9 | 14 |
| work_values | 0.923 | 0.500 | 36 | 3 | 36 |
| max_distance_miles | 0.917 | 0.880 | 22 | 2 | 3 |
| regions | 0.880 | 0.629 | 44 | 6 | 26 |
| size_pref | 0.971 | 0.944 | 34 | 1 | 2 |
| setting_pref | 0.917 | 0.917 | 33 | 3 | 3 |
| priorities | 0.851 | 0.887 | 63 | 11 | 8 |

`interests (any field)`: a hidden interest counts as recovered if it fuzzy-matches an extracted item in interests, strengths, activity names, the dream answer or favorite subjects (the extractor often files "good at drawing" under strengths). The strict `interests` row above is unchanged.

## Cost and latency

Total $7.4398 (counselor $7.4398, simulator $0.0000); per turn $0.0079 (Sonnet reply + extraction); per recommendation $0.1256 (Opus + retrieval + groundedness).

| stage | n | p50 ms | p95 ms |
|---|---|---|---|
| sim | 370 | 2087.8 | 6031.1 |
| extract | 370 | 1816.4 | 2622.9 |
| reply_ttft | 370 | 1908.8 | 3443.0 |
| reply_total | 370 | 2944.9 | 4488.6 |
| retrieve | 36 | 118.5 | 617.7 |
| retrieve.major_match | 36 | 63.7 | 430.9 |
| retrieve.sql_filter | 36 | 44.5 | 147.6 |
| retrieve.rerank | 36 | 3.5 | 13.9 |
| recommend | 36 | 30495.0 | 34886.5 |
| groundedness | 36 | 23.7 | 88.2 |

## Per persona

| persona | status | turns | groundedness | extraction P / R | coverage | cost |
|---|---|---|---|---|---|---|
| aaliyah-ga | ok | 10 | 1.000 | 0.826 / 0.633 | 0.944 | $0.2355 |
| ana-nv | ok | 11 | 1.000 | 0.938 / 0.577 | 0.941 | $0.2124 |
| austin-ok | ok | 11 | 1.000 | 1.000 / 0.867 | 0.941 | $0.2343 |
| bella-la | ok | 10 | 0.929 | 0.917 / 0.815 | 0.944 | $0.1203 |
| brandon-tn | ok | 9 | 1.000 | 0.958 / 0.793 | 0.824 | $0.2049 |
| claire-ma | ok | 10 | 1.000 | 0.917 / 0.759 | 1.000 | $0.2067 |
| destiny-ms | ok | 12 | 1.000 | 1.000 / 0.731 | 0.941 | $0.2193 |
| diego-tx | ok | 8 | 1.000 | 0.900 / 0.643 | 0.750 | $0.1877 |
| dylan-wv | ok | 10 | 1.000 | 0.870 / 0.769 | 1.000 | $0.2063 |
| emily-pa | ok | 9 | 1.000 | 0.815 / 0.759 | 0.882 | $0.1976 |
| ethan-vt | ok | 9 | 1.000 | 0.667 / 0.645 | 0.625 | $0.2125 |
| grace-ks | ok | 10 | 1.000 | 1.000 / 0.759 | 0.824 | $0.2114 |
| hannah-mt | ok | 10 | 1.000 | 0.808 / 0.778 | 0.824 | $0.2006 |
| harper-ut | ok | 11 | 1.000 | 0.852 / 0.719 | 0.944 | $0.2112 |
| isabella-fl | ok | 9 | 1.000 | 0.955 / 0.724 | 0.812 | $0.1940 |
| jamal-md | ok | 12 | 1.000 | 0.964 / 0.871 | 0.941 | $0.2000 |
| jasmine-ny | ok | 10 | 1.000 | 0.920 / 0.821 | 0.750 | $0.2261 |
| jose-nm | ok | 12 | 0.974 | 0.792 / 0.704 | 0.938 | $0.2343 |
| kaitlyn-nd | ok | 11 | 1.000 | 0.895 / 0.680 | 0.938 | $0.2034 |
| kenji-hi | ok | 9 | 1.000 | 0.885 / 0.742 | 1.000 | $0.2076 |
| kevin-mn | ok | 10 | 0.980 | 0.944 / 0.607 | 0.833 | $0.1969 |
| lin-ca | ok | 9 | 1.000 | 0.714 / 0.577 | 0.882 | $0.1946 |
| luis-il | ok | 9 | 1.000 | 0.846 / 0.440 | 0.562 | $0.1964 |
| malik-sc | ok | 12 | 1.000 | 1.000 / 0.692 | 0.933 | $0.2193 |
| marcus-al | ok | 12 | 1.000 | 0.824 / 0.667 | 1.000 | $0.1903 |
| maya-oh | ok | 12 | 1.000 | 0.917 / 0.917 | 1.000 | $0.2154 |
| megan-ne | ok | 12 | 1.000 | 0.941 / 0.667 | 0.867 | $0.2136 |
| noah-wa | ok | 8 | 1.000 | 0.815 / 0.846 | 0.875 | $0.1991 |
| oliver-or | ok | 10 | 1.000 | 0.875 / 0.700 | 0.938 | $0.2009 |
| priya-nj | ok | 11 | 0.979 | 0.750 / 0.828 | 0.875 | $0.2174 |
| riley-nh | ok | 10 | 1.000 | 0.923 / 0.800 | 0.933 | $0.2114 |
| sam-ia | ok | 8 | 1.000 | 0.810 / 0.680 | 0.824 | $0.1843 |
| sofia-az | ok | 11 | 1.000 | 1.000 / 0.758 | 0.889 | $0.2142 |
| tyler-wy | ok | 11 | 0.977 | 0.875 / 0.778 | 0.941 | $0.2211 |
| tyrell-mi | ok | 12 | 1.000 | 0.864 / 0.731 | 0.938 | $0.2244 |
| zoe-co | ok | 10 | 1.000 | 0.808 / 0.677 | 0.875 | $0.2144 |

## Caveats

- **Internal benchmark, not ground truth.** Labels follow the frozen protocol in `evals/labels/criteria.md` (TREC-style pooling, hard criteria H1–H4, soft rubric S1).
- **LLM-judged labels** — claude-opus-5-5 (LLM judge, blind pool; Ohio State 2->1 for maya-oh by the orchestrator per the size rule). Pass 1 major sets were drafted by the assistant from each persona file and reviewed by the project owner; pass 2 fit scores (S1) were assigned by the model blind (shuffled pool, no source, rank or score) under the frozen rubric, with a one-line rationale per school in `evals/labels/rationales/`. The judge is the same model family as the recommender, so self-preference bias is possible; no human agreement is reported.
- **Simulated students.** Personas are invented. The student is played by a local model (`qwen2.5:7b-instruct` via Ollama), a different model family from the Claude counselor, which makes self-flattering scores less likely. The leak guard counts simulator slips (Headline).
- **Heuristic coverage.** Questions-asked coverage uses keyword matching on the counselor's question sentences (`evals/topics.py`).
- **Interest signal is a lenient, secondary score.** `interests (any field)` and the matching micro totals credit a hidden interest found in strengths, activities, the dream answer or favorite subjects; strict per-field scoring stays the headline. Rule: `evals/README.md` (Extraction metrics).
- **Data limits.** Scorecard public net price is in-state; program earnings are missing for many programs; SAT/ACT ranges exist for under half of schools.
- **Small n.** Edge cases with n = 1 (hannah, megan, bella) are anecdotes, not rates.

