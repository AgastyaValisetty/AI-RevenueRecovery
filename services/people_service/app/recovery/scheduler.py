"""RecoveryScheduler — creates persisted RecoveryAction records from decisions.

The scheduler is the bridge between the decision engine (BaselineRecoveryEngine)
and the executor.  It does NOT call LazerPay — it just records what to do and
when.  The orchestrator polls for due actions and hands them to the executor.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from .context import RecoveryContext
from .domain import RecoveryAction, RecoveryActionType, RecoveryDecision, RecoveryOutcome
from .repository import RecoveryActionRepository

logger = logging.getLogger(__name__)


class RecoveryScheduler:
    """Creates and persists RecoveryAction records from RecoveryDecisions."""

    def __init__(self, recovery_repo: RecoveryActionRepository):
        self._recovery_repo = recovery_repo

    def schedule(
        self,
        decision: RecoveryDecision,
        context: RecoveryContext,
        run_id: UUID | None = None,
    ) -> RecoveryAction:
        """Create a RecoveryActionRow based on a RecoveryDecision.

        Parameters
        ----------
        decision :
            The decision from the engine (RETRY or STOP).
        context :
            The full observable context used to make the decision.
        run_id :
            Optional simulation run ID for traceability.

        Returns
        -------
        RecoveryAction
            The newly created action record (already persisted with outcome=PENDING).
        """
        now_ts = datetime.now(context.current_simulation_time.tzinfo)

        if decision.action == RecoveryActionType.STOP:
            action = RecoveryAction(
                action_id=uuid4(),
                run_id=run_id,
                related_attempt_id=context.attempt.attempt_id if context.attempt else None,
                payment_intent_id=UUID(context.intent_id) if context.intent_id else None,
                retry_number=decision.retry_number,
                action_type=RecoveryActionType.STOP,
                reason=decision.reason or "stop",
                schedule_reason=None,
                scheduled_for=context.current_simulation_time,
                executed_at=None,
                outcome=RecoveryOutcome.PENDING,
                failure_code=context.failure_code,
                failure_reason=context.failure_reason,
                amount=context.intent_amount,
                payment_method=context.intent_payment_method,
                customer_declined=(decision.reason == "customer_declined"),
                metadata_json={
                    "intent_id": context.intent_id,
                    "person_id": context.person.person_id,
                    "primary_account_id": context.person.primary_account_id,
                    "merchant_id": context.merchant.merchant_id,
                    "failure_timestamp": (
                        context.failure_timestamp.isoformat()
                        if context.failure_timestamp
                        else None
                    ),
                    "bank_state": context.bank_state,
                    # Persist ENPV at decision time so the SARA tab can render
                    # it without depending on the optional XGBoost model
                    # (which may not be present in the container image).
                    "expected_net_value": (
                        str(decision.expected_net_value)
                        if decision.expected_net_value is not None
                        else None
                    ),
                },
                created_at=now_ts,
            )
        else:
            # RETRY / outreach actions share the same persisted action shape.
            action_type = decision.action
            retry_number = decision.retry_number if action_type == RecoveryActionType.RETRY else None
            action = RecoveryAction(
                action_id=uuid4(),
                run_id=run_id,
                related_attempt_id=context.attempt.attempt_id if context.attempt else None,
                payment_intent_id=UUID(context.intent_id) if context.intent_id else None,
                retry_number=retry_number,
                action_type=action_type,
                reason=decision.reason or action_type.value.lower(),
                schedule_reason=decision.reason,
                scheduled_for=decision.scheduled_for or context.current_simulation_time,
                executed_at=None,
                outcome=RecoveryOutcome.PENDING,
                failure_code=context.failure_code,
                failure_reason=context.failure_reason,
                amount=context.intent_amount,
                payment_method=context.intent_payment_method,
                retry_attempt_id=None,  # set after execution
                customer_declined=False,
                metadata_json={
                    "intent_id": context.intent_id,
                    "person_id": context.person.person_id,
                    "primary_account_id": context.person.primary_account_id,
                    "merchant_id": context.merchant.merchant_id,
                    "failure_timestamp": (
                        context.failure_timestamp.isoformat()
                        if context.failure_timestamp
                        else None
                    ),
                    "bank_state": context.bank_state,
                    "retry_number": retry_number,
                    # Persist ENPV at decision time so the SARA tab can render
                    # it without depending on the optional XGBoost model
                    # (which may not be present in the container image).
                    "expected_net_value": (
                        str(decision.expected_net_value)
                        if decision.expected_net_value is not None
                        else None
                    ),
                },
                created_at=now_ts,
            )

        self._recovery_repo.add(action)
        logger.info(
            "Scheduled %s for intent %s at %s",
            action.action_type.value,
            context.intent_id,
            action.scheduled_for,
        )
        return action

    def find_due_actions(
        self, current_time: datetime
    ) -> list[RecoveryAction]:
        """Return RETRY actions whose scheduled_for <= current_time and not yet executed."""
        return self._recovery_repo.find_scheduled_for_execution(current_time)
