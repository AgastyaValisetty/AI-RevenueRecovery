"""PromiseTracker — promise-to-pay lifecycle management.

When a customer promises to pay, the promise becomes a first-class object:
  - Promise amount, due date, source, and confidence.
  - Reminder scheduled shortly before the promised time.
  - Reconciliation against successful payments.
  - No repeated chase while a valid promise is active.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from ...database import Database
from ...schema import PromiseToPayRow, PaymentIntentRow

logger = logging.getLogger(__name__)

# Grace period after a promise is due — still not chasing
PROMISE_GRACE_HOURS = 12

# Reminder window before promise is due
PROMISE_REMINDER_HOURS = 2


@dataclass(frozen=True)
class PromiseToPay:
    """A recorded promise-to-pay record."""

    promise_id: UUID
    case_id: UUID
    person_id: UUID
    amount: Decimal
    due_at: datetime
    source: str  # "SIMULATED_RESPONSE", "API", "CHAT"
    confidence: float  # 0–1
    status: str  # "ACTIVE", "FULFILLED", "MISSED", "CANCELLED"
    created_at: datetime
    fulfilled_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    @property
    def is_fulfilled_or_expired(self) -> bool:
        if self.status in ("FULFILLED", "CANCELLED"):
            return True
        # Active but past due + grace period
        now = _utcnow()
        return self.status == "ACTIVE" and now > self.due_at + timedelta(hours=PROMISE_GRACE_HOURS)

    @property
    def is_in_grace_period(self) -> bool:
        """True if the promise is past its due date but still in grace window."""
        if self.status != "ACTIVE":
            return False
        now = _utcnow()
        return now <= self.due_at + timedelta(hours=PROMISE_GRACE_HOURS)

    @property
    def reminder_time(self) -> datetime:
        """When to schedule a reminder (before the promise is due)."""
        return self.due_at - timedelta(hours=PROMISE_REMINDER_HOURS)


class PromiseTracker:
    """Manages the promise-to-pay lifecycle.

    Parameters
    ----------
    db :
        Database connection for persistence.
    """

    def __init__(self, db: Database):
        self._db = db

    def create_promise(
        self,
        *,
        case_id: UUID,
        person_id: UUID,
        amount: Decimal,
        due_at: datetime,
        source: str = "SIMULATED_RESPONSE",
        confidence: float = 1.0,
    ) -> PromiseToPay:
        """Record a new promise-to-pay.

        If an existing active promise exists for the same person, it is
        superseded (marked CANCELLED).
        """
        now_ts = _utcnow()

        # Cancel any existing active promise for this person
        self._cancel_existing_active(person_id, exclude=None)

        promise = PromiseToPay(
            promise_id=uuid4(),
            case_id=case_id,
            person_id=person_id,
            amount=amount,
            due_at=due_at,
            source=source,
            confidence=confidence,
            status="ACTIVE",
            created_at=now_ts,
        )

        with self._db.session() as session:
            row = PromiseToPayRow(
                promise_id=promise.promise_id,
                case_id=promise.case_id,
                person_id=promise.person_id,
                amount=promise.amount,
                due_at=promise.due_at,
                source=promise.source,
                confidence=promise.confidence,
                status=promise.status,
                created_at=promise.created_at,
                fulfilled_at=None,
            )
            session.add(row)

        logger.info(
            "Promise-to-pay created: promise_id=%s person=%s amount=%s due_at=%s",
            promise.promise_id,
            person_id,
            amount,
            due_at,
        )
        return promise

    def check_active_promise(self, person_id: UUID) -> Optional[PromiseToPay]:
        """Check if the customer has an active (non-expired) promise.

        Returns the promise if one exists and is still active, None otherwise.
        """
        from sqlalchemy import select

        now_utc = _utcnow()

        with self._db.session() as session:
            row = session.scalars(
                select(PromiseToPayRow)
                .where(
                    PromiseToPayRow.person_id == person_id,
                    PromiseToPayRow.status == "ACTIVE",
                    PromiseToPayRow.due_at > now_utc,
                )
                .order_by(PromiseToPayRow.created_at.desc())
                .limit(1)
            ).first()

        if row is None:
            return None

        return self._row_to_promise(row)

    def get_promises_for_reminder(
        self, current_time: Optional[datetime] = None
    ) -> list[PromiseToPay]:
        """Return active promises where a reminder should be sent.

        Reminder is scheduled PROMISE_REMINDER_HOURS before the due date.
        """
        from sqlalchemy import select

        if current_time is None:
            current_time = _utcnow()

        reminder_before = current_time + timedelta(hours=PROMISE_REMINDER_HOURS)

        with self._db.session() as session:
            rows = session.scalars(
                select(PromiseToPayRow)
                .where(
                    PromiseToPayRow.status == "ACTIVE",
                    PromiseToPayRow.due_at <= reminder_before,
                    PromiseToPayRow.due_at > current_time,
                )
                .order_by(PromiseToPayRow.due_at.asc())
            ).all()

        return [self._row_to_promise(r) for r in rows]

    def fulfill_promise(
        self, promise_id: UUID, payment_intent_id: UUID
    ) -> bool:
        """Mark a promise as fulfilled if the payment was successful.

        Returns True if the promise was found and fulfilled.
        """
        with self._db.session() as session:
            row = session.get(PromiseToPayRow, promise_id)
            if row is None or row.status != "ACTIVE":
                return False

            # Verify the payment was settled
            intent = session.get(PaymentIntentRow, payment_intent_id)
            if intent is None or intent.status != "SETTLED":
                return False

            # Check amount matches
            if intent.amount >= row.amount:
                row.status = "FULFILLED"
                row.fulfilled_at = _utcnow()
                logger.info(
                    "Promise %s fulfilled by payment intent %s",
                    promise_id,
                    payment_intent_id,
                )
                return True
            return False

    def reconcile(
        self, person_id: UUID, amount: Decimal, payment_intent_id: Optional[UUID] = None
    ) -> Optional[PromiseToPay]:
        """Check if a successful payment matches an active promise for this person.

        If a promise exists for this person and the payment amount matches
        (or exceeds) the promised amount, the promise is fulfilled.
        """
        from sqlalchemy import select

        with self._db.session() as session:
            row = session.scalars(
                select(PromiseToPayRow)
                .where(
                    PromiseToPayRow.person_id == person_id,
                    PromiseToPayRow.status == "ACTIVE",
                )
                .order_by(PromiseToPayRow.created_at.desc())
                .limit(1)
            ).first()

        if row is None:
            return None

        promise = self._row_to_promise(row)
        if promise.amount <= amount:
            # Fulfill the promise.  If we have a payment_intent_id, link it.
            if payment_intent_id is not None and payment_intent_id.int != 0:
                self.fulfill_promise(promise.promise_id, payment_intent_id)
            else:
                # Direct mark as fulfilled — caller verified the payment
                with self._db.session() as session:
                    row_to_update = session.get(PromiseToPayRow, promise.promise_id)
                    if row_to_update and row_to_update.status == "ACTIVE":
                        row_to_update.status = "FULFILLED"
                        row_to_update.fulfilled_at = _utcnow()
            return promise

        return promise  # promise still active, not yet fulfilled

    def cancel_promise(self, promise_id: UUID, reason: str = "manual") -> bool:
        """Cancel a promise (e.g., customer declined, case stopped)."""
        with self._db.session() as session:
            row = session.get(PromiseToPayRow, promise_id)
            if row is None or row.status != "ACTIVE":
                return False
            row.status = "CANCELLED"
        logger.info("Promise %s cancelled: %s", promise_id, reason)
        return True

    def get_missed_promises(
        self, current_time: Optional[datetime] = None
    ) -> list[PromiseToPay]:
        """Return promises that were active but have now expired past grace period."""
        from sqlalchemy import select

        if current_time is None:
            current_time = _utcnow()

        grace_cutoff = current_time - timedelta(hours=PROMISE_GRACE_HOURS)

        with self._db.session() as session:
            rows = list(session.scalars(
                select(PromiseToPayRow)
                .where(
                    PromiseToPayRow.status == "ACTIVE",
                    PromiseToPayRow.due_at <= grace_cutoff,
                )
            ))
            # Update their status to MISSED
            result: list[PromiseToPay] = []
            for r in rows:
                r.status = "MISSED"
                result.append(self._row_to_promise(r))

        return result

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _cancel_existing_active(self, person_id: UUID, exclude: Optional[UUID]) -> None:
        """Cancel any existing active promise for this person (supersession)."""
        from sqlalchemy import update

        stmt = (
            update(PromiseToPayRow)
            .where(
                PromiseToPayRow.person_id == person_id,
                PromiseToPayRow.status == "ACTIVE",
            )
            .values(status="CANCELLED")
        )
        if exclude is not None:
            stmt = stmt.where(PromiseToPayRow.promise_id != exclude)
        with self._db.session() as session:
            session.execute(stmt)

    @staticmethod
    def _row_to_promise(row: PromiseToPayRow) -> PromiseToPay:
        return PromiseToPay(
            promise_id=row.promise_id,
            case_id=row.case_id,
            person_id=row.person_id,
            amount=row.amount,
            due_at=row.due_at,
            source=row.source,
            confidence=row.confidence,
            status=row.status,
            created_at=row.created_at,
            fulfilled_at=row.fulfilled_at,
        )


def _utcnow() -> datetime:
    """Return current UTC time (used for promise lifecycle timestamps)."""
    return datetime.now(timezone.utc)
