"""Shared fixtures for integration tests.

These tests verify the full HTTP flow between two real services:

    Test client → **LazerPay** (in-process FastAPI TestClient)
              → **Bank Service** (real uvicorn HTTP server, separate process)

Both services share a single file-based SQLite database.  The Bank Service
runs in a **subprocess** because both services use a Python package named
``app`` — importing both in the same process would cause an import conflict.

Table creation
--------------
The ``banks``, ``bank_accounts``, ``ledger_entries`` and ``bank_metrics``
tables are defined as SQLAlchemy **Core** ``Table`` objects here (matching
the Bank Service's ORM schema exactly).  The ``payment_attempts`` and
``idempotency_keys`` tables come from LazerPay's ``DeclarativeBase``.
Everything is created once at session start before the Bank Service
subprocess launches.
"""
from __future__ import annotations

import os
import sys
import time
import uuid as uuid_lib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    create_engine,
    text,
    MetaData,
    Table,
    Column,
    String,
    Numeric,
    Text,
    DateTime,
    Integer,
    Index,
)
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Make the LazerPay ``app`` package importable
# ---------------------------------------------------------------------------
_LAZERPAY_DIR = Path(__file__).resolve().parent.parent.parent / "lazerpay_service"
if str(_LAZERPAY_DIR) not in sys.path:
    sys.path.insert(0, str(_LAZERPAY_DIR))

from app.config import Settings as LazerPaySettings          # noqa: E402
from app.database import Database as LazerPayDatabase          # noqa: E402
from app.api import router as lazerpay_router                  # noqa: E402
from app.schema import BASE as LAZERPAY_BASE                   # noqa: E402
from app.schema import PaymentAttemptRow                       # noqa: E402

# Path to the Bank Service runner script
_BANK_RUNNER = Path(__file__).resolve().parent.parent / "run_bank_server.py"
_BANK_DIR = Path(__file__).resolve().parent.parent.parent / "bank_service"

BANK_SERVICE_PORT = 8099


# ---------------------------------------------------------------------------
# Core Table definitions for Bank Service shared / owned tables
#
# These mirror ``services/bank_service/app/schema.py`` exactly so the Bank
# Service ORM classes can read / write these tables in the subprocess.
# ---------------------------------------------------------------------------
bank_metadata = MetaData()

banks_table = Table(
    "banks",
    bank_metadata,
    Column("bank_id", String(64), primary_key=True),
    Column("name", String(64), unique=True, nullable=False),
    Column("authorization_success_rate", Numeric(6, 2), nullable=False),
    Column("timeout_rate", Numeric(6, 2), nullable=False),
    Column("issuer_decline_rate", Numeric(6, 2), nullable=False),
    Column("network_error_rate", Numeric(6, 2), nullable=False),
    Column("current_state", String(32), nullable=False),
    Column("state_multipliers_json", Text, nullable=False),
    Column("settlement_account_id", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

bank_accounts_table = Table(
    "bank_accounts",
    bank_metadata,
    Column("account_id", String(64), primary_key=True),
    Column("person_id", String(64), nullable=True, index=True),
    Column("bank_id", String(64), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

ledger_entries_table = Table(
    "ledger_entries",
    bank_metadata,
    Column("entry_id", String(64), primary_key=True),
    Column("event_type", String(32), nullable=False),
    Column("from_account_id", String(64), nullable=True),
    Column("to_account_id", String(64), nullable=True),
    Column("amount", Numeric(14, 2), nullable=False),
    Column("simulation_timestamp", DateTime(timezone=True), nullable=False),
    Column("related_attempt_id", String(64), nullable=True),
    Column("related_subscription_id", String(64), nullable=True),
    Column("metadata_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_ledger_entries_event_type", "event_type"),
    Index("ix_ledger_entries_from_account_id", "from_account_id"),
    Index("ix_ledger_entries_to_account_id", "to_account_id"),
)

bank_metrics_table = Table(
    "bank_metrics",
    bank_metadata,
    Column("metric_id", String(64), primary_key=True),
    Column("bank_id", String(64), nullable=False, index=True),
    Column("timestamp", DateTime(timezone=True), nullable=False, index=True),
    Column("success", Integer, nullable=False),          # 0 or 1
    Column("response_time_ms", Integer, nullable=False, default=0),
    Column("outcome", String(32), nullable=False, default="UNKNOWN"),
    Index("ix_bank_metrics_ts", "timestamp"),
    Index("ix_bank_metrics_bank_ts", "bank_id", "timestamp"),
    Index("ix_bank_metrics_outcome", "outcome"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TABLE_NAMES = [
    "payment_attempts",
    "idempotency_keys",
    "ledger_entries",
    "bank_metrics",
    "bank_accounts",
    "banks",
]


def _seed_data(conn) -> None:
    """Insert the default bank policy, settlement account, person account, and initial credit."""
    now = datetime.now(timezone.utc).isoformat()
    entry_id = str(uuid_lib.uuid4())
    settlement_account = "account_settlement_bank_rupee"

    conn.exec_driver_sql(f"""
        INSERT INTO banks (
            bank_id, name, authorization_success_rate, timeout_rate,
            issuer_decline_rate, network_error_rate, current_state,
            state_multipliers_json, settlement_account_id, created_at
        ) VALUES (
            'bank_rupee', 'RupeeBank', 99.0, 0.5, 0.3, 0.2, 'NORMAL',
            '{{"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0}}',
            '{settlement_account}', '{now}'
        )
    """)

    conn.exec_driver_sql(f"""
        INSERT INTO bank_accounts (account_id, person_id, bank_id, created_at)
        VALUES ('{settlement_account}', NULL, 'bank_rupee', '{now}')
    """)

    conn.exec_driver_sql(f"""
        INSERT INTO bank_accounts (account_id, person_id, bank_id, created_at)
        VALUES ('account_test_person', 'person_test', 'bank_rupee', '{now}')
    """)

    conn.exec_driver_sql(f"""
        INSERT INTO ledger_entries (
            entry_id, event_type, from_account_id, to_account_id, amount,
            simulation_timestamp, related_attempt_id, related_subscription_id,
            metadata_json, created_at
        ) VALUES (
            '{entry_id}', 'CREDIT', NULL, 'account_test_person', 1000.00,
            '{now}', NULL, NULL, '{{}}', '{now}'
        )
    """)


def _clear_tables(conn) -> None:
    """Delete all rows from every table (order doesn't matter for SQLite)."""
    for table_name in _TABLE_NAMES:
        conn.exec_driver_sql(f"DELETE FROM {table_name}")


# ---------------------------------------------------------------------------
# Database / server fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """A session-scoped temporary SQLite database file."""
    return str(tmp_path_factory.mktemp("db") / "shared_integration.db")


@pytest.fixture(scope="session")
def db_url(db_path):
    return f"sqlite:///{db_path}"


@pytest.fixture(scope="session")
def shared_engine(db_url):
    """Create all tables from both Bank Service and LazerPay schemas."""
    engine = create_engine(db_url)
    # Bank Service tables (Core definitions above)
    bank_metadata.create_all(engine)
    # LazerPay tables (payment_attempts, idempotency_keys, indexes)
    LAZERPAY_BASE.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def bank_server(shared_engine, db_url):
    """Start the Bank Service as a **real HTTP server** in a subprocess.

    Runs ``run_bank_server.py`` which imports the Bank Service's ``app``
    package in its own Python process (no import conflict) and starts
    uvicorn.  The subprocess shares the same SQLite file as the in-process
    LazerPay TestClient.
    """
    proc = subprocess.Popen(
        [
            sys.executable,
            str(_BANK_RUNNER),
            db_url,
            str(BANK_SERVICE_PORT),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ},
    )

    bank_url = f"http://127.0.0.1:{BANK_SERVICE_PORT}"
    ready = False
    for _ in range(50):
        try:
            resp = httpx.get(f"{bank_url}/api/status", timeout=0.5)
            if resp.status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.1)

    if not ready:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Bank Service did not start in time.\n"
            f"stdout: {stdout.decode()}\n"
            f"stderr: {stderr.decode()}"
        )

    yield type("BankServer", (), {"base_url": bank_url, "port": BANK_SERVICE_PORT})()

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_db(shared_engine, bank_server):
    """Clean and reseed all tables before **every** test.

    Bank Service tables (banks, bank_accounts, ledger_entries, bank_metrics)
    and LazerPay tables (payment_attempts, idempotency_keys) are wiped and
    re-seeded with the default RupeeBank policy + 1000 credit to
    ``account_test_person``.
    """
    with shared_engine.connect() as conn:
        trans = conn.begin()
        _clear_tables(conn)
        _seed_data(conn)
        trans.commit()
    yield


@pytest.fixture
def shared_db(db_url):
    """A LazerPay Database instance for querying the shared SQLite file.

    Tests use ``shared_db.session()`` to verify persistence of payment
    attempts, ledger entries, and bank metrics.
    """
    db = LazerPayDatabase(
        engine_url=db_url,
        connect_args={"check_same_thread": False, "timeout": 30.0},
        poolclass=StaticPool,
    )
    yield db


@pytest.fixture
def lazerpay_app(shared_db, bank_server):
    """LazerPay FastAPI app wired to the shared DB and real Bank Service HTTP."""
    settings = LazerPaySettings(
        db_host="test",
        db_port=5432,
        db_user="test",
        db_password="test",
        db_name="test",
        bank_url=bank_server.base_url,
        service_port=8001,
        http_timeout_seconds=5.0,
    )
    app = FastAPI(title="LazerPay Service Test", version="1.0.0")
    app.state.db = shared_db
    app.state.settings = settings
    app.include_router(lazerpay_router)
    return app


@pytest.fixture
def client(lazerpay_app):
    """TestClient that runs the LazerPay app in-process."""
    return TestClient(lazerpay_app)


@pytest.fixture
def process_payload() -> dict:
    return {
        "intent_id": "intent-int-001",
        "person_id": "person_test",
        "merchant_id": "merchant-001",
        "amount": 100.00,
        "payment_method": "CARD",
        "source_account_id": "account_test_person",
        "simulation_timestamp": "2024-01-01T12:00:00+00:00",
    }
