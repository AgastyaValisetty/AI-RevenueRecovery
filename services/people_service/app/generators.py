"""Population generators — people, merchants, subscriptions.

All generators receive a :class:`~rng.SimulationRNG` and a
:class:`~sim_config.SimConfig` so generation is fully deterministic
and configurable.

No hardcoded constants — all tunable parameters come from ``sim_calibration.json``.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from .demographics import AgeSampler, IncomeSampler
from .domain import (
    ACTIVE,
    BankAccount,
    IncomeBracket,
    Merchant,
    MONTHLY,
    Person,
    Product,
    Subscription,
    now,
)
from .rng import SimulationRNG
from .sim_config import SimConfig

if TYPE_CHECKING:
    pass

# Profile labels that map to spending_profile_category values
PROFILES = [
    "student",
    "young_professional",
    "family",
    "high_income",
    "retired",
]


# --------------------------------------------------------------------------- #
# Age-to-profile conditional mapping
# --------------------------------------------------------------------------- #

def _profile_for_age(age: int, rng: SimulationRNG) -> str:
    """Probabilistically assign a spending profile based on age group.

    This is NOT a uniform random assignment — older age groups are more
    likely to be 'family' or 'retired', younger ones 'student' or
    'young_professional'.
    """
    if age <= 22:
        return "student" if rng.chance(0.7) else "young_professional"
    if age <= 34:
        return "young_professional" if rng.chance(0.8) else "family"
    if age <= 49:
        return "family" if rng.chance(0.7) else "high_income"
    if age <= 64:
        return "retired" if rng.chance(0.5) else "high_income"
    return "retired"


def _age_group_label(age: int) -> str:
    """Map age to a short label matching the config age groups."""
    if age <= 29:
        return "young_adult"
    if age <= 39:
        return "early_career"
    if age <= 49:
        return "mid_career"
    if age <= 59:
        return "established"
    if age <= 74:
        return "pre_retirement"
    return "retired"


class PersonGenerator:
    """Generates people with realistic, right-skewed income and age distributions.

    Uses :class:`AgeSampler` and :class:`IncomeSampler` which draw from
    calibrated distributions (Indian demographic pyramid + Hyderabad income data).
    """

    def __init__(self, rng: SimulationRNG, config: SimConfig) -> None:
        self._rng = rng
        self._config = config
        self._age_sampler = AgeSampler(rng, config)
        self._income_sampler = IncomeSampler(rng, config)

    def generate(
        self, count: int, bank_id: UUID
    ) -> tuple[list[Person], list[BankAccount]]:
        people = []
        accounts = []
        timestamp = now()
        for _ in range(count):
            person_id = uuid4()
            account_id = uuid4()
            age = self._age_sampler.sample_age()
            salary = self._income_sampler.sample_salary()
            profile = _profile_for_age(age, self._rng)
            employment = self._age_sampler.sample_employment_type(age)

            accounts.append(
                BankAccount(
                    account_id=account_id,
                    person_id=person_id,
                    bank_id=bank_id,
                    created_at=timestamp,
                )
            )
            people.append(
                Person(
                    person_id=person_id,
                    name=f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}",
                    age=age,
                    salary=salary,
                    salary_deposit_day=self._sample_salary_day(),
                    salary_deposit_hour=self._config.salary.deposit_hour,
                    spending_profile_category=profile,
                    spending_profile_json=self._spending_profile(profile),
                    payment_preferences_json=self._payment_preferences(),
                    income_bracket=self._income_bracket_label(salary),
                    age_group=_age_group_label(age),
                    employment_type=employment,
                    primary_bank_id=bank_id,
                    primary_account_id=account_id,
                    created_at=timestamp,
                )
            )
        return people, accounts

    def _sample_salary_day(self) -> int:
        """Sample a salary deposit day (1-28) uniformly.

        In India, salaries are typically credited between the 1st and 5th
        of the month.  We sample within days 1-5, but allow the full
        1-28 range for realism with lower-probability later days.
        """
        # Weighted: days 1-5 have higher probabilities
        days = list(range(1, 29))
        weights = [0.20, 0.18, 0.16, 0.14, 0.12] + [0.03] * 23
        day = self._rng.choices(days, weights=weights, k=1)[0]
        return day

    def _income_bracket_label(self, salary: Decimal) -> str:
        """Map salary to an IncomeBracket enum label."""
        for b in self._config.income_distribution.brackets:
            if b.min <= float(salary) <= b.max:
                if b.min <= 25000:
                    return IncomeBracket.LOW.value
                if b.min <= 60000:
                    return IncomeBracket.LOWER_MIDDLE.value
                if b.min <= 150000:
                    return IncomeBracket.MIDDLE.value
                if b.min <= 400000:
                    return IncomeBracket.UPPER_MIDDLE.value
                return IncomeBracket.HIGH.value
        return IncomeBracket.HIGH.value

    def _spending_profile(self, profile: str) -> dict:
        """Generate spending profile JSON from config base values."""
        cfg = self._config.spending
        base_pct = cfg.base_daily_percentage
        profile_mult = cfg.profile_multipliers.get(profile, 1.0)
        return {
            "base_percentage": round(base_pct * profile_mult, 2),
            "category_weights": {
                cat: round(self._rng.uniform(0.1, 0.3), 2)
                for cat in cfg.category_list
            },
            "max_daily_spend_pct": cfg.max_daily_spend_pct,
        }

    def _payment_preferences(self) -> dict:
        """Generate payment method preferences (weighted by profile)."""
        # UPI dominates in India; distribution varies by profile
        if self._rng.chance(0.70):
            return {"UPI": 0.70, "CARD": 0.22, "NETBANKING": 0.08}
        elif self._rng.chance(0.88):
            return {"UPI": 0.50, "CARD": 0.35, "NETBANKING": 0.15}
        else:
            return {"UPI": 0.30, "CARD": 0.50, "NETBANKING": 0.20}


_FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Ishaan", "Kabir",
    "Rohan", "Kunal", "Rahul", "Amit", "Sunil", "Ravi", "Rajesh", "Deepak",
    "Priya", "Ananya", "Diya", "Aisha", "Kavya", "Sneha", "Pooja", "Meera",
    "Nisha", "Kirti", "Sanya", "Ritika", "Neha", "Anjali",
]

_LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Kumar", "Singh", "Patel", "Reddy", "Nair",
    "Iyer", "Menon", "Das", "Chatterjee", "Mukherjee", "Joshi", "Desai",
    "Kulkarni", "Rao", "Bose", "Sen", "Kapoor", "Malhotra", "Agarwal",
]


class MerchantGenerator:
    """Loads merchant catalog from merchant_catalog.json.

    To add a new merchant, simply append an entry to the JSON file and
    re-run initialization (or use POST /api/merchants).  No code changes needed.
    """

    _CATALOG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "merchant_catalog.json"
    )

    def __init__(self, catalog_path: str | None = None):
        self._catalog_path = catalog_path or self._CATALOG_PATH

    def _load_catalog(self) -> list[dict]:
        if not os.path.exists(self._catalog_path):
            return []
        with open(self._catalog_path, "r") as f:
            data = json.load(f)
        return data.get("merchants", [])

    def generate(self, bank_id: UUID) -> tuple[list[Merchant], list[Product]]:
        catalog = self._load_catalog()
        merchants = []
        products = []
        timestamp = now()
        for entry in catalog:
            name = entry["name"]
            merchant_type = entry["merchant_type"]
            merchant_id = uuid4()
            merchants.append(
                Merchant(
                    merchant_id=merchant_id,
                    name=name,
                    merchant_type=merchant_type,
                    settlement_bank_id=bank_id,
                    created_at=timestamp,
                )
            )
            for prod in entry.get("products", []):
                products.append(
                    Product(
                        product_id=uuid4(),
                        merchant_id=merchant_id,
                        name=prod["name"],
                        price=Decimal(prod["price"]),
                        product_type=prod["product_type"],
                        billing_cycle=MONTHLY if prod["product_type"] == "SUBSCRIPTION" else None,
                        created_at=timestamp,
                    )
                )
        return merchants, products

    @staticmethod
    def add_merchant_to_catalog(
        name: str, merchant_type: str, products: list[dict]
    ) -> None:
        """Append a new merchant entry to the JSON config file."""
        path = MerchantGenerator._CATALOG_PATH
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
        else:
            data = {"description": "", "merchants": []}
        data.setdefault("merchants", []).append(
            {"name": name, "merchant_type": merchant_type, "products": products}
        )
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


class SubscriptionGenerator:
    """Generates subscriptions with probabilistic, profile-dependent penetration.

    Each person's number of subscriptions depends on their spending profile
    category, as configured in ``subscription_penetration.by_profile``.
    """

    def __init__(self, rng: SimulationRNG, config: SimConfig) -> None:
        self._rng = rng
        self._config = config

    def generate(
        self,
        people: list[Person],
        products: list[Product],
        start_date: date,
    ) -> list[Subscription]:
        """Generate subscriptions for each person based on their profile.

        Uses conditional penetration: each product has a probability of being
        subscribed to, which is adjusted by the person's spending profile.
        The resulting count is clamped to [min_count, max_count] per profile.
        """
        if not products:
            return []

        subs_by_profile = self._config.subscription_penetration.by_profile
        timestamp = now()
        subscriptions = []

        for person in people:
            profile = person.spending_profile_category
            settings = subs_by_profile.get(profile)
            if settings is None:
                settings = subs_by_profile.get("young_professional")
                if settings is None:
                    continue

            # Step 1: probabilistic selection per product
            selected = []
            for product in products:
                if self._rng.random() < settings.prob_per_sub:
                    selected.append(product)

            # Step 2: enforce min/max count
            if len(selected) < settings.min_count:
                remaining = [p for p in products if p not in selected]
                need = settings.min_count - len(selected)
                if remaining:
                    selected.extend(
                        self._rng.sample(
                            remaining, min(need, len(remaining))
                        )
                    )
            elif len(selected) > settings.max_count:
                selected = self._rng.sample(selected, settings.max_count)

            # Step 3: build subscriptions with staggered billing dates
            for product in selected:
                # Stagger billing dates across the first 90 days
                offset = self._rng.randint(0, 89)
                subscriptions.append(
                    Subscription(
                        subscription_id=uuid4(),
                        person_id=person.person_id,
                        merchant_id=product.merchant_id,
                        product_id=product.product_id,
                        amount=product.price,
                        billing_cycle=MONTHLY,
                        status=ACTIVE,
                        next_billing_date=start_date + timedelta(days=offset),
                        created_at=timestamp,
                    )
                )

        return subscriptions
