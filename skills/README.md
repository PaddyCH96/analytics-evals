# Skills

Six skills that compose into one loop. Each is useful alone; together they take a team from "we have no idea if this agent works" to a CI gate.

```
                    generate-golden-queries
                        (build the suite)
                               │
                               ▼
   review-sql-safety ──▶  run-agent-eval  ◀── compare-query-results
   (vet the SQL)          (score it)           (grade one case)
                               │                      ▲
                               │                      │
                               ▼              assert-agent-behavior
                      audit-agent-context      (cases with no number)
                    (why the score is what it is)
```

| Skill | Read it when |
|---|---|
| [`generate-golden-queries`](generate-golden-queries/SKILL.md) | You have no test cases, or someone is about to hand-write expected SQL |
| [`compare-query-results`](compare-query-results/SKILL.md) | Correct answers are scoring as failures, or you are writing a grader |
| [`run-agent-eval`](run-agent-eval/SKILL.md) | You need a score you can defend, or you are comparing models |
| [`assert-agent-behavior`](assert-agent-behavior/SKILL.md) | The question is ambiguous, or you care *how* the answer was reached |
| [`audit-agent-context`](audit-agent-context/SKILL.md) | The context corpus is large, costs are rising, or answers are drifting |
| [`review-sql-safety`](review-sql-safety/SKILL.md) | An agent generates SQL that will actually run somewhere |

## Suggested order for a team starting from zero

1. **`generate-golden-queries`** — an afternoon gets you 100+ reviewed cases.
2. **`run-agent-eval`** with `k=3` — your first honest number, with an interval.
3. **`compare-query-results`** — tighten the grader on whatever false failures show up.
4. **`assert-agent-behavior`** — add ambiguity, retrieval and refusal cases.
5. **`audit-agent-context`** — start with free read-set analysis before paying for ablation.
6. **`review-sql-safety`** — before anything reaches a production warehouse.

## Reference implementations

Three skills ship tested Python you can copy into a project. All tests run with no credentials and no network:

```bash
python compare-query-results/templates/test_compare_results.py   # 28 cases
python run-agent-eval/templates/test_pass_at_k.py                # 24 cases
python review-sql-safety/templates/test_read_only.py             # 16 cases (pip install sqlglot)
```
