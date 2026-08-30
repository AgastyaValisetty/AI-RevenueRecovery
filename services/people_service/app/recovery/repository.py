"""RecoveryActionRepository — persistence for recovery action records.

Follows the same pattern as the other repositories in repositories.py:
SQLAlchemy ORM rows with session-scoped transactions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func, and_

from ..database import Database
from ..schema import RecoveryActionRow
from .domain import RecoveryAction, RecoveryActionType, RecoveryOutcome

logger = logging.getLogger(__name__)


def _action_to_row(action: RecoveryAction) -> RecoveryActionRow:
    """Map a RecoveryAction dataclass to its ORM row."""
    return RecoveryActionRow(
        action_id=action.action_id,
        run_id=action.run_id,
        related_attempt_id=action.related_attempt_id,
        payment_intent_id=action.payment_intent_id,
        retry_number=action.retry_number,
        action_type=action.action_type.value,
        reason=action.reason,
        schedule_reason=action.schedule_reason,
        scheduled_for=action.scheduled_for,
        executed_at=action.executed_at,
        outcome=action.outcome.value if action.outcome else None,
        cost=action.cost,
        expected_recovery=action.expected_recovery,
        amount=action.amount,
        payment_method=action.payment_method,
        failure_code=action.failure_code,
        failure_reason=action.failure_reason,
        retry_attempt_id=action.retry_attempt_id,
        customer_declined=action.customer_declined,
        metadata_json=action.metadata_json,
        created_at=action.created_at,
    )


def _action_from_row(row: RecoveryActionRow) -> RecoveryAction:
    """Map an ORM row to a RecoveryAction dataclass."""
    return RecoveryAction(
        action_id=row.action_id,
        run_id=row.run_id,
        related_attempt_id=row.related_attempt_id,
        payment_intent_id=row.payment_intent_id,
        retry_number=row.retry_number,
        action_type=RecoveryActionType(row.action_type),
        reason=row.reason,
        schedule_reason=row.schedule_reason,
        scheduled_for=row.scheduled_for,
        executed_at=row.executed_at,
        outcome=RecoveryOutcome(row.outcome) if row.outcome else None,
        cost=row.cost,
        expected_recovery=row.expected_recovery,
        amount=row.amount,
        payment_method=row.payment_method,
        failure_code=row.failure_code,
        failure_reason=row.failure_reason,
        retry_attempt_id=row.retry_attempt_id,
        customer_declined=row.customer_declined,
        metadata_json=row.metadata_json or {},
        created_at=row.created_at,
    )


class RecoveryActionRepository:
    """Repository for RecoveryAction persistence."""

    def __init__(self, db: Database):
        self._db = db

    def add(self, action: RecoveryAction) -> RecoveryAction:
        """Insert a new recovery action record."""
        with self._db.session() as session:
            session.add(_action_to_row(action))
        return action

    def add_many(self, actions: list[RecoveryAction]) -> None:
        """Insert multiple recovery action records."""
        if not actions:
            return
        with self._db.session() as session:
            session.add_all([_action_to_row(a) for a in actions])

    def find(self, action_id: UUID) -> RecoveryAction | None:
        with self._db.session() as session:
            row = session.get(RecoveryActionRow, action_id)
            return _action_from_row(row) if row else None

    def find_by_intent_id(self, intent_id: UUID) -> list[RecoveryAction]:
        """Return all recovery actions for a given payment intent, chronological."""
        with self._db.session() as session:
            rows = session.scalars(
                select(RecoveryActionRow)
                .where(RecoveryActionRow.payment_intent_id == intent_id)
                .order_by(RecoveryActionRow.created_at.asc())
            ).all()
            return [_action_from_row(r) for r in rows]

    def find_by_intent_ids(self, intent_ids: list[UUID]) -> dict[UUID, list[RecoveryAction]]:
        """Batch-fetch recovery actions for multiple intents in a single query.

        Returns a dict mapping intent_id → list of actions (chronological).
        Intents with no actions are absent from the dict.
        """
        if not intent_ids:
            return {}
        with self._db.session() as session:
            rows = session.scalars(
                select(RecoveryActionRow)
                .where(RecoveryActionRow.payment_intent_id.in_(intent_ids))
                .order_by(RecoveryActionRow.created_at.asc())
            ).all()
            result: dict[UUID, list[RecoveryAction]] = {}
            for row in rows:
                intent_id = row.payment_intent_id
                if intent_id is not None:
                    result.setdefault(intent_id, []).append(_action_from_row(row))
            return result

    def find_by_run_id(self, run_id: UUID) -> list[RecoveryAction]:
        """Return all recovery actions for a given simulation run."""
        with self._db.session() as session:
            rows = session.scalars(
                select(RecoveryActionRow)
                .where(RecoveryActionRow.run_id == run_id)
                .order_by(RecoveryActionRow.created_at.asc())
            ).all()
            return [_action_from_row(r) for r in rows]

    def find_all(
        self,
        limit: int = 500,
        outcome: Optional[str] = None,
        action_type: Optional[str] = None,
    ) -> list[RecoveryAction]:
        """Return recovery actions, optionally filtered by outcome or action type."""
        with self._db.session() as session:
            stmt = select(RecoveryActionRow).order_by(RecoveryActionRow.created_at.desc())
            if outcome is not None:
                stmt = stmt.where(RecoveryActionRow.outcome == outcome)
            if action_type is not None:
                stmt = stmt.where(RecoveryActionRow.action_type == action_type)
            stmt = stmt.limit(limit)
            rows = session.scalars(stmt).all()
            return [_action_from_row(r) for r in rows]

    def find_scheduled_for_execution(
        self, current_time: datetime
    ) -> list[RecoveryAction]:
        """Return recovery actions that are scheduled and not yet executed."""
        with self._db.session() as session:
            rows = session.scalars(
                select(RecoveryActionRow)
                .where(
                    RecoveryActionRow.action_type.in_(
                        [
                            RecoveryActionType.RETRY.value,
                            RecoveryActionType.SEND_PAYMENT_LINK.value,
                            RecoveryActionType.SEND_NOTIFICATION.value,
                        ]
                    ),
                    RecoveryActionRow.scheduled_for <= current_time,
                    RecoveryActionRow.executed_at.is_(None),
                )
                .order_by(RecoveryActionRow.scheduled_for.asc())
            ).all()
            return [_action_from_row(r) for r in rows]

    def has_been_retryed_for_intent(
        self, intent_id: UUID, attempt_id: Optional[str]
    ) -> bool:
        """Check if a retry has already been scheduled for this intent + attempt.

        Prevents duplicate recovery actions for the same failed attempt.
        """
        with self._db.session() as session:
            stmt = (
                select(func.count())
                .select_from(RecoveryActionRow)
                .where(
                    RecoveryActionRow.payment_intent_id == intent_id,
                    RecoveryActionRow.action_type == RecoveryActionType.RETRY.value,
                )
            )
            if attempt_id is not None:
                stmt = stmt.where(
                    RecoveryActionRow.related_attempt_id == attempt_id
                )
            count = session.scalar(stmt)
            return (count or 0) > 0

    def has_customer_declined(self, intent_id: UUID) -> bool:
        """Check if the customer has previously declined a recovery for this intent."""
        with self._db.session() as session:
            count = session.scalar(
                select(func.count())
                .select_from(RecoveryActionRow)
                .where(
                    RecoveryActionRow.payment_intent_id == intent_id,
                    RecoveryActionRow.action_type == RecoveryActionType.STOP.value,
                    RecoveryActionRow.customer_declined.is_(True),
                )
            )
            return (count or 0) > 0

    def max_retry_number(self, intent_id: UUID) -> Optional[int]:
        """Return the highest retry_number for this intent, or None if none."""
        with self._db.session() as session:
            max_retry = session.scalar(
                select(func.max(RecoveryActionRow.retry_number))
                .where(
                    RecoveryActionRow.payment_intent_id == intent_id,
                    RecoveryActionRow.action_type == RecoveryActionType.RETRY.value,
                )
            )
            return max_retry

    def save(self, action: RecoveryAction) -> None:
        """Update an existing recovery action (e.g., set executed_at / outcome)."""
        with self._db.session() as session:
            row = session.get(RecoveryActionRow, action.action_id)
            if row is None:
                logger.warning("Update for non-existent RecoveryAction: %s", action.action_id)
                return
            row.scheduled_for = action.scheduled_for
            row.executed_at = action.executed_at
            row.outcome = action.outcome.value if action.outcome else None
            row.retry_attempt_id = action.retry_attempt_id
            row.customer_declined = action.customer_declined
            row.metadata_json = action.metadata_json

    def count(self) -> int:
        with self._db.session() as session:
            return session.scalar(
                select(func.count()).select_from(RecoveryActionRow)
            )

    def count_by_outcome(self) -> dict[str, int]:
        """Return {outcome: count} for all recovery actions with a set outcome."""
        with self._db.session() as session:
            rows = session.execute(
                select(
                    RecoveryActionRow.outcome,
                    func.count().label("count"),
                )
                .where(RecoveryActionRow.outcome.is_not(None))
                .group_by(RecoveryActionRow.outcome)
            ).all()
            return {row.outcome: row.count for row in rows}
