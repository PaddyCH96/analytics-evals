# Contributing

Issues, pull requests and corrections are all welcome. There is no approval gate — open a PR.

## The most valuable contribution

**A false failure you hit in the wild.** If a correct answer scored as wrong because of a formatting, type or ordering difference, that is a bug in `compare-query-results` and it should become a permanent test case:

1. Add the pair to `skills/compare-query-results/templates/test_compare_results.py`.
2. Fix `compare_results.py` until it passes.
3. If the cause is a general class rather than a one-off, add a row to the decision table in `SKILL.md`.

The comparison corpus is the part of this repo that gets better with use. Every case someone contributes is a false verdict that never happens again.

## Also wanted

- **Warehouse extraction templates.** `generate-golden-queries/templates/query-history.sql` covers Snowflake, BigQuery, Postgres and Databricks. Missing: Redshift, ClickHouse, Trino, Athena, MotherDuck, Fabric. Include the retention window, the permission needed, and any normalisation caveat (Postgres, for example, hands back query *shapes* rather than runnable SQL — that caveat matters more than the query).
- **Agent adapters.** Notes on wiring these skills to a specific agent — nao, Wren AI, LangChain/LangGraph, an MCP server. Especially: which of the four behavioural signals (tool calls, generated SQL, context reads, final message) that agent exposes, since assertions requiring a missing signal must be reported as *skipped*, never as passed.
- **Corrections.** If a claim here is wrong, say so with evidence. Several statements about other projects are cited to specific issues and source files; if one is out of date, that is worth a PR.

## Standards

**Skills are instructions, not essays.** Aim for 80–150 lines. Every section should change what an agent does. If a paragraph would not alter behaviour, cut it.

**Be specific.** "Handle timezones carefully" is worthless. "Normalise to UTC and compare at second granularity, because a tz-aware/naive mismatch raises rather than failing cleanly" is a skill.

**Cite evidence for claims about other tools.** Link the issue, the discussion, or the source file. Claims in this repo about nao, Wren AI and others are all traceable; keep it that way.

**Reference code must be tested and dependency-light.** Standard library where possible, `pandas`/`numpy` where not, `sqlglot` only for the SQL skill. Every test must run on a fresh clone with no credentials and no network.

**Frontmatter.** `name` (lowercase, hyphenated, matching the directory) and `description`. The description is what an agent uses to decide whether to load the skill — state what it does, when to use it, and explicitly when *not* to.

## Running the tests

```bash
python skills/compare-query-results/templates/test_compare_results.py
python skills/run-agent-eval/templates/test_pass_at_k.py
pip install sqlglot && python skills/review-sql-safety/templates/test_read_only.py
```

All three should print `0 failure(s)`.

## Scope

In: measuring analytics and text-to-SQL agents.

Out: writing analytical SQL, dashboards, semantic-layer modelling, and access control. Access control belongs in the database — this repo will not grow an enforcement layer, and `review-sql-safety` is explicit that it is defence in depth only.
