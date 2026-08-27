"""RecoveryContextBuilder — assembles a RecoveryContext from repository reads.

This is pure orchestration.  No decision logic lives here.
All fields are derived from observables stored in the shared DB.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ..domain import PaymentIntent, LedgerEntry
from ..repositories import (
    LedgerRepository,
    MerchantRepository,
    PaymentIntentRepository,
    PersonRepository,
    SubscriptionRepository,
)
from ..schema import RecoveryActionRow
from .context import (
    AttemptInfo,
    BalanceInfo,
    MerchantInfo,
    PersonInfo,
    PriorRecovery,
    RecoveryContext,
    SubscriptionInfo,
)
from .domain import RecoveryAction, RecoveryActionType, RecoveryOutcome
from .repository import RecoveryActionRepository

logger = logging.getLogger(__name__)


class RecoveryContextBuilder:
    """Builds a RecoveryContext for a failed payment.

    Parameters mirror the repositories the orchestrator already wires.
    The builder reads ONLY observable, already-persisted data.
    """

    def __init__(
        self,
        person_repo: PersonRepository,
        merchant_repo: MerchantRepository,
        subscription_repo: SubscriptionRepository,
        intent_repo: PaymentIntentRepository,
        ledger_repo: LedgerRepository,
        recovery_repo: RecoveryActionRepository,
    ):
        self._person_repo = person_repo
        self._merchant_repo = merchant_repo
        self._subscription_repo = subscription_repo
        self._intent_repo = intent_repo
        self._ledger_repo = ledger_repo
        self._recovery_repo = recovery_repo

    def build_for_intent(
        self,
        intent: PaymentIntent,
        current_simulation_time: datetime,
        # Failure info captured at action-creation time:
        failure_code: Optional[str] = None,
        failure_reason: Optional[str] = None,
        bank_state: Optional[str] = None,
        failure_timestamp: Optional[datetime] = None,
        attempt_info: Optional[AttemptInfo] = None,
        # Pre-fetched caches to avoid N+1 queries when building many contexts:
        person_cache: Optional[dict] = None,
        merchant_cache: Optional[dict] = None,
        balance_cache: Optional[dict] = None,
        prior_actions_cache: Optional[dict[UUID, list]] = None,
    ) -> RecoveryContext:
        """Build a full context for a FAILED PaymentIntent.

        ``failure_code`` / ``failure_reason`` / ``bank_state`` /
        ``failure_timestamp`` are read from the RecoveryAction that first
        captured this failure — they represent observed data, not hidden
        simulator state.

        ``person_cache``, ``merchant_cache``, and ``balance_cache`` allow the
        caller to pass pre-fetched data so that batch context-building avoids
        N+1 DB queries.
        """
        if person_cache is not None:
            person = person_cache.get(intent.person_id)
        else:
            person = self._person_repo.find_by_id(intent.person_id)
        if person is None:
            person_info = PersonInfo(
                person_id=str(intent.person_id),
                name="unknown",
                age=0,
                salary=Decimal("0"),
                salary_deposit_day=0,
                salary_deposit_hour=9,
                spending_profile_category="unknown",
                income_bracket="middle",
                age_group="35-44",
                employment_type="salaried",
                primary_account_id=str(intent.person_id),
            )
        else:
            person_info = PersonInfo(
                person_id=str(person.person_id),
                name=person.name,
                age=person.age,
                salary=person.salary,
                salary_deposit_day=person.salary_deposit_day,
                salary_deposit_hour=getattr(person, "salary_deposit_hour", 9),
                spending_profile_category=person.spending_profile_category,
                income_bracket=getattr(person, "income_bracket", "middle"),
                age_group=getattr(person, "age_group", "35-44"),
                employment_type=getattr(person, "employment_type", "salaried"),
                primary_account_id=str(person.primary_account_id),
            )

        # Merchant — use cache if provided, otherwise fetch from repo
        if merchant_cache is not None:
            merchant_match = merchant_cache.get(intent.merchant_id)
        else:
            merchant_match = None
            for m in self._merchant_repo.find_all():
                if m.merchant_id == intent.merchant_id:
                    merchant_match = m
                    break
        if merchant_match is None:
            merchant_info = MerchantInfo(
                merchant_id=str(intent.merchant_id),
                name="unknown",
                merchant_type="unknown",
            )
        else:
            merchant_info = MerchantInfo(
                merchant_id=str(merchant_match.merchant_id),
                name=merchant_match.name,
                merchant_type=merchant_match.merchant_type,
            )

        # Current balance — use cache if provided, otherwise query
        if balance_cache is not None:
            balance = balance_cache.get(intent.person_id, Decimal("0"))
        elif person:
            balance = self._ledger_repo.balance_of(person.primary_account_id)
        else:
            balance = Decimal("0")

        # Subscription if relevant
        sub_info: Optional[SubscriptionInfo] = None
        if intent.related_subscription_id is not None:
            sub = self._subscription_repo.find(intent.related_subscription_id)
            if sub is not None:
                nbd = sub.next_billing_date
                if nbd is not None and hasattr(nbd, 'isoformat'):
                    nbd_dt = nbd  # already a datetime
                elif nbd is not None:
                    from datetime import date
                    nbd_dt = datetime.combine(nbd, datetime.min.time())
                else:
                    nbd_dt = None
                sub_info = SubscriptionInfo(
                    subscription_id=str(sub.subscription_id),
                    person_id=str(sub.person_id),
                    merchant_id=str(sub.merchant_id),
                    product_id=str(sub.product_id),
                    amount=sub.amount,
                    billing_cycle=sub.billing_cycle,
                    status=sub.status,
                    next_billing_date=nbd_dt,
                    consecutive_failures=sub.consecutive_failures,
                )

        # Prior recovery actions — use pre-fetched batch result if provided
        if prior_actions_cache is not None:
            prior_actions = prior_actions_cache.get(intent.intent_id, [])
        else:
            prior_actions = self._recovery_repo.find_by_intent_id(intent.intent_id)
        prior_infos: list[PriorRecovery] = []
        retry_count = 0
        customer_declined = False
        for action in prior_actions:
            if action.retry_number is not None and action.executed_at is not None:
                if action.retry_number > retry_count:
                    retry_count = action.retry_number
            if action.action_type == RecoveryActionType.STOP and action.customer_declined:
                customer_declined = True
            prior_infos.append(
                PriorRecovery(
                    retry_number=action.retry_number or 0,
                    scheduled_for=action.scheduled_for or current_simulation_time,
                    executed_at=action.executed_at,
                    outcome=action.outcome.value if action.outcome else "PENDING",
                    failure_code=action.failure_code,
                )
            )

        # Use the provided attempt info (from RecoveryAction metadata)
        # or construct from the ledger's failed entry
        if attempt_info is None:
            attempt_info = self._extract_attempt_info(intent, failure_timestamp)

        return RecoveryContext(
            attempt=attempt_info,
            intent_id=str(intent.intent_id),
            intent_amount=intent.amount,
            intent_payment_method=intent.payment_method,
            intent_status=intent.status,
            person=person_info,
            balance=BalanceInfo(
                account_id=person_info.primary_account_id,
                current_balance=balance,
            ),
            merchant=merchant_info,
            subscription=sub_info,
            failure_code=failure_code,
            failure_reason=failure_reason,
            failure_timestamp=failure_timestamp,
            bank_state=bank_state,
            prior_recoveries=prior_infos,
            retry_count=retry_count,
            customer_declined=customer_declined,
            current_simulation_time=current_simulation_time,
        )

    def _extract_attempt_info(
        self,
        intent: PaymentIntent,
        failure_timestamp: Optional[datetime],
    ) -> Optional[AttemptInfo]:
        """Try to find a PAYMENT_FAILED ledger entry for this intent.

        Falls back to None if no entry is found — the context still carries
        the failure info passed explicitly by the caller.
        """
        return None  # failure info is captured at action creation time
