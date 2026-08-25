"""Tests for bank_service/app/repos.py — repository layer.

All tests use the in-memory SQLite ``db`` fixture from conftest.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain import BankAccount, BankPolicy, BankState
from app.repos import BankRepository
from app.schema import LedgerEntryRow


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def bank() -> BankPolicy:
    return BankPolicy(
        bank_id="test-bank-id",
        name="TestBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.NORMAL,
        state_multipliers={"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0},
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def account() -> BankAccount:
    return BankAccount(
        account_id="test-account-id",
        bank_id="test-bank-id",
        person_id="test-person-id",
        balance=0.0,
        created_at=datetime.now(timezone.utc),
    )


# ------------------------------------------------------------------ #
# Bank policy CRUD
# ------------------------------------------------------------------ #

class TestBankPolicy:
    def test_add_and_find_by_name(self, db, bank):
        repo = BankRepository(db)
        repo.add(bank)
        found = repo.find_by_name(bank.name)
        assert found is not None
        assert found.bank_id == bank.bank_id
        assert found.name == bank.name
        assert found.authorization_success_rate == bank.authorization_success_rate

    def test_find_by_name_not_found(self, db):
        repo = BankRepository(db)
        assert repo.find_by_name("NonExistent") is None

    def test_find_by_id(self, db, bank):
        repo = BankRepository(db)
        repo.add(bank)
        found = repo.find_by_id(bank.bank_id)
        assert found is not None
        assert found.name == bank.name

    def test_find_by_id_not_found(self, db):
        repo = BankRepository(db)
        assert repo.find_by_id("does-not-exist") is None

    def test_update_state(self, db, bank):
        repo = BankRepository(db)
        repo.add(bank)
        repo.update_state(bank.bank_id, BankState.OUTAGE)
        found = repo.find_by_id(bank.bank_id)
        assert found.current_state == BankState.OUTAGE

    def test_update_state_nonexistent_bank(self, db):
        repo = BankRepository(db)
        # Should not raise even if bank doesn't exist
        repo.update_state("nonexistent", BankState.OUTAGE)

    def test_state_multipliers_roundtrip(self, db, bank):
        repo = BankRepository(db)
        repo.add(bank)
        found = repo.find_by_name(bank.name)
        assert found.state_multipliers == bank.state_multipliers


# ------------------------------------------------------------------ #
# Account balance (from ledger_entries)
# ------------------------------------------------------------------ #

class TestAccountBalance:
    def test_balance_empty(self, db, account):
        """Account with no ledger entries has zero balance."""
        repo = BankRepository(db)
        repo.add_account(account)
        balance = repo.get_balance(account.account_id)
        assert balance == Decimal("0")

    def test_balance_with_credit(self, db, account):
        """Credit entries increase the balance."""
        repo = BankRepository(db)
        repo.add_account(account)
        # Insert a ledger credit directly (Bank Service doesn't own ledger_entries)
        with db.session() as session:
            session.add(LedgerEntryRow(
                entry_id="test-ledger-1",
                event_type="DEPOSIT",
                from_account_id=None,
                to_account_id=account.account_id,
                amount=Decimal("100.00"),
                simulation_timestamp=datetime.now(timezone.utc),
                metadata_json="{}",
                created_at=datetime.now(timezone.utc),
            ))
        balance = repo.get_balance(account.account_id)
        assert balance == Decimal("100.00")

    def test_balance_with_debit(self, db, account):
        """Debit entries decrease the balance."""
        repo = BankRepository(db)
        repo.add_account(account)
        now = datetime.now(timezone.utc)
        # Insert a credit then a debit
        with db.session() as session:
            session.add(LedgerEntryRow(
                entry_id="test-ledger-1",
                event_type="DEPOSIT",
                from_account_id=None,
                to_account_id=account.account_id,
                amount=Decimal("200.00"),
                simulation_timestamp=now,
                metadata_json="{}",
                created_at=now,
            ))
            session.add(LedgerEntryRow(
                entry_id="test-ledger-2",
                event_type="WITHDRAWAL",
                from_account_id=account.account_id,
                to_account_id=None,
                amount=Decimal("50.00"),
                simulation_timestamp=now,
                metadata_json="{}",
                created_at=now,
            ))
        balance = repo.get_balance(account.account_id)
        assert balance == Decimal("150.00")

    def test_balance_account_not_in_ledger(self, db):
        """Balance for an account not in ledger_entries returns zero."""
        repo = BankRepository(db)
        balance = repo.get_balance("unknown-account")
        assert balance == Decimal("0")


# ------------------------------------------------------------------ #
# Account CRUD
# ------------------------------------------------------------------ #

class TestAccountRepository:
    def test_add_account(self, db, account):
        repo = BankRepository(db)
        repo.add_account(account)
        found = repo.get_account(account.account_id)
        assert found is not None
        assert found.account_id == account.account_id
        assert found.person_id == account.person_id
        assert found.bank_id == account.bank_id

    def test_get_account_not_found(self, db):
        repo = BankRepository(db)
        assert repo.get_account("nonexistent") is None

    def test_find_account_by_person_and_bank(self, db, account):
        repo = BankRepository(db)
        repo.add_account(account)
        found = repo.find_account_by_person_and_bank(account.person_id, account.bank_id)
        assert found is not None
        assert found.account_id == account.account_id

    def test_find_account_by_person_and_bank_not_found(self, db):
        repo = BankRepository(db)
        assert repo.find_account_by_person_and_bank("nobody", "nobank") is None

    def test_get_accounts_by_person(self, db, account):
        repo = BankRepository(db)
        repo.add_account(account)
        # Add second account for same person
        account2 = BankAccount(
            account_id="test-account-id-2",
            bank_id="different-bank",
            person_id=account.person_id,
            balance=0.0,
            created_at=datetime.now(timezone.utc),
        )
        repo.add_account(account2)
        accounts = repo.get_accounts_by_person(account.person_id)
        assert len(accounts) == 2
        account_ids = {a.account_id for a in accounts}
        assert account_ids == {account.account_id, account2.account_id}

    def test_get_accounts_by_person_empty(self, db):
        repo = BankRepository(db)
        assert repo.get_accounts_by_person("nobody") == []


# ------------------------------------------------------------------ #
# Transaction metrics
# ------------------------------------------------------------------ #

class TestTransactionMetrics:
    def test_record_and_status_empty(self, db, bank):
        """Status with no recorded transactions returns zeros."""
        repo = BankRepository(db)
        repo.add(bank)
        status = repo.status(bank.bank_id)
        assert status.transactions_last_minute == 0
        assert status.success_rate == 0.0
        assert status.failure_rate == 0.0

    def test_record_success(self, db, bank):
        repo = BankRepository(db)
        repo.add(bank)
        now = datetime.now(timezone.utc)
        repo.record_transaction_result(
            bank.bank_id, True, now, response_time_ms=150, outcome="SETTLED"
        )
        status = repo.status(bank.bank_id)
        assert status.transactions_last_minute == 1
        assert status.success_rate == 100.0
        assert status.failure_rate == 0.0

    def test_record_failure(self, db, bank):
        repo = BankRepository(db)
        repo.add(bank)
        now = datetime.now(timezone.utc)
        repo.record_transaction_result(
            bank.bank_id, False, now, response_time_ms=100, outcome="FAILED"
        )
        status = repo.status(bank.bank_id)
        assert status.transactions_last_minute == 1
        assert status.success_rate == 0.0
        assert status.failure_rate == 100.0

    def test_record_mixed_outcomes(self, db, bank):
        repo = BankRepository(db)
        repo.add(bank)
        now = datetime.now(timezone.utc)
        repo.record_transaction_result(bank.bank_id, True, now, 100, "SETTLED")
        repo.record_transaction_result(bank.bank_id, True, now, 120, "SETTLED")
        repo.record_transaction_result(bank.bank_id, False, now, 90, "FAILED")
        status = repo.status(bank.bank_id)
        assert status.transactions_last_minute == 3
        assert status.success_rate == pytest.approx(66.67, rel=0.01)
        assert status.failure_rate == pytest.approx(33.33, rel=0.01)

    def test_transactions_outside_window_excluded(self, db, bank):
        """Transactions older than 1 minute should not count."""
        repo = BankRepository(db)
        repo.add(bank)
        old_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        recent = datetime.now(timezone.utc) - timedelta(seconds=10)
        repo.record_transaction_result(bank.bank_id, True, old_time, 100, "SETTLED")
        repo.record_transaction_result(bank.bank_id, True, recent, 120, "SETTLED")
        status = repo.status(bank.bank_id)
        assert status.transactions_last_minute == 1
        assert status.success_rate == 100.0

    def test_status_reports_settlement_balance(self, db, bank):
        """Bank status balance should reflect settlement account balance."""
        repo = BankRepository(db)
        repo.add(bank)

        # Create a settlement account and link it to the bank
        settlement_id = repo.get_or_create_settlement_account(bank.bank_id)
        assert settlement_id is not None

        # Before any credits, balance should be zero
        status = repo.status(bank.bank_id)
        assert status.balance == 0.0

        # Credit the settlement account
        now = datetime.now(timezone.utc)
        with db.session() as session:
            from app.schema import LedgerEntryRow
            session.add(LedgerEntryRow(
                entry_id="ledger-settle-1",
                event_type="PAYMENT_SETTLED",
                from_account_id="source-account",
                to_account_id=settlement_id,
                amount=Decimal("100.00"),
                simulation_timestamp=now,
                metadata_json="{}",
                created_at=now,
            ))

        # Now the bank's reported balance should include the settled funds
        status = repo.status(bank.bank_id)
        assert status.balance == 100.0


# ------------------------------------------------------------------ #
# Settlement accounts
# ------------------------------------------------------------------ #

class TestSettlementAccounts:
    def test_create_settlement_account(self, db, bank):
        """get_or_create_settlement_account creates an account and stores its ID on the bank."""
        repo = BankRepository(db)
        repo.add(bank)

        settlement_id = repo.get_or_create_settlement_account(bank.bank_id)
        assert settlement_id is not None
        assert settlement_id.startswith("settlement-")

        # Verify the bank row was updated
        found = repo.find_by_id(bank.bank_id)
        assert found.settlement_account_id == settlement_id

    def test_settlement_account_has_no_person(self, db, bank):
        """Settlement accounts are bank-owned (person_id IS NULL)."""
        repo = BankRepository(db)
        repo.add(bank)

        settlement_id = repo.get_or_create_settlement_account(bank.bank_id)
        account = repo.get_account(settlement_id)
        assert account is not None
        assert account.person_id is None
        assert account.bank_id == bank.bank_id

    def test_settlement_account_idempotent(self, db, bank):
        """Calling get_or_create_settlement_account twice returns the same ID."""
        repo = BankRepository(db)
        repo.add(bank)

        id1 = repo.get_or_create_settlement_account(bank.bank_id)
        id2 = repo.get_or_create_settlement_account(bank.bank_id)
        assert id1 == id2

    def test_settlement_account_balance_from_ledger(self, db, bank):
        """Settlement account balance is calculated from ledger entries."""
        repo = BankRepository(db)
        repo.add(bank)

        settlement_id = repo.get_or_create_settlement_account(bank.bank_id)

        # No credits → zero balance
        assert repo.get_balance(settlement_id) == Decimal("0")

        # Add credits
        now = datetime.now(timezone.utc)
        with db.session() as session:
            from app.schema import LedgerEntryRow
            session.add(LedgerEntryRow(
                entry_id="ledger-settle-a",
                event_type="PAYMENT_SETTLED",
                from_account_id="source-a",
                to_account_id=settlement_id,
                amount=Decimal("250.00"),
                simulation_timestamp=now,
                metadata_json="{}",
                created_at=now,
            ))
            session.add(LedgerEntryRow(
                entry_id="ledger-settle-b",
                event_type="PAYMENT_SETTLED",
                from_account_id="source-b",
                to_account_id=settlement_id,
                amount=Decimal("750.00"),
                simulation_timestamp=now,
                metadata_json="{}",
                created_at=now,
            ))

        balance = repo.get_balance(settlement_id)
        assert balance == Decimal("1000.00")

    def test_update_settlement_account_id(self, db, bank):
        """update_settlement_account_id links a settlement account to a bank."""
        repo = BankRepository(db)
        repo.add(bank)

        # Initially no settlement account
        found = repo.find_by_id(bank.bank_id)
        assert found.settlement_account_id is None

        # Set it
        repo.update_settlement_account(bank.bank_id, "my-settlement-id")
        found = repo.find_by_id(bank.bank_id)
        assert found.settlement_account_id == "my-settlement-id"

        # Clear it
        repo.update_settlement_account(bank.bank_id, None)
        found = repo.find_by_id(bank.bank_id)
        assert found.settlement_account_id is None
