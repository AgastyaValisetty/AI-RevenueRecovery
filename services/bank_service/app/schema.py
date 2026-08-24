from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, Float, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class BASE(DeclarativeBase):
    pass


class BankRow(BASE):
    __tablename__ = "banks"

    bank_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    authorization_success_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    timeout_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    issuer_decline_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    network_error_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    current_state: Mapped[str] = mapped_column(String(32))
    state_multipliers_json: Mapped[dict] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BankMetricRow(BASE):
    """Tracks transaction counts for state transitions (NORMAL→PEAK etc.)"""
    __tablename__ = "bank_metrics"

    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    bank_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    success: Mapped[bool] = mapped_column(Integer)  # 0 or 1 for SQLite compat


class BankAccountRow(BASE):
    """Bank accounts linking persons to banks with balances."""
    __tablename__ = "bank_accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    person_id: Mapped[str] = mapped_column(String(64), index=True)
    bank_id: Mapped[str] = mapped_column(String(64), index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default="0.00")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BankMetricIndex:
    """Index definitions for bank metrics."""
    pass


Index("ix_bank_metrics_ts", BankMetricRow.timestamp)
Index("ix_bank_metrics_bank_ts", BankMetricRow.bank_id, BankMetricRow.timestamp)