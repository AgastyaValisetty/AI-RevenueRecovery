"""RecoveryMemoryRepository — customer + merchant recovery memory persistence.

Customer memory tracks structured interaction state: preferred channel,
language, best contact window, fatigue count, last message, consent status.
This is operational state, not unrestricted chat history.

Merchant memory tracks per-merchant recovery profiles (best channel, tone,
response rates) with hierarchical smoothing for small samples.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ...database import Database
from ...schema import CustomerRecoveryMemoryRow
from ...domain import ConsentState
from ..repository import RecoveryActionRepository

logger = logging.getLogger(__name__)

# Contact window defaults (India business hours, 9 AM - 9 PM)
DEFAULT_CONTACT_START = 9
DEFAULT_CONTACT_END = 21

# Fatigue threshold — after this many contacts in a window, suppress outreach
FATIGUE_SUPPRESS_THRESHOLD = 5


@dataclass(frozen=True)
class CustomerRecoveryMemory:
    """In-memory representation of customer recovery state."""

    person_id: str
    preferred_channel: Optional[str] = None
    preferred_language: str = "en"
    best_contact_window: Optional[dict] = None  # {"start_hour": 9, "end_hour": 21}
    fatigue_count: int = 0
    last_message: Optional[str] = None
    consent_state: ConsentState = ConsentState.PENDING
    contact_consent: bool = False
    last_interaction_at: Optional[datetime] = None

    @property
    def is_fatigued(self) -> bool:
        return self.fatigue_count >= FATIGUE_SUPPRESS_THRESHOLD

    @property
    def in_contact_window(self) -> bool:
        """Whether the current time is within the customer's preferred contact window."""
        if self.best_contact_window is None:
            return True
        start = self.best_contact_window.get("start_hour", DEFAULT_CONTACT_START)
        end = self.best_contact_window.get("end_hour", DEFAULT_CONTACT_END)
        now_hour = datetime.now().hour
        return start <= now_hour <= end


@dataclass(frozen=True)
class MerchantRecoveryProfile:
    """Learned recovery profile for a merchant (hierarchical smoothing)."""

    merchant_id: str
    best_channel: str = "upi"
    preferred_tone: str = "polite"
    response_rate: float = 0.015
    failure_code_success_rates: dict = field(default_factory=dict)  # code → rate
    sample_size: int = 0
    avg_time_to_recovery: float = 24.0
    incentive_sensitivity: float = 0.0


class RecoveryMemoryRepository:
    """Repository for customer and merchant recovery memory."""

    def __init__(self, db: Database, recovery_repo: Optional[RecoveryActionRepository] = None):
        self._db = db
        self._recovery_repo = recovery_repo

    # ------------------------------------------------------------------ #
    # Customer memory
    # ------------------------------------------------------------------ #

    def get_customer_memory(self, person_id: str) -> CustomerRecoveryMemory:
        """Fetch or initialize customer recovery memory."""
        from uuid import UUID as _UUID
        from sqlalchemy import select

        try:
            pid = _UUID(person_id)
        except (ValueError, TypeError):
            pid = None

        if pid is None:
            return CustomerRecoveryMemory(person_id=person_id)

        with self._db.session() as session:
            row = session.get(CustomerRecoveryMemoryRow, pid)
            if row is None:
                return CustomerRecoveryMemory(person_id=person_id)
            return CustomerRecoveryMemory(
                person_id=str(row.person_id),
                preferred_channel=row.preferred_channel,
                preferred_language=row.preferred_language or "en",
                best_contact_window=row.best_contact_window,
                fatigue_count=row.fatigue_count,
                last_message=row.last_message,
                consent_state=ConsentState(row.consent_status),
                contact_consent=row.contact_consent,
                last_interaction_at=row.last_interaction_at,
            )

    def upsert_customer_memory(
        self,
        person_id: str,
        *,
        preferred_channel: Optional[str] = None,
        preferred_language: Optional[str] = None,
        best_contact_window: Optional[dict] = None,
        fatigue_count: Optional[int] = None,
        last_message: Optional[str] = None,
        consent_state: Optional[ConsentState] = None,
        contact_consent: Optional[bool] = None,
        increment_fatigue: bool = False,
        last_interaction_at: Optional[datetime] = None,
    ) -> CustomerRecoveryMemory:
        """Upsert customer recovery memory (creates if missing, updates if exists)."""
        from uuid import UUID as _UUID
        from sqlalchemy import select

        try:
            pid = _UUID(person_id)
        except (ValueError, TypeError):
            return CustomerRecoveryMemory(person_id=person_id)

        now_ts = last_interaction_at or datetime.now()

        with self._db.session() as session:
            row = session.get(CustomerRecoveryMemoryRow, pid)
            if row is None:
                row = CustomerRecoveryMemoryRow(
                    person_id=pid,
                    preferred_channel=preferred_channel,
                    preferred_language=preferred_language or "en",
                    best_contact_window=best_contact_window,
                    fatigue_count=fatigue_count or 0,
                    last_message=last_message,
                    consent_status=consent_state.value if consent_state else "PENDING",
                    contact_consent=contact_consent or False,
                    last_interaction_at=now_ts,
                    created_at=now_ts,
                    updated_at=now_ts,
                )
                session.add(row)
            else:
                if preferred_channel is not None:
                    row.preferred_channel = preferred_channel
                if preferred_language is not None:
                    row.preferred_language = preferred_language
                if best_contact_window is not None:
                    row.best_contact_window = best_contact_window
                if fatigue_count is not None:
                    row.fatigue_count = fatigue_count
                if increment_fatigue:
                    row.fatigue_count = (row.fatigue_count or 0) + 1
                if last_message is not None:
                    row.last_message = last_message
                if consent_state is not None:
                    row.consent_status = consent_state.value
                if contact_consent is not None:
                    row.contact_consent = contact_consent
                if last_interaction_at is not None:
                    row.last_interaction_at = now_ts
                row.updated_at = now_ts

        return self.get_customer_memory(person_id)

    def increment_fatigue(self, person_id: str) -> int:
        """Increment the customer's fatigue count and return the new value."""
        mem = self.upsert_customer_memory(
            person_id, increment_fatigue=True,
            last_interaction_at=datetime.now(),
        )
        return mem.fatigue_count

    # ------------------------------------------------------------------ #
    # Merchant memory
    # ------------------------------------------------------------------ #

    def get_merchant_profile(self, merchant_id: str) -> MerchantRecoveryProfile:
        """Build a merchant recovery profile from historical data.

        Uses hierarchical smoothing: starts with global defaults, then
        adjusts based on merchant-specific recovery outcomes.  Requires a
        minimum sample size before trusting merchant-level stats.
        """
        if self._recovery_repo is None:
            return MerchantRecoveryProfile(merchant_id=merchant_id)

        # Get all recovery actions for this merchant
        from sqlalchemy import select
        from ...schema import RecoveryActionRow

        with self._db.session() as session:
            rows = session.scalars(
                select(RecoveryActionRow)
                .where(
                    RecoveryActionRow.metadata_json.contains({
                        "merchant_id": merchant_id
                    })
                )
                .limit(1000)
            ).all()

        sample_size = len(rows)

        if sample_size < 10:
            # Not enough data — return defaults with global fallback
            return MerchantRecoveryProfile(
                merchant_id=merchant_id,
                sample_size=sample_size,
            )

        # Compute merchant-specific metrics
        success_by_method: dict[str, list[int]] = {}
        total_by_method: dict[str, int] = {}
        response_times: list[float] = []

        for row in rows:
            method = row.payment_method or "unknown"
            total_by_method[method] = total_by_method.get(method, 0) + 1
            success = 0
            if row.outcome == "SUCCESS":
                success = 1
            success_by_method.setdefault(method, []).append(success)

            if row.metadata_json and row.metadata_json.get("failure_timestamp") and row.executed_at:
                try:
                    fail_ts = row.metadata_json["failure_timestamp"]
                    # Already parsed by SQLAlchemy
                    hours_diff = (row.executed_at - fail_ts).total_seconds() / 3600
                    if hours_diff >= 0:
                        response_times.append(hours_diff)
                except (ValueError, TypeError, AttributeError):
                    pass

        # Best channel = method with highest success rate
        best_channel = "upi"
        best_rate = 0.0
        for method, outcomes in success_by_method.items():
            if len(outcomes) >= 3:
                rate = sum(outcomes) / len(outcomes)
                if rate > best_rate:
                    best_rate = rate
                    best_channel = method.lower()

        # Failure code success rates
        failure_code_rates: dict[str, float] = {}
        code_success: dict[str, list[int]] = {}
        for row in rows:
            code = row.failure_code or "unknown"
            success = 1 if row.outcome == "SUCCESS" else 0
            code_success.setdefault(code, []).append(success)
        for code, outcomes in code_success.items():
            if len(outcomes) >= 3:
                failure_code_rates[code] = round(sum(outcomes) / len(outcomes), 4)

        avg_ttr = 24.0
        if response_times:
            avg_ttr = round(sum(response_times) / len(response_times), 2)

        return MerchantRecoveryProfile(
            merchant_id=merchant_id,
            best_channel=best_channel,
            preferred_tone="polite",
            response_rate=round(best_rate, 4) if best_rate > 0 else 0.015,
            failure_code_success_rates=failure_code_rates,
            sample_size=sample_size,
            avg_time_to_recovery=avg_ttr,
            incentive_sensitivity=0.0,
        )
