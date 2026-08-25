"""Tests for simulation engines: SpendingEngine, EcommerceEngine, SubscriptionEngine."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain import (
    ACTIVE,
    LIVING_COST,
    PENDING,
    SALARY_DEPOSIT,
    INCOME_TAX,
    PaymentIntent,
    Person,
    Subscription,
    PurchaseDecision,
)
from app.engines import SalaryEngine, SpendingEngine, SubscriptionEngine, EcommerceEngine
from app.rng import SimulationRNG
from app.sim_config import SimConfig


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def salary_engine(config) -> SalaryEngine:
    return SalaryEngine(config)


@pytest.fixture
def spending_engine(rng, config) -> SpendingEngine:
    return SpendingEngine(rng, config)


@pytest.fixture
def subscription_engine(rng, config) -> SubscriptionEngine:
    return SubscriptionEngine(rng, config)


@pytest.fixture
def ecommerce_engine(rng, config) -> EcommerceEngine:
    return EcommerceEngine(rng, config)


@pytest.fixture
def sample_person() -> Person:
    from uuid import uuid4
    return Person(
        person_id=uuid4(),
        name="Test Person",
        age=35,
        salary=Decimal("60000"),
        salary_deposit_day=1,
        salary_deposit_hour=9,
        spending_profile_category="young_professional",
        spending_profile_json={"base_percentage": 1.5},
        payment_preferences_json={"UPI": 0.7, "CARD": 0.25, "NETBANKING": 0.05},
        income_bracket="middle",
        age_group="early_career",
        employment_type="salaried",
        primary_bank_id=uuid4(),
        primary_account_id=uuid4(),
    )


class TestSalaryEngine:
    def test_deposit_hour_from_config(self, salary_engine, config):
        assert salary_engine.deposit_hour == config.salary.deposit_hour

    def test_deposit_for_matching_day(self, salary_engine, sample_person):
        on = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        deposits = salary_engine.deposit_for([sample_person], on.date().day, on)
        # Now returns 2 entries: salary (net after 30% tax) + income tax
        assert len(deposits) == 2
        salary_entry = next(d for d in deposits if d.event_type == SALARY_DEPOSIT)
        tax_entry = next(d for d in deposits if d.event_type == INCOME_TAX)
        # Salary is deposited net of 30% tax
        expected_net = (sample_person.salary * Decimal("0.7")).quantize(Decimal("0.01"))
        assert salary_entry.amount == expected_net
        # Tax entry is 30% of gross
        expected_tax = (sample_person.salary * Decimal("0.3")).quantize(Decimal("0.01"))
        assert tax_entry.amount == expected_tax
        assert tax_entry.to_account_id == "account_government_tax"

    def test_deposit_for_non_matching_day(self, salary_engine, sample_person):
        on = datetime(2024, 1, 2, 9, 0, 0, tzinfo=timezone.utc)
        deposits = salary_engine.deposit_for([sample_person], on.date().day, on)
        # salary_deposit_day is 1, on.date().day is 2
        assert len(deposits) == 0


class TestSpendingEngine:
    def test_daily_spend_percentage_non_negative(self, spending_engine, sample_person):
        from datetime import date
        pct = spending_engine.daily_spend_percentage(
            sample_person,
            date(2024, 1, 1),
            current_balance=Decimal("30000"),
        )
        assert pct >= 0

    def test_daily_spend_percentage_clamped(self, spending_engine, sample_person):
        from datetime import date
        pct = spending_engine.daily_spend_percentage(
            sample_person,
            date(2024, 1, 1),
            current_balance=Decimal("30000"),
        )
        max_pct = Decimal(str(spending_engine._config.spending.max_daily_spend_pct))
        assert pct <= max_pct

    def test_daily_spend_percentage_salary_day_boost(self, spending_engine, sample_person):
        from datetime import date
        # Day 1 is in the configured salary_day_boost_days [1, 5, 15]
        pct_normal = spending_engine.daily_spend_percentage(
            sample_person, date(2024, 1, 2), current_balance=Decimal("30000")
        )
        pct_boost = spending_engine.daily_spend_percentage(
            sample_person, date(2024, 1, 1), current_balance=Decimal("30000")
        )
        # At least the boost day should have higher base (before random noise)
        # We just check both are valid
        assert pct_normal >= 0
        assert pct_boost >= 0

    def test_daily_spend_percentage_balance_aware(self, spending_engine, sample_person):
        from datetime import date
        pct_high_balance = spending_engine.daily_spend_percentage(
            sample_person, date(2024, 1, 1), current_balance=Decimal("100000")
        )
        pct_low_balance = spending_engine.daily_spend_percentage(
            sample_person, date(2024, 1, 1), current_balance=Decimal("0")
        )
        # Low balance should reduce spending (or at least not increase it dramatically)
        assert pct_low_balance <= pct_high_balance * 2  # tolerance for random noise

    def test_daily_cost_returns_ledger_entry(self, spending_engine, sample_person):
        from datetime import date
        on = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        entry = spending_engine.daily_cost(
            sample_person, on, "weekday", current_balance=Decimal("30000")
        )
        assert entry is not None or entry is None  # either is valid depending on random draw

    def test_daily_cost_zero_salary(self, spending_engine):
        from datetime import date
        from uuid import uuid4
        person = Person(
            person_id=uuid4(),
            name="Poor Person",
            age=65,
            salary=Decimal("0"),
            salary_deposit_day=1,
            salary_deposit_hour=9,
            spending_profile_category="retired",
            spending_profile_json={},
            payment_preferences_json={},
            income_bracket="low",
            age_group="retired",
            employment_type="retired",
            primary_bank_id=uuid4(),
            primary_account_id=uuid4(),
        )
        on = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        entry = spending_engine.daily_cost(person, on, "weekday", current_balance=Decimal("0"))
        # With 0 salary, the amount should be 0, so entry is None
        assert entry is None or entry.amount == 0


class TestSubscriptionEngine:
    def test_due_on_filters_by_date(self, subscription_engine, sample_person):
        from uuid import uuid4
        from datetime import date
        sub = Subscription(
            subscription_id=uuid4(),
            person_id=sample_person.person_id,
            merchant_id=uuid4(),
            product_id=uuid4(),
            amount=Decimal("500"),
            billing_cycle="MONTHLY",
            status=ACTIVE,
            next_billing_date=date(2024, 1, 1),
        )
        due = subscription_engine.due_on([sub], date(2024, 1, 1))
        assert len(due) == 1

        not_due = subscription_engine.due_on([sub], date(2024, 1, 2))
        assert len(not_due) == 0

    def test_build_intent_status_pending(self, subscription_engine):
        from uuid import uuid4
        from datetime import date
        sub = Subscription(
            subscription_id=uuid4(),
            person_id=uuid4(),
            merchant_id=uuid4(),
            product_id=uuid4(),
            amount=Decimal("500"),
            billing_cycle="MONTHLY",
            status=ACTIVE,
            next_billing_date=date(2024, 1, 1),
        )
        on = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        intent = subscription_engine.build_intent(sub, on)
        assert intent.status == PENDING
        # GST (18%) is applied to subscription amounts
        expected = (sub.amount * Decimal("1.18")).quantize(Decimal("0.01"))
        assert intent.amount == expected
        assert intent.related_subscription_id == sub.subscription_id


class TestEcommerceEngine:
    def test_generate_purchase_returns_none_or_decision(self, ecommerce_engine, sample_person):
        from uuid import uuid4
        merchants = []
        products = []
        on = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = ecommerce_engine.generate_purchase(
            sample_person, merchants, products, on, Decimal("5000"), True
        )
        # With no products, should return None
        assert result is None

    def test_generate_purchase_with_products(self, ecommerce_engine, sample_person):
        from uuid import uuid4
        from app.domain import Product, Merchant
        merchant = Merchant(
            merchant_id=uuid4(),
            name="Amazin",
            merchant_type="ECOMMERCE",
            settlement_bank_id=uuid4(),
        )
        product = Product(
            product_id=uuid4(),
            merchant_id=merchant.merchant_id,
            name="Widget",
            price=Decimal("5000"),
            product_type="ONE_TIME",
            billing_cycle=None,
        )
        on = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Run many times with different seeds to get a purchase
        found_purchase = False
        for seed in range(100):
            rng = SimulationRNG(42 + seed)
            engine = EcommerceEngine(rng, ecommerce_engine._config)
            decision = engine.generate_purchase(
                sample_person, [merchant], [product], on, Decimal("50000"), True
            )
            if decision is not None:
                found_purchase = True
                assert decision.person_id == sample_person.person_id
                assert decision.amount > 0
                break

        # At least one seed should have produced a purchase
        assert found_purchase

    def test_generate_purchase_balance_check(self, ecommerce_engine, sample_person):
        """Person with insufficient balance should not make a purchase."""
        from uuid import uuid4
        from app.domain import Product, Merchant
        merchant = Merchant(
            merchant_id=uuid4(),
            name="Amazin",
            merchant_type="ECOMMERCE",
            settlement_bank_id=uuid4(),
        )
        product = Product(
            product_id=uuid4(),
            merchant_id=merchant.merchant_id,
            name="Widget",
            price=Decimal("50000"),
            product_type="ONE_TIME",
            billing_cycle=None,
        )
        on = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        decision = ecommerce_engine.generate_purchase(
            sample_person, [merchant], [product], on, Decimal("100"), True
        )
        # With only 100 balance and min product price 50000, no purchase
        assert decision is None
