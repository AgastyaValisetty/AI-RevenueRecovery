from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import random
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
    bank_id: str
    name: str
    authorization_success_rate: float
    timeout_rate: float
    issuer_decline_rate: float
    network_error_rate: float
    current_state: BankState
    state_multipliers: dict[str, float]
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class BankStatus:
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
    account_id: str
    person_id: str
    bank_id: str
    balance: float
    created_at: datetime = field(default_factory=now)


class FailureCode(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    TIMEOUT = "TIMEOUT"
    HARD_DECLINE = "HARD_DECLINE"
    EXPIRED_CARD = "EXPIRED_CARD"
    FRAUD_BLOCK = "FRAUD_BLOCK"
    NETWORK_ERROR = "NETWORK_ERROR"

    @staticmethod
    def _weighted_pick(rng: random.Random) -> str:
        # TIMEOUT 30%, HARD_DECLINE 30%, EXPIRED_CARD 20%, FRAUD_BLOCK 10%, NETWORK_ERROR 10%
        failure_types = [
            (FailureCode.TIMEOUT.value, 0.30),
            (FailureCode.HARD_DECLINE.value, 0.30),
            (FailureCode.EXPIRED_CARD.value, 0.20),
            (FailureCode.FRAUD_BLOCK.value, 0.10),
            (FailureCode.NETWORK_ERROR.value, 0.10),
        ]
        values, weights = zip(*failure_types)
        return str(rng.choices(values, weights=weights, k=1)[0])