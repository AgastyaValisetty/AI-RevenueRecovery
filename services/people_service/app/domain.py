from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from .failure_model import (
    FAILURE_REASONS,
    FAILURE_CATEGORIES,
    CATEGORY_LABELS,
)

SALARY_DEPOSIT = "SALARY_DEPOSIT"
LIVING_COST = "LIVING_COST"
PAYMENT_SETTLED = "PAYMENT_SETTLED"
PAYMENT_FAILED = "PAYMENT_FAILED"
ORDER_PURCHASE = "ORDER_PURCHASE"
INCOME_TAX = "INCOME_TAX"
GST = "GST"

# Payment intent statuses
INTENT_PENDING = "PENDING"
INTENT_SETTLED = "SETTLED"
INTENT_FAILED = "FAILED"

# Payment attempt statuses (state machine from UML)
ATTEMPT_INITIATED = "INITIATED"
ATTEMPT_ROUTING = "ROUTING"
ATTEMPT_AUTHORIZED = "AUTHORIZED"
ATTEMPT_SETTLED = "SETTLED"
ATTEMPT_FAILED = "FAILED"
ATTEMPT_UNKNOWN = "UNKNOWN"
ATTEMPT_PENDING_LINK = "PENDING_LINK"

MONTHLY = "MONTHLY"
ACTIVE = "ACTIVE"
PENDING = "PENDING"
SETTLED = "SETTLED"
FAILED = "FAILED"

UPI = "UPI"
CARD = "CARD"
NETBANKING = "NETBANKING"

# LazerPay is a payment-gateway entity that takes a cut from the merchant on
# every settled transaction.  Flat 2% across all payment methods (UPI, CARD,
# NETBANKING).  LazerPay revenue accrues as a share of the settled volume.
LAZERPAY_FEE_RATE = "0.02"

# Human-readable reason + category for every failure code. Single source of
# truth lives in failure_model.FAILURE_TYPES; FAILURE_REASONS / FAILURE_CATEGORIES
# (new taxonomy, old dummy codes removed) are re-exported above.

# Simulation run statuses
STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"


class IncomeBracket(str, Enum):
    LOW = "low"
    LOWER_MIDDLE = "lower_middle"
    MIDDLE = "middle"
    UPPER_MIDDLE = "upper_middle"
    HIGH = "high"


class AgeGroup(str, Enum):
    GROUP_18_24 = "18-24"
    GROUP_25_34 = "25-34"
    GROUP_35_44 = "35-44"
    GROUP_45_54 = "45-54"
    GROUP_55_64 = "55-64"
    GROUP_65_PLUS = "65+"


class EmploymentType(str, Enum):
    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    STUDENT = "student"
    RETIRED = "retired"
    UNEMPLOYED = "unemployed"


class SpendingProfile(str, Enum):
    STUDENT = "student"
    YOUNG_PROFESSIONAL = "young_professional"
    FAMILY = "family"
    HIGH_INCOME = "high_income"
    RETIRED = "retired"


class SimulationStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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
    # Settlement account id is a non-UUID string (e.g. "settlement-<hex12>")
    # written by the Bank Service — kept as str to match.
    settlement_account_id: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class BankAccount:
    account_id: UUID
    bank_id: UUID
    person_id: UUID | None = None
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
    income_bracket: str
    age_group: str
    employment_type: str
    primary_bank_id: UUID
    primary_account_id: UUID
    salary_deposit_hour: int = 9
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
    status: str
    idempotency_key: str
    source_account_id: UUID | None = None
    destination_account_id: UUID | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    related_attempt_id: str | None = None
    initiated_at: datetime | None = None
    routed_at: datetime | None = None
    authorized_at: datetime | None = None
    settled_at: datetime | None = None
    failed_at: datetime | None = None
    unknown_at: datetime | None = None
    bank_response_time_ms: int | None = None
    gateway_latency_ms: int | None = None
    bank_state: str | None = None
    simulation_timestamp: datetime | None = None
    correlation_id: str | None = None
    retry_for_attempt_id: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class PaymentAttemptStatus:
    """Lightweight status envelope for query responses."""
    attempt_id: str
    intent_id: str
    attempt_number: int
    person_id: str
    merchant_id: str
    amount: str
    payment_method: str
    status: str
    failure_code: str | None = None
    failure_reason: str | None = None
    simulation_timestamp: str | None = None
    correlation_id: str | None = None
    bank_response_time_ms: int | None = None
    gateway_latency_ms: int | None = None
    initiated_at: str | None = None
    routed_at: str | None = None
    authorized_at: str | None = None
    settled_at: str | None = None
    failed_at: str | None = None
    unknown_at: str | None = None
    bank_state: str | None = None
    retry_for_attempt_id: str | None = None


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: UUID
    event_type: str
    from_account_id: str | None
    to_account_id: str | None
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


@dataclass(frozen=True)
class SimulationRun:
    """Record of a single simulation execution.

    Stores the seed and config snapshot used, enabling reproducibility and
    auditability of simulation results.
    """

    run_id: UUID
    seed: int
    config_snapshot: dict
    people_count: int | None = None
    hours_run: int = 0
    status: str = STATUS_PENDING
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class PurchaseDecision:
    """Result of an e-commerce shopping decision for a person.

    Represents a discretionary purchase from a merchant's one-time product
    catalog.  Created by :class:`~engines.EcommerceEngine` and converted
    into a ``PaymentIntent`` by the orchestrator.
    """

    person_id: UUID
    merchant_id: UUID
    product_id: UUID
    amount: Decimal
    decision_time: datetime
    reason: str = "normal"
