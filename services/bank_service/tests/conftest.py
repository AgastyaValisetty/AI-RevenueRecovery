"""Shared pytest fixtures for the Bank Service test suite.

All database-backed tests use an in-memory SQLite database so no
external PostgreSQL service is required.  Shared tables (``banks``,
``bank_accounts``, ``ledger_entries``) are created alongside the
service-owned ``bank_metrics`` table by calling ``BASE.metadata.create_all``.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure the app package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import router
from app.config import Settings
from app.database import Database
from app.domain import BankPolicy, BankState
from app.schema import BASE

try:
    from sqlalchemy.pool import StaticPool
except ImportError:  # pragma: no cover
    StaticPool = None


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def make_test_settings() -> Settings:
    return Settings(
        db_host="test",
        db_port=5432,
        db_user="test",
        db_password="test",
        db_name="test",
        service_port=8002,
    )


def make_test_db() -> Database:
    """Create an in-memory SQLite database with *all* tables.

    Uses ``StaticPool`` + ``check_same_thread=False`` so that the
    ``TestClient`` (which runs in a separate thread) can see tables
    created here.
    """
    kwargs = {}
    if StaticPool is not None:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    db = Database(engine_url="sqlite:///:memory:", **kwargs)
    # create_schema only creates bank_metrics; for tests we need the shared
    # tables too (banks, bank_accounts, ledger_entries).
    BASE.metadata.create_all(db._engine)
    return db


def seed_default_bank(db: Database) -> BankPolicy:
    """Insert the default RupeeBank policy if not already present."""
    from app.repos import BankRepository
    repo = BankRepository(db)
    bank = repo.find_by_name("RupeeBank")
    if bank is None:
        bank = BankPolicy(
            bank_id="rupee-bank-id",
            name="RupeeBank",
            authorization_success_rate=99.1,
            timeout_rate=0.3,
            issuer_decline_rate=0.4,
            network_error_rate=0.2,
            current_state=BankState.NORMAL,
            state_multipliers={
                "NORMAL": 1.0,
                "PEAK": 2.0,
                "DEGRADED": 5.0,
                "OUTAGE": 50.0,
            },
            created_at=datetime.now(timezone.utc),
        )
        repo.add(bank)
    return bank


def credit_account(
    db: Database,
    account_id: str,
    amount: Decimal,
    sim_ts: datetime | None = None,
) -> None:
    """Insert a ledger credit entry to give an account a balance."""
    if sim_ts is None:
        sim_ts = datetime.now(timezone.utc)
    from app.schema import LedgerEntryRow
    with db.session() as session:
        session.add(
            LedgerEntryRow(
                entry_id=f"ledger-{account_id[-8:]}-{sim_ts.timestamp()}",
                event_type="DEPOSIT",
                from_account_id=None,
                to_account_id=account_id,
                amount=amount,
                simulation_timestamp=sim_ts,
                metadata_json="{}",
                created_at=datetime.now(timezone.utc),
            )
        )


def create_test_app(db: Database | None = None) -> FastAPI:
    """Build a FastAPI instance wired to a test database."""
    if db is None:
        db = make_test_db()
    settings = make_test_settings()
    app = FastAPI(title="Bank Service Test", version="1.0.0")
    app.state.db = db
    app.state.settings = settings
    app.include_router(router)
    return app


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def db() -> Database:
    """An in-memory SQLite database with all tables created."""
    return make_test_db()


@pytest.fixture
def settings() -> Settings:
    return make_test_settings()


@pytest.fixture
def bank_policy() -> BankPolicy:
    """A default BankPolicy instance for domain-level tests."""
    return BankPolicy(
        bank_id="test-bank-id",
        name="RupeeBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.NORMAL,
        state_multipliers={
            "NORMAL": 1.0,
            "PEAK": 2.0,
            "DEGRADED": 5.0,
            "OUTAGE": 50.0,
        },
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def app(db: Database) -> FastAPI:
    """A FastAPI test app with the test database."""
    return create_test_app(db)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """A TestClient wired to the test app."""
    return TestClient(app)
