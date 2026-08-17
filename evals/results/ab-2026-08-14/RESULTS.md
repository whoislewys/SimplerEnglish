# Benchmark results: skill variants A/B

**Fewer STE violations per 100 words vs baseline — V1 (full skill): 86.1% | V2 (one-line): 78.6%** (144 generations, measured).

Pre-registered criterion: the one-line V2 skill passes if its mean violation-reduction-vs-baseline is within 5 percentage points of the full V1 skill's, on the same model x scenario matrix.

## Violations per 100 words

| Model | Baseline viol/100w | V1 (full skill) viol/100w | V2 (one-line) viol/100w | V1 (full skill) reduction | V2 (one-line) reduction |
|---|---|---|---|---|---|
| claude-opus-4-8 | 2.58 | 0.19 | 0.28 | 92.6% | 89.1% |
| claude-opus-4-7 | 3.36 | 0.37 | 0.13 | 89.0% | 96.1% |
| claude-opus-4-6 | 2.96 | 0.46 | 0.56 | 84.5% | 81.1% |
| claude-opus-4-5-20251101 | 2.21 | 0.39 | 0.53 | 82.4% | 76.0% |
| claude-sonnet-5 | 3.31 | 0.84 | 1.31 | 74.6% | 60.4% |
| claude-sonnet-4-6 | 2.77 | 0.18 | 0.86 | 93.5% | 69.0% |
| **mean** | - | - | - | **86.1%** | **78.6%** |

## Mean sentence length (words)

| Model | Baseline | V1 (full skill) | V2 (one-line) |
|---|---|---|---|
| claude-opus-4-8 | 15.6 | 9.6 | 9.5 |
| claude-opus-4-7 | 16.4 | 11.1 | 9.6 |
| claude-opus-4-6 | 15.0 | 10.6 | 10.4 |
| claude-opus-4-5-20251101 | 13.2 | 8.7 | 9.2 |
| claude-sonnet-5 | 19.4 | 11.3 | 9.6 |
| claude-sonnet-4-6 | 16.1 | 9.8 | 8.8 |

## Judge pass (blind pairwise)

For each variant x model x scenario pair, claude-opus-4-8 scored the baseline
text and the variant text on a 0-10 rubric, twice with the texts in both
orders. The two scores were averaged to cancel position bias. The judge saw
no labels. Each variant was judged against the baseline only, never against
the other variant.

Result: the V1 (full skill) output scored higher in 34 of 48 pairs, tied in
5, and lost in 9. Mean rubric score: 6.96 with the skill, 5.26 without.

| Model | V1 (full skill) wins | Ties | Losses |
|---|---|---|---|
| claude-opus-4-8 | 6 | 0 | 2 |
| claude-opus-4-7 | 5 | 2 | 1 |
| claude-opus-4-6 | 4 | 2 | 2 |
| claude-opus-4-5-20251101 | 5 | 0 | 3 |
| claude-sonnet-5 | 6 | 1 | 1 |
| claude-sonnet-4-6 | 8 | 0 | 0 |

Result: the V2 (one-line) output scored higher in 40 of 48 pairs, tied in
3, and lost in 5. Mean rubric score: 6.94 with the skill, 4.58 without.

| Model | V2 (one-line) wins | Ties | Losses |
|---|---|---|---|
| claude-opus-4-8 | 8 | 0 | 0 |
| claude-opus-4-7 | 5 | 1 | 2 |
| claude-opus-4-6 | 8 | 0 | 0 |
| claude-opus-4-5-20251101 | 7 | 0 | 1 |
| claude-sonnet-5 | 6 | 1 | 1 |
| claude-sonnet-4-6 | 6 | 1 | 1 |

Read the win rates within a variant, not across variants. The baseline texts
are identical in every block, but the judge scored them differently depending
on the text they were paired with (V1 (full skill) block 5.26, V2 (one-line) block 4.58). A contrast effect of that
size means the variant-to-variant difference in win rate is weaker evidence
than the linter numbers above.

Caveats: one judge model, judged once per order. The judge is a Claude
model and the texts are Claude output, so family bias is possible. Raw
judge files: ab-2026-08-14/raw/*__judge-*.json. Reproduce with
`python3 evals/run_bench.py --judge`.

## Token and dollar spend

Skill body = SKILL.md with the YAML frontmatter removed. Its token count is an
estimate at 4 characters per token, not a tokenizer run. Prompt tokens are the
measured sum of uncached input, cache writes, and cache reads per cell; they
include the CLI's own system prompt (~13k), so read the difference between arms,
not the absolute number. Cost and token figures per arm are means over every
cell in that arm, as reported by the Claude Code CLI (`total_cost_usd`, `usage`).

| Arm | Skill body words | Skill body est. tokens | Mean prompt tok/cell | Mean output tok/cell | Mean $/cell |
|---|---|---|---|---|---|
| Baseline | - | - | 22838 | 249 | $0.0634 |
| V1 (full skill) | 3259 | 4728 | 28946 | 621 | $0.1108 |
| V2 (one-line) | 11 | 20 | 22712 | 292 | $0.0469 |

## Verdict

- Reduction vs baseline: V1 86.1%, V2 78.6%. Gap: -7.5 percentage points.
- Pre-registered 5-point criterion: **NOT MET**.
- Prompt cost: V2's body is ~4708 estimated tokens lighter than V1's (4728 -> 20); measured mean prompt tokens per cell: 28946 -> 22712; mean cost per cell: $0.1108 -> $0.0469.
- Judge, V1 (full skill): won 34/48 pairs, mean score 6.96 vs baseline 5.26.
- Judge, V2 (one-line): won 40/48 pairs, mean score 6.94 vs baseline 4.58.

## Honest number warnings

- The linter is a regex pass (see ste_lint.py header). It undercounts real STE
  violations: no passive-voice or part-of-speech detection. It counts the same
  way for both conditions, so the comparison is fair even where the absolute
  numbers are low.
- The skill condition sends SKILL.md in the prompt, so its input tokens are
  higher by design. Output tokens are reported; draw your own conclusion.
- One generation per cell. Re-run the matrix for variance; the runner is
  resumable, delete results/raw to start fresh.
- No tool can guarantee ASD-STE100 compliance, including this one.

Reproduce: `python3 evals/run_bench.py` (Claude Code CLI, logged in).

- Both variants use the identical prompt wrapper, including the phrase "including the self-check step". V2's body defines no self-check step; the
  wrapper was left unchanged so the only difference between the arms is the
  skill body.
- This run: `python3 evals/run_bench.py --results-dir ab-2026-08-14` (and `--judge`).
