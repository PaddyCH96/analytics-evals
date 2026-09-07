---
name: generate-golden-queries
description: Build a golden question/SQL test set for a text-to-SQL or analytics agent by mining SQL the team already trusts — warehouse query history, dbt models and metrics, or saved BI questions — instead of hand-writing expected SQL. Use when someone needs to test an analytics agent, has no test cases, or says writing goldens by hand is too slow. Covers Snowflake, BigQuery, Postgres, Databricks and dbt. Do not use to write new analytical SQL from scratch, or to evaluate a run (use run-agent-eval).
---

# Generate golden queries

Every analytics-agent evaluation framework asks you to hand-write the expected SQL for each test. That is why almost nobody has a test suite — nao's own showcase project ships exactly one test case.

You do not need to write them. Your warehouse already contains thousands of queries that real analysts wrote, ran, and acted on. Mine those instead.

## When to use this

- A team has deployed an analytics agent and has no way to measure it.
- Someone is about to hand-write golden SQL. Stop them.
- An existing suite is too small to be meaningful (< 30 cases).

## Pipeline

```
extract → filter → deduplicate → rank → write question → validate → REVIEW
```

Never skip the last step. See "Review" below.

### Step 1 — Extract

Use the template in `templates/query-history.sql` for the user's warehouse. Key points per platform:

| Warehouse | Source | Watch out for |
|---|---|---|
| Snowflake | `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` | Up to 45 min latency. Needs a role with `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database (usually `ACCOUNTADMIN` grants it). |
| BigQuery | `` `region-us`.INFORMATION_SCHEMA.JOBS `` | Must be region-qualified. Use `JOBS_BY_PROJECT` for one project, `JOBS_BY_ORGANIZATION` for all. 180-day retention. |
| Postgres | `pg_stat_statements` | **Query text is normalised** — literals are replaced with `$1`, `$2`. You get query *shapes*, not runnable SQL. You must re-substitute plausible literals before the query will execute. |
| Databricks | `system.query.history` | Requires the system schema to be enabled. |
| DuckDB / local | no persistent history | Fall back to the dbt route below. |

If there is no usable history, use dbt instead: read `target/manifest.json` and turn each model and each metric into a case. A model becomes "show me `<model description>`"; a metric becomes "what is `<metric>` by `<dimension>` for `<period>`".

### Step 2 — Filter

Drop aggressively. Most query history is machine traffic.

- Keep only `SELECT` / `WITH … SELECT`. Drop DDL, DML, `SHOW`, `DESCRIBE`, `USE`.
- Drop by user and application: dbt service accounts, Fivetran/Airbyte, Looker/Tableau/Metabase renderers, Airflow, monitoring. On Snowflake, filter on `USER_NAME` and the `client_application_id` in `SESSION_HISTORY`; on BigQuery, filter `user_email` and `labels`.
- Drop failures (`EXECUTION_STATUS != 'SUCCESS'` / `state != 'DONE'` with `error_result`).
- Drop trivia: `SELECT 1`, `SELECT CURRENT_TIMESTAMP`, single-table scans with no predicate, no aggregation and no join.
- Drop anything referencing tables the agent cannot see.
- Drop anything that took longer than ~60s or scanned more than a few GB — you will re-run these many times during evaluation and cost matters.

### Step 3 — Deduplicate

A dashboard runs the same query 4,000 times. That is one case, not four thousand.

Normalise with `sqlglot` before fingerprinting — parse, then replace literals with placeholders, canonicalise aliases and whitespace, and hash the result:

```python
import sqlglot
from sqlglot import exp

def fingerprint(sql: str, dialect: str) -> str:
    tree = sqlglot.parse_one(sql, read=dialect)
    for lit in tree.find_all(exp.Literal):
        lit.replace(exp.Placeholder())
    return tree.sql(dialect=dialect, normalize=True, pretty=False)
```

Keep one representative per fingerprint and carry forward `executed_count` and `distinct_users`.

### Step 4 — Rank

This is what makes a mined suite *better* than a hand-written one, not just cheaper: it is weighted by what the business actually asks.

```
score = distinct_users × log1p(executed_count) × distinct_tables_referenced
```

Questions many different humans ask, touching several tables, are the ones worth testing. Take the top N by score, but stratify — do not let one dashboard's family of queries fill the whole suite. Cap cases per source table.

### Step 5 — Write the question

For each surviving query, write the natural-language question an analyst would have asked to get it. This is the only step that needs a language model.

Rules:
- Ask what a business user would ask, not a description of the SQL. Good: *"What was net revenue by region last quarter?"* Bad: *"Select region and sum of amount minus refunds from orders grouped by region."*
- Do not leak column names or the join path into the question. If the question names the columns, you are testing string matching, not the agent.
- Preserve any time window as the analyst would say it ("last quarter", "in Q3 2026"), and record the literal dates in the case so the reference SQL stays deterministic.
- If the SQL encodes a business definition (a filter like `status NOT IN ('test','internal')`), the question should *not* mention it. Whether the agent knows that rule is exactly what you are measuring.

### Step 6 — Validate

Execute the reference SQL before accepting the case. Reject it if it errors, returns zero rows, or returns more rows than your comparison cap. A broken golden scored as an agent failure is worse than no test at all.

### Step 7 — Review (mandatory)

**Nothing enters the suite without a human confirming it.** Present each candidate as: question, reference SQL, a preview of the result, and provenance (`executed_count`, `distinct_users`, source query id). The reviewer accepts, edits, or rejects.

Two reasons, and both matter:
- **Quality.** A generated question that is subtly wrong produces a test that is confidently wrong forever.
- **Security.** Query history is untrusted input. A SQL comment can contain text aimed at the model that wrote the question. Human review is the control.

Target throughput is about one case a minute for someone who knows the domain. If review is slower than that, your filters are too loose — go back to step 2.

## Output format

Write one YAML file per case, or one file with a list. Minimum viable shape:

```yaml
id: net_revenue_by_region_q3
question: What was net revenue by region in Q3 2026?
reference_sql: |
  SELECT region, SUM(amount - refunds) AS net_revenue
  FROM analytics.orders
  WHERE order_date BETWEEN '2026-07-01' AND '2026-09-30'
  GROUP BY 1
warehouse: main
tags: [revenue, finance]
provenance:
  source: query_history
  source_ref: snowflake:01b2c3d4-0000-abcd
  executed_count: 47
  distinct_users: 6
  reviewed_by: <name>
```

Keep `provenance`. It is what lets you weight the suite by business importance later, and it is how you audit where a test came from when it starts failing.

## Realistic yield

From ~10,000 history rows expect roughly 200–400 unique candidates after filtering and dedupe, of which 100–150 survive review. That is an afternoon's work for a suite two orders of magnitude larger than what most teams have.

## Related skills

- `compare-query-results` — how to decide whether the agent's answer matches the reference
- `run-agent-eval` — running the suite and reporting `pass^k`
- `review-sql-safety` — before you execute anything mined from history
