"""Recovery domain types — actions, decisions, outcomes.

All types are frozen dataclasses/enums with no infrastructure dependencies.
The decision engine is a Protocol so a future Smart AI Agent can swap in
its own implementation transparently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

# Recovery policy constants (baseline strategy).
MAX_RETRIES = 3
RETRY_INTERVAL_HOURS = 12


class RecoveryActionType(str, Enum):
    """Action types the executor can perform.

    The baseline engine only emits RETRY and STOP.  The executor and
    customer-response simulator also support SEND_PAYMENT_LINK and
    SEND_NOTIFICATION for future AI-agent use.
    """

    RETRY = "RETRY"
    SEND_PAYMENT_LINK = "SEND_PAYMENT_LINK"
    SEND_NOTIFICATION = "SEND_NOTIFICATION"
    STOP = "STOP"


class RecoveryOutcome(str, Enum):
    """Lifecycle outcome recorded on a RecoveryActionRow."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"


class RecoveryEngineType(str, Enum):
    """Identifies which engine produced a run — for comparison experiments."""

    BASELINE = "BASELINE"
    AI_AGENT = "AI_AGENT"


@dataclass(frozen=True)
class RecoveryDecision:
    """Output of a RecoveryDecisionEngine.

    Either ``action`` is a concrete action (RETRY / SEND_PAYMENT_LINK /
    SEND_NOTIFICATION) with ``scheduled_for``, or ``action`` is STOP.
    """

    action: RecoveryActionType
    scheduled_for: Optional[datetime] = None
    reason: Optional[str] = None  # machine-readable label
    retry_number: Optional[int] = None  # 1, 2, 3 for retries; None for STOP/link
    # Expected net value (ENPV) computed by the ActionValueCalculator at
    # decision time. Carried through to the scheduler so the persisted
    # RecoveryAction can record it (the SARA tab reads this for display).
    expected_net_value: Optional[Decimal] = None


@dataclass(frozen=True)
class RecoveryAction:
    """A persisted recovery action record.

    Each retry is an independent row so the audit trail is never overwritten.
    """

    action_id: UUID
    run_id: UUID
    # The LazerPay attempt that failed (nullable — inline-settled intents
    # store only payment_intent_id).
    related_attempt_id: Optional[str]
    # The People Service payment intent that failed.
    payment_intent_id: Optional[UUID]
    # Which retry number (1, 2, 3) — None for non-retry actions.
    retry_number: Optional[int]
    action_type: RecoveryActionType
    reason: Optional[str]
    schedule_reason: Optional[str]
    scheduled_for: Optional[datetime]
    executed_at: Optional[datetime]
    outcome: RecoveryOutcome
    cost: Optional[Decimal] = None
    expected_recovery: Optional[Decimal] = None
    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None
    amount: Optional[Decimal] = None
    payment_method: Optional[str] = None
    # LazerPay attempt_id returned for this retry.
    retry_attempt_id: Optional[str] = None
    # Customer explicitly declined (for STOP on customer decline).
    customer_declined: bool = False
    # Flexible metadata: bank_state, failure_timestamp, original_failure_code, etc.
    metadata_json: dict = None
    created_at: datetime = None


class RecoveryDecisionEngine:
    """Interface for the recovery decision component.

    The future Smart AI Agent will subclass or implement this protocol and
    return a RecoveryDecision just like the baseline.  Everything else
    (scheduling, execution, persistence, metrics) is shared.

    Implementations must be deterministic given the same context + seed.
    """

    def decide(self, context: "RecoveryContext") -> RecoveryDecision:
        raise NotImplementedError
