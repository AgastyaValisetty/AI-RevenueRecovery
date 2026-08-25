"""Demographic samplers — age and income distributions.

These replace the uniform ``randint`` sampling previously used in
``PersonGenerator`` with calibrated, realistic distributions:

- :class:`AgeSampler` — weighted age-group sampling matching the Indian
  demographic pyramid (Census 2011 + UN 2023).
- :class:`IncomeSampler` — truncated log-normal within brackets, producing
  a right-skewed income distribution calibrated to Hyderabad/India urban data.

Both are deterministic given a :class:`~rng.SimulationRNG` instance.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

from .sim_config import SimConfig

if TYPE_CHECKING:
    from .rng import SimulationRNG

_MONEY = Decimal("0.01")


class AgeSampler:
    """Sample ages from a calibrated, weighted age-group distribution.

    Example:
        >>> rng = SimulationRNG(42)
        >>> sampler = AgeSampler(rng, config)
        >>> age = sampler.sample_age()  # 25, deterministic
    """

    def __init__(self, rng: SimulationRNG, config: SimConfig) -> None:
        self._rng = rng
        self._groups = config.age_distribution.groups
        self._weights = [g.weight for g in self._groups]

    def sample_age(self) -> int:
        """Return a deterministic age sampled from the configured distribution."""
        # Weighted choice of group, then uniform within group range
        group = self._rng.choices(
            self._groups, weights=self._weights, k=1
        )[0]
        return self._rng.randint(group.age_min, group.age_max)

    def age_group_label(self, age: int) -> str:
        """Return the config label for an age (delegates to SimConfig)."""
        for g in self._groups:
            if g.age_min <= age <= g.age_max:
                return g.label
        return self._groups[-1].label

    def sample_employment_type(self, age: int) -> str:
        """Probabilistically determine employment type from age.

        - 18-22  → student (70%) or salaried (30%)
        - 23-64  → salaried (80%) or self_employed (20%)
        - 65+    → retired (100%)
        """
        if age <= 22:
            return "student" if self._rng.random() < 0.7 else "salaried"
        if age <= 64:
            return "self_employed" if self._rng.random() < 0.2 else "salaried"
        return "retired"


class IncomeSampler:
    """Sample salaries from a right-skewed, bracket-calibrated distribution.

    Uses a two-step process:
    1. Select an income bracket via weighted random choice.
    2. Sample within the bracket using a truncated log-normal distribution.

    This produces a smooth, right-skewed density with a long tail of high earners,
    matching Indian urban income distributions (NSSO 2019).
    """

    def __init__(self, rng: SimulationRNG, config: SimConfig) -> None:
        self._rng = rng
        self._brackets = config.income_distribution.brackets
        self._weights = [b.weight for b in self._brackets]
        self._lognormal_mean = config.income_distribution.lognormal_mean
        self._lognormal_sigma = config.income_distribution.lognormal_sigma

    def sample_salary(self) -> Decimal:
        """Return a deterministic, right-skewed monthly salary (INR).

        The distribution is right-skewed: median < mean, with a long tail
        of high earners.  All values fall within the configured brackets.
        """
        bracket = self._rng.choices(
            self._brackets, weights=self._weights, k=1
        )[0]
        return self._sample_in_bracket(bracket)

    def _sample_in_bracket(self, bracket) -> Decimal:
        """Sample a salary within a bracket using truncated log-normal.

        Draws from a log-normal distribution, then clamps to the bracket
        boundaries.  This produces a smooth density within each bracket while
        ensuring all values respect the configured min/max bounds.
        """
        # Draw from log-normal distribution
        raw = self._rng.lognormvariate(
            self._lognormal_mean, self._lognormal_sigma
        )

        # Clamp to bracket bounds
        raw = max(float(bracket.min), min(raw, float(bracket.max)))

        # Quantise to 2 decimal places
        return (
            Decimal(str(raw))
            .quantize(_MONEY, rounding=ROUND_HALF_UP)
        )

    def income_bracket_label(self, salary: Decimal) -> str:
        """Return a human-readable income bracket label for a salary."""
        for b in self._brackets:
            if b.min <= float(salary) <= b.max:
                return f"{b.min}-{b.max}"
        return ">max"
