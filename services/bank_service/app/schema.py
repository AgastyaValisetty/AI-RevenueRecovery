"""Bank Service database schema.

This service shares the ``banks``, ``bank_accounts``, and ``ledger_entries``
tables with the People Service (which creates them on startup).  The ORM
classes here are compatible with those shared tables so the Bank Service
can read bank policies, validate accounts, and calculate balances.

The ``bank_metrics`` table is owned by this service for tracking
transaction metrics and state transitions.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BASE(DeclarativeBase):
    pass


class BankRow(BASE):
    """Bank policy table — shared with People Service.

    Maps to the ``banks`` table created by People Service.
    The ``state_multipliers_json`` column stores a JSON object mapping
    bank states to numeric multipliers.
    """
    __tablename__ = "banks"
    __table_args__ = {"extend_existing": True}

    bank_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    authorization_success_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    timeout_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    issuer_decline_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    network_error_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    current_state: Mapped[str] = mapped_column(String(32))
    state_multipliers_json: Mapped[str] = mapped_column(Text)
    settlement_account_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BankAccountRow(BASE):
    """Bank accounts table — shared with People Service.

    Maps to the ``bank_accounts`` table created by People Service.
    Balance is NOT stored here — it is calculated from ledger_entries.
    """
    __tablename__ = "bank_accounts"
    __table_args__ = {"extend_existing": True}

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    bank_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerEntryRow(BASE):
    """Ledger entries table — shared with People Service.

    Read-only mapping for balance calculation.  The table is created
    and written by the People Service.
    """
    __tablename__ = "ledger_entries"
    __table_args__ = {"extend_existing": True}

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32))
    from_account_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    to_account_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    simulation_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    related_attempt_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    related_subscription_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BankMetricRow(BASE):
    """Tracks transaction results for state transitions (NORMAL→PEAK etc.).

    Owned by this service only.
    """
    __tablename__ = "bank_metrics"

    metric_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _uuid_str()
    )
    bank_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    success: Mapped[int] = mapped_column(Integer)  # 0 or 1
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(32), default="UNKNOWN")


Index("ix_bank_metrics_ts", BankMetricRow.timestamp)
Index("ix_bank_metrics_bank_ts", BankMetricRow.bank_id, BankMetricRow.timestamp)
Index("ix_bank_metrics_outcome", BankMetricRow.outcome)


def _uuid_str() -> str:
    from uuid import uuid4
    return str(uuid4())
