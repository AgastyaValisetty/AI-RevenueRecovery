"""Pydantic models for simulation calibration configuration.

Every tunable parameter lives here, validated at load time.  Engines and
generators receive a :class:`SimulationConfig` instance and read from its
sections rather than using module-level constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict


class CalibrationSource(str, Enum):
    """Whether a value is backed by external data or is an assumption."""

    SOURCE_BACKED = "source_backed"
    ASSUMED = "assumed"
    DERIVED = "derived"


@dataclass(frozen=True)
class CalibrationEntry:
    """Metadata describing where a calibration value came from.

    Used for data provenance — every configurable value should have a
    corresponding :class:`CalibrationEntry` in the config's provenance map.
    """

    value: float | int | str | Decimal
    source: CalibrationSource
    description: str
    citation: str | None = None  # e.g. "NSSO 2019", "Reserve Bank of India 2023"
    last_updated: datetime | None = None


class IncomeBracket(str, Enum):
    LOW = "low"
    LOWER_MIDDLE = "lower_middle"
    MIDDLE = "middle"
    UPPER_MIDDLE = "upper_middle"
    HIGH = "high"


class EmploymentType(str, Enum):
    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    STUDENT = "student"
    RETIRED = "retired"
    UNEMPLOYED = "unemployed"


class AgeGroup(str, Enum):
    GROUP_18_24 = "18-24"
    GROUP_25_34 = "25-34"
    GROUP_35_44 = "35-44"
    GROUP_45_54 = "45-54"
    GROUP_55_64 = "55-64"
    GROUP_65_PLUS = "65+"


class SpendingCategory(str, Enum):
    GROCERIES = "groceries"
    UTILITIES = "utilities"
    DINING = "dining"
    TRANSPORT = "transport"
    ENTERTAINMENT = "entertainment"


class PaymentMethod(str, Enum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"


# --------------------------------------------------------------------------- #
# Config subsections
# --------------------------------------------------------------------------- #


class PopulationConfig(BaseModel):
    """Controls how many people are generated and their attributes."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    count: Annotated[int, Field(ge=1, le=10_000, description="Total people in simulation")]
    min_age: Annotated[int, Field(ge=18, le=100)] = 18
    max_age: Annotated[int, Field(ge=18, le=100)] = 80


class IncomeConfig(BaseModel):
    """Right-skewed income distribution calibrated to Hyderabad/India.

    Uses a log-normal distribution whose parameters are fitted to
    NSSO 2019 household consumption data for Telangana.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # Log-normal distribution parameters (mu, sigma of the underlying normal)
    lognormal_mu: float = Field(description="Mean of log(salary)")
    lognormal_sigma: float = Field(description="Std of log(salary)")

    # Hard bounds
    min_salary: Decimal = Field(description="Minimum monthly salary (INR)")
    max_salary: Decimal = Field(description="Maximum monthly salary (INR)")

    # Income bracket thresholds (INR/month, cumulative)
    low_max: Decimal
    lower_middle_max: Decimal
    middle_max: Decimal
    upper_middle_max: Decimal
    # Anything above upper_middle_max → HIGH

    def bracket_for(self, salary: Decimal) -> IncomeBracket:
        """Map a salary to its income bracket."""
        if salary <= self.low_max:
            return IncomeBracket.LOW
        if salary <= self.lower_middle_max:
            return IncomeBracket.LOWER_MIDDLE
        if salary <= self.middle_max:
            return IncomeBracket.MIDDLE
        if salary <= self.upper_middle_max:
            return IncomeBracket.UPPER_MIDDLE
        return IncomeBracket.HIGH


class AgeConfig(BaseModel):
    """Age distribution calibrated to the Indian demographic pyramid."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # Age group probabilities (must sum to 1.0)
    group_18_24: float = Field(ge=0, le=1)
    group_25_34: float = Field(ge=0, le=1)
    group_35_44: float = Field(ge=0, le=1)
    group_45_54: float = Field(ge=0, le=1)
    group_55_64: float = Field(ge=0, le=1)
    group_65_plus: float = Field(ge=0, le=1)

    # Age ranges for each group (inclusive)
    ages_18_24: tuple[int, int] = (18, 24)
    ages_25_34: tuple[int, int] = (25, 34)
    ages_35_44: tuple[int, int] = (35, 44)
    ages_45_54: tuple[int, int] = (45, 54)
    ages_55_64: tuple[int, int] = (55, 64)
    ages_65_plus: tuple[int, int] = (65, 80)

    def group_for(self, age: int) -> AgeGroup:
        if age <= 24:
            return AgeGroup.GROUP_18_24
        if age <= 34:
            return AgeGroup.GROUP_25_34
        if age <= 44:
            return AgeGroup.GROUP_35_44
        if age <= 54:
            return AgeGroup.GROUP_45_54
        if age <= 64:
            return AgeGroup.GROUP_55_64
        return AgeGroup.GROUP_65_PLUS


class SpendingConfig(BaseModel):
    """Conditional behavioural spending model.

    Spending probability and amount depend on income bracket, age group,
    employment type, time of day, day of week, and current balance.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # Base hourly probability that a person spends on any given hour
    base_hourly_probability: float = Field(ge=0, le=1)

    # Per-bracket probability multipliers (relative to base)
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

    # Time-of-day curve (24 values, 0.0–1.0 relative multipliers)
    # Peak during morning commute, lunch, evening; low at night
    hourly_multipliers: list[float] = Field(min_length=24, max_length=24)

    # Day-type multipliers
    weekday_multiplier: float = 1.0
    weekend_multiplier: float = 0.7

    # Spending as fraction of monthly salary (per category, per month)
    # These are the *expected* monthly amounts as % of salary
    category_salary_fraction: dict[str, float] = Field(
        description="Expected monthly spending as fraction of salary per category"
    )
    # Volatility (std dev as % of mean) — higher = more unpredictable spending
    category_volatility: dict[str, float]

    # Balance factor: when balance < threshold, reduce discretionary spending
    low_balance_threshold: Decimal
    low_balance_multiplier: float = 0.5  # reduce spending probability when balance is low


class SubscriptionConfig(BaseModel):
    """Subscription penetration model.

    Probability of having each subscription is income- and age-dependent.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # Base penetration rates (fraction of population with each subscription product)
    # Keyed by product name.  Value is the base probability; actual probability
    # is adjusted by income/age multipliers.
    base_penetration: dict[str, float] = Field(
        description="Base probability of subscribing to each product"
    )

    # Income multipliers for subscription likelihood
    income_multiplier_low: float = 0.3
    income_multiplier_lower_middle: float = 0.6
    income_multiplier_middle: float = 1.0
    income_multiplier_upper_middle: float = 1.4
    income_multiplier_high: float = 1.8

    # Age multipliers
    age_multiplier_18_24: float = 1.3
    age_multiplier_25_34: float = 1.1
    age_multiplier_35_44: float = 0.8
    age_multiplier_45_54: float = 0.6
    age_multiplier_55_64: float = 0.4
    age_multiplier_65_plus: float = 0.2

    def income_multiplier(self, bracket: IncomeBracket) -> float:
        match bracket:
            case IncomeBracket.LOW:
                return self.income_multiplier_low
            case IncomeBracket.LOWER_MIDDLE:
                return self.income_multiplier_lower_middle
            case IncomeBracket.MIDDLE:
                return self.income_multiplier_middle
            case IncomeBracket.UPPER_MIDDLE:
                return self.income_multiplier_upper_middle
            case IncomeBracket.HIGH:
                return self.income_multiplier_high
            case _:
                return 1.0

    def age_multiplier(self, group: AgeGroup) -> float:
        match group:
            case AgeGroup.GROUP_18_24:
                return self.age_multiplier_18_24
            case AgeGroup.GROUP_25_34:
                return self.age_multiplier_25_34
            case AgeGroup.GROUP_35_44:
                return self.age_multiplier_35_44
            case AgeGroup.GROUP_45_54:
                return self.age_multiplier_45_54
            case AgeGroup.GROUP_55_64:
                return self.age_multiplier_55_64
            case AgeGroup.GROUP_65_PLUS:
                return self.age_multiplier_65_plus
            case _:
                return 1.0


class EcommerceConfig(BaseModel):
    """E-commerce purchase model.

    People make occasional discretionary purchases from merchant catalogs.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # Base probability that a person shops on any given hour
    base_hourly_probability: float = Field(ge=0, le=1)

    # Per-bracket probability multipliers
    income_multiplier_low: float = 0.2
    income_multiplier_lower_middle: float = 0.5
    income_multiplier_middle: float = 1.0
    income_multiplier_upper_middle: float = 1.5
    income_multiplier_high: float = 2.0

    # Per-age-group multipliers
    age_multiplier_18_24: float = 1.2
    age_multiplier_25_34: float = 1.4
    age_multiplier_35_44: float = 0.8
    age_multiplier_45_54: float = 0.5
    age_multiplier_55_64: float = 0.3
    age_multiplier_65_plus: float = 0.1

    # Log-normal params for order value relative to monthly salary
    order_value_lognormal_mu: float
    order_value_lognormal_sigma: float
    order_value_min: Decimal
    order_value_max: Decimal

    # Max fraction of monthly salary an individual order can be
    max_salary_fraction: float

    def income_multiplier(self, bracket: IncomeBracket) -> float:
        match bracket:
            case IncomeBracket.LOW:
                return self.income_multiplier_low
            case IncomeBracket.LOWER_MIDDLE:
                return self.income_multiplier_lower_middle
            case IncomeBracket.MIDDLE:
                return self.income_multiplier_middle
            case IncomeBracket.UPPER_MIDDLE:
                return self.income_multiplier_upper_middle
            case IncomeBracket.HIGH:
                return self.income_multiplier_high
            case _:
                return 1.0

    def age_multiplier(self, group: AgeGroup) -> float:
        match group:
            case AgeGroup.GROUP_18_24:
                return self.age_multiplier_18_24
            case AgeGroup.GROUP_25_34:
                return self.age_multiplier_25_34
            case AgeGroup.GROUP_35_44:
                return self.age_multiplier_35_44
            case AgeGroup.GROUP_45_54:
                return self.age_multiplier_45_54
            case AgeGroup.GROUP_55_64:
                return self.age_multiplier_55_64
            case AgeGroup.GROUP_65_PLUS:
                return self.age_multiplier_65_plus
            case _:
                return 1.0


class PaymentMethodConfig(BaseModel):
    """Payment method preference distribution."""

    model_config = ConfigDict(extra="forbid")

    upi: float = Field(ge=0, le=1, description="Probability of using UPI")
    card: float = Field(ge=0, le=1, description="Probability of using CARD")
    netbanking: float = Field(ge=0, le=1, description="Probability of using NETBANKING")

    def to_weights_list(self) -> list[tuple[str, float]]:
        return [
            ("UPI", self.upi),
            ("CARD", self.card),
            ("NETBANKING", self.netbanking),
        ]


class SalaryConfig(BaseModel):
    """Salary deposit timing."""

    model_config = ConfigDict(extra="forbid")

    # Probability distribution over days 1-28 (28 values, must sum to ~1.0)
    deposit_day_probs: list[float] = Field(min_length=28, max_length=28)

    # Hour of day salary is deposited (0-23)
    deposit_hour: int = Field(ge=0, le=23)


class TemporalConfig(BaseModel):
    """Time-related simulation parameters."""

    model_config = ConfigDict(extra="forbid")

    start_datetime: datetime
    hours_per_day: int = Field(default=24, ge=1, le=24)
    working_hours: tuple[int, int] = Field(
        default=(9, 18), description="Start and end of business hours"
    )


class SimulationConfig(BaseModel):
    """Top-level configuration for the synthetic financial world."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0.0"

    population: PopulationConfig
    income: IncomeConfig
    age: AgeConfig
    spending: SpendingConfig
    subscriptions: SubscriptionConfig
    ecommerce: EcommerceConfig
    payment_methods: PaymentMethodConfig
    salary: SalaryConfig
    temporal: TemporalConfig

    @property
    def config_version(self) -> str:
        return self.version

    def model_post_init(self, __context: object) -> None:
        """Validate cross-field constraints after initialization."""
        # Spending config: hourly multipliers must have 24 entries
        if len(self.spending.hourly_multipliers) != 24:
            raise ValueError(
                f"spending.hourly_multipliers must have 24 entries, "
                f"got {len(self.spending.hourly_multipliers)}"
            )
        # Salary config: deposit day probs must have 28 entries
        if len(self.salary.deposit_day_probs) != 28:
            raise ValueError(
                f"salary.deposit_day_probs must have 28 entries, "
                f"got {len(self.salary.deposit_day_probs)}"
            )
        # Payment method weights should roughly sum to 1.0
        total = (
            self.payment_methods.upi
            + self.payment_methods.card
            + self.payment_methods.netbanking
        )
        if not 0.9 <= total <= 1.1:
            raise ValueError(
                f"payment method probabilities should sum to ~1.0, got {total}"
            )
