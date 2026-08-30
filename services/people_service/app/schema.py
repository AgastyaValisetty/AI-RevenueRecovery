from datetime import date, datetime
from decimal import Decimal
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Use a portable JSON type: JSONB for PostgreSQL, JSON for SQLite
class PortableJSON(TypeDecorator):
    """JSON type that uses JSONB on PostgreSQL, JSON on SQLite."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class UUID(TypeDecorator):
    """Universal UUID type — works with both PostgreSQL and SQLite."""

    impl = String
    cache_ok = True

    def __init__(self, *args, **kwargs):
        kwargs.pop("as_uuid", None)
        super().__init__(length=36)

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return PyUUID(value)


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #

class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #

class BankRow(Base):
    __tablename__ = "banks"

    bank_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    authorization_success_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    timeout_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    issuer_decline_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    network_error_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    current_state: Mapped[str] = mapped_column(String(32))
    state_multipliers_json: Mapped[dict] = mapped_column(PortableJSON)
    # Settlement accounts are created by the Bank Service and use a
    # non-UUID id (e.g. "settlement-<hex12>"), so this shared column must be
    # mapped as a string to match the Bank Service's declaration.
    settlement_account_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PersonRow(Base):
    __tablename__ = "persons"

    person_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    age: Mapped[int] = mapped_column(Integer)
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    salary_deposit_day: Mapped[int] = mapped_column(Integer)
    salary_deposit_hour: Mapped[int] = mapped_column(Integer, default=9)
    spending_profile_category: Mapped[str] = mapped_column(String(64))
    spending_profile_json: Mapped[dict] = mapped_column(PortableJSON)
    payment_preferences_json: Mapped[dict] = mapped_column(PortableJSON)
    income_bracket: Mapped[str] = mapped_column(String(32))
    age_group: Mapped[str] = mapped_column(String(32))
    employment_type: Mapped[str] = mapped_column(String(32))
    primary_bank_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("banks.bank_id")
    )
    primary_account_id: Mapped[PyUUID] = mapped_column(
        UUID(),
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

    account_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    person_id: Mapped[PyUUID | None] = mapped_column(
        UUID(),
        ForeignKey(
            "persons.person_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    bank_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("banks.bank_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MerchantRow(Base):
    __tablename__ = "merchants"

    merchant_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    merchant_type: Mapped[str] = mapped_column(String(32))
    settlement_bank_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("banks.bank_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProductRow(Base):
    __tablename__ = "products"

    product_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    merchant_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("merchants.merchant_id")
    )
    name: Mapped[str] = mapped_column(String(128))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    product_type: Mapped[str] = mapped_column(String(32))
    billing_cycle: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubscriptionRow(Base):
    __tablename__ = "subscriptions"

    subscription_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    person_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("persons.person_id")
    )
    merchant_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("merchants.merchant_id")
    )
    product_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("products.product_id")
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

    intent_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    person_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("persons.person_id")
    )
    merchant_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("merchants.merchant_id")
    )
    product_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("products.product_id")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    related_subscription_id: Mapped[PyUUID | None] = mapped_column(
        UUID(), ForeignKey("subscriptions.subscription_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentAttemptRow(Base):
    __tablename__ = "payment_attempts"

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("payment_intents.intent_id")
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    person_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("persons.person_id")
    )
    merchant_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("merchants.merchant_id")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(32))
    source_account_id: Mapped[PyUUID | None] = mapped_column(
        UUID(), ForeignKey("bank_accounts.account_id"), nullable=True
    )
    destination_account_id: Mapped[PyUUID | None] = mapped_column(
        UUID(), ForeignKey("bank_accounts.account_id"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
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
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    retry_for_attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("payment_attempts.attempt_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerEntryRow(Base):
    __tablename__ = "ledger_entries"

    entry_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32))
    from_account_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    to_account_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    related_attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("payment_attempts.attempt_id"), nullable=True
    )
    related_subscription_id: Mapped[PyUUID | None] = mapped_column(
        UUID(),
        ForeignKey("subscriptions.subscription_id"),
        nullable=True,
    )
    simulation_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(PortableJSON, default=dict)


class RecoveryActionRow(Base):
    __tablename__ = "recovery_actions"

    action_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    run_id: Mapped[PyUUID | None] = mapped_column(
        UUID(), ForeignKey("simulation_runs.run_id"), nullable=True
    )
    # The original failed payment attempt (LazerPay) — nullable because
    # some intents are settled inline and don't produce a payment attempt.
    related_attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("payment_attempts.attempt_id"), nullable=True
    )
    # The payment intent that failed (People Service).
    payment_intent_id: Mapped[PyUUID | None] = mapped_column(
        UUID(), ForeignKey("payment_intents.intent_id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # The retry number (1 = first retry, 2 = second, 3 = third).
    retry_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Amount of the original failed payment.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Payment method of the original attempt.
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Failure info from the original failed attempt.
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The attempt_id returned by LazerPay for this retry.
    retry_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Whether the customer explicitly declined a recovery link/notification.
    customer_declined: Mapped[bool] = mapped_column(Boolean, default=False)
    # Flexible metadata (bank_state, failure_timestamp, etc.).
    metadata_json: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SimulationRunRow(Base):
    """Record of a single simulation execution."""
    __tablename__ = "simulation_runs"

    run_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    seed: Mapped[int] = mapped_column(Integer)
    config_snapshot: Mapped[dict] = mapped_column(PortableJSON)
    people_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hours_run: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
Index("ix_recovery_actions_attempt_id", RecoveryActionRow.related_attempt_id)
Index("ix_recovery_actions_intent_id", RecoveryActionRow.payment_intent_id)
Index("ix_recovery_actions_outcome", RecoveryActionRow.outcome)
Index("ix_recovery_actions_scheduled_for", RecoveryActionRow.scheduled_for)


# --------------------------------------------------------------------------- #
# Smart Agent tables
# --------------------------------------------------------------------------- #

class CustomerRecoveryMemoryRow(Base):
    """Structured per-customer recovery memory for the Smart Agent.

    Tracks channel/language preferences, contact fatigue, consent status,
    and the last interaction — used by ``memory.py`` to drive
    next-best-contact decisions.
    """

    __tablename__ = "customer_recovery_memory"

    person_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("persons.person_id"), primary_key=True
    )
    preferred_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # JSON e.g. {"start_hour": 18, "end_hour": 22} for best contact window
    best_contact_window: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    fatigue_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # "GRANTED", "DENIED", "PENDING", "EXPIRED"
    consent_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    contact_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PromiseToPayRow(Base):
    """Records a customer promise-to-pay lifecycle.

    Linked to a recovery case via ``case_id`` (UUID generated by the agent,
    not a FK — the canonical RecoveryCase is an in-memory model).
    """

    __tablename__ = "promise_to_pay"

    promise_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    case_id: Mapped[PyUUID] = mapped_column(UUID(), nullable=False)
    person_id: Mapped[PyUUID] = mapped_column(
        UUID(), ForeignKey("persons.person_id")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # How the promise was captured (e.g. "SIMULATED_RESPONSE", "API", "CHAT")
    source: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    # "ACTIVE", "FULFILLED", "MISSED", "CANCELLED"
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditEventRow(Base):
    """Immutable audit trail for every smart-agent decision and execution.

    Each row captures: who/what acted, what input was seen, what the
    decision was, which policy checks passed or failed, the idempotency
    key, the execution result, and the final outcome.
    """

    __tablename__ = "audit_events"

    event_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    case_id: Mapped[PyUUID | None] = mapped_column(UUID(), nullable=True)
    run_id: Mapped[PyUUID | None] = mapped_column(
        UUID(), ForeignKey("simulation_runs.run_id"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    agent_version: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32))  # "system" | "agent" | "human"
    event_type: Mapped[str] = mapped_column(String(64))
    input_snapshot_hash: Mapped[str] = mapped_column(String(128))
    evidence_refs: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    decision_json: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    policy_checks: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    execution_result: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)


class BaselineAuditEventRow(Base):
    """Immutable audit records for the control/baseline agent.

    This is intentionally a separate physical table so control decisions can
    never be confused with SARA decisions when an experiment is reviewed.
    The columns remain identical, which keeps the API and replay tooling
    consistent across both agents.
    """
    __tablename__ = "baseline_audit_events"

    event_id: Mapped[PyUUID] = mapped_column(UUID(), primary_key=True)
    case_id: Mapped[PyUUID | None] = mapped_column(UUID(), nullable=True)
    run_id: Mapped[PyUUID | None] = mapped_column(UUID(), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    agent_version: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(64))
    input_snapshot_hash: Mapped[str] = mapped_column(String(128))
    evidence_refs: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    decision_json: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    policy_checks: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    execution_result: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)


Index("ix_audit_events_case_id", AuditEventRow.case_id)
Index("ix_audit_events_run_id", AuditEventRow.run_id)
Index("ix_audit_events_event_type", AuditEventRow.event_type)
Index("ix_audit_events_timestamp", AuditEventRow.timestamp)
Index("ix_promise_case_id", PromiseToPayRow.case_id)
Index("ix_promise_person_id", PromiseToPayRow.person_id)
Index("ix_promise_status", PromiseToPayRow.status)
