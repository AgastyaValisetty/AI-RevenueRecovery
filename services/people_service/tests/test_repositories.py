"""Tests for repository classes with in-memory SQLite."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.database import Database
from app.domain import (
    Bank,
    BankAccount,
    LedgerEntry,
    Merchant,
    PaymentIntent,
    Person,
    Product,
    SALARY_DEPOSIT,
    LIVING_COST,
    SETTLED,
    PENDING,
    SimulationRun,
    STATUS_PENDING,
    now,
)
from app.repositories import (
    BankRepository,
    LedgerRepository,
    MerchantRepository,
    PaymentIntentRepository,
    PersonRepository,
    ProductRepository,
    SimulationRunRepository,
    SubscriptionRepository,
)


@pytest.fixture
def db() -> Database:
    database = Database(engine_url="sqlite:///:memory:")
    database.create_schema()
    return database


@pytest.fixture
def bank_id() -> str:
    return str(uuid4())


class TestBankRepository:
    def test_add_and_find_by_name(self, db):
        repo = BankRepository(db)
        bank = Bank(
            bank_id=uuid4(),
            name="TestBank",
            authorization_success_rate=Decimal("99.5"),
            timeout_rate=Decimal("0.3"),
            issuer_decline_rate=Decimal("0.4"),
            network_error_rate=Decimal("0.2"),
            current_state="NORMAL",
            state_multipliers_json={"NORMAL": 1.0},
        )
        repo.add(bank)
        found = repo.find_by_name("TestBank")
        assert found is not None
        assert found.name == "TestBank"

    def test_status(self, db):
        repo = BankRepository(db)
        bank = Bank(
            bank_id=uuid4(),
            name="RupeeBank",
            authorization_success_rate=Decimal("99.1"),
            timeout_rate=Decimal("0.3"),
            issuer_decline_rate=Decimal("0.4"),
            network_error_rate=Decimal("0.2"),
            current_state="NORMAL",
            state_multipliers_json={"NORMAL": 1.0, "PEAK": 2.0},
        )
        repo.add(bank)
        status = repo.status()
        assert status["name"] == "RupeeBank"
        assert status["state"] == "NORMAL"


class TestPersonRepository:
    def test_add_and_find_all(self, db):
        repo = PersonRepository(db)
        bank_id = uuid4()
        people = [
            Person(
                person_id=uuid4(),
                name="Alice",
                age=30,
                salary=Decimal("50000"),
                salary_deposit_day=1,
                salary_deposit_hour=9,
                spending_profile_category="young_professional",
                spending_profile_json={"base_percentage": 1.5},
                payment_preferences_json={"UPI": 0.7},
                income_bracket="middle",
                age_group="early_career",
                employment_type="salaried",
                primary_bank_id=bank_id,
                primary_account_id=uuid4(),
            )
            for _ in range(5)
        ]
        accounts = [
            BankAccount(
                account_id=p.primary_account_id,
                person_id=p.person_id,
                bank_id=bank_id,
            )
            for p in people
        ]
        repo.add_people_with_accounts(people, accounts)

        found = repo.find_all()
        assert len(found) == 5
        assert found[0].name == "Alice"

    def test_count(self, db):
        repo = PersonRepository(db)
        assert repo.count() == 0


class TestLedgerRepository:
    def test_append_and_find_recent(self, db):
        repo = LedgerRepository(db)
        account_id = uuid4()
        entries = [
            LedgerEntry(
                entry_id=uuid4(),
                event_type=SALARY_DEPOSIT,
                from_account_id=None,
                to_account_id=account_id,
                amount=Decimal("50000"),
                simulation_timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
            ),
            LedgerEntry(
                entry_id=uuid4(),
                event_type=LIVING_COST,
                from_account_id=account_id,
                to_account_id=None,
                amount=Decimal("2000"),
                simulation_timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
        ]
        repo.append(entries)

        found = repo.find_recent(limit=500)
        assert len(found) == 2

    def test_balance_of(self, db):
        repo = LedgerRepository(db)
        account_id = uuid4()

        entries = [
            LedgerEntry(
                entry_id=uuid4(),
                event_type=SALARY_DEPOSIT,
                from_account_id=None,
                to_account_id=account_id,
                amount=Decimal("50000"),
                simulation_timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
            ),
            LedgerEntry(
                entry_id=uuid4(),
                event_type=LIVING_COST,
                from_account_id=account_id,
                to_account_id=None,
                amount=Decimal("2000"),
                simulation_timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
        ]
        repo.append(entries)

        balance = repo.balance_of(account_id)
        assert balance == Decimal("48000")

    def test_balances_for_accounts(self, db):
        repo = LedgerRepository(db)
        acc1 = uuid4()
        acc2 = uuid4()

        entries = [
            LedgerEntry(
                entry_id=uuid4(),
                event_type=SALARY_DEPOSIT,
                from_account_id=None,
                to_account_id=acc1,
                amount=Decimal("50000"),
                simulation_timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
            ),
            LedgerEntry(
                entry_id=uuid4(),
                event_type=SALARY_DEPOSIT,
                from_account_id=None,
                to_account_id=acc2,
                amount=Decimal("30000"),
                simulation_timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
            ),
        ]
        repo.append(entries)

        balances = repo.balances_for_accounts([acc1, acc2])
        assert balances[acc1] == Decimal("50000")
        assert balances[acc2] == Decimal("30000")

    def test_latest_simulation_timestamp(self, db):
        repo = LedgerRepository(db)
        assert repo.latest_simulation_timestamp() is None

        entry = LedgerEntry(
            entry_id=uuid4(),
            event_type=SALARY_DEPOSIT,
            from_account_id=None,
            to_account_id=uuid4(),
            amount=Decimal("50000"),
            simulation_timestamp=datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc),
        )
        repo.append([entry])

        latest = repo.latest_simulation_timestamp()
        # SQLite stores datetime without timezone; compare the naive part
        expected = datetime(2024, 6, 15, 10, 30)
        assert latest is not None
        assert latest.replace(tzinfo=None) == expected or latest == expected.replace(tzinfo=timezone.utc)


class TestSimulationRunRepository:
    def test_create_and_find(self, db):
        repo = SimulationRunRepository(db)
        run = SimulationRun(
            run_id=uuid4(),
            seed=42,
            config_snapshot={"version": "1.0.0"},
            people_count=100,
            hours_run=0,
            status=STATUS_PENDING,
            started_at=now(),
        )
        repo.create(run)

        found = repo.find(run.run_id)
        assert found is not None
        assert found.seed == 42
        assert found.people_count == 100

    def test_update_status(self, db):
        repo = SimulationRunRepository(db)
        run_id = uuid4()
        run = SimulationRun(
            run_id=run_id,
            seed=42,
            config_snapshot={"version": "1.0.0"},
            status=STATUS_PENDING,
        )
        repo.create(run)

        repo.update_status(run_id, "COMPLETED", hours_run=24)

        found = repo.find(run_id)
        assert found.status == "COMPLETED"
        assert found.hours_run == 24

    def test_find_latest(self, db):
        repo = SimulationRunRepository(db)

        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        run1 = SimulationRun(
            run_id=uuid4(), seed=42, config_snapshot={}, status="COMPLETED",
            created_at=base,
        )
        run2 = SimulationRun(
            run_id=uuid4(), seed=43, config_snapshot={}, status="COMPLETED",
            created_at=base + timedelta(seconds=1),
        )
        repo.create(run1)
        repo.create(run2)

        latest = repo.find_latest()
        assert latest is not None
        assert latest.seed == 43  # most recent


class TestSubscriptionRepository:
    def test_find_due_on(self, db):
        repo = SubscriptionRepository(db)
        from app.domain import Subscription, ACTIVE, MONTHLY
        sub = Subscription(
            subscription_id=uuid4(),
            person_id=uuid4(),
            merchant_id=uuid4(),
            product_id=uuid4(),
            amount=Decimal("500"),
            billing_cycle=MONTHLY,
            status=ACTIVE,
            next_billing_date=date(2024, 1, 15),
        )
        repo.add([sub])

        due = repo.find_due_on(date(2024, 1, 15))
        assert len(due) == 1

        not_due = repo.find_due_on(date(2024, 1, 16))
        assert len(not_due) == 0


class TestPaymentIntentRepository:
    def test_add_and_find_pending(self, db):
        repo = PaymentIntentRepository(db)
        intent = PaymentIntent(
            intent_id=uuid4(),
            person_id=uuid4(),
            merchant_id=uuid4(),
            product_id=uuid4(),
            amount=Decimal("500"),
            payment_method="UPI",
            status=PENDING,
            related_subscription_id=None,
        )
        repo.add([intent])

        pending = repo.find_pending()
        assert len(pending) == 1
        assert pending[0].status == PENDING
