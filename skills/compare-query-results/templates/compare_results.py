"""Result-set comparison for analytics-agent evaluation.

Decides whether an agent's answer matches a reference result set, handling the
formatting and type differences that cause false failures across warehouses.

Dependencies: pandas, numpy.

    from compare_results import compare

    verdict = compare(actual_rows, expected_rows, decimals=2)
    if not verdict.passed:
        print(verdict.reason)
        print(verdict.diff)

Rows may be a list of dicts, a dict of lists, or a DataFrame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

import numpy as np
import pandas as pd

__all__ = ["Verdict", "compare", "normalize_number"]


# --------------------------------------------------------------------------
# number formatting
# --------------------------------------------------------------------------

_CURRENCY = re.compile(r"[\$€£¥₹]")
_SPACES = re.compile(r"[\s  ]")
_US = re.compile(r"-?\d{1,3}(,\d{3})+(\.\d+)?$")       # 1,234,567.89
_EU = re.compile(r"-?\d{1,3}(\.\d{3})+(,\d+)?$")       # 1.234.567,89
_EU_DEC = re.compile(r"-?\d+,\d+$")                    # 1234,56
_PLAIN = re.compile(r"-?\d+(\.\d+)?$")                 # 1234.56

_RATE_COLUMN = re.compile(r"(_pct|_percent|_rate|_share|_ratio)$|^pct_", re.I)


def normalize_number(value: Any) -> Any:
    """Parse a locale/currency formatted numeric string into a float.

    Returns the input unchanged when it is not a numeric-looking string.
    A trailing '%' is stripped and the value divided by 100.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return value
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1].strip()

    cleaned = _SPACES.sub("", _CURRENCY.sub("", text))
    if cleaned in ("", "-", "+"):
        return value

    negative = cleaned.startswith("-")
    unsigned = cleaned.lstrip("+-")

    parsed: float | None = None
    if _US.fullmatch(unsigned):
        parsed = float(unsigned.replace(",", ""))
    elif _EU.fullmatch(unsigned):
        parsed = float(unsigned.replace(".", "").replace(",", "."))
    elif _EU_DEC.fullmatch(unsigned):
        parsed = float(unsigned.replace(",", "."))
    elif _PLAIN.fullmatch(unsigned):
        parsed = float(unsigned)

    if parsed is None:
        return value
    if negative:
        parsed = -parsed
    return parsed / 100.0 if is_percent else parsed


# --------------------------------------------------------------------------
# coercion
# --------------------------------------------------------------------------

def _coerce_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("UTC").tz_localize(None) if value.tzinfo else value
    return normalize_number(value)


def _coerce_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(_coerce_cell)
        # a column of datetimes may still be tz-aware after map
        if isinstance(out[col].dtype, pd.DatetimeTZDtype):
            out[col] = out[col].dt.tz_convert("UTC").dt.tz_localize(None)
        # try to recover a real numeric dtype from object columns
        if out[col].dtype == object:
            try:
                out[col] = pd.to_numeric(out[col])
            except (TypeError, ValueError):
                pass
    return out


def _rescale_rate_columns(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    """If one side reports a rate column as 0-100 and the other as 0-1, align them.

    Only applied to columns whose name looks like a rate, to avoid silently
    scaling a column called `amount`.
    """
    for col in expected.columns:
        if not _RATE_COLUMN.search(str(col)):
            continue
        a, e = actual[col], expected[col]
        if not (pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(e)):
            continue
        a_max, e_max = a.abs().max(), e.abs().max()
        if pd.isna(a_max) or pd.isna(e_max) or a_max == 0 or e_max == 0:
            continue
        if a_max > 1.5 >= e_max:
            actual[col] = a / 100.0
        elif e_max > 1.5 >= a_max:
            expected[col] = e / 100.0


def _round_floats(df: pd.DataFrame, decimals: int) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_float_dtype(s):
            out[col] = s.round(decimals)
        elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_integer_dtype(s):
            out[col] = pd.to_numeric(s, errors="coerce").round(decimals)
    return out


def _sort_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by every column using a string key so mixed types never raise."""
    if df.empty:
        return df
    key = df.astype(str)
    order = key.sort_values(by=list(key.columns), kind="mergesort").index
    return df.loc[order].reset_index(drop=True)


def _to_frame(rows: Any) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        return rows.copy()
    if rows is None:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------

@dataclass
class Verdict:
    passed: bool
    reason: str
    diff: str | None = None


def _columns_equal(
    a: pd.Series, e: pd.Series, rtol: float, atol: float
) -> pd.Series:
    """Elementwise equality mask; both-NULL counts as equal."""
    both_null = a.isna() & e.isna()
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(e):
        close = pd.Series(
            np.isclose(
                pd.to_numeric(a, errors="coerce").astype(float).to_numpy(),
                pd.to_numeric(e, errors="coerce").astype(float).to_numpy(),
                rtol=rtol,
                atol=atol,
                equal_nan=True,
            ),
            index=a.index,
        )
        return close | both_null
    return (a.astype(str) == e.astype(str)) | both_null


def compare(
    actual_rows: Any,
    expected_rows: Any,
    *,
    columns: Sequence[str] | None = None,
    decimals: int = 2,
    rtol: float = 1e-5,
    atol: float = 1e-8,
    ordered: bool = False,
    max_diff_rows: int = 10,
) -> Verdict:
    """Compare an agent result set against a reference result set.

    columns  restrict the comparison to these columns (defaults to the
             reference's columns)
    ordered  keep row order significant
    """
    actual = _to_frame(actual_rows)
    expected = _to_frame(expected_rows)

    # 2 - empty checks
    if actual.empty and expected.empty:
        return Verdict(True, "both empty")
    if actual.empty:
        return Verdict(False, "agent returned no rows; reference returned "
                              f"{len(expected)}")
    if expected.empty:
        return Verdict(False, "reference returned no rows - the golden case is "
                              "broken, quarantine it")

    # 3 - project to reference columns
    wanted = list(columns) if columns else list(expected.columns)
    missing = [c for c in wanted if c not in actual.columns]
    if missing:
        return Verdict(False, f"missing columns: {', '.join(map(str, missing))}")
    actual = actual[wanted]
    expected = expected[wanted]

    if len(actual) != len(expected):
        return Verdict(
            False, f"row count differs: agent {len(actual)}, reference {len(expected)}"
        )

    # 4, 5 - normalise and coerce
    actual = _coerce_frame(actual)
    expected = _coerce_frame(expected)
    _rescale_rate_columns(actual, expected)

    # 6 - round
    actual = _round_floats(actual, decimals)
    expected = _round_floats(expected, decimals)

    # 1, 2 - ordering
    cols = sorted(wanted, key=str)
    actual = actual[cols]
    expected = expected[cols]
    if not ordered:
        actual = _sort_rows(actual)
        expected = _sort_rows(expected)
    else:
        actual = actual.reset_index(drop=True)
        expected = expected.reset_index(drop=True)

    # 8, 9 - elementwise comparison
    mismatched: list[str] = []
    row_mask = pd.Series(True, index=expected.index)
    for col in cols:
        eq = _columns_equal(actual[col], expected[col], rtol, atol)
        row_mask &= eq
        if not eq.all():
            mismatched.append(str(col))

    if not mismatched:
        return Verdict(True, "match")

    # 10 - render a useful diff
    bad = (~row_mask).to_numpy().nonzero()[0][:max_diff_rows]
    lines = [f"columns differing: {', '.join(mismatched)}", ""]
    for i in bad:
        a_row = {c: actual.iloc[i][c] for c in mismatched}
        e_row = {c: expected.iloc[i][c] for c in mismatched}
        lines.append(f"  row {i}: agent={a_row}  reference={e_row}")
    extra = int((~row_mask).sum()) - len(bad)
    if extra > 0:
        lines.append(f"  ... and {extra} more differing rows")

    return Verdict(False, "values differ", "\n".join(lines))
