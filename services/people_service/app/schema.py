from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BankRow(Base):
    __tablename__ = "banks"

    bank_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    authorization_success_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    timeout_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    issuer_decline_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    network_error_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    current_state: Mapped[str] = mapped_column(String(32))
    state_multipliers_json: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PersonRow(Base):
    __tablename__ = "persons"

    person_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    age: Mapped[int] = mapped_column(Integer)
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    salary_deposit_day: Mapped[int] = mapped_column(Integer)
    spending_profile_category: Mapped[str] = mapped_column(String(64))
    spending_profile_json: Mapped[dict] = mapped_column(JSONB)
    payment_preferences_json: Mapped[dict] = mapped_column(JSONB)
    primary_bank_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("banks.bank_id")
    )
    primary_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "bank_accounts.account_id",
            name="fk_persons_primary_account_id",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BankAccountRow(Base):
    __tablename__ = "bank_accounts"

    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "persons.person_id",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    bank_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("banks.bank_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MerchantRow(Base):
    __tablename__ = "merchants"

    merchant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    merchant_type: Mapped[str] = mapped_column(String(32))
    settlement_bank_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("banks.bank_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProductRow(Base):
    __tablename__ = "products"

    product_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.merchant_id")
    )
    name: Mapped[str] = mapped_column(String(128))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    product_type: Mapped[str] = mapped_column(String(32))
    billing_cycle: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubscriptionRow(Base):
    __tablename__ = "subscriptions"

    subscription_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("persons.person_id")
    )
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.merchant_id")
    )
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("products.product_id")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    billing_cycle: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    next_billing_date: Mapped[date] = mapped_column(Date)
    last_successful_payment_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PaymentIntentRow(Base):
    __tablename__ = "payment_intents"

    intent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("persons.person_id")
    )
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.merchant_id")
    )
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("products.product_id")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    related_subscription_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("subscriptions.subscription_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentAttemptRow(Base):
    __tablename__ = "payment_attempts"

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payment_intents.intent_id")
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    person_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("persons.person_id")
    )
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.merchant_id")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(32))
    source_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bank_accounts.account_id")
    )
    destination_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bank_accounts.account_id")
    )
    status: Mapped[str] = mapped_column(String(32))
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    initiated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bank_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gateway_processing_time_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerEntryRow(Base):
    __tablename__ = "ledger_entries"

    entry_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32))
    from_account_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bank_accounts.account_id"), nullable=True
    )
    to_account_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bank_accounts.account_id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    related_attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("payment_attempts.attempt_id"), nullable=True
    )
    related_subscription_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("subscriptions.subscription_id"),
        nullable=True,
    )
    simulation_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class RecoveryActionRow(Base):
    __tablename__ = "recovery_actions"

    action_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    related_attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("payment_attempts.attempt_id")
    )
    action_type: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    expected_recovery: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_subscriptions_next_billing_date", SubscriptionRow.next_billing_date)
Index("ix_payment_intents_status", PaymentIntentRow.status)
Index("ix_payment_attempts_status", PaymentAttemptRow.status)
Index("ix_payment_attempts_failure_code", PaymentAttemptRow.failure_code)
Index("ix_ledger_entries_event_type", LedgerEntryRow.event_type)
Index("ix_ledger_entries_simulation_timestamp", LedgerEntryRow.simulation_timestamp)
Index("ix_ledger_entries_from_account_id", LedgerEntryRow.from_account_id)
Index("ix_ledger_entries_to_account_id", LedgerEntryRow.to_account_id)


