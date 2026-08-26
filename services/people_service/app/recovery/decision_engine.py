"""BaselineRecoveryEngine — deterministic retry logic.

RULES (from spec Part 3):
  - Max 3 recovery retries per intent.
  - Retries are scheduled 12 simulation hours apart.
  - On explicit customer decline → STOP.
  - If 3 retries already executed → STOP.
  - Otherwise → RETRY.

The engine is a pure function of RecoveryContext — no RNG, no external calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .context import RecoveryContext
from .domain import RecoveryAction, RecoveryActionType, RecoveryDecision, RecoveryDecisionEngine

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_INTERVAL_HOURS = 12


class BaselineRecoveryEngine(RecoveryDecisionEngine):
    """Deliberately simple, deterministic recovery decision engine.

    Decision flow:
      1. If customer already explicitly declined → STOP
      2. If retry_count >= MAX_RETRIES → STOP
      3. Otherwise → RETRY at current_time + RETRY_INTERVAL_HOURS
    """

    def decide(self, context: RecoveryContext) -> RecoveryDecision:
        # Rule 1: customer explicitly declined
        if context.customer_declined:
            logger.info(
                "STOP: customer declined for intent %s", context.intent_id
            )
            return RecoveryDecision(
                action=RecoveryActionType.STOP,
                reason="customer_declined",
            )

        # Rule 2: max retries exhausted
        if context.retry_count >= MAX_RETRIES:
            logger.info(
                "STOP: max retries (%d) exhausted for intent %s",
                MAX_RETRIES,
                context.intent_id,
            )
            return RecoveryDecision(
                action=RecoveryActionType.STOP,
                reason="max_retries_exhausted",
            )

        # Rule 3: schedule next retry
        next_retry_number = context.retry_count + 1
        scheduled_for = context.current_simulation_time + timedelta(
            hours=RETRY_INTERVAL_HOURS
        )

        logger.info(
            "RETRY #%d for intent %s scheduled at %s",
            next_retry_number,
            context.intent_id,
            scheduled_for.isoformat(),
        )
        return RecoveryDecision(
            action=RecoveryActionType.RETRY,
            scheduled_for=scheduled_for,
            reason="retry_scheduled",
            retry_number=next_retry_number,
        )

    @property
    def max_retries(self) -> int:
        return MAX_RETRIES

    @property
    def retry_interval_hours(self) -> int:
        return RETRY_INTERVAL_HOURS
