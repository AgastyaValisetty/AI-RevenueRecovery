"""ScenarioLibrary — seeded scenario presets for reproducible demo runs.

The 10 testing scenarios from 1.md section 15, encoded as factory functions
that build a RecoveryContext + features for each scenario.  These are used by
the experiment runner and integration tests to verify specific behaviors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from ..context import RecoveryContext, AttemptInfo, PersonInfo, MerchantInfo, BalanceInfo, PriorRecovery
from .diagnosis import Diagnosis
from .feature_store import CaseFeatures, CustomerBehaviorProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioSpec:
    """Specification of a test scenario.

    Parameters
    ----------
    name :
        Short identifier.
    description :
        What this scenario tests.
    failure_code :
        The root failure code that triggered this scenario.
    bank_state :
        The bank state at failure time.
    retry_count :
        Number of prior retries (for testing retry exhaustion).
    customer_declined :
        Whether the customer explicitly declined a previous action.
    balance :
        Customer's current balance at decision time.
    amount :
        The payment amount.
    hours_since_failure :
        Hours elapsed since the original failure.
    expected_outcome :
        Expected recovery behavior (for assertions).
    """

    name: str
    description: str
    failure_code: str
    bank_state: str
    retry_count: int = 0
    customer_declined: bool = False
    balance: Decimal = Decimal("5000")
    amount: Decimal = Decimal("1000")
    hours_since_failure: int = 0
    expected_outcome: str = "retry"

    # Optional overrides for richer scenarios
    payment_method: str = "UPI"
    subscription: bool = False
    is_merchant_config: bool = False
    promise_active: bool = False
    consent_denied: bool = False


# The 10 canonical testing scenarios from 1.md section 15.
SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="bank_degradation",
        description="Bank temporarily degraded — recovery should wait, not retry blindly",
        failure_code="BANK_DEGRADED",
        bank_state="DEGRADED",
        expected_outcome="wait_then_retry",
    ),
    ScenarioSpec(
        name="insufficient_balance",
        description="Customer insufficient funds — should suggest link, not instant retry",
        failure_code="INSUFFICIENT_FUNDS",
        bank_state="NORMAL",
        balance=Decimal("300"),
        amount=Decimal("1000"),
        expected_outcome="link_or_wait",
    ),
    ScenarioSpec(
        name="method_expired",
        description="Payment method expired — should suggest method switch via link",
        failure_code="EXPIRED_PAYMENT_METHOD",
        bank_state="NORMAL",
        payment_method="CARD",
        expected_outcome="link",
    ),
    ScenarioSpec(
        name="customer_declined",
        description="Customer explicitly declined — should STOP immediately",
        failure_code="CANCELLED",
        bank_state="NORMAL",
        customer_declined=True,
        expected_outcome="stop",
    ),
    ScenarioSpec(
        name="retry_exhaustion",
        description="All retries exhausted — should STOP gracefully",
        failure_code="ISSUER_DECLINE",
        bank_state="NORMAL",
        retry_count=3,
        expected_outcome="stop",
    ),
    ScenarioSpec(
        name="promised_to_pay",
        description="Customer has an active promise-to-pay — should wait, not chase",
        failure_code="ISSUER_DECLINE",
        bank_state="NORMAL",
        promise_active=True,
        expected_outcome="wait",
    ),
    ScenarioSpec(
        name="subscription_churn",
        description="Subscription payment failing consecutively — higher urgency",
        failure_code="ISSUER_DECLINE",
        bank_state="PEAK",
        subscription=True,
        hours_since_failure=48,
        expected_outcome="retry",
    ),
    ScenarioSpec(
        name="large_amount_high_risk",
        description="Large amount transaction with bank risk decline — fraud risk penalty",
        failure_code="RISK_DECLINE",
        bank_state="NORMAL",
        amount=Decimal("15000"),
        expected_outcome="link_or_stop",
    ),
    ScenarioSpec(
        name="infrastructure_timeout",
        description="Infrastructure timeout — transient, should retry quickly",
        failure_code="TIMEOUT",
        bank_state="NORMAL",
        hours_since_failure=1,
        expected_outcome="retry_quick",
    ),
    ScenarioSpec(
        name="consent_denied",
        description="Customer has denied contact consent — should STOP or use non-contact method",
        failure_code="ISSUER_DECLINE",
        bank_state="NORMAL",
        consent_denied=True,
        expected_outcome="stop_or_no_contact",
    ),
]


class ScenarioLibrary:
    """Factory for building RecoveryContext instances for test scenarios.

    Provides deterministic, reproducible contexts for the 10 canonical scenarios.
    """

    @staticmethod
    def get(name: str) -> Optional[ScenarioSpec]:
        """Get a scenario spec by name."""
        for s in SCENARIOS:
            if s.name == name:
                return s
        return None

    @staticmethod
    def get_all() -> list[ScenarioSpec]:
        """Return all scenario specs."""
        return list(SCENARIOS)

    @staticmethod
    def build_context(
        spec: ScenarioSpec,
        *,
        case_id: Optional[UUID] = None,
        person_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        current_time: Optional[datetime] = None,
    ) -> RecoveryContext:
        """Build a RecoveryContext for the given scenario spec.

        This creates a fully deterministic context with no DB dependencies —
        suitable for unit testing the smart agent components.
        """
        if case_id is None:
            case_id = uuid4()
        if person_id is None:
            person_id = uuid4()
        if current_time is None:
            current_time = datetime.now()

        person = PersonInfo(
            person_id=str(person_id),
            name="Test Customer",
            age=30,
            salary=Decimal("50000"),
            salary_deposit_day=1,
            salary_deposit_hour=9,
            spending_profile_category="moderate",
            income_bracket="middle",
            age_group="30-39",
            employment_type="salaried",
            primary_account_id=str(uuid4()),
        )

        merchant = MerchantInfo(
            merchant_id=str(uuid4()),
            name="TestMerchant",
            merchant_type="ecommerce",
        )

        balance = BalanceInfo(
            account_id=person.primary_account_id,
            current_balance=spec.balance,
        )

        failure_ts = current_time - timedelta(hours=spec.hours_since_failure)

        attempt = AttemptInfo(
            attempt_id=str(uuid4()),
            intent_id=str(case_id),
            attempt_number=spec.retry_count + 1,
            person_id=person.person_id,
            merchant_id=merchant.merchant_id,
            amount=spec.amount,
            payment_method=spec.payment_method,
            status="FAILED",
            failure_code=spec.failure_code,
            failure_reason=f"Simulated failure: {spec.failure_code}",
            source_account_id=person.primary_account_id,
            simulation_timestamp=failure_ts,
            bank_state=spec.bank_state,
            bank_response_time_ms=200,
            gateway_latency_ms=50,
            failed_at=failure_ts,
        )

        # Build prior recoveries for retry scenarios
        prior: list[PriorRecovery] = []
        for i in range(spec.retry_count):
            prior.append(PriorRecovery(
                retry_number=i + 1,
                scheduled_for=failure_ts + timedelta(hours=12 * (i + 1)),
                executed_at=failure_ts + timedelta(hours=12 * (i + 1)),
                outcome="FAILED",
                failure_code=spec.failure_code,
            ))

        subscription_info = None
        if spec.subscription:
            from ..context import SubscriptionInfo
            subscription_info = SubscriptionInfo(
                subscription_id=str(uuid4()),
                person_id=person.person_id,
                merchant_id=merchant.merchant_id,
                product_id=str(uuid4()),
                amount=spec.amount,
                billing_cycle="monthly",
                status="ACTIVE",
                next_billing_date=current_time + timedelta(days=30),
                consecutive_failures=spec.retry_count + 1,
            )

        return RecoveryContext(
            attempt=attempt,
            intent_id=str(case_id),
            intent_amount=spec.amount,
            intent_payment_method=spec.payment_method,
            intent_status="FAILED",
            person=person,
            balance=balance,
            merchant=merchant,
            subscription=subscription_info,
            failure_code=spec.failure_code,
            failure_reason=attempt.failure_reason,
            failure_timestamp=failure_ts,
            bank_state=spec.bank_state,
            prior_recoveries=prior,
            retry_count=spec.retry_count,
            customer_declined=spec.customer_declined,
            current_simulation_time=current_time,
        )
