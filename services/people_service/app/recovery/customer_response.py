"""CustomerResponseSimulator — probabilistic simulation of customer behaviour.

When a recovery action (retry via payment link, notification, etc.) is executed,
the customer may:

  1. Ignore  — no response, payment not recovered
  2. Respond & pay  — payment succeeds
  3. Decline  — explicit decline (only for link/notification paths)

The simulator is seeded from the SimulationRNG so results are reproducible.
It does NOT drive real emails or links — it models the statistical outcome.

Config:
  - ignore_rate: probability the customer ignores the outreach (0.0–1.0)
  - decline_rate: probability the customer explicitly declines (0.0–1.0)
  - respond_and_pay_rate: 1 - ignore_rate - decline_rate (implicit)

The spec says the customer response simulator has probabilistic
ignore/response/decline, with 0.5-1.5% decline rate on recovery actions.
"""

from __future__ import annotations

import logging
from enum import Enum
from ..rng import SimulationRNG

logger = logging.getLogger(__name__)


class CustomerResponse(str, Enum):
    """Possible customer responses to a recovery outreach."""

    IGNORE = "IGNORE"           # No response
    RESPOND_AND_PAY = "RESPOND_AND_PAY"  # Customer pays
    DECLINE = "DECLINE"         # Explicit decline


class CustomerResponseSimulator:
    """Simulates how a customer responds to a recovery action.

    Default rates per the spec:
      - ignore: ~98.5% (1 - respond - decline)
      - respond_and_pay: ~1.0% (varies by outreach type)
      - decline: 0.5–1.5%

    Parameters:
        rng: shared SimulationRNG for reproducibility
        ignore_rate: probability of no response (default 0.985)
        respond_rate: probability of responding and paying (default 0.010)
        decline_rate: probability of explicit decline (default 0.005)
    """

    def __init__(
        self,
        rng: SimulationRNG,
        *,
        ignore_rate: float = 0.985,
        respond_rate: float = 0.010,
        decline_rate: float = 0.005,
    ):
        self._rng = rng
        # Normalise so the three probabilities sum to 1.0
        total = ignore_rate + respond_rate + decline_rate
        if total == 0:
            # Edge case: uniform defaults
            self._ignore_rate = 0.985
            self._respond_rate = 0.010
            self._decline_rate = 0.005
        else:
            scale = 1.0 / total
            self._ignore_rate = ignore_rate * scale
            self._respond_rate = respond_rate * scale
            self._decline_rate = decline_rate * scale

    def simulate(self) -> CustomerResponse:
        """Return a simulated customer response.

        Uses the rng for deterministic, reproducible results.
        """
        roll = self._rng.random()
        if roll < self._ignore_rate:
            return CustomerResponse.IGNORE
        roll -= self._ignore_rate
        if roll < self._respond_rate:
            return CustomerResponse.RESPOND_AND_PAY
        return CustomerResponse.DECLINE

    @property
    def ignore_rate(self) -> float:
        return self._ignore_rate

    @property
    def respond_rate(self) -> float:
        return self._respond_rate

    @property
    def decline_rate(self) -> float:
        return self._decline_rate
