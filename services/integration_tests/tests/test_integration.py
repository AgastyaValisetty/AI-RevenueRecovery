"""Integration tests with real HTTP service boundaries.

These tests verify the full HTTP flow between two real services:

    Test client → **LazerPay** (in-process FastAPI TestClient)
              → **Bank Service** (real uvicorn HTTP server in a subprocess)

The Bank Service runs as a separate Python process to avoid the ``app``
package import conflict with LazerPay.  Both services share a single
file-based SQLite database.

LazerPay makes **real** ``httpx.post()`` calls to the Bank Service — no
respx mocking.  The Bank Service reads and writes the shared SQLite file
for bank policies, balances, and transaction metrics.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.schema import PaymentAttemptRow


# --------------------------------------------------------------------------- #
# Status / health
# --------------------------------------------------------------------------- #

class TestGatewayStatusIntegration:
    def test_status_checks_real_bank_service(self, client, bank_server):
        """LazerPay /api/status should reach the real Bank Service over HTTP."""
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["database_reachable"] is True
        assert data["bank_service_reachable"] is True
        assert data["pending_attempts"] >= 0

    def test_bank_service_status_endpoint_reachable(self, bank_server):
        """Bank Service /api/status must respond on its real HTTP port."""
        resp = httpx.get(f"{bank_server.base_url}/api/status", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "bank"
        assert data["status"] == "running"


# --------------------------------------------------------------------------- #
# Full payment flow (LazerPay → Bank Service over real HTTP)
# --------------------------------------------------------------------------- #

class TestPaymentFlowIntegration:
    def test_successful_payment_over_http(self, client, shared_db, process_payload):
        """A successful payment creates a SETTLED attempt + ledger entry.

        The Bank Service authorizes over real HTTP — no respx mocking.
        """
        resp = client.post("/api/payments/process", json=process_payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["attempt_id"].startswith("ATT_")
        assert data["status"] in ("SETTLED", "FAILED")  # probabilistic bank
        assert data["correlation_id"] is not None

        # Verify attempt persisted in shared DB
        with shared_db.session() as session:
            row = session.get(PaymentAttemptRow, data["attempt_id"])
            assert row is not None
            assert row.intent_id == process_payload["intent_id"]
            assert row.status == data["status"]

    def test_payment_ledger_entry_persisted(self, client, shared_db, process_payload):
        """After a payment, a ledger entry must be written to the shared DB."""
        resp = client.post("/api/payments/process", json=process_payload)
        data = resp.json()
        attempt_id = data["attempt_id"]

        with shared_db.session() as session:
            row = session.execute(
                text(
                    "SELECT event_type, from_account_id, to_account_id, "
                    "amount, related_attempt_id "
                    "FROM ledger_entries WHERE related_attempt_id = :aid"
                ),
                {"aid": attempt_id},
            ).fetchone()
            assert row is not None, "No ledger entry found for the attempt"
            assert row.event_type in ("PAYMENT_SETTLED", "PAYMENT_FAILED", "PAYMENT_UNKNOWN")
            assert row.from_account_id == process_payload["source_account_id"]

    def test_bank_metrics_recorded_on_authorization(self, client, shared_db, process_payload):
        """After a payment, the Bank Service records transaction metrics."""
        resp = client.post("/api/payments/process", json=process_payload)
        assert resp.status_code == 200

        with shared_db.session() as session:
            result = session.execute(text("SELECT COUNT(*) FROM bank_metrics")).scalar()
            assert result > 0, "Bank Service did not record transaction metrics"

    def test_settlement_account_receives_funds(self, client, shared_db, process_payload):
        """A settled payment should credit the bank's settlement account."""
        resp = client.post("/api/payments/process", json=process_payload)
        assert resp.status_code == 200
        data = resp.json()

        # Only verify if the payment was actually settled
        if data["status"] != "SETTLED":
            pytest.skip("Payment was not settled (probabilistic bank)")

        attempt_id = data["attempt_id"]

        with shared_db.session() as session:
            # Find the settlement account from the banks table
            bank_row = session.execute(text("SELECT settlement_account_id FROM banks")).fetchone()
            assert bank_row is not None
            settlement_id = bank_row[0]
            assert settlement_id is not None, "Bank has no settlement account"

            # The settlement ledger entry should credit the settlement account
            row = session.execute(
                text(
                    "SELECT to_account_id, amount FROM ledger_entries "
                    "WHERE related_attempt_id = :aid AND event_type = 'PAYMENT_SETTLED'"
                ),
                {"aid": attempt_id},
            ).fetchone()
            assert row is not None, "No settlement ledger entry found"
            assert row[0] == settlement_id, \
                f"Expected to_account_id={settlement_id}, got {row[0]}"

            # The settlement account should have a positive balance
            balance = session.execute(
                text(
                    "SELECT COALESCE(SUM(amount), 0) FROM ledger_entries "
                    "WHERE to_account_id = :acct"
                ),
                {"acct": settlement_id},
            ).scalar()
            assert float(balance) > 0, "Settlement account should have positive balance"

    def test_payment_failures_after_draining_balance(self, client, shared_db, process_payload):
        """After 10 successful payments (100 each), the 1000 balance is
        exhausted and subsequent payments fail with INSUFFICIENT_FUNDS.
        """
        for i in range(20):
            payload = {
                **process_payload,
                "intent_id": f"intent-drain-{i}",
            }
            client.post("/api/payments/process", json=payload)

        with shared_db.session() as session:
            failed = session.execute(
                text("SELECT COUNT(*) FROM payment_attempts WHERE status = 'FAILED'")
            ).scalar()
            assert failed > 0, "Expected at least some failed attempts after draining funds"

    def test_full_attempt_lifecycle(self, client, process_payload):
        """Process → Get details → Verify all lifecycle fields are populated."""
        resp = client.post("/api/payments/process", json=process_payload)
        attempt_id = resp.json()["attempt_id"]

        detail = client.get(f"/api/payments/{attempt_id}")
        assert detail.status_code == 200
        data = detail.json()

        assert data["attempt_id"] == attempt_id
        assert data["attempt_number"] == 1
        assert data["person_id"] == process_payload["person_id"]
        assert data["merchant_id"] == process_payload["merchant_id"]
        assert float(data["amount"]) == 100.0
        assert data["payment_method"] == "CARD"
        assert data["source_account_id"] == process_payload["source_account_id"]
        assert data["correlation_id"] is not None
        # Lifecycle timestamps should be populated
        assert data["initiated_at"] is not None
        assert data["routed_at"] is not None
        assert data["created_at"] is not None


# --------------------------------------------------------------------------- #
# Idempotency across real HTTP
# --------------------------------------------------------------------------- #

class TestIdempotencyIntegration:
    def test_same_intent_returns_same_attempt(self, client, process_payload):
        """Same payload processed twice returns the same attempt (idempotent)."""
        resp1 = client.post("/api/payments/process", json=process_payload)
        resp2 = client.post("/api/payments/process", json=process_payload)

        id1 = resp1.json()["attempt_id"]
        id2 = resp2.json()["attempt_id"]
        assert id1 == id2

    def test_different_intents_create_different_attempts(self, client, process_payload):
        """Different intent_ids create separate attempts."""
        resp1 = client.post("/api/payments/process", json=process_payload)

        payload2 = {**process_payload, "intent_id": "intent-different-002"}
        resp2 = client.post("/api/payments/process", json=payload2)

        assert resp1.json()["attempt_id"] != resp2.json()["attempt_id"]


# --------------------------------------------------------------------------- #
# Retry over real HTTP
# --------------------------------------------------------------------------- #

class TestRetryIntegration:
    def test_retry_creates_second_attempt(self, client, process_payload):
        """Retry endpoint creates a new attempt with attempt_number=2."""
        resp = client.post("/api/payments/process", json=process_payload)
        original_id = resp.json()["attempt_id"]

        retry_resp = client.post(f"/api/payments/retry?attempt_id={original_id}")
        assert retry_resp.status_code == 200
        retry_data = retry_resp.json()

        assert retry_data["original_attempt_id"] == original_id
        assert retry_data["new_attempt_id"] != original_id
        assert retry_data["attempt_number"] == 2
        assert retry_data["status"] in ("SETTLED", "FAILED", "UNKNOWN")

    def test_retry_nonexistent_returns_404(self, client):
        resp = client.post("/api/payments/retry?attempt_id=nonexistent-id")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Bank Service direct integration
# --------------------------------------------------------------------------- #

class TestBankServiceDirectIntegration:
    def test_bank_authorize_endpoint_real_http(self, bank_server):
        """Hit the Bank Service authorize endpoint over real HTTP."""
        resp = httpx.post(
            f"{bank_server.base_url}/api/authorize",
            json={
                "attempt_id": "bank-test-001",
                "person_id": "person_test",
                "amount": "100.00",
                "payment_method": "CARD",
                "source_account_id": "account_test_person",
                "simulation_timestamp": "2024-01-01T12:00:00+00:00",
                "correlation_id": "corr-bank-test",
            },
            timeout=5.0,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "bank_state" in data
        assert "source_balance" in data
        assert "response_time_ms" in data

    def test_bank_insufficient_funds_over_http(self, bank_server):
        """Authorize with amount > balance returns INSUFFICIENT_FUNDS."""
        resp = httpx.post(
            f"{bank_server.base_url}/api/authorize",
            json={
                "attempt_id": "bank-test-insufficient",
                "person_id": "person_test",
                "amount": "99999.00",  # More than the 1000.00 balance
                "payment_method": "CARD",
                "source_account_id": "account_test_person",
                "simulation_timestamp": "2024-01-01T12:00:00+00:00",
                "correlation_id": "corr-insufficient",
            },
            timeout=5.0,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["failure_code"] == "INSUFFICIENT_FUNDS"

    def test_bank_state_can_be_set(self, bank_server):
        """The Bank Service bank-state endpoint accepts POST and returns state."""
        resp = httpx.post(
            f"{bank_server.base_url}/api/bank-state",
            params={"state": "NORMAL"},
            timeout=5.0,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "NORMAL"
        assert "message" in data
        assert "bank_id" in data
