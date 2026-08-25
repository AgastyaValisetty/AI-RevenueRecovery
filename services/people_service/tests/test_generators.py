"""Tests for PersonGenerator, MerchantGenerator, SubscriptionGenerator."""

from __future__ import annotations

from decimal import Decimal
from datetime import date, timedelta

import pytest

from app.rng import SimulationRNG
from app.sim_config import SimConfig
from uuid import uuid4

from app.generators import PersonGenerator, MerchantGenerator, SubscriptionGenerator
from app.domain import Person, BankAccount, Merchant, Product, Subscription, MONTHLY, ACTIVE


class TestPersonGenerator:
    """Verify person generation uses calibrated distributions."""

    def test_deterministic_generation(self, config):
        """Same seed + config should produce identical results."""
        bank_id = uuid4()

        rng_a = SimulationRNG(42)
        gen_a = PersonGenerator(rng_a, config)
        people_a, _ = gen_a.generate(10, bank_id)

        rng_b = SimulationRNG(42)
        gen_b = PersonGenerator(rng_b, config)
        people_b, _ = gen_b.generate(10, bank_id)

        assert len(people_a) == len(people_b)
        for pa, pb in zip(people_a, people_b):
            assert pa.name == pb.name
            assert pa.salary == pb.salary
            assert pa.age == pb.age

    def test_age_within_distribution_range(self, config):
        rng = SimulationRNG(42)
        gen = PersonGenerator(rng, config)
        people, _ = gen.generate(100, uuid4())

        all_ages_min = min(g.age_min for g in config.age_distribution.groups)
        all_ages_max = max(g.age_max for g in config.age_distribution.groups)
        for p in people:
            assert all_ages_min <= p.age <= all_ages_max

    def test_salary_within_distribution_range(self, config):
        rng = SimulationRNG(42)
        gen = PersonGenerator(rng, config)
        people, _ = gen.generate(100, uuid4())

        overall_min = min(b.min for b in config.income_distribution.brackets)
        overall_max = max(b.max for b in config.income_distribution.brackets)
        for p in people:
            assert Decimal(overall_min) <= p.salary <= Decimal(overall_max)

    def test_people_have_correct_fields(self, config):
        rng = SimulationRNG(42)
        gen = PersonGenerator(rng, config)
        people, _ = gen.generate(5, uuid4())

        p = people[0]
        assert p.person_id is not None
        assert p.name is not None
        assert p.salary_deposit_hour == config.salary.deposit_hour
        assert p.spending_profile_category in ("student", "young_professional", "family", "high_income", "retired")
        assert p.income_bracket is not None
        assert p.age_group is not None
        assert p.employment_type is not None

    def test_accounts_match_people(self, config):
        rng = SimulationRNG(42)
        gen = PersonGenerator(rng, config)
        people, accounts = gen.generate(10, uuid4())

        assert len(people) == len(accounts)
        for p, a in zip(people, accounts):
            assert p.person_id == a.person_id


class TestMerchantGenerator:
    """Verify merchant generation loads from catalog."""

    def test_generates_merchants_and_products(self):
        gen = MerchantGenerator()
        from uuid import uuid4
        merchants, products = gen.generate(uuid4())

        assert len(merchants) > 0
        assert len(products) > 0
        # Each product should belong to a merchant
        merchant_ids = {m.merchant_id for m in merchants}
        for p in products:
            assert p.merchant_id in merchant_ids

    def test_all_products_have_prices(self):
        gen = MerchantGenerator()
        from uuid import uuid4
        _, products = gen.generate(uuid4())

        for p in products:
            assert p.price > 0
            assert isinstance(p.price, Decimal)


class TestSubscriptionGenerator:
    """Verify subscription generation with profile-dependent penetration."""

    def test_deterministic_generation(self, config):
        people = [
            Person(
                person_id=uuid4(),
                name="Test",
                age=30,
                salary=Decimal("50000"),
                salary_deposit_day=1,
                salary_deposit_hour=9,
                spending_profile_category="young_professional",
                spending_profile_json={},
                payment_preferences_json={},
                income_bracket="middle",
                age_group="early_career",
                employment_type="salaried",
                primary_bank_id=uuid4(),
                primary_account_id=uuid4(),
            )
        ]

        rng_a = SimulationRNG(42)
        rng_b = SimulationRNG(42)
        gen_a = SubscriptionGenerator(rng_a, config)
        gen_b = SubscriptionGenerator(rng_b, config)

        # Create a fake product
        products = [
            Product(
                product_id=uuid4(),
                merchant_id=uuid4(),
                name="Netflix",
                price=Decimal("649"),
                product_type="SUBSCRIPTION",
                billing_cycle=MONTHLY,
            )
        ]

        start_date = date(2024, 1, 1)
        subs_a = gen_a.generate(people, products, start_date)
        subs_b = gen_b.generate(people, products, start_date)

        # Same seed → same result
        assert len(subs_a) == len(subs_b)
        if len(subs_a) > 0:
            assert subs_a[0].amount == subs_b[0].amount

    def test_returns_empty_for_no_products(self, config):
        from uuid import uuid4
        rng = SimulationRNG(42)
        gen = SubscriptionGenerator(rng, config)
        people = [
            Person(
                person_id=uuid4(),
                name="Test",
                age=30,
                salary=Decimal("50000"),
                salary_deposit_day=1,
                salary_deposit_hour=9,
                spending_profile_category="young_professional",
                spending_profile_json={},
                payment_preferences_json={},
                income_bracket="middle",
                age_group="early_career",
                employment_type="salaried",
                primary_bank_id=uuid4(),
                primary_account_id=uuid4(),
            )
        ]
        subs = gen.generate(people, [], date(2024, 1, 1))
        assert len(subs) == 0

    def test_subscription_count_within_bounds(self, config):
        from uuid import uuid4
        from app.domain import MONTHLY
        rng = SimulationRNG(42)
        gen = SubscriptionGenerator(rng, config)

        people = [
            Person(
                person_id=uuid4(),
                name="Test",
                age=30,
                salary=Decimal("50000"),
                salary_deposit_day=1,
                salary_deposit_hour=9,
                spending_profile_category="high_income",
                spending_profile_json={},
                payment_preferences_json={},
                income_bracket="middle",
                age_group="early_career",
                employment_type="salaried",
                primary_bank_id=uuid4(),
                primary_account_id=uuid4(),
            )
        ]
        products = [
            Product(
                product_id=uuid4(),
                merchant_id=uuid4(),
                name=f"Product {i}",
                price=Decimal("100"),
                product_type="SUBSCRIPTION",
                billing_cycle=MONTHLY,
            )
            for i in range(10)
        ]

        subs = gen.generate(people, products, date(2024, 1, 1))
        settings = config.subscription_penetration.by_profile["high_income"]
        assert settings.min_count <= len(subs) <= settings.max_count
