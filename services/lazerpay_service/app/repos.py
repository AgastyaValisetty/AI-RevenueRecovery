from datetime import datetime, timezone

from sqlalchemy import func, select, update
from .database import Database
from .schema import PaymentAttemptRow, IdempotencyKeyRow


class LazerPayRepository:
    def __init__(self, db: Database):
        self._db = db

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
        from .schema import PaymentAttemptRow as PAR
        with self._db.session() as session:
            row = session.get(PAR, attempt_id)
            return row

    def find_pending(self) -> list[PaymentAttemptRow]:
        with self._db.session() as session:
            rows = session.scalars(
                select(PaymentAttemptRow).where(PaymentAttemptRow.status == "PENDING")
            ).all()
            return list(rows)

    def find_by_status(self, status: str) -> list[PaymentAttemptRow]:
        with self._db.session() as session:
            rows = session.scalars(
                select(PaymentAttemptRow).where(PaymentAttemptRow.status == status)
            ).all()
            return list(rows)

    def update_attempt_status(
        self,
        attempt_id: str,
        status: str,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        authorized_at: datetime | None = None,
        settled_at: datetime | None = None,
        gateway_processing_time_ms: int | None = None,
    ) -> None:
        with self._db.session() as session:
            session.execute(
                update(PaymentAttemptRow)
                .where(PaymentAttemptRow.attempt_id == attempt_id)
                .values(
                    status=status,
                    failure_code=failure_code,
                    failure_reason=failure_reason,
                    authorized_at=authorized_at,
                    settled_at=settled_at,
                    gateway_processing_time_ms=gateway_processing_time_ms,
                )
            )

    def record_idempotency_key(self, key: str, attempt_id: str) -> None:
        with self._db.session() as session:
            session.add(
                IdempotencyKeyRow(
                    key=key,
                    attempt_id=attempt_id,
                    created_at=datetime.now(timezone.utc),
                )
            )

    def get_attempt(self, attempt_id: str) -> dict | None:
        with self._db.session() as session:
            row = session.get(PaymentAttemptRow, attempt_id)
            if row is None:
                return None
            return {
                "attempt_id": row.attempt_id,
                "intent_id": row.intent_id,
                "attempt_number": row.attempt_number,
                "person_id": row.person_id,
                "merchant_id": row.merchant_id,
                "amount": float(row.amount) if row.amount else 0.0,
                "payment_method": row.payment_method,
                "source_account_id": row.source_account_id,
                "destination_account_id": row.destination_account_id,
                "status": row.status,
                "failure_code": row.failure_code,
                "failure_reason": row.failure_reason,
                "initiated_at": row.initiated_at.isoformat() if row.initiated_at else None,
                "authorized_at": row.authorized_at.isoformat() if row.authorized_at else None,
                "settled_at": row.settled_at.isoformat() if row.settled_at else None,
                "gateway_processing_time_ms": row.gateway_processing_time_ms,
            }