"""Tests for the GET /api/payments/failures analytics endpoint.

Uses a *file-backed* SQLite database (not ``:memory:``) so the TestClient's
request thread and the test body share the same data. In-memory SQLite would
give each connection its own private database and the endpoint would see no
tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router
from app.container import build_orchestrator
from app.database import Database
from app.domain import FAILURE_REASONS, LedgerEntry, PAYMENT_FAILED, PAYMENT_SETTLED
from app.repositories import LedgerRepository
from app.sim_config import SimConfig


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(engine_url=f"sqlite:///{tmp_path / 'test.db'}")
    database.create_schema()
    return database


@pytest.fixture
def client(db) -> TestClient:
    """A TestClient exposing the router with an orchestrator on the file DB."""
    orchestrator = build_orchestrator(db, seed=42, config=SimConfig.defaults())
    app = FastAPI()
    app.state.orchestrator = orchestrator
    app.include_router(router)
    return TestClient(app)


def _base_ts() -> datetime:
    return datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc)


def _fail_entry(code: str, reason: str | None = None) -> LedgerEntry:
    meta = {"payment_method": "UPI", "failure_code": code}
    if reason is not None:
        meta["failure_reason"] = reason
    return LedgerEntry(
        entry_id=uuid4(),
        event_type=PAYMENT_FAILED,
        from_account_id=uuid4(),
        to_account_id=None,
        amount=Decimal("100"),
        simulation_timestamp=_base_ts(),
        metadata_json=meta,
    )


def _settled_entry() -> LedgerEntry:
    return LedgerEntry(
        entry_id=uuid4(),
        event_type=PAYMENT_SETTLED,
        from_account_id=uuid4(),
        to_account_id=None,
        amount=Decimal("100"),
        simulation_timestamp=_base_ts(),
        metadata_json={"payment_method": "UPI"},
    )


class TestFailuresEndpoint:
    def test_empty_db_returns_zero_rate(self, client):
        resp = client.get("/api/payments/failures")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_failed"] == 0
        assert data["total_settled"] == 0
        assert data["failure_rate"] == 0.0
        assert data["by_reason"] == []
        assert data["recent_failures"] == []

    def test_failure_rate_and_breakdown(self, client, db):
        repo = LedgerRepository(db)
        repo.append([_fail_entry("INSUFFICIENT_FUNDS") for _ in range(25)])

        data = client.get("/api/payments/failures").json()
        assert data["total_failed"] == 25
        assert data["total_settled"] == 0
        assert data["failure_rate"] == 100.0
        assert len(data["by_reason"]) == 1
        bucket = data["by_reason"][0]
        assert bucket["code"] == "INSUFFICIENT_FUNDS"
        assert bucket["count"] == 25
        assert bucket["pct_of_failures"] == 100.0
        assert bucket["category"] == "CUSTOMER_STATE"
        assert len(data["recent_failures"]) == 25

    def test_failure_rate_with_settled(self, client, db):
        repo = LedgerRepository(db)
        repo.append([_settled_entry() for _ in range(75)])
        repo.append([_fail_entry("INSUFFICIENT_FUNDS") for _ in range(25)])

        data = client.get("/api/payments/failures").json()
        assert data["total_settled"] == 75
        assert data["total_failed"] == 25
        assert data["failure_rate"] == 25.0  # 25 / (75 + 25)


class TestFailuresBreakdown:
    def test_groups_mixed_codes(self, client, db):
        repo = LedgerRepository(db)
        repo.append([_fail_entry("INSUFFICIENT_FUNDS") for _ in range(3)])
        repo.append([_fail_entry("TIMEOUT") for _ in range(1)])

        data = client.get("/api/payments/failures").json()
        by_reason = {b["code"]: b for b in data["by_reason"]}
        assert by_reason["INSUFFICIENT_FUNDS"]["count"] == 3
        assert by_reason["TIMEOUT"]["count"] == 1
        assert by_reason["INSUFFICIENT_FUNDS"]["pct_of_failures"] == 75.0
        assert by_reason["TIMEOUT"]["pct_of_failures"] == 25.0

    def test_missing_reason_falls_back_to_code_label(self, client, db):
        repo = LedgerRepository(db)
        repo.append([_fail_entry("BANK_DEGRADED")])  # code but no reason

        data = client.get("/api/payments/failures").json()
        recent = data["recent_failures"][0]
        assert recent["failure_code"] == "BANK_DEGRADED"
        assert recent["failure_reason"] == FAILURE_REASONS["BANK_DEGRADED"]