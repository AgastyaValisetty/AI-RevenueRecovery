"""Bank Service domain models.

Defines the bank policy, authorization contracts, and state machine
used by the Bank Service for payment authorization.

Bank state machine (from UML 10_bank_state_diagram):
    NORMAL → PEAK → DEGRADED → OUTAGE
    Each state multiplies the failure rate, reducing the effective
    authorization success rate.

Authorization contract:
    Bank Service receives a request from LazerPay, checks funds
    and applies state-dependent probabilistic decision logic.
    The response includes an ``unknown_outcome`` flag to signal
    delivery uncertainty (TIMEOUT) — this is distinct from a hard
    FAILED decline.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from random import Random


def now() -> datetime:
    return datetime.now(timezone.utc)


class BankState(str, Enum):
    NORMAL = "NORMAL"
    PEAK = "PEAK"
    DEGRADED = "DEGRADED"
    OUTAGE = "OUTAGE"


class FailureCode(str, Enum):
    """Bank-side failure categories (new real-world taxonomy).

    Old dummy placeholder codes (HARD_DECLINE, EXPIRED_CARD, FRAUD_BLOCK,
    BANK_OUTAGE) have been removed — only the calibrated taxonomy remains.
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

    @staticmethod
    def _weighted_pick(rng: Random, bank_state: str = "NORMAL") -> str:
        """Pick a decline code weighted by the user's composition split.

        ``bank_state`` folds weight toward ``BANK_DEGRADED`` while the bank is
        in a degraded/outage state.
        """
        # Base conditional distribution among failures (INSUFFICIENT_FUNDS is
        # handled by the hard funds check, not here). Weights mirror
        # people_service.failure_model.COMPOSITION.
        failure_types: list[tuple[str, float]] = [
            (FailureCode.ISSUER_DECLINE.value, 14),
            (FailureCode.NETWORK_ERROR.value, 12),
            (FailureCode.TIMEOUT.value, 9),
            (FailureCode.LIMIT_EXCEEDED.value, 8),
            (FailureCode.RISK_DECLINE.value, 7),
            (FailureCode.EXPIRED_PAYMENT_METHOD.value, 5),
            (FailureCode.AUTHENTICATION_FAILURE.value, 4),
            (FailureCode.INVALID_DETAILS.value, 3),
            (FailureCode.CANCELLED.value, 2),
            (FailureCode.UNSUPPORTED_METHOD.value, 1),
        ]
        if bank_state in ("DEGRADED", "OUTAGE"):
            # Boil over toward infra/load failure while the bank is sick.
            total = sum(w for _c, w in failure_types)
            failure_types = [
                (FailureCode.BANK_DEGRADED.value, 60.0),
            ] + [
                (c, w * 40.0 / total) for c, w in failure_types
            ]
        values, weights = zip(*failure_types)
        return str(rng.choices(values, weights=weights, k=1)[0])


# Human-readable reasons for the new failure taxonomy (mirrors the
# people_service.failure_model so the dashboard shows one coherent vocabulary).
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
}


@dataclass(frozen=True)
class BankPolicy:
    """Bank configuration controlling authorization behavior."""
    bank_id: str
    name: str
    authorization_success_rate: float
    timeout_rate: float
    issuer_decline_rate: float
    network_error_rate: float
    current_state: BankState
    state_multipliers: dict[str, float]
    settlement_account_id: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class BankStatus:
    """Runtime status snapshot of a bank."""
    bank_id: str
    name: str
    current_state: BankState
    success_rate: float
    failure_rate: float
    transactions_last_minute: int
    failures_last_minute: int
    balance: float = 0.0


@dataclass(frozen=True)
class BankAccount:
    """A bank account linked to a person and bank.

    Settlement accounts (bank-owned) have ``person_id=None``.
    """
    account_id: str
    bank_id: str
    person_id: str | None = None
    balance: float = 0.0
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class BankAuthorizationRequest:
    """Request received from LazerPay for authorization."""
    attempt_id: str
    amount: str
    payment_method: str
    source_account_id: str
    simulation_timestamp: str | None = None
    correlation_id: str | None = None
    person_id: str | None = None


@dataclass(frozen=True)
class BankAuthorizationResult:
    """Response sent back to LazerPay.

    Fields:
        success          — whether the bank authorized the payment
        failure_code     — bank-side failure category (None if success)
        failure_reason   — human-readable failure description
        response_time_ms — simulated bank processing time (not real elapsed)
        bank_state       — bank's state at time of authorization
        source_balance   — account balance at time of authorization
        unknown_outcome  — True if the bank's response may not have been
                           reliably delivered (TIMEOUT).  LazerPay must
                           treat this as UNKNOWN, not FAILED.  The bank
                           may have actually authorized — idempotency
                           prevents double-charging.
    """
    success: bool
    failure_code: str | None
    failure_reason: str | None
    response_time_ms: int
    bank_state: str
    source_balance: str
    unknown_outcome: bool = False
