# Labeling criteria for the retrieval benchmark

> **Status:** frozen before any labeling. Record the commit hash of this file in the header of `labels.yaml`. If anything here changes after labeling starts, add a dated entry to the changelog at the bottom and relabel the affected personas.

## What this is, and what it isn't

For each persona in `evals/personas/`, `labels.yaml` lists the schools a careful human counselor would call **acceptable** recommendations. recall@10 and nDCG@10 (SPEC §10) are scored against these lists.

This is an **internal benchmark, not ground truth.** It shows whether one version of the retriever does better or worse than another on a fixed, documented set of judgments. It doesn't say which colleges are right for real students. The README reports it under that name.

### Known biases (stated up front)

1. **Single labeler.** One person, the project owner, labels everything. There is no inter-rater agreement. If time allows, a second person labels 5 personas blind, and Cohen's kappa on acceptable/not is reported. If not, the README says so.
2. **The labeler built the system.** The labeler wrote or approved these criteria, knows how the retriever works, and has seen its outputs during development. Unconscious alignment with the system's habits is likely. The judged pool also contains every retrieval mode's top 10 (see Pooling). Mitigations: criteria are frozen first; pooled candidates are shuffled together with the stratified sample and shown with no source, rank or score, so the labeler can't tell which rows a system picked; and the labeler doesn't look at any system output for that persona outside the labeling tool.
3. **The hard criteria mirror Stage B.** The budget rule (cap × 1.15) is the same as the retriever's SQL filter. Any retriever that uses those filters passes the hard part for free. That is why there is a soft criterion (see below).
4. **Data limits are inherited.** Scorecard net price for public schools is the **in-state** figure, so out-of-state publics look cheaper than they are. Program earnings are missing for 61% of programs. SAT/ACT ranges exist for only ~44% of schools. Labels can't be better than this data. The out-of-state public problem is handled by a mandatory rule in H2. The rest is inherited as is.
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
- **Out-of-state publics (mandatory).** Scorecard's public net price is for in-state students. For a **public school outside the persona's `home_state`**, H2 uses an out-of-state estimate: the bracket net price + (`TUITIONFEE_OUT` − `TUITIONFEE_IN`), the published sticker gap. If that estimate is above the H2 ceiling (cap × 1.15, or the bracket default), the school **fails** H2. This matters most for `leave_home_far` personas (`ethan-vt`, `kenji-hi`, `riley-nh`) and anyone with an out-of-state region list. The rule is deliberately stricter than the retriever's Stage B filter, which uses the in-state figure, so the benchmark penalizes recommending out-of-state publics a student can't afford.
  - **Only exception:** a published tuition-reciprocity price that applies to the persona's home state (WUE, Midwest Student Exchange, Academic Common Market, New England RSP). Use that price instead of the sticker gap, and say so in `notes`. If tuition fields are missing, the school fails.
- **Relaxation (only when too few schools pass).** If fewer than 5 schools pass H1–H4, H2 is relaxed once, from the cap to the bracket default, and the relaxation is recorded in `relaxed`. This exists for `bella-la`, whose $2,000 cap is below any realistic net price. Whether the counselor tells her this honestly is judged in the transcript review, not by recall.

**H3. Geography.**
- If `max_distance_miles` is given: the great-circle distance from the `home_zip` centroid to the school's lat/long is ≤ `max_distance_miles × 1.10` (students' numbers are rough).
- Otherwise, if `regions` is non-empty: the school's state must be in the **union** of the listed entries (Census regions, divisions, or two-letter state codes, using the table below). If `out_of_state` is listed, the home state is also **excluded**. `out_of_state` on its own means any state except home.
- If both are given, distance is the hard rule and regions only feed the soft rubric.
- If neither is given, there is no geographic constraint.

The **region table is frozen here.** It is the US Census Bureau's four regions and nine divisions. It is not taken from the retriever's code, so a mapping bug in the retriever can't leak into the labels.

| Region | Division | States |
|---|---|---|
| `northeast` | `new_england` | CT, ME, MA, NH, RI, VT |
| `northeast` | `mid_atlantic` | NJ, NY, PA |
| `midwest` | `east_north_central` | IL, IN, MI, OH, WI |
| `midwest` | `west_north_central` | IA, KS, MN, MO, NE, ND, SD |
| `south` | `south_atlantic` | DE, DC, FL, GA, MD, NC, SC, VA, WV |
| `south` | `east_south_central` | AL, KY, MS, TN |
| `south` | `west_south_central` | AR, LA, OK, TX |
| `west` | `mountain` | AZ, CO, ID, MT, NV, NM, UT, WY |
| `west` | `pacific` | AK, CA, HI, OR, WA |

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
3. **Run retrieval.** Run every retrieval mode (SQL only, hybrid, hybrid + rerank, and hybrid + RIASEC + rerank if it exists) on both the **gold-profile** and the **end-to-end** profile for each persona. Save each top 10. The labeler doesn't look at these results.
4. **Build the judged pool** (TREC-style pooling; tool comes later). See Pooling below.
5. **Pass 2, mark acceptable (~3–4 min per persona).** Score S1 for each shown row. Mark acceptable where S1 ≥ 1. Apply the H4 band-mix check. **Target 10–25 acceptable schools.** If more than 25 pass, keep only the S1 = 2 schools, and if that is still more than 25, keep all of them and note it. If fewer than 10 pass, keep them and note why (thin market, tight budget).
6. **Record** in `labels.yaml` and commit. Labels aren't revised after this. A genuine labeling error gets a changelog entry.

### Pooling

For each persona:

**judged pool = stratified sample ∪ top-10 from every retrieval mode × {gold-profile, end-to-end}**

- **Stratified sample:** draw from the in-scope schools that pass H1–H4. If there are 60 or fewer, include them all. Otherwise draw a stratified random sample of 60 by control × admission band (fixed seed per persona), and record the true count of schools passing H1–H4 as `pool_size`.
- **System top-10s:** each pooled school is checked against H1–H4 first. One that fails a hard criterion is **auto-judged not acceptable** and isn't shown. The rest are shown.
- **Display:** all shown rows are **shuffled together** (fixed seed). Nothing shows a row's source (sample or which system), rank or score, and duplicates are collapsed. Each row shows:
  - name and city/state
  - control, undergrad size and locale
  - net price at the bracket, plus the out-of-state estimate if one applies
  - admission rate and SAT/ACT range
  - matched CIP titles and program earnings (if not suppressed)
  - distance from home
- **Judged set:** every school shown or auto-judged becomes the persona's judged set (`judged_unitids`).
- **Later runs:** a later system version whose top 10 includes schools outside the judged set gets **no** benefit of the doubt (see Scoring). Optionally, those new schools can be judged in a dated top-up pass. The top-up is listed in the changelog, and the same rules apply.

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
  judged_unitids: [204796, 201885, 206084, 204024]   # every school shown or auto-judged
  # optional fields below
  major_cip4s: ["50.04", "14.19", "15.08"]
  pool_size: 47        # schools passing H1-H4 before sampling
  relaxed: []          # e.g. [budget] when the H2 relaxation was used
```

Required per persona:
- `acceptable_unitids` (list of int, may be empty)
- `judged_unitids` (list of int, a superset of `acceptable_unitids`; needed for judged-only precision)
- `notes` (str)
- `labeled_at` (ISO date)

The optional fields are recommended because they make the labels auditable. A persona with an empty acceptable list is left out of averaged recall and reported separately.

## Scoring (for `metrics.py`)

- **Unjudged = non-hit.** A top-10 school that isn't in `judged_unitids` counts as **not acceptable** in recall@10 and nDCG@10. With pooling this only happens for system versions run after labeling. Report the unjudged count next to the scores.
- **recall@10** = |acceptable ∩ top-10| / min(10, |acceptable|). The denominator stops personas with large acceptable sets from being penalized.
- **nDCG@10:** binary gain (acceptable = 1), log2 discount. The ideal DCG assumes **min(10, |acceptable|)** relevant items in the first positions, so a persona with 4 acceptable schools can still reach 1.0.
- **Judged-only precision@10** = |acceptable ∩ top-10| / |judged ∩ top-10|. Report it next to recall and nDCG. It shows how good the system's picks are among the ones a human actually looked at, separately from the unjudged penalty.

## Changelog

- 2026-11-19: initial version, written before any labeling.
- 2026-11-19 (review, still before any labeling):
  - TREC-style pooling replaces the random-60 pool.
  - Unjudged schools count as non-hits, and judged-only precision@10 is added.
  - `judged_unitids` is now required.
  - The out-of-state public rule in H2 is mandatory.
  - The Census region table is frozen in H3, and the `regions` union / `out_of_state` rule is defined.
- 2026-11-20 (note only, no rule change, still before any labeling): after the live-run fixes merge, the retriever's Stage B also prices out-of-state publics as bracket net price + (`TUITIONFEE_OUT` − `TUITIONFEE_IN`). H2's "deliberately stricter than the retriever's Stage B filter" now applies only to the remaining differences: the retriever floors the surcharge at 0 and has no reciprocity exception, whereas H2 applies no floor and uses a reciprocity price only when the labeler applies it by hand and says so in `notes`.
- 2026-11-20 (labeling, no rule change):
  - **Labeler.** The project owner did not complete pass 2 by hand. Pass 1 major sets were drafted by the assistant from each persona file only and reviewed by the owner. Pass 2 S1 scores were assigned by claude-opus-5-5, working blind under this rubric (shuffled pool; no source, rank or score), with a one-line rationale per school in `evals/labels/rationales/`. One score was changed by the orchestrator: Ohio State for `maya-oh`, 2 → 1, because its size conflicts with her stated preference. `labels.yaml` `_meta.labeler` records this. The owner's partial hand labels were discarded, not mixed in.
  - **Pool top-up after the retriever fix** (no silent location relaxation, bracket-default budget, far-reach cap). New top-10 picks outside `judged_unitids` were H1–H4-checked with `pool.py`'s own logic. The 23 that pass (ethan-vt 13, kenji-hi 9, maya-oh 1) were labeled blind by a separate claude-opus-5-5 instance, calibrated on the original rationales (`rationales/<id>.extra.jsonl`), then appended to the pools. The 20 that fail were added to `judged_unitids` as auto-judged. Caveat: every top-up row is a system pick with no stratified sample mixed in, so the labeler could infer that these rows came from a system. Acceptable sets were re-finalized with the unchanged 10–25 rule. kenji-hi now has 26 schools at S1 ≥ 1, so only its 5 S1 = 2 schools are kept.
