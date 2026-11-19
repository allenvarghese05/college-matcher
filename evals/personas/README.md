# Simulated-student personas

36 made-up high-school students used to drive the counselor end to end. Each persona is a YAML file holding a **hidden profile** (the ground truth the counselor is trying to recover) plus instructions for how the student talks. A simulator model plays the student; the counselor never sees the file.

All names, towns and details are invented. ZIP codes are real ZIPs for the student's town, used only so distance filters have a location to work from.

## How they're used

| Run | What happens | What it measures |
|---|---|---|
| **Text run** (all 36) | `evals/simulator.py` plays each persona against the counselor's text API until the counselor recommends or a turn cap is hit. | Extraction precision/recall per field (final profile vs `hidden_profile`), questions-asked coverage, end-to-end recall@10 / nDCG@10, groundedness, cost and turns per session. |
| **Gold-profile retrieval** (all 36) | `hidden_profile` goes straight into the retriever, with no conversation. | recall@10 / nDCG@10 with perfect extraction. The gap to end-to-end recall is what extraction loses. |
| **Voice run** (the 10 marked below) | The simulator's text goes through Deepgram TTS, then the full voice pipeline. | Time to first audio p50/p95 per stage, and extraction accuracy voice vs text for the same personas. |

The simulator is a different model family from the counselor (SPEC §10, P2), which makes it less likely that the counselor scores well just because it is grading itself.

## File format

```yaml
id: maya-oh                 # = filename, <firstname>-<state>
summary: one line for humans
hidden_profile: {...}       # keys are exactly SPEC §6 StudentProfile field names
style: how they talk
reveal: only_when_asked
quirks: [optional behaviours]
meta:                       # eval bookkeeping; NOT given to the simulator
  articulateness: terse     # terse | casual | rambling | anxious | confident
  edge_cases: [first_gen]   # controlled vocabulary, see validate.py
  voice_subset: true
```

**The simulator receives only `summary`, `hidden_profile`, `style`, `reveal` and `quirks`. `meta` must be stripped before the persona is handed to the simulator.** It holds eval labels (edge cases, articulateness), and giving them to the simulator could make it overact.

### Three states for a profile field

| In `hidden_profile` | Meaning | Extraction scoring |
|---|---|---|
| **Key absent** | The student has no value or won't share it (homeschooled with no GPA, never tested, no budget number). | The correct extraction is null. Any extracted value is a **false positive**. |
| **Empty list `[]`** | Known to be empty, e.g. `intended_majors: []` (no major in mind) or `regions: []` (no regional preference). | Nothing to recall. An empty or null extraction is correct and is **never a false positive**, and it doesn't count toward recall. A non-empty extraction counts as false positives. |
| **Value** | Ground truth. | Exact match for enums and numbers (GPA ±0.05, SAT ±10). Set overlap for lists. |

SPEC §6 ("missing vs none") stores both "absent" and "never asked" as null in the live profile. Telling them apart for the questions-asked metric is a tier-2 follow-up.

### Other field notes

- `riasec` is the student's true interest profile, used for the RIASEC retrieval path (tier 2) and for diversity tracking. The student never says these numbers. They come out only through what the student says about interests, or through the optional quiz.
- `activities` items follow `app.schemas.Activity`: `{name, role, years, hours_per_week}`, all optional except `name`.
- `regions` uses the SPEC §6 vocabulary:
  - Census regions: `northeast`, `midwest`, `south`, `west`
  - Census divisions: `new_england`, `mid_atlantic`, `east_north_central`, `west_north_central`, `south_atlantic`, `east_south_central`, `west_south_central`, `mountain`, `pacific`
  - two-letter state codes
  - `out_of_state`

  How the personas read a list: a school qualifies if its state is in **any** listed region, division or state (union). `out_of_state` also **excludes the home state**. On its own it means "anywhere but home". Every `leave_home_far` persona includes it, and the validator enforces that.
- When a persona changes their mind (`jose-nm` on distance, `harper-ut` on budget), the hidden profile holds the **final** answer, and the quirk describes the earlier one.

## The reveal rule

`reveal: only_when_asked`. The simulator must **never volunteer a profile fact** the counselor hasn't asked about, or clearly invited with an open question. "What's on your mind about college?" invites interests and worries. It does not invite GPA, ZIP or income. Rambling personas still ramble, but they ramble about the topic they were asked, and they don't drop extra structured facts. This keeps questions-asked coverage meaningful: the counselor gets credit only for information it actually drew out.

The simulator also has to:
- answer in the persona's `style`, including vagueness ("like a B?") when the style says so;
- give numbers the way a teenager would ("thirteen-ten", "maybe fifty thousand?"), not in field format;
- act out each `quirk` once, at a natural moment;
- never mention RIASEC scores, field names, or that it is a simulation.

## Voice subset (10)

`maya-oh`, `marcus-al`, `aaliyah-ga`, `ethan-vt`, `priya-nj`, `bella-la`, `jose-nm`, `destiny-ms`, `kenji-hi`, `luis-il`.

They were picked to cover the range: two very terse speakers (short utterances are hard for endpointing), one rambler (long turns), two anxious and two confident speakers, one student who changes his answer, one unrealistic budget, a code-switching speaker (Spanish words in `luis-il`), the neither-GPA-nor-test case, a spoken SAT score, and four income brackets.

## All 36

Run `validate.py --table` to regenerate this table, and check it against the files before editing.

| id | state | income | gpa? | test? | dominant RIASEC | priorities | edge case | voice |
|---|---|---|---|---|---|---|---|---|
| aaliyah-ga | GA | 0-30k | yes | SAT | I | cost, outcomes | low_income_high_stats, first_gen | yes |
| ana-nv | NV | 30-48k | yes | - | C | cost, outcomes | nursing_health |  |
| austin-ok | OK | 75-110k | yes | ACT | E | cost, outcomes | military_rotc |  |
| bella-la | LA | 30-48k | yes | ACT | A | cost, fit | unrealistic_budget, arts | yes |
| brandon-tn | TN | 110k+ | yes | SAT | E | outcomes, fit | - |  |
| claire-ma | MA | 110k+ | - | SAT | E | prestige, outcomes | prestige |  |
| destiny-ms | MS | 0-30k | yes | ACT | S | cost, outcomes | nursing_health, first_gen | yes |
| diego-tx | TX | 30-48k | yes | SAT | R | cost, outcomes | military_rotc |  |
| dylan-wv | WV | 0-30k | yes | ACT | C | cost, outcomes | low_income_high_stats, cs |  |
| emily-pa | PA | 75-110k | yes | - | S | cost, fit | - |  |
| ethan-vt | VT | 75-110k | yes | - | I | fit, location | leave_home_far | yes |
| grace-ks | KS | 48-75k | - | ACT | S | cost, outcomes | nursing_health |  |
| hannah-mt | MT | 48-75k | yes | - | R | fit, cost | small_rural_college |  |
| harper-ut | UT | 110k+ | yes | ACT | C | outcomes, cost | contradicts_self |  |
| isabella-fl | FL | 110k+ | yes | SAT | S | prestige, outcomes | prestige, nursing_health |  |
| jamal-md | MD | 30-48k | yes | SAT | S | cost, fit | - |  |
| jasmine-ny | NY | 0-30k | yes | - | A | cost, fit | arts, first_gen |  |
| jose-nm | NM | 30-48k | yes | ACT | R | cost, fit | contradicts_self | yes |
| kaitlyn-nd | ND | 110k+ | - | ACT | R | outcomes, location | specific_major_outcomes |  |
| kenji-hi | HI | 48-75k | yes | SAT | A | fit, outcomes | leave_home_far, arts | yes |
| kevin-mn | MN | 75-110k | yes | ACT | C | outcomes, cost | specific_major_outcomes |  |
| lin-ca | CA | 48-75k | yes | SAT | I | outcomes, cost | specific_major_outcomes |  |
| luis-il | IL | 30-48k | - | SAT | C | cost, outcomes | first_gen | yes |
| malik-sc | SC | 0-30k | - | - | S | cost, outcomes | military_rotc, nursing_health |  |
| marcus-al | AL | 0-30k | - | - | R | cost | trades_adjacent, first_gen | yes |
| maya-oh | OH | 48-75k | yes | SAT | A | cost, outcomes | - | yes |
| megan-ne | NE | 48-75k | - | - | C | cost, fit | undecided |  |
| noah-wa | WA | 30-48k | - | SAT | I | cost, outcomes | cs |  |
| oliver-or | OR | 110k+ | yes | SAT | A | fit, location | arts |  |
| priya-nj | NJ | 110k+ | yes | SAT | I | prestige, outcomes | cs, prestige | yes |
| riley-nh | NH | 48-75k | - | - | E | location, fit | leave_home_far |  |
| sam-ia | IA | 48-75k | yes | ACT | I | cost, outcomes | - |  |
| sofia-az | AZ | 30-48k | yes | ACT | E | cost, outcomes | first_gen |  |
| tyler-wy | WY | 75-110k | yes | ACT | R | cost, location | trades_adjacent |  |
| tyrell-mi | MI | 0-30k | yes | - | E | cost, fit | - |  |
| zoe-co | CO | 75-110k | - | - | A | fit, cost | - |  |

### Diversity summary (from `validate.py`)

- **Income:** 0-30k = 7, 30-48k = 8, 48-75k = 8, 75-110k = 6, 110k+ = 7.
- **States:** 36 different states, one persona each. 13 of them are mostly-rural states: AL IA KS MS MT ND NE NH NM OK VT WV WY.
- **Academics:** both GPA and test = 20, GPA only = 6, test only = 5, neither = 5.
- **Dominant RIASEC type:** 6 each of R, I, A, S, E, C.
- **Articulateness:** terse 8, casual 8, rambling 5, anxious 5, confident 10.
- **Edge cases:**
  - undecided: megan
  - wants to leave home far away: ethan, kenji, riley
  - low income + high stats: aaliyah, dylan
  - first-gen: 6 personas
  - specific major with strong outcomes: kaitlyn (aviation), lin (EE), kevin (accounting)
  - prestige: priya, isabella, claire
  - arts: jasmine, oliver, kenji, bella
  - trades-adjacent: tyler, marcus
  - contradicts themselves: jose, harper
  - budget below any realistic price: bella ($2,000/yr)
  - nursing/health: destiny, malik, grace, ana, isabella
  - CS: priya, noah, dylan
  - ROTC: diego (Army), malik (Navy), austin (Air Force)
  - small rural college: hannah

**Low-n warning:** `small_rural_college` (hannah), `undecided` (megan) and `unrealistic_budget` (bella) each have **n = 1**. Read results for these as anecdotes, not rates, and don't report a per-edge-case metric for them.

## Validating

From the repo root:

```bash
UV_CACHE_DIR="$TMPDIR/uv-cache" uv run --directory backend python ../evals/personas/validate.py [--table]
```

Field names, enum values (`IncomeBracket`, `WorkValue`, `SizePref`, `SettingPref`, `Priority`) and `Activity` keys are **imported from `backend/app/schemas.py`**. Every `hidden_profile` value is validated with a pydantic `TypeAdapter` against its `StudentProfile` field type, so the personas can't drift from the contract.

On top of that, the validator checks:
- required keys and ranges (GPA 0–4, SAT, ACT);
- ZIP is in the home state;
- the regions vocabulary;
- `out_of_state` is present for every `leave_home_far` persona;
- RIASEC has a unique dominant type;
- ids are unique;
- the diversity requirements above.

It exits non-zero on any failure.

## SPEC §6 notes

Resolved since the first draft:
- `Activity` is defined in `schemas.py`.
- `work_values` uses `working_conditions`.
- `regions` has a fixed vocabulary.
- "Far from home" is expressed as `out_of_state`.

Still open:

1. **How `regions` entries combine.** SPEC defines the vocabulary but not how a list like `[out_of_state, CA, OR, WA]` combines. The personas assume union, with `out_of_state` also excluding the home state (see above). The retriever (`app/retrieval/geo.py`, not written yet) and the extraction scorer should use the same rule. The region → state table is copied in `validate.py` and frozen in `evals/labels/criteria.md`, because `geo.py` doesn't exist yet.
2. **Colloquial regions.** Students say "Mid-Atlantic" or "the Southeast", which don't match Census divisions (Census `mid_atlantic` leaves out MD/DE/DC). The personas use explicit state lists in those cases (`jamal-md`, `claire-ma`). The extractor will face the same mapping choice.
3. **Matching `intended_majors`** is free text such as "construction management" or "professional pilot", so extraction scoring needs fuzzy or CIP-mapped comparison rather than exact match.
4. **ROTC, team sports, studios.** Several quirks ask about features that aren't in Scorecard (ROTC detachments, varsity teams, studios, CPA pass rates). The counselor should say it doesn't have that data. These quirks are there to test honesty, not retrieval.
