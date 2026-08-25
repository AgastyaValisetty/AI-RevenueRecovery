"""Default calibration values for the simulation configuration.

These are the pydantic-model defaults that match ``sim_calibration.json``.
The canonical source of runtime parameters is the JSON file loaded by
``sim_config.SimConfig.defaults()``; this module provides the pydantic
``SimulationConfig`` defaults for programmatic construction and validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import ValidationError

from .simulation import (
    AgeConfig,
    EcommerceConfig,
    IncomeConfig,
    PaymentMethodConfig,
    PopulationConfig,
    SalaryConfig,
    SimulationConfig,
    SpendingConfig,
    SubscriptionConfig,
    TemporalConfig,
)

DEFAULT_CONFIG_VERSION = "1.0.0"


def _build_default_config() -> SimulationConfig:
    """Build and validate the default :class:`SimulationConfig`."""
    spending = SpendingConfig(
        base_hourly_probability=0.005,
        probability_multiplier_low=0.6,
        probability_multiplier_lower_middle=0.8,
        probability_multiplier_middle=1.0,
        probability_multiplier_upper_middle=1.2,
        probability_multiplier_high=1.5,
        prob_mult_age_18_24=0.8,
        prob_mult_age_25_34=1.0,
        prob_mult_age_35_44=1.3,
        prob_mult_age_45_54=0.9,
        prob_mult_age_55_64=0.6,
        prob_mult_age_65_plus=0.4,
        prob_mult_employed=1.0,
        prob_mult_self_employed=1.4,
        prob_mult_student=0.3,
        prob_mult_retired=0.3,
        prob_mult_unemployed=0.2,
        hourly_multipliers=[
            0.3, 0.2, 0.1, 0.1, 0.2, 0.5,  # 00–05
            0.7, 0.9, 1.0, 1.1, 1.2, 1.3,  # 06–11
            1.4, 1.5, 1.3, 1.2, 1.3, 1.4,  # 12–17
            1.2, 1.1, 1.0, 0.8, 0.7, 0.6,  # 18–23
        ],
        weekday_multiplier=1.0,
        weekend_multiplier=0.7,
        category_salary_fraction={
            "groceries": 0.10, "utilities": 0.05, "dining": 0.08,
            "transport": 0.06, "entertainment": 0.04,
        },
        category_volatility={
            "groceries": 0.15, "utilities": 0.05, "dining": 0.30,
            "transport": 0.20, "entertainment": 0.50,
        },
        low_balance_threshold=Decimal("2000"),
        low_balance_multiplier=0.5,
    )

    return SimulationConfig(
        version=DEFAULT_CONFIG_VERSION,
        population=PopulationConfig(count=100, min_age=18, max_age=80),
        income=IncomeConfig(
            lognormal_mu=10.6,
            lognormal_sigma=0.5,
            min_salary=Decimal("15000"),
            max_salary=Decimal("1500000"),
            low_max=Decimal("25000"),
            lower_middle_max=Decimal("60000"),
            middle_max=Decimal("150000"),
            upper_middle_max=Decimal("400000"),
        ),
        age=AgeConfig(
            group_18_24=0.18,
            group_25_34=0.20,
            group_35_44=0.22,
            group_45_54=0.18,
            group_55_64=0.12,
            group_65_plus=0.10,
        ),
        spending=spending,
        subscriptions=SubscriptionConfig(
            base_penetration={
                "netflix": 0.85,
                "spotify": 0.70,
                "amazon_prime": 0.60,
            },
            income_multiplier_low=0.3,
            income_multiplier_lower_middle=0.6,
            income_multiplier_middle=1.0,
            income_multiplier_upper_middle=1.4,
            income_multiplier_high=1.8,
            age_multiplier_18_24=1.3,
            age_multiplier_25_34=1.1,
            age_multiplier_35_44=0.8,
            age_multiplier_45_54=0.6,
            age_multiplier_55_64=0.4,
            age_multiplier_65_plus=0.2,
        ),
        ecommerce=EcommerceConfig(
            base_hourly_probability=0.02,
            income_multiplier_low=0.2,
            income_multiplier_lower_middle=0.5,
            income_multiplier_middle=1.0,
            income_multiplier_upper_middle=1.5,
            income_multiplier_high=2.0,
            age_multiplier_18_24=1.2,
            age_multiplier_25_34=1.4,
            age_multiplier_35_44=0.8,
            age_multiplier_45_54=0.5,
            age_multiplier_55_64=0.3,
            age_multiplier_65_plus=0.1,
            order_value_lognormal_mu=8.0,
            order_value_lognormal_sigma=1.0,
            order_value_min=Decimal("500"),
            order_value_max=Decimal("50000"),
            max_salary_fraction=0.15,
        ),
        payment_methods=PaymentMethodConfig(
            upi=0.70, card=0.25, netbanking=0.05,
        ),
        salary=SalaryConfig(
            deposit_day_probs=[0.20, 0.18, 0.16, 0.14, 0.12] + [0.03] * 23,
            deposit_hour=9,
        ),
        temporal=TemporalConfig(
            start_datetime=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            hours_per_day=24,
            working_hours=(9, 18),
        ),
    )


DEFAULT_CONFIG: SimulationConfig = _build_default_config()
