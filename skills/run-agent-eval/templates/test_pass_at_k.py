import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pass_at_k import wilson_interval, pass_at_k_unbiased, score_suite, Outcome

fails = []
def check(name, got, want, tol=None):
    ok = (abs(got-want) < tol) if tol is not None else (got == want)
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   got={got} want={want}"))
    if not ok: fails.append(name)

# Wilson: known reference values
lo, hi = wilson_interval(1, 1)
check("wilson 1/1 lo", lo, 0.2065, 1e-3); check("wilson 1/1 hi", hi, 1.0, 1e-6)
lo, hi = wilson_interval(50, 100)
check("wilson 50/100 lo", lo, 0.4038, 1e-3); check("wilson 50/100 hi", hi, 0.5962, 1e-3)
lo, hi = wilson_interval(0, 10)
check("wilson 0/10 lo", lo, 0.0, 1e-9); check("wilson 0/10 hi", hi, 0.2775, 1e-3)
check("wilson n=0 wide", wilson_interval(0,0), (0.0,1.0))

# unbiased pass@k
check("pass@1 == c/n", pass_at_k_unbiased(10, 5, 1), 0.5, 1e-9)
check("pass@1 all wrong", pass_at_k_unbiased(10, 0, 1), 0.0, 1e-9)
check("pass@3 saturated", pass_at_k_unbiased(5, 5, 3), 1.0, 1e-9)
check("pass@2 of 10,c=1", pass_at_k_unbiased(10, 1, 2), 0.2, 1e-9)
try:
    pass_at_k_unbiased(3, 1, 5); check("k>n raises", False, True)
except ValueError:
    check("k>n raises", True, True)

# suite scoring
C, I, A, CL = Outcome.CORRECT, Outcome.INCORRECT, Outcome.ABSTAINED, Outcome.CLARIFICATION
runs = []
for cid, outs in {
    "a": [C, C, C],      # solid
    "b": [C, I, C],      # flaky
    "c": [I, I, I],      # wrong
    "d": [A, A, A],      # abstains
    "e": [C, C, C],
}.items():
    runs += [(cid, o) for o in outs]

r = score_suite(runs, model="test-model", cost_usd=1.50)
check("k detected", r.k, 3)
check("n_cases", r.n_cases, 5)
check("pass^3 count", r.pass_all_count, 2)          # a, e
check("pass@3 count", r.pass_any_count, 3)          # a, b, e
check("flaky count", len(r.flaky_cases), 1)         # b
check("total runs", r.total_runs, 15)
# correct=3+2+2=7? a:3, b:2, e:3 => 8 correct; incorrect: b:1, c:3 => 4; abstained 3
check("accuracy", r.accuracy, 8/12, 1e-9)
check("coverage", r.coverage, 12/15, 1e-9)
check("usefulness", r.usefulness, 8/15, 1e-9)
check("cost per correct", r.cost_per_correct, 1.50/8, 1e-9)
out = r.render()
check("render has headline", "pass^3" in out, True)
check("render warns small n", "WARNING" in out, True)
print(); print(out)
print()
print(f"{len(fails)} failure(s)" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
