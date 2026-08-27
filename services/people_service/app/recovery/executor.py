"""RecoveryActionExecutor — executes scheduled recovery actions.

For RETRY actions, it calls the LazerPay /payments/retry endpoint to re-attempt
the payment.  When the original failure was an inline-settled intent (no
LazerPay attempt_id), the executor falls back to inline settlement: it re-checks
the person's balance and settles or fails the payment directly.

The customer-response simulator determines whether the customer
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
from uuid import UUID, uuid4

from ..config import Settings
from ..domain import PaymentIntent, LedgerEntry, INTENT_SETTLED, INTENT_FAILED, now
from ..domain import PAYMENT_SETTLED, PAYMENT_FAILED
from ..failure_model import classify_failure, failure_probability, FAILURE_REASONS, FAILURE_CATEGORIES
# Note: PaymentIntentRepository and LedgerRepository protocols are not imported
# here to avoid a circular import (ports.py imports recovery.domain which
# triggers recovery/__init__.py → executor.py).  We rely on duck typing instead.
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
    intent_repo :
        Optional PaymentIntent repository, used for inline settlement fallback
        when there is no LazerPay attempt_id to retry.
    ledger_repo :
        Optional LedgerRepository, used for inline settlement fallback to
        debit/credit balances and record ledger entries.
    rng :
        Optional SimulationRNG for inline settlement failure probability.
    """

    def __init__(
        self,
        settings: Settings,
        recovery_repo: RecoveryActionRepository,
        customer_response_sim: Optional[CustomerResponseSimulator] = None,
        intent_repo: Optional[PaymentIntentRepository] = None,
        ledger_repo: Optional[LedgerRepository] = None,
        subscription_repo=None,
        rng=None,
    ):
        self._settings = settings
        self._recovery_repo = recovery_repo
        self._customer_response_sim = customer_response_sim
        self._intent_repo = intent_repo
        self._ledger_repo = ledger_repo
        self._subscription_repo = subscription_repo
        self._rng = rng

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
        """Retry a failed payment.

        If ``related_attempt_id`` is present (LazerPay origin), call the
        LazerPay /payments/retry endpoint.  Otherwise, fall back to inline
        settlement: check the person's balance and settle or fail directly.
        """
        if action.related_attempt_id is not None:
            return self._execute_lazerpay_retry(
                action, simulation_timestamp
            )
        # Inline fallback — attempt to settle the failed payment intent inline.
        return self._execute_inline_retry(
            action, simulation_timestamp
        )

    def _execute_lazerpay_retry(
        self,
        action: RecoveryAction,
        simulation_timestamp: datetime,
    ) -> RecoveryAction:
        """Call LazerPay to retry the failed payment attempt."""
        lazerpay_url = self._settings.lazerpay_url

        try:
            response = httpx.post(
                f"{lazerpay_url}/api/payments/retry",
                json={
                    "attempt_id": action.related_attempt_id,
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
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "LazerPay returned error status for retry of attempt %s: %s",
                action.related_attempt_id,
                exc,
            )
            return self._mark_failed(
                action, "lazerpay_error",
                simulation_timestamp=simulation_timestamp,
            )

        new_attempt_id = data.get("new_attempt_id", "")
        status = data.get("status", "FAILED")
        failure_code = data.get("failure_code")
        failure_reason = data.get("failure_reason")

        executed_at = datetime.now(timezone.utc)

        if status in ("SETTLED", "AUTHORIZED"):
            outcome = RecoveryOutcome.SUCCESS
            # Update the payment intent status to reflect the successful recovery
            if self._intent_repo is not None and action.payment_intent_id is not None:
                try:
                    intent = self._intent_repo.find_by_id(action.payment_intent_id)
                    if intent is not None:
                        from dataclasses import replace
                        updated_intent = replace(intent, status=status)
                        self._intent_repo.save(updated_intent)
                except Exception as exc:
                    logger.warning(
                        "Failed to update payment intent %s after successful recovery: %s",
                        action.payment_intent_id,
                        exc,
                    )
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

    def _execute_inline_retry(
        self,
        action: RecoveryAction,
        simulation_timestamp: datetime,
    ) -> RecoveryAction:
        """Inline settlement fallback for failed payment intents that have no
        LazerPay ``attempt_id`` (i.e. they were settled inline by the
        orchestrator and failed).

        This mirrors the orchestrator's ``_settle_payment_intents`` logic:
        check the person's balance, roll against the failure probability,
        and record the outcome as a new ledger entry + intent status update.
        """
        if self._intent_repo is None or self._ledger_repo is None:
            logger.error(
                "Cannot inline-retry action %s — no intent_repo/ledger_repo "
                "configured on executor",
                action.action_id,
            )
            return self._mark_failed(
                action, "no_inline_repos",
                simulation_timestamp=simulation_timestamp,
            )

        intent_id = action.payment_intent_id
        if intent_id is None:
            logger.error(
                "Cannot inline-retry action %s — no payment_intent_id",
                action.action_id,
            )
            return self._mark_failed(
                action, "no_payment_intent_id",
                simulation_timestamp=simulation_timestamp,
            )

        intent = self._intent_repo.find_by_id(intent_id)
        if intent is None:
            logger.error(
                "Cannot inline-retry — payment intent %s not found", intent_id
            )
            return self._mark_failed(
                action, "intent_not_found",
                simulation_timestamp=simulation_timestamp,
            )

        orig_code = action.failure_code or "UNKNOWN"
        logger.debug(
            "_execute_inline_retry: intent=%s retry_num=%s orig_code=%s "
            "intent_status=%s method=%s amount=%s",
            intent_id, action.retry_number, orig_code,
            intent.status, intent.payment_method, intent.amount,
        )

        # Re-check the person's balance.
        source_account_id = (
            action.metadata_json.get("primary_account_id")
            or action.metadata_json.get("source_account_id")
            or action.metadata_json.get("person_id")
            or str(intent.person_id)
        )
        balance = self._ledger_repo.balance_of(source_account_id)

        # Determine failure probability.  If we have an RNG, use it;
        # otherwise treat as a deterministic retry (no random failure).
        failure_code = None
        failure_reason = None
        status = INTENT_SETTLED

        # For INSUFFICIENT_FUNDS failures, the customer's balance was genuinely
        # too low.  Re-checking the balance is a hard fail.
        # For transient failures (ISSUER_DECLINE, NETWORK_ERROR, TIMEOUT, etc.)
        # the balance WAS sufficient when the original payment was attempted —
        # the failure was a transient bank/network issue, not insolvency.
        # On retry, we skip the balance check and just roll with reduced probability.
        is_insufficient_funds = orig_code == "INSUFFICIENT_FUNDS"

        # Classify the original failure to decide how recovery should behave.
        # Infrastructure failures (NETWORK_ERROR, TIMEOUT) are transient by
        # nature — retrying gives a high probability of success.
        # Bank decines (ISSUER_DECLINE, LIMIT_EXCEEDED, RISK_DECLINE) are also
        # often temporary and recover with moderate probability.
        orig_category = FAILURE_CATEGORIES.get(orig_code, "UNKNOWN")

        if is_insufficient_funds and balance < intent.amount:
            # Genuine insolvency — can't recover unless balance increased.
            status = INTENT_FAILED
            failure_code = "INSUFFICIENT_FUNDS"
            failure_reason = "Customer balance insufficient at retry time"
        elif self._rng is not None:
            # On retry, transient failures have a higher chance of success.
            bank_state = "NORMAL"

            amount_f = float(intent.amount)
            balance_f = float(balance)

            retry_num = action.retry_number or 1

            # Base failure probability from the calibrated model.
            base_p = failure_probability(
                intent.payment_method,
                bank_state=bank_state,
                amount=amount_f,
                balance=balance_f,
                hour=simulation_timestamp.hour,
            )

            # Adjust failure probability based on failure type:
            # - Infrastructure failures (NETWORK_ERROR, TIMEOUT): transient,
            #   reduce failure probability heavily (80% recovery on retry).
            # - Bank declinations (ISSUER_DECLINE, LIMIT_EXCEEDED, RISK_DECLINE):
            #   moderate recovery (40% on retry 1, better on later retries).
            # - Other failures: standard halving per retry.
            if orig_category == "INFRASTRUCTURE":
                # Transient infrastructure issues resolve on retry.
                # Success probability starts at ~85% and grows with each retry.
                retry_success_p = min(0.95, 0.85 + (0.05 * (retry_num - 1)))
                retry_p = 1.0 - retry_success_p  # failure probability on retry
            elif orig_category == "BANK_DECLINE":
                # Bank-side declines can be retried with improving odds.
                retry_adjustment = 0.4 * (0.6 ** (retry_num - 1))
                retry_p = base_p * retry_adjustment
            else:
                # Standard retry adjustment: halve failure probability each retry.
                retry_adjustment = 0.5 ** (retry_num - 1) if retry_num > 0 else 1.0
                retry_p = base_p * retry_adjustment

            rng_val = self._rng.random()

            logger.debug(
                "Inline retry: intent=%s retry=%d balance=%.2f amount=%.2f "
                "orig_code=%s base_p=%.4f retry_p=%.4f rng_val=%.4f method=%s",
                intent.intent_id, retry_num, balance_f, amount_f,
                orig_code, base_p, retry_p, rng_val, intent.payment_method,
            )

            if rng_val < retry_p:
                status = INTENT_FAILED
                # If the original was a transient error, keep it transient —
                # if it was a bank decline, pick a new decline code.
                if orig_category == "INFRASTRUCTURE":
                    failure_code = orig_code
                    failure_reason = FAILURE_REASONS.get(orig_code, "Transient error recurred")
                else:
                    failure_code, _cat = classify_failure(
                        self._rng, method=intent.payment_method, bank_state=bank_state
                    )
                    failure_reason = FAILURE_REASONS[failure_code]

        executed_at = datetime.now(timezone.utc)
        new_attempt_id = str(uuid4())

        # Persist the outcome.
        from dataclasses import replace
        updated_intent = replace(intent, status=status)
        self._intent_repo.save(updated_intent)

        # Record a ledger entry for the retry.
        event_type = PAYMENT_SETTLED if status == INTENT_SETTLED else PAYMENT_FAILED
        meta: dict = {
            "payment_method": intent.payment_method,
            "amount": str(intent.amount),
            "person_id": str(intent.person_id),
            "merchant_id": str(intent.merchant_id),
            "retry_attempt_id": new_attempt_id,
            "retry_number": action.retry_number,
        }
        if status == INTENT_FAILED:
            meta["failure_code"] = failure_code
            meta["failure_reason"] = failure_reason

        # NOTE: related_attempt_id must be None here — the payment_attempts
        # table has a FK and we don't create a row there for inline retries.
        # The retry_attempt_id is tracked only in metadata for audit purposes.
        ledger_entry = LedgerEntry(
            entry_id=uuid4(),
            event_type=event_type,
            from_account_id=source_account_id if status == INTENT_SETTLED else None,
            to_account_id=None,
            amount=intent.amount,
            simulation_timestamp=simulation_timestamp,
            related_attempt_id=None,
            related_subscription_id=intent.related_subscription_id,
            metadata_json=meta,
        )
        self._ledger_repo.append([ledger_entry])

        outcome = RecoveryOutcome.SUCCESS if status == INTENT_SETTLED else RecoveryOutcome.FAILED

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
            failure_code=failure_code or action.failure_code,
            failure_reason=failure_reason or action.failure_reason,
            cost=action.cost,
            expected_recovery=action.expected_recovery,
            amount=action.amount,
            payment_method=action.payment_method,
            retry_attempt_id=new_attempt_id,
            customer_declined=action.customer_declined,
            metadata_json={
                **action.metadata_json,
                "retry_attempt_id": new_attempt_id,
                "inline_retry": True,
                "outcome": status,
                "executed_at": executed_at.isoformat(),
            },
            created_at=action.created_at,
        )

        self._recovery_repo.save(updated)
        logger.info(
            "Inline RETRY #%d for intent %s → %s (attempt %s)",
            action.retry_number or 0,
            intent_id,
            outcome.value,
            new_attempt_id,
        )
        return updated

    def _execute_stop(self, action: RecoveryAction) -> RecoveryAction:
        """Mark a STOP action as executed and cancel associated subscription if applicable."""
        # Cancel subscription if this intent has a related_subscription_id and we have exhausted retries
        if action.payment_intent_id is not None and self._intent_repo is not None and self._subscription_repo is not None:
            try:
                intent = self._intent_repo.find_by_id(action.payment_intent_id)
                if intent is not None and intent.related_subscription_id is not None:
                    sub = self._subscription_repo.find(intent.related_subscription_id)
                    if sub is not None and sub.status == "ACTIVE":
                        from dataclasses import replace
                        # Cancel the subscription
                        updated_sub = replace(
                            sub,
                            status="CANCELLED",
                            cancelled_at=now(),
                        )
                        self._subscription_repo.save(updated_sub)
                        logger.info(
                            "CANCELLED subscription %s for intent %s after recovery stop",
                            intent.related_subscription_id,
                            action.payment_intent_id,
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to cancel subscription for intent %s during stop: %s",
                    action.payment_intent_id,
                    exc,
                )

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
