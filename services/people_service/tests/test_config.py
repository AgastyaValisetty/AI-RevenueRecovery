"""Tests for SimConfig — loading, validation, and immutability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.sim_config import SimConfig, SalaryConfig


class TestConfigLoading:
    """Verify config loads from the default JSON file."""

    def test_defaults_loads_without_error(self, config):
        assert config is not None
        assert config.version == "1.0.0"

    def test_defaults_has_population_settings(self, config):
        assert config.population.default_size == 100
        assert config.population.default_seed == 42

    def test_defaults_has_temporal_settings(self, config):
        assert config.temporal.start_datetime is not None
        assert config.temporal.clock_granularity_hours == 1

    def test_defaults_has_age_groups(self, config):
        assert len(config.age_distribution.groups) >= 2
        # First group should start at age 18
        first_group = config.age_distribution.groups[0]
        assert first_group.age_min == 18

    def test_defaults_has_income_brackets(self, config):
        assert len(config.income_distribution.brackets) >= 2
        # Brackets should cover a wide range
        lowest = min(config.income_distribution.brackets, key=lambda b: b.min)
        highest = max(config.income_distribution.brackets, key=lambda b: b.max)
        assert lowest.min < 20000
        assert highest.max > 500000

    def test_defaults_has_salary_config(self, config):
        assert config.salary.deposit_hour == 9
        assert 1 in config.salary.deposit_days_range

    def test_defaults_has_spending_config(self, config):
        assert config.spending.base_daily_percentage > 0
        assert config.spending.max_daily_spend_pct > 0
        assert len(config.spending.categories) > 0
        assert len(config.spending.profile_multipliers) == 5

    def test_defaults_has_ecommerce_config(self, config):
        assert config.ecommerce.business_hours_start >= 0
        assert config.ecommerce.business_hours_end <= 24
        assert len(config.ecommerce.order_value_brackets) >= 1
        assert config.ecommerce.max_order_pct_of_salary > 0

    def test_defaults_has_subscription_penetration(self, config):
        for profile in ("student", "young_professional", "family", "high_income", "retired"):
            assert profile in config.subscription_penetration.by_profile

    def test_defaults_has_bank_config(self, config):
        assert config.bank.name == "RupeeBank"
        assert config.bank.authorization_success_rate > 0


class TestConfigValidation:
    """Verify config validation raises on invalid data."""

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SimConfig.from_file(tmp_path / "nonexistent.json")

    def test_invalid_age_groups_raise(self):
        """Empty age_distribution.groups should raise ValueError."""
        bad_data = {
            "version": "1.0.0",
            "population": {"default_size": 100, "default_seed": 42},
            "time": {"start_datetime": "2024-01-01T00:00:00Z", "clock_granularity_hours": 1},
            "age_distribution": {"groups": []},
            "income_distribution": {
                "brackets": [{"min": 15000, "max": 25000, "weight": 1.0}],
                "lognormal_mean": 10.6, "lognormal_sigma": 0.5,
            },
            "spending": {
                "base_daily_percentage": 1.5,
                "salary_day_boost_days": [1],
                "salary_day_boost": 0.5,
                "weekend_boost": 0.3,
                "random_variation_std": 0.2,
                "profile_multipliers": {"student": 0.7, "young_professional": 1.0, "family": 1.3, "high_income": 1.5, "retired": 0.8},
                "max_daily_spend_pct": 8.0,
                "categories": ["groceries"],
            },
            "subscription_penetration": {"by_profile": {
                "student": {"prob_per_sub": 0.35, "min_count": 1, "max_count": 2},
                "young_professional": {"prob_per_sub": 0.85, "min_count": 2, "max_count": 3},
                "family": {"prob_per_sub": 0.90, "min_count": 2, "max_count": 3},
                "high_income": {"prob_per_sub": 0.95, "min_count": 2, "max_count": 4},
                "retired": {"prob_per_sub": 0.40, "min_count": 0, "max_count": 1},
            }},
            "ecommerce": {
                "shop_probability_by_profile": {"student": 0.05, "young_professional": 0.18, "family": 0.12, "high_income": 0.25, "retired": 0.03},
                "salary_day_boost_multiplier": 2.0,
                "merchant_split": {"amazin": 0.5, "flip_cartel": 0.5},
                "order_value_dist": {"low": {"min": 500, "max": 2000, "weight": 1.0}},
                "max_order_pct_of_balance": 0.30,
                "max_salary_fraction": 0.15,
                "business_hours_start": 10,
                "business_hours_end": 20,
            },
            "bank": {"name": "RupeeBank", "authorization_success_rate": 99.1, "state_multipliers": {"NORMAL": 1.0}},
            "salary": {"deposit_hour": 9, "deposit_days_range": [1, 2, 3, 4, 5]},
        }
        with pytest.raises(ValueError):
            SimConfig._from_dict(bad_data)


class TestConfigFrozen:
    """Verify the config dataclasses are immutable."""

    def test_config_is_frozen(self, config):
        with pytest.raises(AttributeError):
            config.version = "2.0.0"

    def test_salary_config_is_frozen(self, config):
        with pytest.raises(AttributeError):
            config.salary.deposit_hour = 10


class TestConfigHelpers:
    """Verify config convenience helpers."""

    def test_age_group_for(self, config):
        label = config.age_group_for(25)
        assert label is not None

    def test_income_bracket_for(self, config):
        label = config.income_bracket_for(50000)
        assert label is not None

    def test_income_bracket_for_high_salary(self, config):
        # Highest bracket max is 1500000
        label = config.income_bracket_for(2000000)
        assert label == ">max"
