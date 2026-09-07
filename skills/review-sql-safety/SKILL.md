---
name: review-sql-safety
description: Review SQL that an LLM or analytics agent generated, before it runs — parse it with an AST to catch write operations hiding inside read-looking statements, unbounded or unpartitioned scans that will cost real money, and join patterns that silently inflate aggregates. Use when building a text-to-SQL agent, reviewing agent-generated SQL, or hardening a query path. Do not use as the primary access control — read-only database credentials are that.
---

# Review agent-generated SQL

Start with the thing most implementations get backwards:

> **The database is the security boundary. The application is not.**

The primary control on an analytics agent is a **read-only role**, scoped to the schemas it needs. Everything in this skill is defence in depth. If you find yourself relying on application-level SQL filtering to prevent writes, stop and fix the credentials instead.

With that said, defence in depth is worth having — and the common implementation of it is broken.

## Why regex read-only filters fail

The usual approach is: reject if the statement starts with a write keyword, accept if it starts with `SELECT` or `WITH`. This is what shipped analytics tools actually do, and it has verified bypasses.

**Bypass 1 — data-modifying CTE.** PostgreSQL and Redshift-family engines allow DML inside `WITH`:

```sql
WITH deleted AS (DELETE FROM orders RETURNING *) SELECT * FROM deleted;
```

A filter that finds the keyword after the CTE list sees `SELECT` and allows it. The data is gone. This is a real defect in shipped software, not a hypothetical.

**Bypass 2 — `SELECT … INTO`.** Starts with `SELECT`, creates a table:

```sql
SELECT * INTO exfiltrated FROM customers;
```

**Bypass 3 — volatile functions.** No parser catches this one:

```sql
SELECT audit_and_purge();
```

Only database permissions stop it. Which is the point.

## Parse, don't match

Use `sqlglot` — it is multi-dialect and understands CTEs, subqueries and dialect quirks that regex cannot.

```python
import sqlglot
from sqlglot import exp

WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
    exp.Alter, exp.TruncateTable, exp.Merge, exp.Grant,
)

def is_read_only(sql: str, dialect: str) -> tuple[bool, str]:
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:
        # A statement you cannot parse is a statement you cannot vet.
        return False, f"unparseable as {dialect}: {e}"

    for stmt in statements:
        if stmt is None:
            continue
        # catches DML anywhere, including inside CTEs and subqueries
        for node_type in WRITE_NODES:
            if isinstance(stmt, node_type) or stmt.find(node_type):
                return False, f"contains {node_type.__name__.lower()}"
        # SELECT ... INTO
        if stmt.args.get("into"):
            return False, "SELECT ... INTO creates an object"
    return True, "read-only"
```

Three rules that matter more than the code:

1. **Traverse the whole tree**, not the top-level node. `stmt.find(exp.Delete)` is what catches the CTE bypass.
2. **Parse failure is rejection.** Never fall through to "allow" because the parser choked — that is how dialect-specific payloads get in.
3. **Parse in the target dialect.** Parsing Snowflake SQL as generic ANSI produces both false rejections and false acceptances.

## Cost and blast radius

An agent that is correct but expensive still gets switched off. Check before executing:

| Check | How | Why |
|---|---|---|
| **Missing partition filter** | Table is partitioned (from catalogue) and no predicate on the partition column | The single biggest source of surprise warehouse bills. A real user request against nao (#1406) asks for exactly this as an enforced option. |
| **No `LIMIT` on an exploratory query** | No top-level `LIMIT` / `TOP` / `FETCH FIRST` | Cap it yourself; do not rely on the model remembering. |
| **`SELECT *` on a wide or large table** | Star projection + column count or row estimate from the catalogue | Wastes scan and floods the context window. |
| **Cartesian join** | A join with no `ON` / `USING`, or a cross join over base tables | Almost always a bug. |
| **Cross-database or cross-region reference** | Qualified names outside the allowed set | Egress cost and, often, a governance violation. |
| **Estimated cost** | BigQuery dry-run; Snowflake `EXPLAIN` | Cheap, exact, and available. Use it. |

Enforce a timeout and a row cap in the execution layer itself, so an unbounded query is not expressible. A cap you have to remember to pass is a cap you will forget.

## Correctness smells

These do not fail — they return a wrong number that nobody notices. They are the most damaging category and no security tool looks for them.

**Fan-out on a one-to-many join.** The classic silent analytics error:

```sql
SELECT c.region, SUM(o.amount)
FROM customers c
JOIN orders o     USING (customer_id)
JOIN order_items i USING (order_id)   -- one order, many items
GROUP BY 1
```

`SUM(o.amount)` is now multiplied by the item count per order. The query runs, the number is wrong, and it is plausible enough to ship. **Check: is an aggregate applied to a column from a table that is on the "one" side of a join to a finer grain?** If so, flag it — the fix is usually pre-aggregation or `SUM(DISTINCT ...)` on a key.

Others worth flagging:

- **`COUNT(*)` after a `LEFT JOIN`** — counts unmatched rows as 1. Usually `COUNT(target.id)` is meant.
- **Filtering the right table in the `WHERE` clause of a `LEFT JOIN`** — silently converts it to an inner join. The predicate belongs in `ON`.
- **`NOT IN` against a nullable column** — returns no rows if any value is NULL. `NOT EXISTS` is almost always intended.
- **Date range with `BETWEEN` on a timestamp** — `BETWEEN '2026-07-01' AND '2026-09-30'` drops everything after midnight on the last day. Use a half-open range.
- **Averaging an average** — `AVG` over pre-aggregated values is not the overall average unless the groups are equal-sized.

An agent that produces these will pass a naive result comparison whenever the reference SQL contains the same mistake — which is one more reason golden SQL should come from queries analysts already trusted and reviewed.

## Untrusted content

Table values, synced wiki pages and SQL comments are attacker-controlled input to the model. Two rules:

- **Never execute SQL the model generated in an evaluation harness.** Execute only human-reviewed reference SQL. Parse and display the agent's SQL; do not run it. That single decision means a fully compromised agent can produce a failing test and nothing worse.
- **Escape agent output before rendering it.** Reports containing agent prose and raw row values are an XSS vector. Autoescape on, no `innerHTML`, and a restrictive CSP.

## Review checklist

```
[ ] parsed successfully in the target dialect
[ ] no write nodes anywhere in the tree (including CTEs and subqueries)
[ ] no SELECT ... INTO
[ ] every referenced table and column exists in the catalogue
[ ] no reference outside the allowed schemas
[ ] partition filter present where the table is partitioned
[ ] top-level row limit present, or enforced by the executor
[ ] no cartesian join
[ ] estimated cost within budget
[ ] no aggregate over a fan-out join
[ ] date ranges half-open on timestamp columns
[ ] running under read-only credentials  <- the one that actually matters
```

## What this skill is not

It is not an access-control system and should not be sold or deployed as one. Row- and column-level security belong in the database, where they are enforced regardless of which client connects. Application-layer filtering that *looks* like access control teaches people to trust the wrong layer — which is more dangerous than having no filter at all.

## Related skills

- `assert-agent-behavior` — `not_referenced`, `no_table_hallucination` as test assertions
- `compare-query-results` — catching wrong numbers that ran fine
- `generate-golden-queries` — validate mined SQL before it enters a suite
