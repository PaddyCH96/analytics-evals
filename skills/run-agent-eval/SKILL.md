---
name: run-agent-eval
description: Run a golden question set against an analytics or text-to-SQL agent and report a score that survives scrutiny — repeated runs, pass@k and pass^k, Wilson confidence intervals, coverage separated from accuracy, and cost per correct answer. Use when measuring agent quality, comparing models, or gating a release. Do not use to write test cases (use generate-golden-queries) or to decide whether one answer matches (use compare-query-results).
---

# Run an agent evaluation

Most analytics-agent evaluation reports one number from one run per question. That number is a single sample from a stochastic process presented as a fact. It is the main reason eval results in this space are not trusted.

Fix three things and the score becomes defensible: **repeat the runs**, **report an interval**, and **separate coverage from accuracy**.

## 1. Repeat every case

Run each case `k` times. `k = 3` for iteration, `k = 5` before a release gate.

| Metric | Definition | Use |
|---|---|---|
| `pass@k` | passed **at least once** in k | Upper bound on capability. "Can it do this at all?" |
| `pass^k` | passed **all** k times | **Headline.** A business user gets one answer, not the best of five. |
| `pass_rate` | successes / k | Feeds the interval |

**Report `pass^k` as the headline and `pass@k` beside it.** The gap between them is the finding, not noise:

- Small gap, low score → the agent lacks knowledge. Fix context, add a semantic layer.
- **Large gap** → the agent knows how but is unreliable. Fix temperature, tool constraints, prompt determinism. Adding more context will not help.

That diagnosis is invisible in single-run evaluation, which is why it never gets made.

If you sample `n > k` times and want an unbiased `pass@k`, use the estimator from the Codex paper rather than the naive ratio:

```
pass@k = 1 - C(n - c, k) / C(n, k)      # c = number of correct samples out of n
```

## 2. Report an interval, not a point

Use a **Wilson score interval**, not the normal approximation. At the sample sizes and extreme proportions evaluation actually operates at (30 cases, 95% pass rate), the normal approximation produces intervals that extend past 1.0 and are simply wrong.

```
        p̂ + z²/2n            z              p̂(1-p̂)     z²
centre = ───────────   half = ────────  ·  √(────── + ────)
         1 + z²/n            1 + z²/n           n      4n²
```

`templates/pass_at_k.py` implements this along with `pass@k`, `pass^k` and the coverage split.

**Minimum useful suite size is about 30 cases.** Below that the interval is wider than any effect you are trying to detect, and you should say so rather than quoting a number.

## 3. Separate coverage from accuracy

Collapsing everything into pass/fail destroys the most actionable signal. Classify every run into one of five outcomes:

| Outcome | Meaning |
|---|---|
| `correct` | passed all assertions |
| `incorrect` | answered, and was wrong |
| `abstained` | explicitly declined ("I don't have enough information") |
| `clarification` | asked a question instead of answering |
| `error` | crashed, timed out, or hit a budget limit |

Then:

```
accuracy   = correct / (correct + incorrect)     quality when it answers
coverage   = (correct + incorrect) / total       willingness to answer
usefulness = correct / total                     what the business feels
```

Why this matters: an agent at **95% accuracy / 40% coverage** is cautious, not good. An agent at **70% accuracy / 100% coverage** is dangerous. A single pass rate reports them identically.

This split is also how you evaluate a semantic layer honestly. Adding one raises accuracy and lowers coverage — it makes metrics reliable while shrinking the set of answerable questions. Measure both before and after; do not take the trade on faith.

Detection of `abstained` and `clarification` is heuristic unless the agent reports its tool calls. **Label it as heuristic in the output.** If the agent exposes a clarification tool, key off that instead of classifying prose.

## 4. Account for cost

Record per run: LLM tokens in/out and cost, wall-clock latency, and warehouse bytes scanned or slot time where available.

Then report **cost per correct answer**, not cost per run. It is the number that decides model selection and nobody publishes it:

```
model                    pass^3   95% CI          $/correct   p95 latency
claude-sonnet-5          78.3%  [71.1, 84.1]        $0.021         8.4s
gpt-5.2                  74.6%  [67.1, 80.9]        $0.033        11.2s
qwen3-coder:30b (local)  61.1%  [53.3, 68.4]        $0.000        22.7s
```

A local model at 61% and zero marginal cost is the right choice for some workloads and disqualifying for others. That is a decision the table supports and a single accuracy number does not.

## 5. Gate CI on it

Store a baseline and compare against the merge base. Use distinct exit codes so a budget stop is not mistaken for a quality regression:

```
0  pass
1  accuracy regressed beyond threshold
2  budget exceeded
3  infrastructure error
```

A useful default threshold is `-2pp` on `pass^k` against the baseline. Emit JUnit XML for native CI rendering plus a short markdown summary for the PR:

```
eval: 178/180 pass^5 (98.9%) - baseline 98.3% (+0.6pp) OK
  new failure: churn_by_cohort_q3 (3/5, was 5/5)
  cost: $2.14 - 4m12s
```

Set a hard budget and check it **before** dispatching each batch, never after. An eval suite that silently spends $400 gets deleted.

## Procedure

1. Pre-flight: execute every reference SQL first. Quarantine cases whose reference fails — a broken golden scored as an agent failure poisons the whole report.
2. Run `cases × k`, bounded concurrency (4 is a reasonable default), persisting each result as it completes so an interrupted sweep can resume.
3. Grade with `compare-query-results`.
4. Classify outcomes, compute `pass@k`, `pass^k`, Wilson intervals, coverage split, cost per correct.
5. Report, including `k`, suite size, and the model — a score without those three is not interpretable.

## Anti-patterns

- **One run per case.** The whole problem.
- **Quoting a pass rate with no interval or no `n`.** Unfalsifiable.
- **Blending a strict rate and an LLM-judge rate into one number.** Report both, side by side, as a range.
- **Cherry-picking the suite after seeing results.** Fix the suite, re-baseline, and say you did.
- **Comparing models at different `k` or on different suites.** Meaningless.

## Related skills

- `generate-golden-queries` — build the suite
- `compare-query-results` — per-case grading
- `assert-agent-behavior` — cases with no reference result set
- `audit-agent-context` — why the score is what it is
