---
name: audit-agent-context
description: Find out which context files an analytics agent actually reads, what they cost in tokens, and which ones measurably change answer accuracy — using read-set analysis and cheap leave-one-out ablation instead of guesswork. Use when a context corpus has grown large, answers are getting worse, token costs are rising, or someone asks whether a table preview or profiling file is worth including. Requires an existing golden set (see generate-golden-queries).
---

# Audit agent context

Teams building analytics agents accumulate hundreds of context artefacts — table descriptions, column lists, profiling summaries, previews, `RULES.md` entries, synced Notion pages, few-shot examples. Nobody knows which ones work.

The available tooling is observational: it can tell you a file is read often and costs a lot of tokens. It cannot tell you whether removing it would change a single answer. That is a different question and it needs an experiment.

This is a known, unmet ask. nao's founders opened a public discussion asking for exactly it — *"the users can see the impact of adding this or this context on the performance of the output (eg. should I add a preview of the tables or not)"* — and then shipped mean-based heuristics instead, because the causal version is expensive. This skill is how you do it affordably.

## Prerequisites

- A golden set of **at least 30 cases** (`generate-golden-queries`).
- An agent whose context you can vary between runs (include/exclude by glob).
- An agent that reports which context files it opened. Without this, stage 1 is unavailable and everything costs 5–10× more. Check first.

## Stage 1 — Read-set analysis (free)

**Do this before anything else. It is free and it usually eliminates most of the corpus.**

Run the golden suite once with the full context. Record, per run, which context files the agent opened. Then:

```
for each file f in the corpus:
    reads(f)      = number of runs that opened f
    tokens(f)     = size of f in tokens
    total_cost(f) = reads(f) x tokens(f)
```

Classify:

| Class | Condition | Action |
|---|---|---|
| `unread` | `reads(f) == 0` | **Cannot have affected any answer.** Report at zero cost. Candidate for deletion or for a retrieval problem. |
| `hot` | high reads, low tokens | Leave alone. Working as intended. |
| `expensive` | high reads × high tokens | Ablate first — biggest potential saving. |
| `rare-but-heavy` | low reads, very high tokens | Ablate — likely dead weight. |

On a typical corpus — hundreds of per-table `columns.md` / `preview.md` / `profiling.md` files where any one question touches two or three tables — `unread` is usually the large majority. Your ablation candidate list drops from hundreds to tens before you spend anything.

**Two honest caveats to print in the report:**
1. `unread` is derived from the agent's own trace. It is a claim, not a proof.
2. An unread file may still be doing work if the agent's retrieval is failing — a file nobody reads might be a *retrieval* bug, not a useless file. Check whether the cases that should have needed it are the ones failing.

## Stage 2 — Grouped ablation (cheap)

Ablate **directories before files**. This answers the question people actually ask — "are table previews worth it at all?" — for the cost of one comparison rather than one per table.

```
baseline:        full context
variant A:       full context minus databases/**/preview.md
variant B:       full context minus databases/**/profiling.md
variant C:       full context minus docs/notion/**
```

Descend into a group only if the group shows an effect. This turns roughly linear cost into roughly logarithmic.

## Stage 3 — Leave-one-out on survivors

Only for files that survived stages 1 and 2.

```
Δ(f) = pass^k(full context) − pass^k(context without f)
```

### Making it affordable

Naive leave-one-out is `cases × k × (files + 1)` agent runs. For 200 cases, k=3, 20 files that is 12,600 runs — hours, and hundreds of dollars. Four techniques, in order of value:

**1. Paired runs (biggest win, and free).** Compare baseline and variant on the *same* cases with the *same* seeds, then analyse the paired differences `d_i = pass_i(full) − pass_i(without f)` rather than two independent means. Case difficulty is by far the largest variance component and it cancels out entirely. Typically 2–4× fewer runs for the same interval width.

**2. Sequential testing with early stopping.** Process cases incrementally, maintaining a running interval on `Δ(f)`. Stop as soon as the interval clearly excludes zero in either direction. Use an alpha-spending boundary so early stopping does not inflate the false-positive rate. Files with large effects resolve on a fraction of the suite; only genuinely marginal files consume the full budget — which is the right place to spend.

**3. Two-stage screening.** Screen every candidate with a cheap model on a stratified sample; confirm only the survivors with the production model on the full suite. Effects are correlated across models but not identical, so stage 1 is a *filter*, not a substitute. Label which stage produced each verdict.

**4. Trajectory caching.** If a run never opened file `f`, its result under "without `f`" is identical — reuse it instead of re-running.

Combined, the 12,600-run example typically lands in the low hundreds to low thousands of runs: minutes to an hour, single-digit to low-double-digit dollars.

## Reporting rules

These are not politeness. A confidently wrong "drop this file" destroys trust in the whole exercise permanently.

1. **Always report a confidence interval.** Never a bare point estimate.
2. **Use `inconclusive` as a first-class verdict.** If the interval spans zero, say so. Do not round it to a recommendation.
3. **Correct for multiple comparisons** across files — Benjamini–Hochberg is a reasonable default. Testing 40 files at α=0.05 yields two false positives by construction.
4. **Refuse a verdict below a minimum sample size.** Print the reason.
5. **Publish the design** — suite size, k, stopping rule, correction, which stage produced each verdict.
6. **State what leave-one-out cannot see.** It is additive by construction and is blind to interaction effects: two files that are individually inert but jointly essential will both read as `drop`. Print this in every report.

## Output

```
Context ablation - 180 cases x 3 reps, claude-sonnet-5, paired, BH-corrected, 95% CI

  ARTEFACT                                  Δ pass^3    95% CI       tok/run   VERDICT
  RULES.md                                  +18.3pp  [15.2, 21.4]      1,240   keep
  databases/../orders/columns.md            +11.7pp  [ 8.9, 14.5]        890   keep
  semantics/revenue.md                       +9.8pp  [ 7.4, 12.2]        620   keep
  databases/../orders/profiling.md           +4.2pp  [ 0.3,  8.1]      2,100   inconclusive
  databases/../orders/preview.md             +0.4pp  [-2.2,  3.0]      3,400   drop
  docs/notion/2024-pricing-migration.md      -3.1pp  [-5.3, -0.9]      1,850   drop (harmful)
  databases/../{131 other tables}/*                -        -          6,900   unread (0 reads)

  baseline pass^3 ......... 71.1%  [65.3, 76.4]
  recommended corpus ...... 3,750 tok/run (-63%), 70.9%  [65.0, 76.2]
  sweep cost .............. $11.40, 22 min, 1,340 runs
  not measured: interaction effects between artefacts (leave-one-out is additive)
```

The two rows that justify the whole exercise are `unread` — most of your corpus is dead weight — and `drop (harmful)`, a stale document that is actively making the agent worse. Neither is findable by reading token counts.

## Acting on the results

- `drop (harmful)` — delete or fix immediately. Stale business rules are the usual culprit.
- `drop` — remove, then **re-run the suite to confirm** the score held. Do not batch twenty deletions and hope.
- `unread` — investigate before deleting. Dead file, or broken retrieval?
- `inconclusive` — leave it. Absence of evidence is not evidence of absence, and the token cost is usually small.

Open a PR against the context repo with the report attached. Context changes deserve review like any other change.

## Related skills

- `generate-golden-queries` — you need a suite first
- `run-agent-eval` — produces the `pass^k` this measures against
- `assert-agent-behavior` — `context_file_read` is the read-set signal
