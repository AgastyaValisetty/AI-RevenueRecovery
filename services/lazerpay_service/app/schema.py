"""LazerPay Service database schema.

The ``payment_attempts`` table is shared with the People Service
(which creates it in its own schema).  This module defines an ORM
class that is compatible with that shared table so LazerPay can
read and write attempt records.

The ``idempotency_keys`` table is owned by LazerPay.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BASE(DeclarativeBase):
    pass


class PaymentAttemptRow(BASE):
    """Payment attempts table tracking all transaction attempts.

    Mirrors people_service.app.schema.PaymentAttemptRow so both
    services can read and write the same table.
    """
    __tablename__ = "payment_attempts"
    __table_args__ = {"extend_existing": True}

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    person_id: Mapped[str] = mapped_column(String(64), index=True)
    merchant_id: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    payment_method: Mapped[str] = mapped_column(String(32))
    source_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("payment_attempts.attempt_id"), nullable=True
    )
    initiated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    routed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unknown_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bank_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gateway_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bank_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    simulation_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    retry_for_attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("payment_attempts.attempt_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyKeyRow(BASE):
    """Idempotency key tracking to prevent double-processing."""
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_payment_attempts_status", PaymentAttemptRow.status)
Index("ix_payment_attempts_intent_id", PaymentAttemptRow.intent_id)
Index("ix_payment_attempts_idempotency_key", PaymentAttemptRow.idempotency_key)
Index("ix_payment_attempts_correlation_id", PaymentAttemptRow.correlation_id)
