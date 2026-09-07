---
name: compare-query-results
description: Decide correctly whether an analytics agent's answer matches a reference result set, without the false failures that come from column aliases, row order, rounding, percent signs, Decimal vs float, timezones or NULL handling. Use when grading text-to-SQL output, writing an eval harness, or when someone says their strict-match accuracy is misleadingly low. Do not use for comparing SQL text similarity — comparing the executed results is the point.
---

# Compare query results

The right way to grade a text-to-SQL answer is to execute the reference SQL, execute (or take) the agent's result, and compare the two result sets. Comparing SQL *text* is wrong — two very different queries can be equally correct, and two near-identical queries can differ on a join grain.

The trap is that a naive result comparison produces **false failures**, and teams respond by abandoning the metric. This is documented in the field: nao issue #1469 reports teams whose strict-match score "would tank accuracy", who now run every failure through a second LLM and publish *that* number instead. The fix is not an LLM judge. The fix is to get the comparison right.

## The ten decisions

Work through these in order. Each one is a real source of false verdicts.

| # | Decision | Default | Why |
|---|---|---|---|
| 1 | Row order | **Ignore** — sort by all columns | "Top 5 customers" cares about membership; ties order arbitrarily. Set `ordered: true` only when the question asks for a ranking *and* the ordering column has no ties. |
| 2 | Column order | **Ignore** — sort alphabetically | Cosmetic. |
| 3 | Column names | **Must match** the reference | This is the one thing you should be strict about. Without it, two different quantities that happen to be numerically equal will pass. If the agent aliases `total_revenue` as `revenue`, that is a *reference* problem — fix the reference or add an alias map, do not relax the rule globally. |
| 4 | Extra columns | Project to the reference's columns | An agent returning a helpful extra column is not wrong. |
| 5 | Missing columns | Fail, naming the column | Actionable failure message. |
| 6 | Float tolerance | `rtol=1e-5`, `atol=1e-8`, round to 2 dp | Sane for money. Raise `decimals` for ratios. |
| 7 | **Numeric types** | Coerce `Decimal` → float before comparing | Snowflake returns `Decimal`, DuckDB returns `float`, BigQuery returns `NUMERIC`. Comparing them raw fails on identical answers. **This is the single most common false failure.** |
| 8 | **Timestamps** | Normalise to UTC, compare at second granularity | Warehouses differ on session timezone and on tz-aware vs tz-naive. A tz-aware/naive mismatch raises or fails silently. |
| 9 | **NULL semantics** | Map `None` / `NaN` / `NaT` / `pd.NA` to one sentinel; treat NULL == NULL | SQL says `NULL != NULL`. A test framework must not — otherwise any row with a NULL never matches itself. |
| 10 | Empty results | empty vs empty passes; empty vs non-empty fails with a *distinct* reason | "Agent returned nothing" and "agent returned wrong rows" need different fixes. |

## Formatting normalisation

Before comparing, normalise string cells that are really numbers. These all mean 1234.56:

```
"1,234.56"   "$1,234.56"   "1.234,56"   "1 234,56"   "€1234.56"   "1234.56 "
```

And these are the same value with a presentation difference:

```
0.42   "42%"   "42.0%"
```

Strip currency symbols, thin/non-breaking spaces and thousands separators; detect EU vs US decimal convention; and if one side is a percentage string and the other a fraction, scale before comparing — but **only** when the column name suggests a rate (`*_pct`, `*_rate`, `*_share`). Do not silently multiply by 100 on a column called `amount`.

## Order of operations

```
1. both sides -> DataFrame
2. empty checks                       (decision 10)
3. project to reference columns       (decisions 4, 5)
4. normalise formatted strings        (percent, currency, locale)
5. coerce types: Decimal->float, tz->UTC, NULL->sentinel  (7, 8, 9)
6. round floats to `decimals`         (6)
7. sort columns, then sort rows       (1, 2)
8. exact equality
9. if not equal: np.allclose per numeric column, exact for the rest
10. on failure: emit a DataFrame.compare diff, not just "mismatch"
```

Step 10 matters more than it looks. A verdict of "values differ" costs the user ten minutes; a rendered diff costs them ten seconds.

## Reference implementation

`templates/compare_results.py` is a dependency-light implementation of the above (pandas + numpy only). Copy it into the project and adapt. It returns a verdict, a reason, and a rendered diff.

```python
from compare_results import compare

verdict = compare(actual_rows, expected_rows, decimals=2)
if not verdict.passed:
    print(verdict.reason)
    print(verdict.diff)
```

## When you genuinely cannot compare deterministically

Some answers have no reference result set — "summarise what changed in churn last quarter". For those:

- Do **not** stretch result comparison to cover them. Use a behavioural assertion instead (see `assert-agent-behavior`), or an explicit LLM judge.
- If you use a judge, judge **the result output only**, never the whole conversation — otherwise you reward a wrong path that reached a right answer.
- Report the judge rate as a **separate number alongside** the strict rate, never blended into one figure. Two numbers give an honest range; one blended number is a claim you cannot defend.

## Anti-patterns

- **Comparing SQL strings, or embedding-similarity of SQL.** Measures style, not correctness.
- **Relaxing column-name matching to raise the pass rate.** You are now measuring nothing.
- **Comparing a single aggregate row without checking the column name.** Coincidental numeric equality passes.
- **Using an LLM judge as the primary metric.** It is not reproducible, it costs money to re-grade, and it can be talked into anything by a compromised agent.

## Related skills

- `generate-golden-queries` — where the reference SQL comes from
- `run-agent-eval` — turning per-case verdicts into a defensible score
- `assert-agent-behavior` — grading cases that have no reference result
