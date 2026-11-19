# Labeling criteria for the retrieval benchmark

> **Status:** frozen before any labeling. Record the commit hash of this file in the header of `labels.yaml`. If anything here changes after labeling starts, add a dated entry to the changelog at the bottom and relabel the affected personas.

## What this is, and what it isn't

For each persona in `evals/personas/`, `labels.yaml` lists the schools a careful human counselor would call **acceptable** recommendations. recall@10 and nDCG@10 (SPEC §10) are scored against these lists.

This is an **internal benchmark, not ground truth.** It shows whether one version of the retriever does better or worse than another on a fixed, documented set of judgments. It doesn't say which colleges are right for real students. The README reports it under that name.

### Known biases (stated up front)

1. **Single labeler.** One person, the project owner, labels everything. There is no inter-rater agreement. If time allows, a second person labels 5 personas blind, and Cohen's kappa on acceptable/not is reported. If not, the README says so.
2. **The labeler built the system.** The labeler wrote or approved these criteria, knows how the retriever works, and has seen its outputs during development. Unconscious alignment with the system's habits is likely. Mitigations: criteria are frozen first, candidates are shown in random order with no system scores, and labeling happens without looking at any system output for that persona.
3. **The hard criteria mirror Stage B.** The budget rule (cap × 1.15) is the same as the retriever's SQL filter. Any retriever that uses those filters passes the hard part for free. That is why there is a soft criterion (see below).
4. **Data limits are inherited.** Scorecard net price for public schools is the **in-state** figure, so out-of-state publics look cheaper than they are. Program earnings are missing for 61% of programs. SAT/ACT ranges exist for only ~44% of schools. Labels can't be better than this data. The labeler may flag a known problem (for example, an out-of-state flagship that is clearly unaffordable) in `notes` and score it 0 on the soft rubric.
5. **The labeler's own taste.** "Fit" and "prestige" are partly subjective. The rubric below narrows this but doesn't remove it.
6. **Hidden profile = gold profile.** The labeler works from the same `hidden_profile` that is fed to the gold-profile retrieval run, so that run is graded against a target written from the same facts it receives. End-to-end runs have to recover those facts from conversation first.

### Why there is a soft criterion

If "acceptable" meant only "passes the SQL filters", a retriever running those same filters would return nothing *but* acceptable schools. Its recall would depend only on how it orders a set that is already all correct, and it would score close to 100% by construction. The ablation (SQL only vs hybrid vs hybrid + rerank) would then measure nothing. The soft criterion adds a judgment SQL can't make, so embedding search and reranking can show whether they help.

### Why there are two retrieval evals

- **Gold profile:** the persona's `hidden_profile` goes straight into the retriever. This measures retrieval quality on its own, with perfect extraction.
- **End-to-end:** the profile the counselor extracted from the simulated conversation goes into the retriever. This measures what a student would actually get.
- **The gap between them** is how much recall is lost to extraction: facts missed, misheard or invented. Both runs use the same labels.

## Definitions

A school is **acceptable** for a persona if it **passes every hard criterion (H1–H4)** and **scores ≥ 1 on the soft rubric (S1)**.

Only in-scope schools count (SPEC D6: currently operating, in the 50 states + DC, offers at least one bachelor's program).

### Hard criteria (derivable from data)

**H1. Major.** The school offers at least one CIP-4 code from the persona's **label major set** at the bachelor's level (`CREDLEV = 3`).
- The label major set (`major_cip4s`, 2–8 codes; up to 10 for undecided personas) is chosen by the labeler **before** the candidate pool is generated. It comes from the persona's `intended_majors`, `interests`, `dream_without_money` and `strengths`, picked from the CIP list by hand.
- The labeler must **not** look at the system's Stage A (interests → majors) output when choosing codes.

**H2. Net price.** Use the Scorecard net price at the persona's `income_bracket` (`NPT4x_PUB` or `NPT4x_PRIV`).
- If `budget_cap` is given: net price ≤ `budget_cap × 1.15`.
- If no cap: net price ≤ the bracket default below. These defaults are set here, before labeling, as "a stretch most families in the bracket could plausibly manage with loans and work":

  | Bracket | Default ceiling (no cap given) |
  |---|---|
  | 0-30k | $12,000 |
  | 30-48k | $15,000 |
  | 48-75k | $20,000 |
  | 75-110k | $27,000 |
  | 110k+ | $40,000 (no ceiling if `priorities` includes `prestige`) |

- If the bracket net price is missing, use the school's average net price (`NPT4`). If both are missing, the school **fails** H2: nobody can say it is affordable, and the system can't cite a price for it either.
- **Relaxation (only when too few schools pass).** If fewer than 5 schools pass H1–H4, H2 is relaxed once, from the cap to the bracket default, and the relaxation is recorded in `relaxed`. This exists for `bella-la`, whose $2,000 cap is below any realistic net price. Whether the counselor tells her this honestly is judged in the transcript review, not by recall.

**H3. Geography.**
- If `max_distance_miles` is given: the great-circle distance from the `home_zip` centroid to the school's lat/long is ≤ `max_distance_miles × 1.10` (students' numbers are rough).
- Otherwise, if `regions` is non-empty: the school's state is in one of the listed regions. The region → states mapping is the one used by the retriever, and it is recorded in the labeling tool.
- If both are given, distance is the hard rule and regions only feed the soft rubric.
- If neither is given, there is no geographic constraint.

**H4. Admission plausibility.** This is per school, based on raw Scorecard data, and deliberately **not** the system's estimator.
- A school fails H4 if it is a *far reach* for the persona:
  - **Test given and school reports ranges:** the student's score is below the school's 25th percentile by more than 80 SAT points or 3 ACT points, **and** the admission rate is below 50%. ACT and SAT are converted with the 2018 ACT/College Board concordance when the school reports only the other test.
  - **Admission rate < 15%:** fails unless the student's test score is at or above the school's 75th percentile, or the student has no test but a GPA ≥ 3.85.
  - **GPA only:** GPA < 3.0 fails schools with admission rate < 30%. GPA 3.0–3.49 fails schools with admission rate < 20%.
  - **Neither GPA nor test:** fails only schools with admission rate < 15%.
- Open-admission schools always pass.
- **Set-level check (band mix).** After marking, if the persona has stats, the acceptable set should not be mostly reaches. If more than a third of acceptable schools have admission rate < 25% *and* the student is below their median, the labeler removes the lowest-scoring of those (S1 = 1 first) until the set is ≤ 1/3 reaches. Any removals are recorded in `notes`.

Size and setting preferences are **not** hard criteria. Students state them loosely ("medium-ish?"), so they feed the soft rubric instead.

### Soft criterion S1: fit with stated interests and goals (human-judged)

Score 0 / 1 / 2. Judge the **school + matched program** against everything the student said: interests, dream, the career they described, size/setting wishes, and any quirk that states a want (a studio, ROTC, a swim team, staying near family). Outside knowledge about the school is allowed. Capturing what Scorecard can't is the point of this criterion. Spend no more than ~10 seconds per school, and look something up only when a 1-vs-2 call is genuinely unclear.

| Score | Meaning | Examples |
|---|---|---|
| **2: strong fit** | The program is a direct path to what the student described, and nothing about the school conflicts with a stated want. | `hannah-mt`: a small rural public with an animal science program, in reach and in budget. `kaitlyn-nd`: a school with a flight-training aviation bachelor's. `lin-ca`: a California public with an accredited EE program. |
| **1: acceptable** | A relevant program, but only one of these holds: the program is an adjacent field rather than the one described, **or** the school mildly conflicts with a stated preference (size or setting a step off, a bit farther than ideal). A reasonable counselor might list it. | `maya-oh`: a school with mechanical engineering but no industrial design. `tyler-wy`: construction management at a mid-size school in a small city when he said "town". `jasmine-ny`: a general studio art BA at a commuter school, with no animation track. |
| **0: poor fit** | It passes SQL, but the match is nominal, or the school clearly conflicts with something the student said. Includes: the CIP technically matches but the program is a different emphasis; online-only or for-profit programs for a student wanting campus life; a single-sex or mission-specific school the student wouldn't choose given what they said; a big urban campus for a student who said that scares them; a known affordability trap (see bias 4). | `hannah-mt`: a 40,000-student urban university. `brandon-tn`: a small religious college with a business major (he asked for big game-day schools). `ana-nv`: a nursing-only school (she ruled out nursing). `marcus-al`: an architecture program heavy on theory and design studios, when he wants to build. |

## Procedure

1. **Freeze.** Commit this file. Write its commit hash in `labels.yaml`.
2. **Pass 1, major sets (~1 min per persona).** For each persona, read the YAML and write `major_cip4s`. Don't look at system output.
3. **Generate candidate pools** (tool comes later). The pool is every in-scope school passing H1–H4 for the persona. Each row shows: name, city/state, control, undergrad size, locale, net price at bracket, admission rate, SAT/ACT range, matched CIP titles, program earnings if not suppressed, and distance from home. Rows come in **random order** (fixed seed per persona), with **no system scores or rankings**. If the pool has more than 60 schools, the tool shows a stratified random sample of 60 (by control × admission band), and the true pool size is recorded.
4. **Pass 2, mark acceptable (~3–4 min per persona).** Score S1 for each row. Mark acceptable where S1 ≥ 1. Apply the H4 band-mix check. **Target 10–25 acceptable schools.** If more than 25 pass, keep only the S1 = 2 schools, and if that is still more than 25, keep all of them and note it. If fewer than 10 pass, keep them and note why (thin market, tight budget).
5. **Record** in `labels.yaml` and commit. Don't revise a persona's labels after seeing system output for it. A genuine labeling error gets a changelog entry.

**Time budget:** about 4–5 minutes per persona, so roughly 2.5–3 hours for 36. If time runs short, label in this priority order: the voice subset first, then one persona per edge case, then the rest. The README reports how many were labeled.

## `labels.yaml` format

```yaml
_meta:
  criteria_commit: <git sha of this file when frozen>
  labeler: project owner
  candidate_tool_version: <sha>

maya-oh:
  acceptable_unitids: [204796, 201885, 206084]   # Scorecard UNITIDs (int); illustrative only
  notes: "Few industrial design programs in 300 mi; mech-eng-only schools scored 1."
  labeled_at: 2026-11-21
  # optional fields below
  major_cip4s: ["50.04", "14.19", "15.08"]
  pool_size: 47
  relaxed: []          # e.g. [budget] when the H2 relaxation was used
```

Required per persona: `acceptable_unitids` (list of int, may be empty), `notes` (str), `labeled_at` (ISO date). The optional fields are recommended because they make the labels auditable. A persona with an empty acceptable list is left out of averaged recall and reported separately.

## Scoring notes for `metrics.py` (proposed)

- **recall@10** = |acceptable ∩ top-10| / min(10, |acceptable|). The denominator stops personas with large acceptable sets from being penalized.
- **nDCG@10:** binary gain (acceptable = 1).
- Retrieved schools the labeler never saw (outside the sampled pool) are **unjudged**, not wrong. Report the unjudged rate in the top 10 next to recall.

## Changelog

- 2026-11-19: initial version, written before any labeling.
