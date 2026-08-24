"""LazerPay domain models: payment gateway entities.

These mirror the core concepts from the people_service domain
but are LazerPay-specific (attempts, retries, recovery actions).
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from decimal import Decimal
from uuid import uuid4


def now() -> datetime:
    return datetime.now(timezone.utc)


class BankState(str, Enum):
    NORMAL = "NORMAL"
    PEAK = "PEAK"
    DEGRADED = "DEGRADED"
    OUTAGE = "OUTAGE"


@dataclass(frozen=True)
class BankPolicy:
    """Bank policy parameters for probabilistic authorization decisions."""
    bank_id: str
    name: str
    authorization_success_rate: float
    timeout_rate: float
    issuer_decline_rate: float
    network_error_rate: float
    current_state: BankState
    state_multipliers: dict[str, float]
    created_at: datetime = field(default_factory=now)


class BankStatus:
    """Lightweight snapshot of a bank's health for gateway decisions."""
    def __init__(
        self,
        bank_id: str,
        name: str,
        current_state: str,
        success_rate: float,
        failure_rate: float,
        transactions_last_minute: int,
        failures_last_minute: int,
        balance: float = 0.0,
    ):
        self.bank_id = bank_id
        self.name = name
        self.current_state = current_state
        self.success_rate = success_rate
        self.failure_rate = failure_rate
        self.transactions_last_minute = transactions_last_minute
        self.failures_last_minute = failures_last_minute
        self.balance = balance


class FailureCode(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    TIMEOUT = "TIMEOUT"
    HARD_DECLINE = "HARD_DECLINE"
    EXPIRED_CARD = "EXPIRED_CARD"
    FRAUD_BLOCK = "FRAUD_BLOCK"
    NETWORK_ERROR = "NETWORK_ERROR"

    @staticmethod
    def _weighted_pick(rng) -> str:
        """Pick a failure code weighted by frequency (mirrors bank_service)."""
        failure_types = [
            (FailureCode.TIMEOUT.value, 0.30),
            (FailureCode.HARD_DECLINE.value, 0.30),
            (FailureCode.EXPIRED_CARD.value, 0.20),
            (FailureCode.FRAUD_BLOCK.value, 0.10),
            (FailureCode.NETWORK_ERROR.value, 0.10),
        ]
        values, weights = zip(*failure_types)
        return str(rng.choices(values, weights=weights, k=1)[0])


@dataclass(frozen=True)
class PaymentIntent:
    """Payment intent created by the People Service and processed by LazerPay."""
    intent_id: str
    person_id: str
    merchant_id: str
    amount: Decimal
    payment_method: str
    status: str  # PENDING, SETTLED, FAILED
    created_at: datetime = field(default_factory=now)
    expires_at: datetime = field(default_factory=lambda: now() + timedelta(hours=1))


@dataclass(frozen=True)
class PaymentAttempt:
    """A single authorization attempt for a payment intent."""
    attempt_id: str
    intent_id: str
    attempt_number: int
    person_id: str
    merchant_id: str
    amount: Decimal
    payment_method: str
    source_account_id: str
    destination_account_id: str
    status: str  # INITIATED, PENDING, SETTLED, FAILED, PENDING_LINK
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
class RecoveryAction:
    """A recovery action taken on a failed payment attempt (retry, link, etc.)."""
    action_id: str
    attempt_id: str
    intent_id: str
    action_type: str  # RETRY, SEND_LINK, ESCALATE
    reason: str | None = None
    scheduled_for: datetime | None = None
    executed_at: datetime | None = None
    outcome: str | None = None
    cost: Decimal | None = None
    expected_recovery: Decimal | None = None
    created_at: datetime = field(default_factory=now)
