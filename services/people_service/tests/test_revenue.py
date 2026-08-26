"""Tests for GET /api/revenue — merchant revenue + LazerPay gateway fee.

Uses a file-backed SQLite DB (not ``:memory:``) so the TestClient's request
thread and the test body share the same data.
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
from app.domain import (
    LAZERPAY_FEE_RATE,
    INTENT_SETTLED,
    LedgerEntry,
    PAYMENT_SETTLED,
    PaymentIntent,
)
from app.repositories import MerchantRepository, PaymentIntentRepository, LedgerRepository
from app.sim_config import SimConfig


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(engine_url=f"sqlite:///{tmp_path / 'test.db'}")
    database.create_schema()
    return database


@pytest.fixture
def client(db) -> TestClient:
    orchestrator = build_orchestrator(db, seed=42, config=SimConfig.defaults())
    orchestrator.initialize(people_count=5, seed=42)
    app = FastAPI()
    app.state.orchestrator = orchestrator
    app.include_router(router)
    return TestClient(app)


def _ts() -> datetime:
    return datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc)


def _seed_settled_intent(db, amount: str, merchant_id) -> None:
    """Insert a SETTLED PaymentIntent + a PAYMENT_SETTLED ledger entry directly."""
    amount_dec = Decimal(amount)
    intent = PaymentIntent(
        intent_id=uuid4(),
        person_id=uuid4(),
        merchant_id=merchant_id,
        product_id=uuid4(),
        amount=amount_dec,
        payment_method="UPI",
        status=INTENT_SETTLED,
        related_subscription_id=None,
        created_at=_ts(),
        expires_at=_ts(),
    )
    PaymentIntentRepository(db).add([intent])
    LedgerRepository(db).append([
        LedgerEntry(
            entry_id=uuid4(),
            event_type=PAYMENT_SETTLED,
            from_account_id=uuid4(),
            to_account_id=None,
            amount=amount_dec,
            simulation_timestamp=_ts(),
            metadata_json={"payment_method": "UPI"},
        )
    ])


def test_revenue_returns_lazerpay_fields(db, client):
    merchant = MerchantRepository(db).find_all()[0]
    _seed_settled_intent(db, "1000.00", merchant_id=merchant.merchant_id)

    resp = client.get("/api/revenue")
    assert resp.status_code == 200
    data = resp.json()

    # Top-level LazerPay totals present and equal to 2% of gross volume.
    assert "lazerpay_revenue" in data
    assert "lazerpay_fee_rate" in data
    assert data["lazerpay_fee_rate"] == LAZERPAY_FEE_RATE
    assert Decimal(data["lazerpay_revenue"]) == Decimal("20.00")

    # Per-merchant fee also present.
    merchant_entry = next(
        (m for m in data["merchants"] if m["merchant_id"] == str(merchant.merchant_id)),
        None,
    )
    assert merchant_entry is not None
    assert merchant_entry["lifetime_revenue"] == "1000.00"
    assert merchant_entry["lazerpay_fee"] == "20.00"


def test_lazerpay_revenue_is_zero_with_no_settled(db, client):
    resp = client.get("/api/revenue")
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["lazerpay_revenue"]) == Decimal("0")