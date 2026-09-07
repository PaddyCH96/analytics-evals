"""Scoring for analytics-agent evaluation.

pass@k, pass^k, Wilson score intervals, and the coverage/accuracy split.
Standard library only - no dependencies.

    from pass_at_k import score_suite, Outcome

    report = score_suite(runs)   # runs: list[(case_id, Outcome)]
    print(report.render())
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "Outcome",
    "CaseScore",
    "SuiteReport",
    "wilson_interval",
    "pass_at_k_unbiased",
    "score_suite",
]


class Outcome(str, Enum):
    """One run of one case."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    ABSTAINED = "abstained"       # explicitly declined to answer
    CLARIFICATION = "clarification"  # asked a question instead of answering
    ERROR = "error"               # crash, timeout, budget stop

    @property
    def answered(self) -> bool:
        return self in (Outcome.CORRECT, Outcome.INCORRECT)


# --------------------------------------------------------------------------
# intervals
# --------------------------------------------------------------------------

# two-sided normal quantiles for common confidence levels
_Z = {0.80: 1.281552, 0.90: 1.644854, 0.95: 1.959964, 0.99: 2.575829}


def wilson_interval(
    successes: int, n: int, confidence: float = 0.95
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation, which misbehaves badly at small n
    and at proportions near 0 or 1 - exactly where evaluation operates.
    """
    if n <= 0:
        return (0.0, 1.0)
    z = _Z.get(round(confidence, 2), 1.959964)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def pass_at_k_unbiased(n: int, c: int, k: int) -> float:
    """Unbiased pass@k when n samples were drawn and c of them were correct.

    From Chen et al., "Evaluating Large Language Models Trained on Code" (2021).
    Use when n > k. When n == k the naive "any correct" is already exact.
    """
    if k > n:
        raise ValueError("k cannot exceed n")
    if n - c < k:
        return 1.0
    # prod_{i=n-c+1}^{n} (1 - k/i)
    result = 1.0
    for i in range(n - c + 1, n + 1):
        result *= 1.0 - k / i
    return 1.0 - result


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

@dataclass
class CaseScore:
    case_id: str
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def k(self) -> int:
        return len(self.outcomes)

    @property
    def n_correct(self) -> int:
        return sum(1 for o in self.outcomes if o is Outcome.CORRECT)

    @property
    def pass_any(self) -> bool:
        """pass@k - correct at least once."""
        return self.n_correct > 0

    @property
    def pass_all(self) -> bool:
        """pass^k - correct every time. The deployment-relevant metric."""
        return self.k > 0 and self.n_correct == self.k

    @property
    def flaky(self) -> bool:
        return self.pass_any and not self.pass_all


@dataclass
class SuiteReport:
    cases: list[CaseScore]
    k: int
    confidence: float = 0.95
    model: str | None = None
    cost_usd: float = 0.0
    wall_seconds: float = 0.0

    # ---- headline -------------------------------------------------------
    @property
    def n_cases(self) -> int:
        return len(self.cases)

    @property
    def pass_all_count(self) -> int:
        return sum(1 for c in self.cases if c.pass_all)

    @property
    def pass_any_count(self) -> int:
        return sum(1 for c in self.cases if c.pass_any)

    @property
    def pass_all_rate(self) -> float:
        return self.pass_all_count / self.n_cases if self.n_cases else 0.0

    @property
    def pass_any_rate(self) -> float:
        return self.pass_any_count / self.n_cases if self.n_cases else 0.0

    @property
    def pass_all_ci(self) -> tuple[float, float]:
        return wilson_interval(self.pass_all_count, self.n_cases, self.confidence)

    @property
    def flaky_cases(self) -> list[CaseScore]:
        return [c for c in self.cases if c.flaky]

    # ---- coverage split -------------------------------------------------
    @property
    def _counts(self) -> dict[Outcome, int]:
        counts: dict[Outcome, int] = defaultdict(int)
        for case in self.cases:
            for outcome in case.outcomes:
                counts[outcome] += 1
        return counts

    @property
    def total_runs(self) -> int:
        return sum(c.k for c in self.cases)

    @property
    def accuracy(self) -> float:
        """Quality when the agent answers."""
        counts = self._counts
        answered = counts[Outcome.CORRECT] + counts[Outcome.INCORRECT]
        return counts[Outcome.CORRECT] / answered if answered else 0.0

    @property
    def coverage(self) -> float:
        """Willingness to answer at all."""
        counts = self._counts
        answered = counts[Outcome.CORRECT] + counts[Outcome.INCORRECT]
        return answered / self.total_runs if self.total_runs else 0.0

    @property
    def usefulness(self) -> float:
        """What the business actually feels: correct out of everything asked."""
        counts = self._counts
        return counts[Outcome.CORRECT] / self.total_runs if self.total_runs else 0.0

    @property
    def cost_per_correct(self) -> float | None:
        correct = self._counts[Outcome.CORRECT]
        return self.cost_usd / correct if correct else None

    # ---- output ---------------------------------------------------------
    def render(self) -> str:
        lo, hi = self.pass_all_ci
        counts = self._counts
        lines = [
            f"suite: {self.n_cases} cases x k={self.k}"
            + (f"  model: {self.model}" if self.model else ""),
            "",
            f"  pass^{self.k}  {self.pass_all_rate:6.1%}   "
            f"[{lo:.1%}, {hi:.1%}]   <- headline",
            f"  pass@{self.k}  {self.pass_any_rate:6.1%}",
            f"  flaky    {len(self.flaky_cases):6d}   "
            "(passed sometimes - reliability problem, not a knowledge problem)",
            "",
            f"  accuracy    {self.accuracy:6.1%}   quality when it answers",
            f"  coverage    {self.coverage:6.1%}   willingness to answer",
            f"  usefulness  {self.usefulness:6.1%}   correct / everything asked",
            "",
            "  outcomes: "
            + "  ".join(
                f"{o.value}={counts[o]}" for o in Outcome if counts[o]
            ),
        ]
        if self.cost_usd:
            cpc = self.cost_per_correct
            lines += [
                "",
                f"  cost  ${self.cost_usd:.2f}"
                + (f"   ${cpc:.4f}/correct" if cpc is not None else "")
                + (f"   {self.wall_seconds:.0f}s" if self.wall_seconds else ""),
            ]
        if self.n_cases < 30:
            lines += [
                "",
                f"  WARNING: {self.n_cases} cases is below the ~30 needed for a "
                "usable interval. Treat this as directional only.",
            ]
        return "\n".join(lines)


def score_suite(
    runs: list[tuple[str, Outcome]],
    *,
    confidence: float = 0.95,
    model: str | None = None,
    cost_usd: float = 0.0,
    wall_seconds: float = 0.0,
) -> SuiteReport:
    """Score a flat list of (case_id, outcome) runs."""
    grouped: dict[str, CaseScore] = {}
    for case_id, outcome in runs:
        grouped.setdefault(case_id, CaseScore(case_id)).outcomes.append(outcome)
    cases = list(grouped.values())
    k = max((c.k for c in cases), default=0)
    return SuiteReport(
        cases=cases,
        k=k,
        confidence=confidence,
        model=model,
        cost_usd=cost_usd,
        wall_seconds=wall_seconds,
    )
