"""Core bank logic: funds validation, probabilistic decision, latency simulation, state machine."""
import random
from datetime import datetime, timezone
from decimal import Decimal

from .domain import BankPolicy, BankState, FailureCode


class FundsValidator:
    @staticmethod
    def has_sufficient_funds(source_balance: Decimal, amount: Decimal) -> bool:
        return source_balance >= amount


class LatencySimulator:
    def __init__(self, rng: random.Random):
        self._rng = rng

    def simulate_response_time(self) -> int:
        return self._rng.randint(50, 500)


class ProbabilityEngine:
    """Makes probabilistic authorization decisions based on bank state."""

    def __init__(self, rng: random.Random):
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


class BankStateMachine:
    """Manages bank state transitions based on transaction metrics."""

    def __init__(self, rng: random.Random):
        self._rng = rng

    def get_state_multiplier(self, state: BankState) -> float:
        multipliers = {
            BankState.NORMAL: 1.0,
            BankState.PEAK: 2.0,
            BankState.DEGRADED: 5.0,
            BankState.OUTAGE: 50.0,
        }
        return multipliers.get(state, 1.0)

    def bank_state_transition(
        self,
        current_state: BankState,
        txn_count_last_minute: int,
        failure_rate_last_minute: float,
        consecutive_failures: int,
        outage_started_at: datetime | None,
    ) -> BankState | None:
        """
        Returns new state if transition occurred, None if no change.
        Logic from ARCHITECTURE.md Part 3.2
        """
        now = datetime.now(timezone.utc)

        if current_state == BankState.NORMAL:
            if txn_count_last_minute > 100 and failure_rate_last_minute > 0.01:
                return BankState.PEAK

        elif current_state == BankState.PEAK:
            if failure_rate_last_minute > 0.05:
                return BankState.DEGRADED
            if txn_count_last_minute < 50:
                return BankState.NORMAL

        elif current_state == BankState.DEGRADED:
            if failure_rate_last_minute > 0.10:
                return BankState.OUTAGE
            if failure_rate_last_minute < 0.05:
                return BankState.NORMAL

        elif current_state == BankState.OUTAGE:
            if outage_started_at and (now - outage_started_at).total_seconds() > 1800:
                return BankState.NORMAL

        return None
