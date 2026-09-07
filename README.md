# analytics-evals

**Agent skills for testing analytics and text-to-SQL agents.** Build a golden test set from SQL your team already runs, score it in a way that survives scrutiny, and find out which context files are actually earning their tokens.

Works in Claude Code, Codex, Cursor, OpenCode, nao, and ~70 other agents via the [open agent skills spec](https://github.com/vercel-labs/skills).

```bash
npx skills add PaddyCH96/analytics-evals
```

---

## What this is

Six skills that teach a coding agent how to evaluate an analytics agent:

| Skill | What it does |
|---|---|
| **`generate-golden-queries`** | Mines your warehouse query history, dbt manifest or saved BI questions into a golden question/SQL test set — instead of hand-writing expected SQL |
| **`compare-query-results`** | Decides whether an answer matches the reference without false failures from aliases, row order, `Decimal` vs float, timezones, percent signs or NULLs |
| **`run-agent-eval`** | Repeated runs, `pass@k` and `pass^k`, Wilson confidence intervals, coverage separated from accuracy, cost per correct answer |
| **`assert-agent-behavior`** | Asserts what the agent *did* — asked a clarifying question, read a context file, avoided a forbidden table — not just the final number |
| **`audit-agent-context`** | Read-set analysis and cheap ablation: which context files change accuracy, and which are dead weight |
| **`review-sql-safety`** | AST review of agent-generated SQL — write operations hiding in CTEs, unpartitioned scans, joins that silently inflate aggregates |

## Why it exists

Analytics agents are now easy to stand up and nearly impossible to trust. Three specific problems, all of which show up in production:

**1. Nobody writes golden SQL by hand.** Every evaluation framework in this space asks you to. So nobody has a test suite — [nao](https://github.com/getnao/nao)'s own showcase project ships exactly one test case. Meanwhile your warehouse holds thousands of queries that real analysts wrote, ran, and acted on. `generate-golden-queries` mines those instead.

**2. One run per question is a coin flip reported as a fact.** LLM agents are stochastic. A framework that runs each case once and prints "82% accuracy" is quoting a single sample from a random process with no interval. `run-agent-eval` reports `pass^k` with a Wilson interval, and separates *accuracy* (quality when it answers) from *coverage* (willingness to answer) — an agent at 95%/40% and one at 70%/100% are very different products and a single pass rate reports them identically.

**3. Strict matching gets abandoned instead of fixed.** [nao issue #1469](https://github.com/getnao/nao/issues/1469) documents teams whose strict-match score "would tank accuracy", who now pipe every failure through a second LLM and publish *that* number. The cause is fixable: column aliases, row order, `Decimal` vs float, `42%` vs `0.42`, timezone-aware vs naive. `compare-query-results` handles all of them, with [a test suite](skills/compare-query-results/templates/test_compare_results.py) proving it.

**4. Nobody knows which context is working.** Teams accumulate hundreds of context artefacts and measure none of them. nao's founders [asked for this publicly](https://github.com/getnao/nao/discussions/68) — *"the users can see the impact of adding this or this context on the performance of the output (eg. should I add a preview of the tables or not)"* — and shipped token-count heuristics instead, because the causal version is expensive. `audit-agent-context` makes it affordable: free read-set pruning first, then paired runs with early stopping.

## What it looks like

```
Context ablation - 180 cases x 3 reps, claude-sonnet-5, paired, BH-corrected, 95% CI

  ARTEFACT                                  Δ pass^3    95% CI       tok/run   VERDICT
  RULES.md                                  +18.3pp  [15.2, 21.4]      1,240   keep
  databases/../orders/columns.md            +11.7pp  [ 8.9, 14.5]        890   keep
  databases/../orders/profiling.md           +4.2pp  [ 0.3,  8.1]      2,100   inconclusive
  databases/../orders/preview.md             +0.4pp  [-2.2,  3.0]      3,400   drop
  docs/notion/2024-pricing-migration.md      -3.1pp  [-5.3, -0.9]      1,850   drop (harmful)
  databases/../{131 other tables}/*                -        -          6,900   unread (0 reads)

  recommended corpus ...... 3,750 tok/run (-63%), accuracy unchanged
  sweep cost .............. $11.40, 22 min
```

The `unread` row is most of your corpus. The `drop (harmful)` row is a stale document actively making the agent worse. Neither is findable by reading token counts.

## Getting started

```bash
# install all six
npx skills add PaddyCH96/analytics-evals

# or just the ones you want
npx skills add PaddyCH96/analytics-evals --skill generate-golden-queries --skill run-agent-eval

# use one without installing
npx skills use PaddyCH96/analytics-evals@compare-query-results | claude
```

Then, in your agent:

> "Use generate-golden-queries to build a test set for our Snowflake warehouse from the last 90 days of query history."

> "Run the golden set against our agent 3 times per case and report pass^3 with confidence intervals."

> "Audit which context files in ./context are worth their tokens."

## Reference code

The skills are instructions, but three of them ship working implementations you can copy:

| File | Tests |
|---|---|
| [`compare_results.py`](skills/compare-query-results/templates/compare_results.py) | [28 cases](skills/compare-query-results/templates/test_compare_results.py) — locale numbers, `Decimal`, timezones, NULLs, rate rescaling |
| [`pass_at_k.py`](skills/run-agent-eval/templates/pass_at_k.py) | [24 cases](skills/run-agent-eval/templates/test_pass_at_k.py) — Wilson intervals checked against published values, unbiased `pass@k` |
| [`read_only.py`](skills/review-sql-safety/templates/read_only.py) | [16 cases](skills/review-sql-safety/templates/test_read_only.py) — including the data-modifying-CTE and `SELECT … INTO` bypasses that defeat regex filters |

```bash
python skills/compare-query-results/templates/test_compare_results.py
python skills/run-agent-eval/templates/test_pass_at_k.py
python skills/review-sql-safety/templates/test_read_only.py   # needs: pip install sqlglot
```

## How this differs from other data skill packs

[`dbt-labs/dbt-agent-skills`](https://github.com/dbt-labs/dbt-agent-skills) and [`astronomer/agents`](https://github.com/astronomer/agents) teach agents to **author** — write dbt models, write DAGs. This pack teaches agents to **verify**. They compose: author with those, measure with these.

## Scope

**In scope:** measuring analytics and text-to-SQL agents — test-set construction, result grading, scoring, behavioural assertions, context attribution, SQL review.

**Out of scope:** writing analytical SQL, building dashboards, semantic-layer modelling, and access control. On the last one especially — read-only database credentials are the security boundary, not anything in this repo. `review-sql-safety` says so explicitly.

## Contributing

New warehouse extraction templates, additional false-failure cases for the comparison corpus, and adapters for other agents are all welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

The comparison corpus in particular gets better with every real false failure someone reports — if a formatting difference made a correct answer score as wrong, that is a bug worth a test case.

## Licence

[Apache 2.0](LICENSE).
