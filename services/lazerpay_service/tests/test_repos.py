"""Tests for lazerpay_service/app/repos.py — repository layer.

Tests cover PaymentAttempt persistence, idempotency, and ledger entry
writing against an in-memory SQLite database.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.repos import LazerPayRepository
from app.schema import IdempotencyKeyRow, PaymentAttemptRow


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def repo(db) -> LazerPayRepository:
    return LazerPayRepository(db)


@pytest.fixture
def sample_attempt() -> PaymentAttemptRow:
    now = datetime.now(timezone.utc)
    return PaymentAttemptRow(
        attempt_id="test-attempt-001",
        intent_id="intent-001",
        attempt_number=1,
        person_id="person-001",
        merchant_id="merchant-001",
        amount=Decimal("100.00"),
        payment_method="CARD",
        source_account_id="account-001",
        destination_account_id=None,
        idempotency_key="idem_intent-001_1",
        status="INITIATED",
        failure_code=None,
        failure_reason=None,
        related_attempt_id=None,
        initiated_at=now,
        routed_at=None,
        authorized_at=None,
        settled_at=None,
        failed_at=None,
        unknown_at=None,
        bank_response_time_ms=None,
        gateway_latency_ms=None,
        bank_state=None,
        simulation_timestamp=now,
        correlation_id="corr-001",
        retry_for_attempt_id=None,
        created_at=now,
    )


# ------------------------------------------------------------------ #
# Attempt creation and lookup
# ------------------------------------------------------------------ #

class TestAttemptCreation:
    def test_create_and_find_by_attempt_id(self, repo, sample_attempt):
        repo.create_attempt(sample_attempt)
        found = repo.find_by_attempt_id(sample_attempt.attempt_id)
        assert found is not None
        assert found.attempt_id == sample_attempt.attempt_id
        assert found.intent_id == sample_attempt.intent_id
        assert found.status == "INITIATED"

    def test_find_by_attempt_id_not_found(self, repo):
        assert repo.find_by_attempt_id("does-not-exist") is None

    def test_find_by_idempotency_key(self, repo, sample_attempt):
        repo.create_attempt(sample_attempt)
        found = repo.find_by_idempotency_key(sample_attempt.idempotency_key)
        assert found is not None
        assert found.attempt_id == sample_attempt.attempt_id

    def test_find_by_idempotency_key_not_found(self, repo):
        assert repo.find_by_idempotency_key("nonexistent-key") is None


# ------------------------------------------------------------------ #
# Attempt updates
# ------------------------------------------------------------------ #

class TestAttemptUpdates:
    def test_update_status(self, repo, sample_attempt):
        repo.create_attempt(sample_attempt)
        repo.update_attempt(sample_attempt.attempt_id, status="SETTLED", settled_at=datetime.now(timezone.utc))
        found = repo.find_by_attempt_id(sample_attempt.attempt_id)
        assert found.status == "SETTLED"
        assert found.settled_at is not None

    def test_update_failure_fields(self, repo, sample_attempt):
        repo.create_attempt(sample_attempt)
        repo.update_attempt(
            sample_attempt.attempt_id,
            status="FAILED",
            failure_code="HARD_DECLINE",
            failure_reason="Card declined",
            failed_at=datetime.now(timezone.utc),
        )
        found = repo.find_by_attempt_id(sample_attempt.attempt_id)
        assert found.status == "FAILED"
        assert found.failure_code == "HARD_DECLINE"
        assert found.failure_reason == "Card declined"
        assert found.failed_at is not None

    def test_update_multiple_fields(self, repo, sample_attempt):
        repo.create_attempt(sample_attempt)
        ts = datetime.now(timezone.utc)
        repo.update_attempt(
            sample_attempt.attempt_id,
            status="SETTLED",
            bank_response_time_ms=150,
            gateway_latency_ms=200,
            bank_state="NORMAL",
            settled_at=ts,
        )
        found = repo.find_by_attempt_id(sample_attempt.attempt_id)
        assert found.status == "SETTLED"
        assert found.bank_response_time_ms == 150
        assert found.gateway_latency_ms == 200
        assert found.bank_state == "NORMAL"

    def test_update_nonexistent_attempt(self, repo):
        """Updating a non-existent attempt should not raise."""
        repo.update_attempt("nonexistent", status="SETTLED")


# ------------------------------------------------------------------ #
# Query methods
# ------------------------------------------------------------------ #

class TestAttemptQueries:
    def test_find_pending(self, repo, db):
        """find_pending returns INITIATED, ROUTING, AUTHORIZED attempts."""
        for status in ["INITIATED", "ROUTING", "AUTHORIZED", "SETTLED", "FAILED", "UNKNOWN"]:
            repo.create_attempt(PaymentAttemptRow(
                attempt_id=f"attempt-{status}",
                intent_id="intent-001",
                attempt_number=1,
                person_id="person-001",
                merchant_id="merchant-001",
                amount=Decimal("100.00"),
                payment_method="CARD",
                source_account_id="account-001",
                destination_account_id=None,
                idempotency_key=f"key-{status}",
                status=status,
                simulation_timestamp=datetime.now(timezone.utc),
                correlation_id=None,
                related_attempt_id=None,
                retry_for_attempt_id=None,
                created_at=datetime.now(timezone.utc),
            ))

        pending = repo.find_pending()
        statuses = {a.status for a in pending}
        assert statuses == {"INITIATED", "ROUTING", "AUTHORIZED"}
        assert len(pending) == 3

    def test_find_by_status(self, repo):
        now = datetime.now(timezone.utc)
        for i, status in enumerate(["SETTLED", "SETTLED", "FAILED"]):
            repo.create_attempt(PaymentAttemptRow(
                attempt_id=f"attempt-{status}-{i}",
                intent_id="intent-001",
                attempt_number=1,
                person_id="person-001",
                merchant_id="merchant-001",
                amount=Decimal("100.00"),
                payment_method="CARD",
                source_account_id="account-001",
                destination_account_id=None,
                idempotency_key=f"key-{status}-{i}",
                status=status,
                simulation_timestamp=now,
                correlation_id=None,
                related_attempt_id=None,
                retry_for_attempt_id=None,
                created_at=now,
            ))

        settled = repo.find_by_status("SETTLED")
        assert len(settled) == 2
        assert all(a.status == "SETTLED" for a in settled)

    def test_find_by_intent(self, repo):
        """find_by_intent returns all attempts for an intent, ordered by attempt_number."""
        now = datetime.now(timezone.utc)
        for i in range(3):
            repo.create_attempt(PaymentAttemptRow(
                attempt_id=f"attempt-{i}",
                intent_id="intent-shared",
                attempt_number=i + 1,
                person_id="person-001",
                merchant_id="merchant-001",
                amount=Decimal("100.00"),
                payment_method="CARD",
                source_account_id="account-001",
                destination_account_id=None,
                idempotency_key=f"key-{i}",
                status="SETTLED" if i < 2 else "FAILED",
                simulation_timestamp=now,
                correlation_id=None,
                related_attempt_id=f"attempt-{i-1}" if i > 0 else None,
                retry_for_attempt_id=f"attempt-{i-1}" if i > 0 else None,
                created_at=now,
            ))

        attempts = repo.find_by_intent("intent-shared")
        assert len(attempts) == 3
        # Should be ordered by attempt_number
        assert [a.attempt_number for a in attempts] == [1, 2, 3]


# ------------------------------------------------------------------ #
# Idempotency
# ------------------------------------------------------------------ #

class TestIdempotency:
    def test_record_and_duplicate_key_rejected(self, repo, db):
        """The unique constraint on key prevents duplicate keys."""
        repo.record_idempotency_key("idem-key-1", "attempt-1")

        # Duplicate key should fail
        with pytest.raises(Exception):  # IntegrityError
            repo.record_idempotency_key("idem-key-1", "attempt-2")

        # Duplicate attempt_id should also fail
        with pytest.raises(Exception):
            repo.record_idempotency_key("idem-key-2", "attempt-1")

    def test_clear_idempotency_key(self, repo, db):
        """clear_idempotency_key removes a key from the idempotency_keys table."""
        repo.record_idempotency_key("idem-key-clear", "attempt-clear")

        # Verify the key exists
        with db.session() as session:
            row = session.scalar(select(IdempotencyKeyRow).where(IdempotencyKeyRow.key == "idem-key-clear"))
            assert row is not None

        repo.clear_idempotency_key("idem-key-clear")

        # Verify the key is gone
        with db.session() as session:
            row = session.scalar(select(IdempotencyKeyRow).where(IdempotencyKeyRow.key == "idem-key-clear"))
            assert row is None

    def test_clear_nonexistent_key(self, repo):
        """Clearing a non-existent key should not raise."""
        repo.clear_idempotency_key("nonexistent-key")


# ------------------------------------------------------------------ #
# Ledger entries
# ------------------------------------------------------------------ #

class TestLedgerEntries:
    def test_write_ledger_entry(self, repo, db):
        """write_ledger_entry inserts a row into the shared ledger_entries table."""
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        repo.write_ledger_entry(
            event_type="PAYMENT_SETTLED",
            from_account_id="account-001",
            to_account_id="merchant-001",
            amount=Decimal("100.00"),
            simulation_timestamp=now,
            related_attempt_id="attempt-001",
            metadata_json={"key": "value"},
        )

        with db._engine.connect() as conn:
            rows = conn.execute(text("SELECT event_type, from_account_id, to_account_id, amount, metadata_json FROM ledger_entries")).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "PAYMENT_SETTLED"
            assert rows[0][1] == "account-001"
            assert rows[0][2] == "merchant-001"
            assert Decimal(rows[0][3]) == Decimal("100.00")

    def test_write_multiple_ledger_entries(self, repo, db):
        """Multiple ledger entries are written independently."""
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        repo.write_ledger_entry(
            event_type="PAYMENT_FAILED",
            from_account_id=None,
            to_account_id=None,
            amount=Decimal("0"),
            simulation_timestamp=now,
            related_attempt_id="attempt-001",
        )
        repo.write_ledger_entry(
            event_type="PAYMENT_SETTLED",
            from_account_id="account-002",
            to_account_id="merchant-002",
            amount=Decimal("250.00"),
            simulation_timestamp=now,
            related_attempt_id="attempt-002",
        )

        with db._engine.connect() as conn:
            rows = conn.execute(text("SELECT event_type, amount FROM ledger_entries")).fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "PAYMENT_FAILED"
            assert rows[1][0] == "PAYMENT_SETTLED"

    def test_write_ledger_entry_zero_amount(self, repo, db):
        """UNKNOWN/failed ledger entries have amount=0 (no money moved)."""
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        repo.write_ledger_entry(
            event_type="PAYMENT_UNKNOWN",
            from_account_id="account-001",
            to_account_id=None,
            amount=Decimal("0"),
            simulation_timestamp=now,
        )

        with db._engine.connect() as conn:
            rows = conn.execute(text("SELECT amount FROM ledger_entries WHERE event_type = 'PAYMENT_UNKNOWN'")).fetchall()
            assert len(rows) == 1
            assert Decimal(rows[0][0]) == Decimal("0")
