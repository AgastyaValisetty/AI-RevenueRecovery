"""Tests for bank_service/app/api.py — HTTP endpoints via TestClient.

Tests cover:
- GET  /api/status       — service health and bank metrics
- POST /api/authorize    — full authorization flow (success, decline,
  UNKNOWN timeout, network error, insufficient funds)
- POST /api/bank-state    — manual state transitions

All tests use the in-memory SQLite ``app``/``client`` fixtures from conftest.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api import BankStateMachine, _derive_rng, _get_multiplier, _simulate_response_time
from app.domain import BankPolicy, BankState


# ------------------------------------------------------------------ #
# Helpers for deterministic outcome prediction
# ------------------------------------------------------------------ #

SIM_TS = "2024-01-01T12:00:00+00:00"
PERSON_ID = "test-person-id"
SOURCE_ACCOUNT = "test-account-id"


def _expected_roll(
    attempt_id: str,
    sim_ts_str: str | None,
    person_id: str,
    bank: BankPolicy,
) -> tuple[float, float]:
    """Reproduce the exact RNG roll the API will compute for a given request.

    Returns (roll, response_time_ms).
    """
    rng = _derive_rng(attempt_id, sim_ts_str, person_id)
    response_time_ms = _simulate_response_time(rng)
    roll = rng.random() * 100.0
    return roll, response_time_ms


def _expected_outcome(
    attempt_id: str,
    bank: BankPolicy,
) -> str:
    """Classify which bucket the roll falls into."""
    roll, _ = _expected_roll(attempt_id, SIM_TS, PERSON_ID, bank)
    multiplier = bank.state_multipliers.get(bank.current_state.value, 1.0)
    adjusted = bank.authorization_success_rate / multiplier
    timeout_b = bank.timeout_rate
    net_err_b = timeout_b + bank.network_error_rate
    success_b = net_err_b + adjusted

    if roll < timeout_b:
        return "timeout"
    elif roll < net_err_b:
        return "network_error"
    elif roll < success_b:
        return "success"
    else:
        return "decline"


def _find_attempt_id(bank: BankPolicy, desired_outcome: str, max_tries: int = 500_000) -> str:
    """Find an attempt_id whose predicted outcome matches ``desired_outcome``."""
    for i in range(max_tries):
        aid = f"find-aid-{i:010d}"
        if _expected_outcome(aid, bank) == desired_outcome:
            return aid
    pytest.fail(f"Could not find attempt_id for '{desired_outcome}' in {max_tries} tries")


# ------------------------------------------------------------------ #
# Fixtures — seed the database for API tests
# ------------------------------------------------------------------ #

@pytest.fixture
def seeded_bank(db) -> BankPolicy:
    """Insert a RupeeBank with default rates into the test database."""
    from app.repos import BankRepository
    repo = BankRepository(db)
    bank = BankPolicy(
        bank_id="rupee-bank-id",
        name="RupeeBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.NORMAL,
        state_multipliers={"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0},
        created_at=datetime.now(timezone.utc),
    )
    repo.add(bank)
    return bank


@pytest.fixture
def funded_account(db, seeded_bank):
    """Create a bank account with a 1000.00 credit balance."""
    from app.repos import BankRepository
    from app.schema import BankAccountRow
    repo = BankRepository(db)
    repo.add_account(repo._to_domain_account(BankAccountRow(
        account_id=SOURCE_ACCOUNT,
        person_id=PERSON_ID,
        bank_id=seeded_bank.bank_id,
        created_at=datetime.now(timezone.utc),
    )))
    credit_account(db, SOURCE_ACCOUNT, Decimal("1000.00"))
    return SOURCE_ACCOUNT


def credit_account(db, account_id: str, amount: Decimal) -> None:
    """Insert a ledger credit entry directly."""
    from app.schema import LedgerEntryRow
    with db.session() as session:
        session.add(LedgerEntryRow(
            entry_id=f"ledger-credit-{account_id[-8:]}-{datetime.now().timestamp()}",
            event_type="DEPOSIT",
            from_account_id=None,
            to_account_id=account_id,
            amount=amount,
            simulation_timestamp=datetime.now(timezone.utc),
            metadata_json="{}",
            created_at=datetime.now(timezone.utc),
        ))


# ------------------------------------------------------------------ #
# Status endpoint
# ------------------------------------------------------------------ #

class TestStatusEndpoint:
    def test_status_returns_service_info(self, client, seeded_bank):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "bank"
        assert data["status"] == "running"
        assert data["database_reachable"] is True
        assert data["bank"]["name"] == "RupeeBank"
        assert "current_state" in data["bank"]
        assert "authorization_success_rate" in data["bank"]

    def test_status_creates_default_bank_if_missing(self, client):
        """If no bank exists, status should still work (creates default)."""
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "bank"
        assert data["bank"]["name"] == "RupeeBank"

    def test_status_reports_settlement_account_and_balance(self, client, db):
        """Status should report the settlement account ID and bank balance."""
        from app.repos import BankRepository
        from app.domain import BankPolicy, BankState
        from app.schema import LedgerEntryRow
        repo = BankRepository(db)
        bank = BankPolicy(
            bank_id="status-bank-id",
            name="RupeeBank",
            authorization_success_rate=99.1,
            timeout_rate=0.3,
            issuer_decline_rate=0.4,
            network_error_rate=0.2,
            current_state=BankState.NORMAL,
            state_multipliers={"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0},
            created_at=datetime.now(timezone.utc),
        )
        repo.add(bank)

        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bank"]["settlement_account_id"] is not None
        assert data["bank"]["bank_balance"] == 0.0  # No credits yet

        # Credit the settlement account
        settlement_id = data["bank"]["settlement_account_id"]
        now = datetime.now(timezone.utc)
        with db.session() as session:
            session.add(LedgerEntryRow(
                entry_id="ledger-settle-status",
                event_type="PAYMENT_SETTLED",
                from_account_id="source-acc",
                to_account_id=settlement_id,
                amount=Decimal("500.00"),
                simulation_timestamp=now,
                metadata_json="{}",
                created_at=now,
            ))

        resp2 = client.get("/api/status")
        data2 = resp2.json()
        assert data2["bank"]["bank_balance"] == 500.0


# ------------------------------------------------------------------ #
# Authorize endpoint
# ------------------------------------------------------------------ #

class TestAuthorizeEndpoint:
    def test_insufficient_funds(self, client, seeded_bank):
        """Account with zero balance → INSUFFICIENT_FUNDS."""
        resp = client.post("/api/authorize", json={
            "attempt_id": "test-insufficient-001",
            "person_id": PERSON_ID,
            "amount": "500.00",
            "payment_method": "CARD",
            "source_account_id": "no-such-account",
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["failure_code"] == "INSUFFICIENT_FUNDS"
        assert data["unknown_outcome"] is False
        assert Decimal(data["source_balance"]) == Decimal("0")

    def test_success_path(self, client, seeded_bank, funded_account):
        """Successful authorization returns success with no failure code."""
        aid = _find_attempt_id(seeded_bank, "success")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-success",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["failure_code"] is None
        assert data["failure_reason"] is None
        assert data["unknown_outcome"] is False
        assert data["bank_state"] == "NORMAL"
        assert Decimal(data["source_balance"]) == Decimal("1000.00")
        assert data["authorized_at"] == SIM_TS

    def test_unknown_outcome_timeout(self, client, seeded_bank, funded_account):
        """Timeout path returns success=True but unknown_outcome=True."""
        aid = _find_attempt_id(seeded_bank, "timeout")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-timeout",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["unknown_outcome"] is True
        assert data["failure_code"] is None
        assert "delayed" in data["failure_reason"].lower()

    def test_network_error(self, client, seeded_bank, funded_account):
        """Network error path returns success=False with NETWORK_ERROR code."""
        aid = _find_attempt_id(seeded_bank, "network_error")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-neterr",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["failure_code"] == "NETWORK_ERROR"
        assert data["unknown_outcome"] is False

    def test_bank_decline(self, client, seeded_bank, funded_account):
        """Bank decline returns success=False with a decline failure code."""
        aid = _find_attempt_id(seeded_bank, "decline")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-decline",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["failure_code"] is not None
        assert data["unknown_outcome"] is False
        valid_codes = {"TIMEOUT", "HARD_DECLINE", "EXPIRED_CARD", "FRAUD_BLOCK", "NETWORK_ERROR"}
        assert data["failure_code"] in valid_codes

    def test_idempotency_same_attempt_id(self, client, seeded_bank, funded_account):
        """Same attempt_id must produce same result."""
        aid = _find_attempt_id(seeded_bank, "success")
        payload = {
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-idem-1",
        }
        resp1 = client.post("/api/authorize", json=payload)
        resp2 = client.post("/api/authorize", json={**payload, "correlation_id": "corr-idem-2"})
        data1 = resp1.json()
        data2 = resp2.json()
        # Core outcome must be identical
        assert data1["success"] == data2["success"]
        assert data1["failure_code"] == data2["failure_code"]
        assert data1["unknown_outcome"] == data2["unknown_outcome"]
        assert data1["response_time_ms"] == data2["response_time_ms"]

    def test_different_attempt_id_different_result(self, client, seeded_bank, funded_account):
        """Different attempt_ids can produce different outcomes (in degenerate cases)."""
        aid1 = _find_attempt_id(seeded_bank, "success")
        # Find a decline with a *different* attempt_id
        aid2 = _find_attempt_id(seeded_bank, "decline")
        assert aid1 != aid2  # Should be different

        resp1 = client.post("/api/authorize", json={
            "attempt_id": aid1,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-1",
        })
        resp2 = client.post("/api/authorize", json={
            "attempt_id": aid2,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-2",
        })
        data1 = resp1.json()
        data2 = resp2.json()
        assert data1["success"] is True
        assert data2["success"] is False

    def test_response_time_in_range(self, client, seeded_bank, funded_account):
        """Response time must be 50-500ms and recorded numerically."""
        aid = _find_attempt_id(seeded_bank, "success")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-rt",
        })
        data = resp.json()
        assert 50 <= data["response_time_ms"] <= 500

    def test_no_real_sleep(self, client, seeded_bank, funded_account):
        """The endpoint must return immediately (no real sleep for latency)."""
        import time
        aid = _find_attempt_id(seeded_bank, "success")
        start = time.monotonic()
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-nosleep",
        })
        elapsed = time.monotonic() - start
        assert elapsed < 3.0  # Should be fast, no real sleeping

    def test_simulation_timestamp_propagation(self, client, seeded_bank, funded_account):
        """The simulation_timestamp is used for the RNG seed and returned in response."""
        aid = _find_attempt_id(seeded_bank, "success")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": "2024-06-15T14:30:00+00:00",
            "correlation_id": "corr-ts",
        })
        data = resp.json()
        assert data["authorized_at"] == "2024-06-15T14:30:00+00:00"

    def test_outage_state_makes_failure_likely(self, client, db):
        """In OUTAGE state, most authorizations should fail."""
        from app.repos import BankRepository
        from app.schema import BankAccountRow, LedgerEntryRow
        repo = BankRepository(db)

        # Set up bank in OUTAGE
        bank = BankPolicy(
            bank_id="outage-bank-id",
            name="RupeeBank",
            authorization_success_rate=99.1,
            timeout_rate=0.3,
            issuer_decline_rate=0.4,
            network_error_rate=0.2,
            current_state=BankState.OUTAGE,
            state_multipliers={"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0},
            created_at=datetime.now(timezone.utc),
        )
        repo.add(bank)

        # Create funded account
        repo.add_account(repo._to_domain_account(BankAccountRow(
            account_id=SOURCE_ACCOUNT,
            person_id=PERSON_ID,
            bank_id=bank.bank_id,
            created_at=datetime.now(timezone.utc),
        )))
        with db.session() as session:
            session.add(LedgerEntryRow(
                entry_id="ledger-outage-1",
                event_type="DEPOSIT",
                from_account_id=None,
                to_account_id=SOURCE_ACCOUNT,
                amount=Decimal("1000.00"),
                simulation_timestamp=datetime.now(timezone.utc),
                metadata_json="{}",
                created_at=datetime.now(timezone.utc),
            ))

        # Find an attempt_id that produces decline (should be easy in OUTAGE)
        aid = _find_attempt_id(bank, "decline")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-outage",
        })
        data = resp.json()
        assert data["success"] is False
        assert data["bank_state"] == "OUTAGE"

    def test_correlation_id_accepted(self, client, seeded_bank, funded_account):
        """The X-Correlation-ID header is accepted and doesn't cause errors."""
        aid = _find_attempt_id(seeded_bank, "success")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "my-correlation-id-123",
        }, headers={"X-Correlation-ID": "my-correlation-id-123"})
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# Bank state endpoint
# ------------------------------------------------------------------ #

class TestBankStateEndpoint:
    def test_set_bank_state(self, client, seeded_bank):
        resp = client.post("/api/bank-state?state=OUTAGE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_state"] == "OUTAGE"

    def test_invalid_bank_state(self, client, seeded_bank):
        resp = client.post("/api/bank-state?state=INVALID")
        assert resp.status_code == 400
        assert "Invalid bank state" in resp.json()["detail"]

    def test_state_reflected_in_authorize(self, client, seeded_bank, funded_account):
        """After setting state, authorize should report the new state."""
        aid = _find_attempt_id(seeded_bank, "success")
        # Set to DEGRADED
        client.post("/api/bank-state?state=DEGRADED")
        resp = client.post("/api/authorize", json={
            "attempt_id": aid,
            "person_id": PERSON_ID,
            "amount": "100.00",
            "payment_method": "CARD",
            "source_account_id": SOURCE_ACCOUNT,
            "simulation_timestamp": SIM_TS,
            "correlation_id": "corr-degraded",
        })
        data = resp.json()
        assert data["bank_state"] == "DEGRADED"

    def test_state_cycled_through_all_states(self, client, seeded_bank, funded_account):
        """Cycle PEAK → DEGRADED → OUTAGE → NORMAL and verify each step."""
        rates = {"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0}
        bank = seeded_bank

        # PEAK: find an attempt_id that produces success in PEAK mode
        peak_bank = BankPolicy(
            bank_id=bank.bank_id,
            name=bank.name,
            authorization_success_rate=bank.authorization_success_rate,
            timeout_rate=bank.timeout_rate,
            issuer_decline_rate=bank.issuer_decline_rate,
            network_error_rate=bank.network_error_rate,
            current_state=BankState.PEAK,
            state_multipliers=rates,
            created_at=bank.created_at,
        )
        aid = _find_attempt_id(peak_bank, "success")

        states = ["PEAK", "DEGRADED", "OUTAGE"]
        for state in states:
            resp = client.post(f"/api/bank-state?state={state}")
            assert resp.status_code == 200

            resp = client.post("/api/authorize", json={
                "attempt_id": aid,
                "person_id": PERSON_ID,
                "amount": "100.00",
                "payment_method": "CARD",
                "source_account_id": SOURCE_ACCOUNT,
                "simulation_timestamp": SIM_TS,
                "correlation_id": f"corr-{state.lower()}",
            })
            data = resp.json()
            assert data["bank_state"] == state


# ------------------------------------------------------------------ #
# BankStateMachine unit tests (api.py version)
# ------------------------------------------------------------------ #

class TestBankStateMachineApi:
    def test_normal_to_peak_threshold(self):
        sm = BankStateMachine()
        result = sm.bank_state_transition(
            current_state=BankState.NORMAL,
            txn_count_last_minute=150,
            failure_rate_last_minute=2.5,
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result == BankState.PEAK

    def test_normal_stays_normal_low_traffic(self):
        sm = BankStateMachine()
        result = sm.bank_state_transition(
            current_state=BankState.NORMAL,
            txn_count_last_minute=10,
            failure_rate_last_minute=2.5,
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result is None

    def test_peak_to_degraded(self):
        sm = BankStateMachine()
        result = sm.bank_state_transition(
            current_state=BankState.PEAK,
            txn_count_last_minute=200,
            failure_rate_last_minute=6.0,
            consecutive_failures=10,
            outage_started_at=None,
        )
        assert result == BankState.DEGRADED

    def test_degraded_to_outage(self):
        sm = BankStateMachine()
        result = sm.bank_state_transition(
            current_state=BankState.DEGRADED,
            txn_count_last_minute=200,
            failure_rate_last_minute=12.0,
            consecutive_failures=20,
            outage_started_at=None,
        )
        assert result == BankState.OUTAGE

    def test_outage_no_recovery(self):
        sm = BankStateMachine()
        result = sm.bank_state_transition(
            current_state=BankState.OUTAGE,
            txn_count_last_minute=10,
            failure_rate_last_minute=60.0,
            consecutive_failures=50,
            outage_started_at=None,
        )
        assert result is None  # No outage_started_at → stays in OUTAGE

    def test_get_state_multiplier(self):
        sm = BankStateMachine()
        assert sm.get_state_multiplier(BankState.NORMAL) == 1.0
        assert sm.get_state_multiplier(BankState.PEAK) == 2.0
        assert sm.get_state_multiplier(BankState.DEGRADED) == 5.0
        assert sm.get_state_multiplier(BankState.OUTAGE) == 50.0


# ------------------------------------------------------------------ #
# RNG determinism
# ------------------------------------------------------------------ #

class TestRngDeterminism:
    def test_same_inputs_same_roll(self):
        rng1 = _derive_rng("attempt-1", SIM_TS, PERSON_ID)
        rng2 = _derive_rng("attempt-1", SIM_TS, PERSON_ID)
        # Consume response_time_ms (same call order as API)
        _ = _simulate_response_time(rng1)
        _ = _simulate_response_time(rng2)
        assert rng1.random() == rng2.random()

    def test_different_inputs_different_roll(self):
        rng1 = _derive_rng("attempt-1", SIM_TS, PERSON_ID)
        rng2 = _derive_rng("attempt-2", SIM_TS, PERSON_ID)
        _ = _simulate_response_time(rng1)
        _ = _simulate_response_time(rng2)
        assert rng1.random() != rng2.random()

    def test_no_simulation_timestamp(self):
        """Missing sim_ts should still produce a deterministic (but different) roll."""
        rng1 = _derive_rng("attempt-1", None, PERSON_ID)
        rng2 = _derive_rng("attempt-1", SIM_TS, PERSON_ID)
        _ = _simulate_response_time(rng1)
        _ = _simulate_response_time(rng2)
        assert rng1.random() != rng2.random()
