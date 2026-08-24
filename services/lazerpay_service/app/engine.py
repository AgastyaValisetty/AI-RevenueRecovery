"""LazerPay payment gateway core logic: idempotency, latency simulation,
funds validation, and probabilistic authorization decisions.
"""
import time
import uuid
from decimal import Decimal
from random import Random
from typing import Optional

from .domain import BankPolicy, BankState, FailureCode, PaymentAttempt, PaymentIntent, RecoveryAction
from .schema import PaymentAttemptRow


class IdempotencyGuard:
    """Prevents double-processing of payment attempts."""

    @staticmethod
    def check_key(repo, key: str) -> Optional[PaymentAttemptRow]:
        """Check if idempotency key already exists. Returns existing attempt or None."""
        return repo.find_by_idempotency_key(key)

    @staticmethod
    def generate_key(intent_id: str, attempt_number: int) -> str:
        """Generate deterministic idempotency key from intent_id + attempt_number."""
        return f"idem_{intent_id}_{attempt_number}"


class LatencySimulator:
    """Simulates network latency for bank/gateway calls."""

    @staticmethod
    def simulate_response_time(rng: Random) -> int:
        """Return latency in milliseconds (50-500ms per model)."""
        return rng.randint(50, 500)


def _simulate_latency(rng: Random, min_seconds: float = 0.05, max_seconds: float = 0.5) -> None:
    """Sleep for simulated network latency."""
    target = rng.uniform(min_seconds, max_seconds)
    time.sleep(target)


class FundsValidator:
    """Checks whether a source account has sufficient funds for a payment."""

    @staticmethod
    def has_sufficient_funds(source_balance: Decimal, amount: Decimal) -> bool:
        return source_balance >= amount


class ProbabilityEngine:
    """Makes probabilistic authorization decisions based on bank policy.

    Mirrors the logic in bank_service.engine.ProbabilityEngine so that
    LazerPay can function standalone without importing from the bank service.
    """

    def __init__(self, rng: Random):
        self._rng = rng

    def get_adjusted_success_rate(self, bank: BankPolicy) -> float:
        """Adjust success rate based on current bank state."""
        multiplier = bank.state_multipliers.get(bank.current_state.value, 1.0)
        return bank.authorization_success_rate / multiplier

    def decide(self, bank: BankPolicy) -> tuple[bool, str | None, str | None]:
        """
        Returns (success, failure_code, failure_reason).
        Hard failures (insufficient funds) are checked separately by FundsValidator.
        This handles the probabilistic bank-side failures.
        """
        adjusted_rate = self.get_adjusted_success_rate(bank)
        roll = self._rng.random()

        if roll < adjusted_rate:
            return True, None, None

        failure_type = FailureCode._weighted_pick(self._rng)
        reason_map = {
            FailureCode.TIMEOUT.value: "Bank did not respond in time",
            FailureCode.HARD_DECLINE.value: "Bank declined transaction (issuer check)",
            FailureCode.EXPIRED_CARD.value: "Card has expired",
            FailureCode.FRAUD_BLOCK.value: "Transaction blocked by fraud detection",
            FailureCode.NETWORK_ERROR.value: "Network error communicating with bank",
        }
        return False, failure_type, reason_map.get(failure_type, "Unknown failure")


# Re-export default bank factory for api.py convenience
def default_bank_policy() -> BankPolicy:
    """Create the default RupeeBank policy used for probability decisions."""
    return BankPolicy(
        bank_id=str(uuid.uuid4()),
        name="RupeeBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.NORMAL,
        state_multipliers={
            BankState.NORMAL.value: 1.0,
            BankState.PEAK.value: 2.0,
            BankState.DEGRADED.value: 5.0,
            BankState.OUTAGE.value: 50.0,
        },
    )
