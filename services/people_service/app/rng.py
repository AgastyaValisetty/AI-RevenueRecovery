"""SimulationRNG — deterministic random number generation for the simulation.

All randomness must flow through this abstraction.  Domain classes, generators,
and engines must NOT call ``random.random()`` / ``random.randint()`` directly.

Usage:
    rng = SimulationRNG(seed=42)
    value = rng.randint(18, 80)           # deterministic
    child = rng.spawn("child_label")      # derive independent stream

The class wraps :class:`random.Random` and delegates basic calls while
providing deterministic sub-seed derivation via :meth:`spawn` / :meth:`next_seed`.
"""

from __future__ import annotations

import random as _stdlib_random
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Sequence

_MONEY = Decimal("0.01")


class SimulationRNG:
    """Deterministic RNG wrapper for all simulation randomness.

    A single root seed produces a tree of sub-seeds via :meth:`spawn`, ensuring
    that each component has a reproducible but independent stream of randomness.
    """

    def __init__(self, seed: int | None = None) -> None:
        self._seed = seed
        self._rng = _stdlib_random.Random(seed)

    @property
    def seed(self) -> int | None:
        return self._seed

    def next_seed(self) -> int:
        """Generate a deterministic sub-seed for component-level RNG."""
        return self._rng.randint(0, 2**31 - 1)

    def spawn(self, label: str) -> SimulationRNG:
        """Derive a child RNG from the current internal state.

        Each child gets an independent but reproducible stream.
        """
        child_seed = self._rng.randint(0, 2**63 - 1)
        return SimulationRNG(child_seed)

    # ------------------------------------------------------------------
    # Basic delegation
    # ------------------------------------------------------------------

    def random(self) -> float:
        return self._rng.random()

    def randint(self, lo: int, hi: int) -> int:
        return self._rng.randint(lo, hi)

    def uniform(self, lo: float, hi: float) -> float:
        return self._rng.uniform(lo, hi)

    def normalvariate(self, mu: float, sigma: float) -> float:
        return self._rng.gauss(mu, sigma)

    def lognormvariate(self, mu: float, sigma: float) -> float:
        return self._rng.lognormvariate(mu, sigma)

    def choice(self, seq: Sequence[Any]) -> Any:
        return self._rng.choice(seq)

    def sample(self, seq: Sequence[Any], k: int) -> list[Any]:
        return self._rng.sample(seq, k)

    def choices(self, population: Sequence[Any], weights: Sequence[float] | None = None, k: int = 1) -> list[Any]:
        return self._rng.choices(population, weights=weights, k=k)

    def chance(self, probability: float) -> bool:
        """Return ``True`` with probability ``probability`` (0.0 – 1.0)."""
        if probability <= 0.0:
            return False
        if probability >= 1.0:
            return True
        return self._rng.random() < probability

    def poisson(self, lamb: float) -> int:
        """Draw from a Poisson distribution."""
        if lamb <= 0:
            return 0
        return self._rng.poisson(lamb) if hasattr(self._rng, "poisson") else max(
            0, int(self._rng.gauss(lamb, lamb**0.5))
        )

    def money(self, amount: float) -> Decimal:
        """Quantise a float amount to a 2-decimal ``Decimal``."""
        return Decimal(str(amount)).quantize(_MONEY, rounding=ROUND_HALF_UP)

    def deterministic_now(self) -> datetime:
        """Return a fixed timestamp — useful for tests that need determinism."""
        return datetime(2024, 1, 1, tzinfo=timezone.utc)
