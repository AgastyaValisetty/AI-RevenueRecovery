"""Typed configuration for the synthetic financial world simulation.

Two-layer design:
- ``sim_calibration.json`` — human-editable JSON with all tunable parameters.
- :class:`SimConfig` — frozen dataclass accessor that validates and exposes
  typed values to engines and generators.

Non-engineers edit the JSON; engineers/programmatic users can also build a
config in Python via :meth:`SimConfig.defaults`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
from typing import Any


# --------------------------------------------------------------------------- #
# Frozen dataclass config sections
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AgeGroup:
    label: str
    age_min: int
    age_max: int
    weight: float


@dataclass(frozen=True)
class IncomeBracket:
    min: int
    max: int
    weight: float


@dataclass(frozen=True)
class OrderValueBracket:
    min: int
    max: int
    weight: float


@dataclass(frozen=True)
class SpendingConfig:
    base_daily_percentage: float
    salary_day_boost_days: tuple[int, ...]
    salary_day_boost: float
    weekend_boost: float
    random_variation_std: float
    profile_multipliers: dict[str, float]
    max_daily_spend_pct: float
    categories: tuple[str, ...]

    # Income bracket probability multipliers
    probability_multiplier_low: float = 1.0
    probability_multiplier_lower_middle: float = 1.0
    probability_multiplier_middle: float = 1.0
    probability_multiplier_upper_middle: float = 1.2
    probability_multiplier_high: float = 1.5

    # Per-age-group probability multipliers
    prob_mult_age_18_24: float = 0.8
    prob_mult_age_25_34: float = 1.0
    prob_mult_age_35_44: float = 1.3
    prob_mult_age_45_54: float = 0.9
    prob_mult_age_55_64: float = 0.6
    prob_mult_age_65_plus: float = 0.4

    # Employment-type multipliers
    prob_mult_employed: float = 1.0
    prob_mult_self_employed: float = 1.4
    prob_mult_student: float = 0.3
    prob_mult_retired: float = 0.3
    prob_mult_unemployed: float = 0.2

    # Balance factor: when balance < threshold, reduce discretionary spending
    low_balance_threshold: Decimal = Decimal("2000")
    low_balance_multiplier: float = 0.5

    # Day-type multipliers
    weekday_multiplier: float = 1.0
    weekend_multiplier: float = 0.7

    @property
    def category_list(self) -> list[str]:
        return list(self.categories)


@dataclass(frozen=True)
class PenetrationSettings:
    prob_per_sub: float
    min_count: int
    max_count: int


@dataclass(frozen=True)
class EcommerceConfig:
    shop_probability_by_profile: dict[str, float]
    salary_day_boost_multiplier: float
    merchant_split: dict[str, float]
    order_value_brackets: tuple[OrderValueBracket, ...]
    max_order_pct_of_balance: float
    max_order_pct_of_salary: float
    business_hours_start: int
    business_hours_end: int

    # Income bracket probability multipliers
    income_multiplier_low: float = 0.2
    income_multiplier_lower_middle: float = 0.5
    income_multiplier_middle: float = 1.0
    income_multiplier_upper_middle: float = 1.5
    income_multiplier_high: float = 2.0

    # Per-age-group probability multipliers
    age_multiplier_18_24: float = 1.2
    age_multiplier_25_34: float = 1.4
    age_multiplier_35_44: float = 0.8
    age_multiplier_45_54: float = 0.5
    age_multiplier_55_64: float = 0.3
    age_multiplier_65_plus: float = 0.1

    @property
    def order_bracket_list(self) -> list[OrderValueBracket]:
        return list(self.order_value_brackets)


@dataclass(frozen=True)
class SalaryConfig:
    deposit_hour: int
    deposit_days_range: tuple[int, ...]


@dataclass(frozen=True)
class BankConfig:
    name: str
    authorization_success_rate: float
    state_multipliers: dict[str, float]


@dataclass(frozen=True)
class TaxConfig:
    """Tax and duty configuration for the simulation."""
    income_tax_rate: float
    gst_rate: float


@dataclass(frozen=True)
class PopulationConfig:
    default_size: int
    default_seed: int


@dataclass(frozen=True)
class TemporalConfig:
    start_datetime: datetime
    clock_granularity_hours: int


@dataclass(frozen=True)
class IncomeConfig:
    brackets: tuple[IncomeBracket, ...]
    lognormal_mean: float
    lognormal_sigma: float


@dataclass(frozen=True)
class AgeConfig:
    groups: tuple[AgeGroup, ...]


@dataclass(frozen=True)
class SubscriptionConfig:
    by_profile: dict[str, PenetrationSettings]


# --------------------------------------------------------------------------- #
# Top-level SimConfig
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SimConfig:
    """Root configuration object — immutable, typed, validated."""

    population: PopulationConfig
    temporal: TemporalConfig
    age_distribution: AgeConfig
    income_distribution: IncomeConfig
    spending: SpendingConfig
    subscription_penetration: SubscriptionConfig
    ecommerce: EcommerceConfig
    bank: BankConfig
    salary: SalaryConfig
    tax: TaxConfig
    version: str = "1.0.0"

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> "SimConfig":
        """Load configuration from a JSON calibration file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Calibration file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls._from_dict(data)

    @classmethod
    def defaults(cls) -> "SimConfig":
        """Load the default calibration file shipped with the service."""
        default_path = (
            Path(__file__).resolve().parent / "sim_calibration.json"
        )
        return cls.from_file(default_path)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "SimConfig":
        """Parse a JSON dict into validated dataclass config."""
        # Validation
        age_groups_raw = data.get("age_distribution", {}).get("groups", [])
        if len(age_groups_raw) < 2:
            raise ValueError("At least 2 age groups required in config")

        income_brackets_raw = data.get("income_distribution", {}).get("brackets", [])
        if len(income_brackets_raw) < 2:
            raise ValueError("At least 2 income brackets required in config")

        spending_cfg = data.get("spending", {})
        profile_mults = spending_cfg.get("profile_multipliers", {})
        for profile in ("student", "young_professional", "family", "high_income", "retired"):
            if profile not in profile_mults:
                raise ValueError(f"Missing profile multiplier for '{profile}'")

        subs_raw = data.get("subscription_penetration", {}).get("by_profile", {})
        for profile in ("student", "young_professional", "family", "high_income", "retired"):
            if profile not in subs_raw:
                raise ValueError(f"Missing subscription penetration for '{profile}'")

        ecom_raw = data.get("ecommerce", {})
        order_brackets_raw = ecom_raw.get("order_value_dist", {})
        if not order_brackets_raw:
            raise ValueError("At least one order value bracket required")

        return cls(
            version=data.get("version", "1.0.0"),
            population=PopulationConfig(
                default_size=data["population"]["default_size"],
                default_seed=data["population"].get("default_seed", 42),
            ),
            temporal=TemporalConfig(
                start_datetime=datetime.fromisoformat(
                    data["time"]["start_datetime"]
                ),
                clock_granularity_hours=data["time"].get(
                    "clock_granularity_hours", 1
                ),
            ),
            age_distribution=AgeConfig(
                groups=tuple(
                    AgeGroup(
                        label=g["label"],
                        age_min=g["age_min"],
                        age_max=g["age_max"],
                        weight=g["weight"],
                    )
                    for g in age_groups_raw
                ),
            ),
            income_distribution=IncomeConfig(
                brackets=tuple(
                    IncomeBracket(
                        min=b["min"], max=b["max"], weight=b["weight"]
                    )
                    for b in income_brackets_raw
                ),
                lognormal_mean=data["income_distribution"]["lognormal_mean"],
                lognormal_sigma=data["income_distribution"]["lognormal_sigma"],
            ),
            spending=SpendingConfig(
                base_daily_percentage=spending_cfg["base_daily_percentage"],
                salary_day_boost_days=tuple(spending_cfg["salary_day_boost_days"]),
                salary_day_boost=spending_cfg["salary_day_boost"],
                weekend_boost=spending_cfg["weekend_boost"],
                random_variation_std=spending_cfg["random_variation_std"],
                profile_multipliers=dict(profile_mults),
                max_daily_spend_pct=spending_cfg["max_daily_spend_pct"],
                categories=tuple(spending_cfg["categories"]),
                probability_multiplier_low=spending_cfg.get("probability_multiplier_low", 1.0),
                probability_multiplier_lower_middle=spending_cfg.get("probability_multiplier_lower_middle", 1.0),
                probability_multiplier_middle=spending_cfg.get("probability_multiplier_middle", 1.0),
                probability_multiplier_upper_middle=spending_cfg.get("probability_multiplier_upper_middle", 1.2),
                probability_multiplier_high=spending_cfg.get("probability_multiplier_high", 1.5),
                prob_mult_age_18_24=spending_cfg.get("prob_mult_age_18_24", 0.8),
                prob_mult_age_25_34=spending_cfg.get("prob_mult_age_25_34", 1.0),
                prob_mult_age_35_44=spending_cfg.get("prob_mult_age_35_44", 1.3),
                prob_mult_age_45_54=spending_cfg.get("prob_mult_age_45_54", 0.9),
                prob_mult_age_55_64=spending_cfg.get("prob_mult_age_55_64", 0.6),
                prob_mult_age_65_plus=spending_cfg.get("prob_mult_age_65_plus", 0.4),
                prob_mult_employed=spending_cfg.get("prob_mult_employed", 1.0),
                prob_mult_self_employed=spending_cfg.get("prob_mult_self_employed", 1.4),
                prob_mult_student=spending_cfg.get("prob_mult_student", 0.3),
                prob_mult_retired=spending_cfg.get("prob_mult_retired", 0.3),
                prob_mult_unemployed=spending_cfg.get("prob_mult_unemployed", 0.2),
                low_balance_threshold=Decimal(str(spending_cfg.get("low_balance_threshold", 2000))),
                low_balance_multiplier=spending_cfg.get("low_balance_multiplier", 0.5),
                weekday_multiplier=spending_cfg.get("weekday_multiplier", 1.0),
                weekend_multiplier=spending_cfg.get("weekend_multiplier", 0.7),
            ),
            subscription_penetration=SubscriptionConfig(
                by_profile={
                    profile: PenetrationSettings(
                        prob_per_sub=p["prob_per_sub"],
                        min_count=p["min_count"],
                        max_count=p["max_count"],
                    )
                    for profile, p in subs_raw.items()
                },
            ),
            ecommerce=EcommerceConfig(
                shop_probability_by_profile=ecom_raw["shop_probability_by_profile"],
                salary_day_boost_multiplier=ecom_raw["salary_day_boost_multiplier"],
                merchant_split=ecom_raw["merchant_split"],
                order_value_brackets=tuple(
                    OrderValueBracket(
                        min=b["min"], max=b["max"], weight=b["weight"]
                    )
                    for b in order_brackets_raw.values()
                ),
                max_order_pct_of_balance=ecom_raw["max_order_pct_of_balance"],
                max_order_pct_of_salary=ecom_raw.get("max_salary_fraction", 0.15),
                business_hours_start=ecom_raw["business_hours_start"],
                business_hours_end=ecom_raw["business_hours_end"],
                income_multiplier_low=ecom_raw.get("income_multiplier_low", 0.2),
                income_multiplier_lower_middle=ecom_raw.get("income_multiplier_lower_middle", 0.5),
                income_multiplier_middle=ecom_raw.get("income_multiplier_middle", 1.0),
                income_multiplier_upper_middle=ecom_raw.get("income_multiplier_upper_middle", 1.5),
                income_multiplier_high=ecom_raw.get("income_multiplier_high", 2.0),
                age_multiplier_18_24=ecom_raw.get("age_multiplier_18_24", 1.2),
                age_multiplier_25_34=ecom_raw.get("age_multiplier_25_34", 1.4),
                age_multiplier_35_44=ecom_raw.get("age_multiplier_35_44", 0.8),
                age_multiplier_45_54=ecom_raw.get("age_multiplier_45_54", 0.5),
                age_multiplier_55_64=ecom_raw.get("age_multiplier_55_64", 0.3),
                age_multiplier_65_plus=ecom_raw.get("age_multiplier_65_plus", 0.1),
            ),
            bank=BankConfig(
                name=data["bank"]["name"],
                authorization_success_rate=data["bank"]["authorization_success_rate"],
                state_multipliers=dict(data["bank"]["state_multipliers"]),
            ),
            salary=SalaryConfig(
                deposit_hour=data.get("salary", {}).get("deposit_hour", 9),
                deposit_days_range=tuple(
                    data.get("salary", {}).get("deposit_days_range", [1, 2, 3, 4, 5])
                ),
            ),
            tax=TaxConfig(
                income_tax_rate=data.get("tax", {}).get("income_tax_rate", 0.30),
                gst_rate=data.get("tax", {}).get("gst_rate", 0.18),
            ),
        )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def age_group_for(self, age: int) -> str:
        """Return the label of the age group that contains ``age``."""
        for g in self.age_distribution.groups:
            if g.age_min <= age <= g.age_max:
                return g.label
        return "retired"  # fallback for ages outside all groups

    def income_bracket_for(self, salary: Decimal) -> str:
        """Return a human-readable bracket label for a salary."""
        for b in self.income_distribution.brackets:
            if b.min <= float(salary) <= b.max:
                return f"{b.min}-{b.max}"
        return ">max"
