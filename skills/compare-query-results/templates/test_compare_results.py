import sys, datetime as dt
from decimal import Decimal
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import pandas as pd
from compare_results import compare, normalize_number

fails = []
def check(name, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   got={got} want={want}"))
    if not ok: fails.append(name)

# --- normalize_number
check("num: plain", normalize_number("1234.56"), 1234.56)
check("num: US thousands", normalize_number("1,234.56"), 1234.56)
check("num: currency", normalize_number("$1,234.56"), 1234.56)
check("num: EU", normalize_number("1.234,56"), 1234.56)
check("num: EU decimal", normalize_number("1234,56"), 1234.56)
check("num: percent", normalize_number("42%"), 0.42)
check("num: negative", normalize_number("-$1,234.56"), -1234.56)
check("num: passthrough text", normalize_number("EMEA"), "EMEA")
check("num: Decimal", normalize_number(Decimal("10.5")), 10.5)

# --- compare
base = [{"region":"EMEA","revenue":100.0},{"region":"APAC","revenue":250.0}]

check("identical", compare(base, base).passed, True)
check("Decimal vs float", compare(
    [{"region":"EMEA","revenue":Decimal("100.00")},{"region":"APAC","revenue":Decimal("250.00")}],
    base).passed, True)
check("row order ignored", compare(list(reversed(base)), base).passed, True)
check("column order ignored", compare(
    [{"revenue":100.0,"region":"EMEA"},{"revenue":250.0,"region":"APAC"}], base).passed, True)
check("currency strings", compare(
    [{"region":"EMEA","revenue":"$100.00"},{"region":"APAC","revenue":"$250.00"}], base).passed, True)
check("extra column projected away", compare(
    [{"region":"EMEA","revenue":100.0,"note":"x"},{"region":"APAC","revenue":250.0,"note":"y"}],
    base).passed, True)
check("rounding within tolerance", compare(
    [{"region":"EMEA","revenue":100.001},{"region":"APAC","revenue":250.004}], base,
    decimals=2).passed, True)
check("NULL == NULL", compare(
    [{"region":"EMEA","revenue":None}], [{"region":"EMEA","revenue":None}]).passed, True)
check("percent vs fraction on rate col", compare(
    [{"region":"EMEA","churn_rate":42.0}], [{"region":"EMEA","churn_rate":0.42}]).passed, True)
check("tz-aware vs naive", compare(
    [{"d": pd.Timestamp("2026-01-01 12:00:00", tz="UTC"), "n":1}],
    [{"d": pd.Timestamp("2026-01-01 12:00:00"), "n":1}]).passed, True)

v = compare([{"region":"EMEA","revenue":100.0},{"region":"APAC","revenue":999.0}], base)
check("wrong value fails", v.passed, False)
check("wrong value has diff", v.diff is not None and "revenue" in v.diff, True)
check("missing column fails", compare([{"region":"EMEA"}], base).passed, False)
check("row count mismatch fails", compare([base[0]], base).passed, False)
check("empty actual fails", compare([], base).passed, False)
check("empty reference flagged", "golden case is broken" in compare(base, []).reason, True)
check("both empty passes", compare([], []).passed, True)
check("ordered=True catches order", compare(list(reversed(base)), base, ordered=True).passed, False)
check("amount col NOT rescaled", compare(
    [{"region":"EMEA","amount":42.0}], [{"region":"EMEA","amount":0.42}]).passed, False)

print()
print(f"{len(fails)} failure(s)" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
