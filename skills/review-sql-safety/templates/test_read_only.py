import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from read_only import is_read_only

cases = [
    # (sql, dialect, expect_allowed, label)
    ("SELECT region, SUM(amount) FROM orders GROUP BY 1", "postgres", True, "plain select"),
    ("WITH x AS (SELECT 1 AS a) SELECT * FROM x", "postgres", True, "benign CTE"),
    ("WITH deleted AS (DELETE FROM orders RETURNING *) SELECT * FROM deleted", "postgres", False, "BYPASS 1: data-modifying CTE"),
    ("WITH ins AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM ins", "postgres", False, "data-modifying CTE (insert)"),
    ("WITH upd AS (UPDATE t SET a=1 RETURNING *) SELECT * FROM upd", "postgres", False, "data-modifying CTE (update)"),
    ("SELECT * INTO exfiltrated FROM customers", "postgres", False, "BYPASS 2: SELECT INTO"),
    ("DROP TABLE orders", "postgres", False, "drop"),
    ("TRUNCATE TABLE orders", "postgres", False, "truncate"),
    ("CREATE TABLE t AS SELECT 1", "postgres", False, "ctas"),
    ("MERGE INTO t USING s ON t.id=s.id WHEN MATCHED THEN UPDATE SET a=1", "snowflake", False, "merge"),
    ("GRANT SELECT ON t TO r", "postgres", False, "grant"),
    ("SELECT * FROM t; DROP TABLE t", "postgres", False, "stacked statements"),
    ("SELECT a FROM (SELECT a FROM t) s", "postgres", True, "subquery select"),
    ("this is not sql at all !!!", "postgres", False, "unparseable -> reject"),
    ("SELECT TOP 10 * FROM orders", "tsql", True, "tsql top"),
    ("SELECT * FROM t QUALIFY ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) = 1", "snowflake", True, "snowflake qualify"),
]

fails = []
for sql, dialect, expect, label in cases:
    allowed, reason = is_read_only(sql, dialect)
    ok = allowed == expect
    verdict = "ALLOW" if allowed else "REJECT"
    print(("  PASS  " if ok else "  FAIL  ") + f"{label:38s} -> {verdict:6s} ({reason[:45]})")
    if not ok: fails.append(label)

print()
print(f"{len(fails)} failure(s)" + (": " + ", ".join(fails) if fails else ""))
