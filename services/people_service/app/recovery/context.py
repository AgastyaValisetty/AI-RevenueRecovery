"""RecoveryContext — typed observable state used by recovery decision engines.

RecoveryContext is built by RecoveryContextBuilder from repository reads.
It contains ONLY information observable at decision time:

  * the failed payment intent
  * the associated payment attempt (if processed through LazerPay)
  * the person + their current balance
  * the merchant
  * the subscription (if relevant)
  * the failure code and reason
  * the simulation timestamp and bank state
  * prior recovery history for this attempt

It deliberately does NOT expose:
  - future balances
  - future payment outcomes
  - hidden simulator ground truth
  - internal RNG state

The same structure will be reusable by the future Smart AI Agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class AttemptInfo:
    """Observable snapshot of a payment attempt (LazerPay record)."""

    attempt_id: str
    intent_id: str
    attempt_number: int
    person_id: str
    merchant_id: str
    amount: Decimal
    payment_method: str
    status: str
    failure_code: Optional[str]
    failure_reason: Optional[str]
    source_account_id: Optional[str]
    simulation_timestamp: Optional[datetime]
    bank_state: Optional[str]
    bank_response_time_ms: Optional[int]
    gateway_latency_ms: Optional[int]
    failed_at: Optional[datetime]


@dataclass(frozen=True)
class PersonInfo:
    """Observable person attributes (no hidden state)."""

    person_id: str
    name: str
    age: int
    salary: Decimal
    salary_deposit_day: int
    salary_deposit_hour: int
    spending_profile_category: str
    income_bracket: str
    age_group: str
    employment_type: str
    primary_account_id: str


@dataclass(frozen=True)
class MerchantInfo:
    merchant_id: str
    name: str
    merchant_type: str


@dataclass(frozen=True)
class SubscriptionInfo:
    subscription_id: str
    person_id: str
    merchant_id: str
    product_id: str
    amount: Decimal
    billing_cycle: str
    status: str
    next_billing_date: Optional[datetime]
    consecutive_failures: int


@dataclass(frozen=True)
class BalanceInfo:
    """Current balance at decision time."""

    account_id: str
    current_balance: Decimal


@dataclass(frozen=True)
class PriorRecovery:
    """A prior recovery action for this attempt (chronological)."""

    retry_number: int
    scheduled_for: datetime
    executed_at: Optional[datetime]
    outcome: str
    failure_code: Optional[str]


@dataclass(frozen=True)
class RecoveryContext:
    """Full observable context for a recovery decision.

    Built by RecoveryContextBuilder from repository reads.  No simulator
    internals or future state are exposed.
    """

    # The failed payment attempt (from LazerPay, if one exists).
    attempt: Optional[AttemptInfo]

    # The originating payment intent (People Service).
    intent_id: str
    intent_amount: Decimal
    intent_payment_method: str
    intent_status: str

    # Person info + current balance.
    person: PersonInfo
    balance: BalanceInfo

    # Merchant info.
    merchant: MerchantInfo

    # Subscription if this was a subscription payment (None for one-time).
    subscription: Optional[SubscriptionInfo]

    # Failure info — from the RecoveryAction's stored metadata.
    failure_code: Optional[str]
    failure_reason: Optional[str]

    # Time + bank state at failure.
    failure_timestamp: Optional[datetime]
    bank_state: Optional[str]

    # Prior recovery actions for this intent (chronological).
    prior_recoveries: list[PriorRecovery]

    # Count of already-executed retries.
    retry_count: int

    # Whether the customer has explicitly declined a previous recovery.
    customer_declined: bool

    # Simulation timestamp now (the clock).
    current_simulation_time: datetime

    @property
    def hours_since_failure(self) -> int:
        """Whole hours elapsed since the original failure."""
        if self.failure_timestamp is None:
            return 0
        delta = self.current_simulation_time - self.failure_timestamp
        return int(delta.total_seconds() // 3600)
