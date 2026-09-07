"""AST-based read-only validation for LLM-generated SQL.

Defence in depth only - read-only database credentials are the real control.
Verified against sqlglot 30.x; see test_read_only.py.

    pip install sqlglot
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
    exp.Alter, exp.TruncateTable, exp.Merge, exp.Grant,
)


def is_read_only(sql: str, dialect: str) -> tuple[bool, str]:
    """Return (allowed, reason).

    Rejects write operations anywhere in the tree - including inside CTEs,
    which is where regex-based filters are bypassed - and rejects anything
    that fails to parse in the target dialect.
    """
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as exc:  # a statement you cannot parse is one you cannot vet
        return False, f"unparseable as {dialect}: {exc}"

    for stmt in statements:
        if stmt is None:
            continue
        for node_type in WRITE_NODES:
            if isinstance(stmt, node_type) or stmt.find(node_type):
                return False, f"contains {node_type.__name__.lower()}"
        if stmt.args.get("into"):
            return False, "SELECT ... INTO creates an object"
    return True, "read-only"
