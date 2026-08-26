"""RecoveryActionExecutor — executes scheduled recovery actions.

For RETRY actions, it calls the LazerPay /payments/retry endpoint to re-attempt
the payment.  The customer-response simulator determines whether the customer
explicitly declines a retry (only relevant for link/notification outreach, but
the simulator is consulted for retry too).

After execution, the action's outcome (SUCCESS / FAILED / STOPPED) is persisted.
"""

from __future__ import annotations

import logging
import httpx
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ..config import Settings
from .customer_response import CustomerResponse, CustomerResponseSimulator
from .domain import RecoveryAction, RecoveryActionType, RecoveryOutcome
from .repository import RecoveryActionRepository

logger = logging.getLogger(__name__)


class RecoveryActionExecutor:
    """Executes recovery actions by calling LazerPay.

    Parameters
    ----------
    settings :
        Application settings (contains lazerpay_url, http_timeout).
    recovery_repo :
        Repository for persisting action outcomes.
    customer_response_sim :
        Optional customer-response simulator.  If provided and the action
        involves customer outreach, the simulator models the response.
    """

    def __init__(
        self,
        settings: Settings,
        recovery_repo: RecoveryActionRepository,
        customer_response_sim: Optional[CustomerResponseSimulator] = None,
    ):
        self._settings = settings
        self._recovery_repo = recovery_repo
        self._customer_response_sim = customer_response_sim

    def execute(
        self,
        action: RecoveryAction,
        simulation_timestamp: datetime,
    ) -> RecoveryAction:
        """Execute a scheduled recovery action and persist its outcome.

        Returns the updated RecoveryAction with outcome set.
        """
        if action.action_type == RecoveryActionType.STOP:
            return self._execute_stop(action)

        if action.action_type == RecoveryActionType.RETRY:
            return self._execute_retry(
                action, simulation_timestamp
            )

        # SEND_PAYMENT_LINK and SEND_NOTIFICATION are future paths;
        # for the baseline we only implement RETRY and STOP.
        logger.warning(
            "Unsupported action type %s — skipping execution", action.action_type
        )
        return action

    def _execute_retry(
        self,
        action: RecoveryAction,
        simulation_timestamp: datetime,
    ) -> RecoveryAction:
        """Call LazerPay to retry the failed payment attempt."""
        if action.related_attempt_id is None:
            logger.error(
                "Cannot retry action %s — no related_attempt_id", action.action_id
            )
            return self._mark_failed(
                action, "no_related_attempt_id",
                simulation_timestamp=simulation_timestamp,
            )

        lazerpay_url = self._settings.lazerpay_url

        try:
            response = httpx.post(
                f"{lazerpay_url}/api/payments/retry",
                params={"attempt_id": action.related_attempt_id},
                json={
                    "amount": float(action.amount) if action.amount else None,
                    "payment_method": action.payment_method,
                    "simulation_timestamp": simulation_timestamp.isoformat(),
                },
                timeout=self._settings.http_timeout_seconds,
            )
            data = response.json()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning(
                "LazerPay unreachable for retry of attempt %s: %s",
                action.related_attempt_id,
                exc,
            )
            return self._mark_failed(
                action, "lazerpay_unavailable",
                simulation_timestamp=simulation_timestamp,
            )

        new_attempt_id = data.get("new_attempt_id", "")
        status = data.get("status", "FAILED")
        failure_code = data.get("failure_code")
        failure_reason = data.get("failure_reason")

        executed_at = datetime.now(timezone.utc)

        if status in ("SETTLED", "AUTHORIZED"):
            outcome = RecoveryOutcome.SUCCESS
        elif status in ("FAILED",):
            outcome = RecoveryOutcome.FAILED
        elif status in ("UNKNOWN",):
            outcome = RecoveryOutcome.UNKNOWN
        else:
            outcome = RecoveryOutcome.FAILED

        updated = RecoveryAction(
            action_id=action.action_id,
            run_id=action.run_id,
            related_attempt_id=action.related_attempt_id,
            payment_intent_id=action.payment_intent_id,
            retry_number=action.retry_number,
            action_type=action.action_type,
            reason=action.reason,
            schedule_reason=action.schedule_reason,
            scheduled_for=action.scheduled_for,
            executed_at=executed_at,
            outcome=outcome,
            failure_code=action.failure_code,
            failure_reason=action.failure_reason,
            cost=action.cost,
            expected_recovery=action.expected_recovery,
            amount=action.amount,
            payment_method=action.payment_method,
            retry_attempt_id=new_attempt_id,
            customer_declined=action.customer_declined,
            metadata_json={
                **action.metadata_json,
                "retry_attempt_id": new_attempt_id,
                "lazerpay_status": status,
                "lazerpay_failure_code": failure_code,
                "lazerpay_failure_reason": failure_reason,
                "executed_at": executed_at.isoformat(),
            },
            created_at=action.created_at,
        )

        self._recovery_repo.save(updated)
        logger.info(
            "Executed RETRY #%d for intent %s → %s (attempt %s)",
            action.retry_number or 0,
            action.payment_intent_id,
            outcome.value,
            new_attempt_id,
        )
        return updated

    def _execute_stop(self, action: RecoveryAction) -> RecoveryAction:
        """Mark a STOP action as executed."""
        updated = RecoveryAction(
            action_id=action.action_id,
            run_id=action.run_id,
            related_attempt_id=action.related_attempt_id,
            payment_intent_id=action.payment_intent_id,
            retry_number=action.retry_number,
            action_type=action.action_type,
            reason=action.reason,
            schedule_reason=action.schedule_reason,
            scheduled_for=action.scheduled_for,
            executed_at=datetime.now(timezone.utc),
            outcome=RecoveryOutcome.STOPPED,
            failure_code=action.failure_code,
            failure_reason=action.failure_reason,
            cost=action.cost,
            expected_recovery=action.expected_recovery,
            amount=action.amount,
            payment_method=action.payment_method,
            retry_attempt_id=action.retry_attempt_id,
            customer_declined=action.customer_declined,
            metadata_json={
                **action.metadata_json,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
            created_at=action.created_at,
        )
        self._recovery_repo.save(updated)
        logger.info(
            "STOP executed for intent %s — reason: %s",
            action.payment_intent_id,
            action.reason,
        )
        return updated

    def _mark_failed(
        self,
        action: RecoveryAction,
        reason: str,
        simulation_timestamp: datetime,
    ) -> RecoveryAction:
        """Mark an action as FAILED due to an operational error (not a payment failure)."""
        updated = RecoveryAction(
            action_id=action.action_id,
            run_id=action.run_id,
            related_attempt_id=action.related_attempt_id,
            payment_intent_id=action.payment_intent_id,
            retry_number=action.retry_number,
            action_type=action.action_type,
            reason=action.reason,
            schedule_reason=action.schedule_reason,
            scheduled_for=action.scheduled_for,
            executed_at=datetime.now(timezone.utc),
            outcome=RecoveryOutcome.FAILED,
            failure_code=action.failure_code,
            failure_reason=action.failure_reason,
            cost=action.cost,
            expected_recovery=action.expected_recovery,
            amount=action.amount,
            payment_method=action.payment_method,
            retry_attempt_id=action.retry_attempt_id,
            customer_declined=action.customer_declined,
            metadata_json={
                **action.metadata_json,
                "operational_error": reason,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
            created_at=action.created_at,
        )
        self._recovery_repo.save(updated)
        return updated

    def simulate_customer_response(self, action: RecoveryAction) -> Optional[CustomerResponse]:
        """Optionally consult the customer-response simulator.

        Used for SEND_PAYMENT_LINK / SEND_NOTIFICATION paths in the future.
        Returns None if no simulator is configured.
        """
        if self._customer_response_sim is None:
            return None
        response = self._customer_response_sim.simulate()
        logger.info(
            "Customer response for action %s: %s",
            action.action_id,
            response.value,
        )
        return response
