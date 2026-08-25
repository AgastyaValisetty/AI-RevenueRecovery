"""Tests for AgeSampler and IncomeSampler."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.demographics import AgeSampler, IncomeSampler
from app.rng import SimulationRNG
from app.sim_config import SimConfig


class TestAgeSampler:
    """Verify the age sampler produces realistic, deterministic ages."""

    def test_deterministic_age(self, config):
        rng_a = SimulationRNG(42)
        rng_b = SimulationRNG(42)
        sampler_a = AgeSampler(rng_a, config)
        sampler_b = AgeSampler(rng_b, config)

        age_a = sampler_a.sample_age()
        age_b = sampler_b.sample_age()
        assert age_a == age_b

    def test_age_within_group_bounds(self, config):
        rng = SimulationRNG(42)
        sampler = AgeSampler(rng, config)

        for _ in range(500):
            age = sampler.sample_age()
            # All ages should be within the overall range
            all_mins = [g.age_min for g in config.age_distribution.groups]
            all_maxs = [g.age_max for g in config.age_distribution.groups]
            assert age >= min(all_mins)
            assert age <= max(all_maxs)

    def test_age_group_label(self, config):
        rng = SimulationRNG(42)
        sampler = AgeSampler(rng, config)

        # Pick an age within the first group
        first_group = config.age_distribution.groups[0]
        mid_age = (first_group.age_min + first_group.age_max) // 2
        label = sampler.age_group_label(mid_age)
        assert label == first_group.label

    def test_employment_type_by_age(self, config):
        """Employment type should be deterministic and age-appropriate."""
        # Young person → student or salaried
        rng_young = SimulationRNG(42)
        sampler_young = AgeSampler(rng_young, config)
        et_young = sampler_young.sample_employment_type(20)
        assert et_young in ("student", "salaried")

        # Senior → retired
        rng_senior = SimulationRNG(42)
        sampler_senior = AgeSampler(rng_senior, config)
        et_senior = sampler_senior.sample_employment_type(70)
        assert et_senior == "retired"


class TestIncomeSampler:
    """Verify the income sampler produces right-skewed, bracket-bounded salaries."""

    def test_deterministic_salary(self, config):
        rng_a = SimulationRNG(42)
        rng_b = SimulationRNG(42)
        sampler_a = IncomeSampler(rng_a, config)
        sampler_b = IncomeSampler(rng_b, config)

        salary_a = sampler_a.sample_salary()
        salary_b = sampler_b.sample_salary()
        assert salary_a == salary_b

    def test_salary_within_brackets(self, config):
        rng = SimulationRNG(42)
        sampler = IncomeSampler(rng, config)

        for _ in range(500):
            salary = sampler.sample_salary()
            overall_min = min(b.min for b in config.income_distribution.brackets)
            overall_max = max(b.max for b in config.income_distribution.brackets)
            assert Decimal(overall_min) <= salary <= Decimal(overall_max)

    def test_salary_is_positive(self, config):
        rng = SimulationRNG(42)
        sampler = IncomeSampler(rng, config)

        for _ in range(500):
            salary = sampler.sample_salary()
            assert salary > 0

    def test_salary_right_skewed(self, config):
        """The distribution should be right-skewed: median < mean."""
        rng = SimulationRNG(42)
        sampler = IncomeSampler(rng, config)

        salaries = sorted([sampler.sample_salary() for _ in range(10000)])
        median = salaries[len(salaries) // 2]
        mean = sum(salaries) / len(salaries)

        # With a right-skewed distribution, median should be <= mean
        # (some extreme values pull the mean up)
        assert median <= mean

    def test_income_bracket_label(self, config):
        rng = SimulationRNG(42)
        sampler = IncomeSampler(rng, config)

        label = sampler.income_bracket_label(Decimal("30000"))
        assert label is not None
        assert "-" in label or label == ">max"
