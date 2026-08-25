"""LazerPay repository — payment attempt persistence.

This service owns the ``idempotency_keys`` table and shares
the ``payment_attempts`` and ``ledger_entries`` tables with
the People Service.
"""
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy import Table, Column, String, DateTime, Text, Integer, Numeric, MetaData
from sqlalchemy import ForeignKey as SAF

from .database import Database
from .domain import PaymentAttempt, BankAuthorizationResult
from .schema import PaymentAttemptRow, IdempotencyKeyRow


def now() -> datetime:
    return datetime.now(timezone.utc)


class LazerPayRepository:
    def __init__(self, db: Database):
        self._db = db

    # ------------------------------------------------------------------
    # PaymentAttempt persistence
    # ------------------------------------------------------------------

    def create_attempt(self, attempt: PaymentAttemptRow) -> None:
        with self._db.session() as session:
            session.add(attempt)

    def find_by_idempotency_key(self, key: str) -> PaymentAttemptRow | None:
        with self._db.session() as session:
            row = session.scalar(
                select(PaymentAttemptRow).where(
                    PaymentAttemptRow.idempotency_key == key
                )
            )
            return row

    def find_by_attempt_id(self, attempt_id: str) -> PaymentAttemptRow | None:
        with self._db.session() as session:
            row = session.get(PaymentAttemptRow, attempt_id)
            return row

    def find_pending(self) -> list[PaymentAttemptRow]:
        with self._db.session() as session:
            rows = session.scalars(
                select(PaymentAttemptRow).where(
                    PaymentAttemptRow.status.in_(["INITIATED", "ROUTING", "AUTHORIZED"])
                )
            ).all()
            return list(rows)

    def find_by_status(self, status: str) -> list[PaymentAttemptRow]:
        with self._db.session() as session:
            rows = session.scalars(
                select(PaymentAttemptRow).where(PaymentAttemptRow.status == status)
            ).all()
            return list(rows)

    def find_by_intent(self, intent_id: str) -> list[PaymentAttemptRow]:
        """Return all attempts for a given payment intent, ordered by attempt_number."""
        with self._db.session() as session:
            rows = session.scalars(
                select(PaymentAttemptRow)
                .where(PaymentAttemptRow.intent_id == intent_id)
                .order_by(PaymentAttemptRow.attempt_number.asc())
            ).all()
            return list(rows)

    def update_attempt(
        self,
        attempt_id: str,
        *,
        status: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        initiated_at: datetime | None = None,
        routed_at: datetime | None = None,
        authorized_at: datetime | None = None,
        settled_at: datetime | None = None,
        failed_at: datetime | None = None,
        unknown_at: datetime | None = None,
        bank_response_time_ms: int | None = None,
        gateway_latency_ms: int | None = None,
        bank_state: str | None = None,
        simulation_timestamp: datetime | None = None,
        correlation_id: str | None = None,
        related_attempt_id: str | None = None,
    ) -> None:
        """Update selected fields on a payment attempt."""
        with self._db.session() as session:
            stmt = (
                update(PaymentAttemptRow)
                .where(PaymentAttemptRow.attempt_id == attempt_id)
            )
            values: dict = {}
            if status is not None:
                values["status"] = status
            if failure_code is not None:
                values["failure_code"] = failure_code
            if failure_reason is not None:
                values["failure_reason"] = failure_reason
            if initiated_at is not None:
                values["initiated_at"] = initiated_at
            if routed_at is not None:
                values["routed_at"] = routed_at
            if authorized_at is not None:
                values["authorized_at"] = authorized_at
            if settled_at is not None:
                values["settled_at"] = settled_at
            if failed_at is not None:
                values["failed_at"] = failed_at
            if unknown_at is not None:
                values["unknown_at"] = unknown_at
            if bank_response_time_ms is not None:
                values["bank_response_time_ms"] = bank_response_time_ms
            if gateway_latency_ms is not None:
                values["gateway_latency_ms"] = gateway_latency_ms
            if bank_state is not None:
                values["bank_state"] = bank_state
            if simulation_timestamp is not None:
                values["simulation_timestamp"] = simulation_timestamp
            if correlation_id is not None:
                values["correlation_id"] = correlation_id
            if related_attempt_id is not None:
                values["related_attempt_id"] = related_attempt_id
            if values:
                session.execute(stmt.values(**values))

    def to_domain(self, row: PaymentAttemptRow) -> PaymentAttempt:
        """Convert an ORM row to the domain model."""
        return PaymentAttempt(
            attempt_id=row.attempt_id,
            intent_id=row.intent_id,
            attempt_number=row.attempt_number,
            person_id=row.person_id,
            merchant_id=row.merchant_id,
            amount=row.amount,
            payment_method=row.payment_method,
            source_account_id=row.source_account_id,
            destination_account_id=row.destination_account_id,
            status=row.status,
            idempotency_key=row.idempotency_key,
            failure_code=row.failure_code,
            failure_reason=row.failure_reason,
            related_attempt_id=row.related_attempt_id,
            initiated_at=row.initiated_at,
            routed_at=row.routed_at,
            authorized_at=row.authorized_at,
            settled_at=row.settled_at,
            failed_at=row.failed_at,
            unknown_at=row.unknown_at,
            bank_response_time_ms=row.bank_response_time_ms,
            gateway_latency_ms=row.gateway_latency_ms,
            bank_state=row.bank_state,
            simulation_timestamp=row.simulation_timestamp,
            correlation_id=row.correlation_id,
            retry_for_attempt_id=row.retry_for_attempt_id,
            created_at=row.created_at,
        )

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def record_idempotency_key(self, key: str, attempt_id: str) -> None:
        with self._db.session() as session:
            session.add(
                IdempotencyKeyRow(
                    key=key,
                    attempt_id=attempt_id,
                    created_at=now(),
                )
            )

    def clear_idempotency_key(self, key: str) -> None:
        """Delete a stale idempotency key (e.g. for a failed/retried attempt)."""
        with self._db.session() as session:
            session.execute(
                delete(IdempotencyKeyRow).where(
                    IdempotencyKeyRow.key == key
                )
            )

    # ------------------------------------------------------------------
    # Ledger entries (shared with People Service)
    # ------------------------------------------------------------------

    def write_ledger_entry(
        self,
        *,
        event_type: str,
        from_account_id: str | None,
        to_account_id: str | None,
        amount: Decimal,
        simulation_timestamp: datetime,
        related_attempt_id: str | None = None,
        metadata_json: dict | None = None,
    ) -> None:
        """Write a ledger entry via the shared ledger_entries table.

        Uses Core Table access since the table is defined in people_service.
        """
        metadata = metadata_json or {}
        with self._db.session() as session:
            from .schema import BASE
            # Use a Core Table reflected from the existing schema
            # (the ledger_entries table is created by People Service)
            ledger_table = Table(
                "ledger_entries",
                BASE.metadata,
                autoload_with=self._db._engine,
            )
            from uuid import uuid4
            session.execute(
                ledger_table.insert().values(
                    entry_id=str(uuid4()),
                    event_type=event_type,
                    from_account_id=from_account_id,
                    to_account_id=to_account_id,
                    amount=amount,
                    simulation_timestamp=simulation_timestamp,
                    related_attempt_id=related_attempt_id,
                    related_subscription_id=None,
                    metadata_json=json.dumps(metadata),
                    created_at=now(),
                )
            )
