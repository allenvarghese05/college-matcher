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

What the profile fields hold:

- A field that is **missing** from `hidden_profile` means the student doesn't have that information or won't share it, for example no GPA (homeschooled, or doesn't know it), no test score, or no budget number. The counselor should *not* extract a value for it. If the extracted profile contains a value for a missing key, that counts as a false positive.
- `riasec` is the student's true interest profile, used for the RIASEC retrieval path (tier 2) and for diversity tracking. The student never says these numbers. They come out only through what the student says about interests, or through the optional quiz.
- `activities` items are `{name, role, years}` (SPEC §6 names `Activity` but doesn't define it; see the ambiguities below).
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

## Validating

```bash
uv run --python 3.12 --no-project --with pyyaml python -I evals/personas/validate.py [--table]
```

It checks required keys, enum values, that every `hidden_profile` key is a SPEC §6 field (the list is hard-coded), ZIP-in-state, RIASEC ranges with a unique dominant type, unique ids, and the diversity requirements above. It exits non-zero on any failure.

## SPEC §6 ambiguities (assumptions made here)

1. **`Activity` is not defined.** The personas use `{name, role, years}`. If `schemas.py` defines it differently, update the personas and `ACTIVITY_KEYS` in `validate.py`.
2. **`regions` has no vocabulary.** The personas use informal labels such as `Midwest`, `Mountain West`, `Pacific Northwest`, `West Coast` and `Southeast`, plus single states such as `Texas` and `California`. Someone needs to choose a canonical list, region → states, so that both the retriever and the extraction scorer can use it.
3. **There is no "far from home" field.** Students who want to leave (`ethan-vt`, `kenji-hi`, `riley-nh`) are encoded as out-of-state `regions` with no `max_distance_miles`. A `min_distance_miles`, or an `exclude_home_state` flag, would represent them more faithfully.
4. **`work_values` vocabulary** is taken from the SPEC comment (the O\*NET six: achievement, independence, recognition, relationships, support, conditions), and the validator enforces it.
5. **Matching `intended_majors`** is free text such as "construction management" or "professional pilot", so extraction scoring needs fuzzy or CIP-mapped comparison rather than exact match.
6. **"Unknown" vs "won't say".** SPEC has no way to record "the student explicitly has no GPA". An absent key covers both "never asked" and "doesn't have one", so the questions-asked metric can't separate them.
7. **ROTC, team sports, studios.** Several quirks ask about features that aren't in Scorecard (ROTC detachments, varsity teams, studios). The counselor should say it doesn't have that data. These quirks are there to test honesty, not retrieval.
