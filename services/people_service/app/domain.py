from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

SALARY_DEPOSIT = "SALARY_DEPOSIT"
LIVING_COST = "LIVING_COST"
PAYMENT_SETTLED = "PAYMENT_SETTLED"
PAYMENT_FAILED = "PAYMENT_FAILED"

MONTHLY = "MONTHLY"
ACTIVE = "ACTIVE"
PENDING = "PENDING"
SETTLED = "SETTLED"
FAILED = "FAILED"

UPI = "UPI"
CARD = "CARD"
NETBANKING = "NETBANKING"


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Bank:
    bank_id: UUID
    name: str
    authorization_success_rate: Decimal
    timeout_rate: Decimal
    issuer_decline_rate: Decimal
    network_error_rate: Decimal
    current_state: str
    state_multipliers_json: dict
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class BankAccount:
    account_id: UUID
    person_id: UUID
    bank_id: UUID
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Person:
    person_id: UUID
    name: str
    age: int
    salary: Decimal
    salary_deposit_day: int
    spending_profile_category: str
    spending_profile_json: dict
    payment_preferences_json: dict
    primary_bank_id: UUID
    primary_account_id: UUID
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Merchant:
    merchant_id: UUID
    name: str
    merchant_type: str
    settlement_bank_id: UUID
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Product:
    product_id: UUID
    merchant_id: UUID
    name: str
    price: Decimal
    product_type: str
    billing_cycle: str | None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Subscription:
    subscription_id: UUID
    person_id: UUID
    merchant_id: UUID
    product_id: UUID
    amount: Decimal
    billing_cycle: str
    status: str
    next_billing_date: date
    last_successful_payment_date: date | None = None
    consecutive_failures: int = 0
    created_at: datetime = field(default_factory=now)
    cancelled_at: datetime | None = None


@dataclass(frozen=True)
class PaymentIntent:
    intent_id: UUID
    person_id: UUID
    merchant_id: UUID
    product_id: UUID
    amount: Decimal
    payment_method: str
    status: str
    related_subscription_id: UUID | None
    created_at: datetime = field(default_factory=now)
    expires_at: datetime = field(default_factory=lambda: now() + timedelta(hours=1))


@dataclass(frozen=True)
class PaymentAttempt:
    attempt_id: str
    intent_id: UUID
    attempt_number: int
    person_id: UUID
    merchant_id: UUID
    amount: Decimal
    payment_method: str
    source_account_id: UUID
    destination_account_id: UUID
    status: str
    idempotency_key: str
    failure_code: str | None = None
    failure_reason: str | None = None
    initiated_at: datetime | None = None
    authorized_at: datetime | None = None
    settled_at: datetime | None = None
    bank_response_time_ms: int | None = None
    gateway_processing_time_ms: int | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: UUID
    event_type: str
    from_account_id: UUID | None
    to_account_id: UUID | None
    amount: Decimal
    simulation_timestamp: datetime
    related_attempt_id: str | None = None
    related_subscription_id: UUID | None = None
    metadata_json: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class RecoveryAction:
    action_id: UUID
    related_attempt_id: str
    action_type: str
    reason: str
    scheduled_for: datetime | None = None
    executed_at: datetime | None = None
    outcome: str | None = None
    cost: Decimal | None = None
    expected_recovery: Decimal | None = None
    created_at: datetime = field(default_factory=now)
