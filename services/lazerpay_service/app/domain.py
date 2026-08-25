"""LazerPay domain models: payment gateway entities.

These mirror the core concepts from the people_service domain
but are LazerPay-specific (attempts, retries, recovery actions).

PaymentAttempt state machine (from UML 11_attempt_state_diagram):
    [*]    --> INITIATED
    INITIATED --> ROUTING
    ROUTING --> AUTHORIZED   (bank success)
    AUTHORIZED --> SETTLED  (ledger PAYMENT_SETTLED written)
    ROUTING --> FAILED      (bank decline / timeout / network error / insufficient funds)
    AUTHORIZED --> FAILED   (settlement failure)
    INITIATED --> FAILED    (insufficient funds hard check)
    ROUTING --> UNKNOWN     (ambiguous bank response — not a definitive failure)
    FAILED --> [*]           (picked up by Recovery Agent)
    SETTLED --> [*]          (idempotency key blocks re-processing)
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


class FailureCode(str, Enum):
    """Bank-side failure categories used for recovery reasoning.

    The live gateway passes through the bank service's codes; this enum is the
    recovery/domain mirror of that taxonomy.  Old dummy codes (HARD_DECLINE,
    EXPIRED_CARD, FRAUD_BLOCK) have been removed.
    """
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    EXPIRED_PAYMENT_METHOD = "EXPIRED_PAYMENT_METHOD"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    CANCELLED = "CANCELLED"
    ISSUER_DECLINE = "ISSUER_DECLINE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    RISK_DECLINE = "RISK_DECLINE"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    BANK_DEGRADED = "BANK_DEGRADED"
    INVALID_DETAILS = "INVALID_DETAILS"
    UNSUPPORTED_METHOD = "UNSUPPORTED_METHOD"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


# Human-readable reasons for the new taxonomy (mirrors bank_service + people_service).
FAILURE_REASONS: dict[str, str] = {
    "INSUFFICIENT_FUNDS": "Insufficient balance",
    "EXPIRED_PAYMENT_METHOD": "Payment method expired / blocked",
    "AUTHENTICATION_FAILURE": "Authentication failed (PIN/OTP/3DS)",
    "CANCELLED": "Customer cancelled / abandoned",
    "ISSUER_DECLINE": "Temporary decline by issuing bank",
    "LIMIT_EXCEEDED": "Transaction / daily limit exceeded",
    "RISK_DECLINE": "Blocked for suspected fraud / risk",
    "NETWORK_ERROR": "Network / connectivity failure",
    "TIMEOUT": "Bank response timed out / unknown outcome",
    "BANK_DEGRADED": "Bank under load / degraded",
    "INVALID_DETAILS": "Incorrect payment details (CVV/account)",
    "UNSUPPORTED_METHOD": "Payment method not supported",
    "UNKNOWN_OUTCOME": "Bank response delayed beyond delivery window",
}


@dataclass(frozen=True)
class BankAuthorizationRequest:
    """Request sent to Bank Service for authorization.

    This is the typed contract — not an arbitrary dict — that
    LazerPay sends to Bank Service via HTTP.
    """
    attempt_id: str
    amount: str
    payment_method: str
    source_account_id: str
    source_balance: str
    simulation_timestamp: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class BankAuthorizationResult:
    """Response received from Bank Service."""
    success: bool
    failure_code: str | None
    failure_reason: str | None
    response_time_ms: int
    bank_state: str
    source_balance: str
    authorized_at: datetime
    unknown_outcome: bool = False


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
    """A single authorization attempt for a payment intent.

    Implements the full state machine from UML 11_attempt_state_diagram:
    INITIATED -> ROUTING -> AUTHORIZED -> SETTLED
    """
    attempt_id: str
    intent_id: str
    attempt_number: int
    person_id: str
    merchant_id: str
    amount: Decimal
    payment_method: str
    status: str  # INITIATED, ROUTING, AUTHORIZED, SETTLED, FAILED, UNKNOWN, PENDING_LINK
    idempotency_key: str
    source_account_id: str | None = None
    destination_account_id: str | None = None
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
