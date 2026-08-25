"""Shared pytest fixtures for the LazerPay Service test suite.

All database-backed tests use an in-memory SQLite database with
``StaticPool`` so that the FastAPI ``TestClient`` (which runs in a
separate thread) can see tables created here.

The ``ledger_entries`` table (created by the People Service in
production) is created using a Core ``Table`` definition so that
LazerPay's ``write_ledger_entry`` (which uses ``autoload_with``)
can reflect it.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, DateTime, MetaData, Numeric, String, Table, Text
from sqlalchemy.pool import StaticPool

# Ensure the app package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import router
from app.config import Settings
from app.database import Database
from app.schema import BASE  # noqa: E402


# ------------------------------------------------------------------ #
# Table for the shared ledger_entries (created by People Service in prod)
# ------------------------------------------------------------------ #

ledger_entries_meta = MetaData()
ledger_entries_table = Table(
    "ledger_entries",
    ledger_entries_meta,
    Column("entry_id", String(64), primary_key=True),
    Column("event_type", String(32), nullable=False),
    Column("from_account_id", String(64), nullable=True),
    Column("to_account_id", String(64), nullable=True),
    Column("amount", Numeric(14, 2), nullable=False),
    Column("simulation_timestamp", DateTime(timezone=True), nullable=True),
    Column("related_attempt_id", String(64), nullable=True),
    Column("related_subscription_id", String(64), nullable=True),
    Column("metadata_json", Text, nullable=True),
    Column("created_at", DateTime(timezone=True)),
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def make_test_settings(bank_url: str = "http://mock-bank:8002") -> Settings:
    return Settings(
        db_host="test",
        db_port=5432,
        db_user="test",
        db_password="test",
        db_name="test",
        bank_url=bank_url,
        service_port=8001,
        http_timeout_seconds=5.0,
    )


def make_test_db() -> Database:
    """Create an in-memory SQLite database with all needed tables."""
    db = Database(
        engine_url="sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create LazerPay-owned tables
    BASE.metadata.create_all(db._engine)
    # Create shared ledger_entries table
    ledger_entries_table.create(db._engine, checkfirst=True)
    return db


def create_test_app(db: Database | None = None, bank_url: str = "http://mock-bank:8002") -> FastAPI:
    """Build a FastAPI test app wired to a test database."""
    if db is None:
        db = make_test_db()
    settings = make_test_settings(bank_url=bank_url)
    app = FastAPI(title="LazerPay Service Test", version="1.0.0")
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
def app(db: Database) -> FastAPI:
    """A FastAPI test app with the test database and mock Bank URL."""
    return create_test_app(db)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_bank_url() -> str:
    return "http://mock-bank:8002"


@pytest.fixture
def mock_bank_success(mock_bank_url):
    """Mock Bank Service that always returns success."""
    with respx.mock(base_url=mock_bank_url, assert_all_called=False) as mock:
        mock.post("/api/authorize").respond(
            200,
            json={
                "success": True,
                "failure_code": None,
                "failure_reason": None,
                "response_time_ms": 150,
                "bank_state": "NORMAL",
                "source_balance": "1000.00",
                "authorized_at": "2024-01-01T12:00:00+00:00",
                "unknown_outcome": False,
            },
        )
        mock.get("/api/status").respond(200, json={"service": "bank", "status": "running"})
        yield mock


@pytest.fixture
def mock_bank_failure(mock_bank_url):
    """Mock Bank Service that always returns a decline."""
    with respx.mock(base_url=mock_bank_url, assert_all_called=False) as mock:
        mock.post("/api/authorize").respond(
            200,
            json={
                "success": False,
                "failure_code": "HARD_DECLINE",
                "failure_reason": "Bank declined transaction",
                "response_time_ms": 200,
                "bank_state": "NORMAL",
                "source_balance": "500.00",
                "authorized_at": "2024-01-01T12:00:00+00:00",
                "unknown_outcome": False,
            },
        )
        mock.get("/api/status").respond(200, json={"service": "bank", "status": "running"})
        yield mock


@pytest.fixture
def mock_bank_unknown(mock_bank_url):
    """Mock Bank Service that returns UNKNOWN (timeout) outcome."""
    with respx.mock(base_url=mock_bank_url, assert_all_called=False) as mock:
        mock.post("/api/authorize").respond(
            200,
            json={
                "success": True,
                "failure_code": None,
                "failure_reason": "Bank response delayed beyond delivery window",
                "response_time_ms": 300,
                "bank_state": "NORMAL",
                "source_balance": "500.00",
                "authorized_at": "2024-01-01T12:00:00+00:00",
                "unknown_outcome": True,
            },
        )
        mock.get("/api/status").respond(200, json={"service": "bank", "status": "running"})
        yield mock


@pytest.fixture
def mock_bank_unreachable(mock_bank_url):
    """Mock Bank Service that is unreachable (connection timeout)."""
    with respx.mock(base_url=mock_bank_url, assert_all_called=False) as mock:
        mock.post("/api/authorize").mock(
            side_effect=httpx.ConnectTimeout("Connection timed out")
        )
        mock.get("/api/status").respond(200, json={"service": "bank", "status": "running"})
        yield mock


@pytest.fixture
def mock_bank_network_error(mock_bank_url):
    """Mock Bank Service that returns NETWORK_ERROR."""
    with respx.mock(base_url=mock_bank_url, assert_all_called=False) as mock:
        mock.post("/api/authorize").respond(
            200,
            json={
                "success": False,
                "failure_code": "NETWORK_ERROR",
                "failure_reason": "Network error communicating with bank",
                "response_time_ms": 100,
                "bank_state": "NORMAL",
                "source_balance": "500.00",
                "authorized_at": "2024-01-01T12:00:00+00:00",
                "unknown_outcome": False,
            },
        )
        mock.get("/api/status").respond(200, json={"service": "bank", "status": "running"})
        yield mock


# ------------------------------------------------------------------
# Sequential-response mocks for retry tests
# ------------------------------------------------------------------

_BANK_FAILURE_RESPONSE = {
    "success": False,
    "failure_code": "HARD_DECLINE",
    "failure_reason": "Bank declined transaction",
    "response_time_ms": 200,
    "bank_state": "NORMAL",
    "source_balance": "500.00",
    "authorized_at": "2024-01-01T12:00:00+00:00",
}

_BANK_UNKNOWN_RESPONSE = {
    "success": True,
    "failure_code": None,
    "failure_reason": "Bank response delayed beyond delivery window",
    "response_time_ms": 300,
    "bank_state": "NORMAL",
    "source_balance": "500.00",
    "authorized_at": "2024-01-01T12:00:00+00:00",
    "unknown_outcome": True,
}

_BANK_SUCCESS_RESPONSE = {
    "success": True,
    "failure_code": None,
    "failure_reason": None,
    "response_time_ms": 150,
    "bank_state": "NORMAL",
    "source_balance": "1000.00",
    "authorized_at": "2024-01-01T12:00:00+00:00",
    "unknown_outcome": False,
}


@pytest.fixture
def mock_bank_fail_then_success(mock_bank_url):
    """Mock Bank Service: first authorize call fails, subsequent calls succeed."""
    with respx.mock(base_url=mock_bank_url, assert_all_called=False) as mock:
        mock.post("/api/authorize").mock(
            side_effect=[
                httpx.Response(200, json=_BANK_FAILURE_RESPONSE),
                httpx.Response(200, json=_BANK_SUCCESS_RESPONSE),
                httpx.Response(200, json=_BANK_SUCCESS_RESPONSE),
                httpx.Response(200, json=_BANK_SUCCESS_RESPONSE),
            ]
        )
        mock.get("/api/status").respond(200, json={"service": "bank", "status": "running"})
        yield mock


@pytest.fixture
def mock_bank_unknown_then_success(mock_bank_url):
    """Mock Bank Service: first authorize call returns UNKNOWN, second succeeds."""
    with respx.mock(base_url=mock_bank_url, assert_all_called=False) as mock:
        mock.post("/api/authorize").mock(
            side_effect=[
                httpx.Response(200, json=_BANK_UNKNOWN_RESPONSE),
                httpx.Response(200, json=_BANK_SUCCESS_RESPONSE),
            ]
        )
        mock.get("/api/status").respond(200, json={"service": "bank", "status": "running"})
        yield mock
