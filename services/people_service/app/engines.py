"""Simulation engines — salary, spending, subscription, and e-commerce.

Each engine receives a :class:`~rng.SimulationRNG` and a :class:`~sim_config.SimConfig`
so all behaviour is fully deterministic and configurable.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from .domain import (
    ACTIVE,
    LIVING_COST,
    ORDER_PURCHASE,
    PENDING,
    SALARY_DEPOSIT,
    INCOME_TAX,
    PaymentIntent,
    PurchaseDecision,
    Person,
    Subscription,
    LedgerEntry,
    now,
)
from .rng import SimulationRNG
from .sim_config import SimConfig

logger = logging.getLogger(__name__)

_MONEY = Decimal("0.01")

# Government (tax) account — receives income tax and GST
GOV_TAX_ACCOUNT = "account_government_tax"


class SalaryEngine:
    """Deposits salaries when a person's deposit day matches the current date.

    Salary is deposited at the configured hour (default 09:00).
    Income tax (configurable rate, default 30%) is deducted from gross
    salary before deposit, with the tax amount recorded as a separate
    ``INCOME_TAX`` ledger entry to the government account.
    """

    def __init__(self, config: SimConfig) -> None:
        self._config = config
        self._deposit_hour = config.salary.deposit_hour
        self._tax_rate = config.tax.income_tax_rate

    @property
    def deposit_hour(self) -> int:
        return self._deposit_hour

    def deposit_for(
        self, people: list[Person], day_of_month: int, on: datetime
    ) -> list[LedgerEntry]:
        entries = []
        for person in people:
            if person.salary_deposit_day != day_of_month:
                continue
            gross = person.salary
            tax_amount = (gross * Decimal(str(self._tax_rate))).quantize(
                _MONEY, rounding=ROUND_HALF_UP
            )
            net = (gross - tax_amount).quantize(_MONEY, rounding=ROUND_HALF_UP)

            entries.append(
                LedgerEntry(
                    entry_id=uuid4(),
                    event_type=SALARY_DEPOSIT,
                    from_account_id=None,
                    to_account_id=str(person.primary_account_id),
                    amount=net,
                    simulation_timestamp=on,
                    metadata_json={
                        "person_id": str(person.person_id),
                        "salary_deposit_day": person.salary_deposit_day,
                        "gross_salary": str(gross),
                        "tax_deducted": str(tax_amount),
                        "tax_rate": str(self._tax_rate),
                    },
                )
            )
            entries.append(
                LedgerEntry(
                    entry_id=uuid4(),
                    event_type=INCOME_TAX,
                    from_account_id=None,
                    to_account_id=GOV_TAX_ACCOUNT,
                    amount=tax_amount,
                    simulation_timestamp=on,
                    metadata_json={
                        "person_id": str(person.person_id),
                        "gross_salary": str(gross),
                        "tax_rate": str(self._tax_rate),
                    },
                )
            )
        return entries


class SpendingEngine:
    """Conditional behavioural spending model.

    Spending probability and amount depend on:
    - Person's income bracket, age group, employment type, spending profile
    - Time of day (hour), day type (weekday/weekend)
    - Current account balance (balance-aware scaling)

    The engine produces one ``LIVING_COST`` ledger entry per person per day
    (at 12:00 simulation time), but the *probability* and *amount* are
    computed conditionally.  GST (configurable, default 18%) is added to
    every spending amount — the quoted amount is exclusive of tax.
    """

    def __init__(self, rng: SimulationRNG, config: SimConfig) -> None:
        self._rng = rng
        self._config = config
        self._gst_rate = config.tax.gst_rate

    def daily_spend_percentage(
        self,
        person: Person,
        on_date: date,
        current_balance: Decimal | None = None,
    ) -> Decimal:
        """Compute the percentage of salary to spend on a given day.

        Algorithm:
        1. Start with ``base_daily_percentage`` from config.
        2. Apply salary-day boost if today is a salary deposit day.
        3. Apply weekend boost if Saturday/Sunday.
        4. Multiply by profile multiplier (student, family, etc.).
        5. Scale by balance factor if balance < low_balance_threshold.
        6. Add random variation (Gaussian) around the computed base.
        7. Clamp to [0, max_daily_spend_pct].
        """
        cfg = self._config.spending
        base = cfg.base_daily_percentage

        # Salary-day boost
        if on_date.day in cfg.salary_day_boost_days:
            base += cfg.salary_day_boost

        # Weekend adjustment
        if on_date.weekday() >= 5:
            base *= cfg.weekend_multiplier
        else:
            base *= cfg.weekday_multiplier

        # Profile multiplier
        profile = person.spending_profile_category
        profile_mult = cfg.profile_multipliers.get(profile, 1.0)
        base *= profile_mult

        # Income bracket multiplier (higher income → higher spend proportion)
        income_mults = {
            "low": cfg.probability_multiplier_low,
            "lower_middle": cfg.probability_multiplier_lower_middle,
            "middle": cfg.probability_multiplier_middle,
            "upper_middle": cfg.probability_multiplier_upper_middle,
            "high": cfg.probability_multiplier_high,
        }
        income_mult = income_mults.get(
            getattr(person, "income_bracket", "middle"), 1.0
        )
        base *= income_mult

        # Age group multiplier
        age_mults = {
            "18-24": cfg.prob_mult_age_18_24,
            "25-34": cfg.prob_mult_age_25_34,
            "35-44": cfg.prob_mult_age_35_44,
            "45-54": cfg.prob_mult_age_45_54,
            "55-64": cfg.prob_mult_age_55_64,
            "65+": cfg.prob_mult_age_65_plus,
        }
        age_mult = age_mults.get(getattr(person, "age_group", "35-44"), 1.0)
        base *= age_mult

        # Employment multiplier
        emp_mults = {
            "salaried": cfg.prob_mult_employed,
            "self_employed": cfg.prob_mult_self_employed,
            "student": cfg.prob_mult_student,
            "retired": cfg.prob_mult_retired,
            "unemployed": cfg.prob_mult_unemployed,
        }
        emp_mult = emp_mults.get(
            getattr(person, "employment_type", "salaried"), 1.0
        )
        base *= emp_mult

        # Balance-aware scaling
        if current_balance is not None and current_balance is not None:
            low_threshold = cfg.low_balance_threshold
            if current_balance < low_threshold:
                # Reduce spending when balance is low
                if person.salary > 0:
                    ratio = float(current_balance / person.salary)
                    ratio = max(0.0, min(1.0, ratio))
                    base *= ratio * cfg.low_balance_multiplier + (1 - ratio)
                else:
                    base *= cfg.low_balance_multiplier

        # Random variation (Gaussian noise)
        if cfg.random_variation_std > 0:
            noise = self._rng.normalvariate(0, cfg.random_variation_std)
            base = max(0.0, base * (1 + noise))

        # Clamp
        base = max(0.0, min(base, cfg.max_daily_spend_pct))

        return Decimal(str(base)).quantize(_MONEY, rounding=ROUND_HALF_UP)

    def daily_cost(
        self,
        person: Person,
        on: datetime,
        day_type: str,
        current_balance: Decimal | None = None,
    ) -> LedgerEntry | None:
        """Generate a living-cost ledger entry for a person on a given day.

        Returns ``None`` if the person has zero balance and insufficient
        salary history (edge case — shouldn't normally happen).
        """
        percentage = self.daily_spend_percentage(
            person, on.date(), current_balance
        )
        amount = (
            person.salary * percentage / Decimal(100)
        ).quantize(_MONEY, rounding=ROUND_HALF_UP)

        if amount <= 0:
            return None

        # Apply GST — the quoted amount is exclusive of tax
        gst_amount = (amount * Decimal(str(self._gst_rate))).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )
        total = (amount + gst_amount).quantize(_MONEY, rounding=ROUND_HALF_UP)

        # Never spend more than the person currently holds — prevents the
        # balance from going negative on living costs.
        if current_balance is not None:
            total = min(total, current_balance).quantize(_MONEY, rounding=ROUND_HALF_UP)
            if total <= 0:
                return None

        category = self._rng.choice(self._config.spending.category_list)
        return LedgerEntry(
            entry_id=uuid4(),
            event_type=LIVING_COST,
            from_account_id=str(person.primary_account_id),
            to_account_id=None,
            amount=total,
            simulation_timestamp=on,
            metadata_json={
                "category": category,
                "day_type": day_type,
                "percentage": str(percentage),
                "income_bracket": getattr(person, "income_bracket", "unknown"),
                "base_amount": str(amount),
                "gst_amount": str(gst_amount),
                "gst_rate": str(self._gst_rate),
            },
        )


class SubscriptionEngine:
    """Builds payment intents for due subscriptions.

    GST (configurable, default 18%) is applied to subscription amounts —
    the stored ``amount`` is the exclusive-of-tax product price; the
    intent amount is grossed up by ``1 + gst_rate``.
    """

    def __init__(self, rng: SimulationRNG, config: SimConfig | None = None) -> None:
        self._rng = rng
        self._gst_rate = config.tax.gst_rate if config else 0.18

    def due_on(self, subscriptions: list[Subscription], on_date: date) -> list[Subscription]:
        return [
            subscription
            for subscription in subscriptions
            if subscription.next_billing_date == on_date
            and subscription.status == ACTIVE
        ]

    def _apply_gst(self, amount: Decimal) -> Decimal:
        """Add GST to a base amount."""
        gst = (amount * Decimal(str(self._gst_rate))).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )
        return (amount + gst).quantize(_MONEY, rounding=ROUND_HALF_UP)

    def _pick_method(self, preferences: dict | None) -> str:
        """Sample a payment method using the person's stored weighted
        preferences (UPI-dominated in India), falling back to a sensible
        default split when no preferences are available."""
        if preferences:
            options = ["UPI", "CARD", "NETBANKING"]
            weights = [
                max(0.0, float(preferences.get(m, 0.0))) for m in options
            ]
            if sum(weights) > 0:
                return self._rng.choices(options, weights=weights, k=1)[0]
        # Uniform fallback (matches prior default behaviour)
        return self._rng.choice(["UPI", "CARD", "NETBANKING"])

    def build_intent(
        self, subscription: Subscription, on: datetime, preferences: dict | None = None
    ) -> PaymentIntent:
        payment_method = self._pick_method(preferences)
        gross_amount = self._apply_gst(subscription.amount)
        return PaymentIntent(
            intent_id=uuid4(),
            person_id=subscription.person_id,
            merchant_id=subscription.merchant_id,
            product_id=subscription.product_id,
            amount=gross_amount,
            payment_method=payment_method,
            status=PENDING,
            related_subscription_id=subscription.subscription_id,
            created_at=on,
            expires_at=on + timedelta(hours=1),
        )

    def build_intent_from_decision(
        self, decision: PurchaseDecision, on: datetime, preferences: dict | None = None
    ) -> PaymentIntent:
        """Build a PaymentIntent from an e-commerce PurchaseDecision."""
        payment_method = self._pick_method(preferences)
        return PaymentIntent(
            intent_id=uuid4(),
            person_id=decision.person_id,
            merchant_id=decision.merchant_id,
            product_id=decision.product_id,
            amount=decision.amount,
            payment_method=payment_method,
            status=PENDING,
            related_subscription_id=None,
            created_at=on,
            expires_at=on + timedelta(hours=1),
        )


class EcommerceEngine:
    """Conditional e-commerce purchase model.

    Decides whether a person shops during a given hour based on:
    - Person's income bracket, age group, spending profile
    - Whether it's a salary day (boosted shopping probability)
    - Current balance (must afford at least the minimum order)
    - Business hours constraint (checked by orchestrator)

    GST (configurable, default 18%) is added to every purchase amount.
    """

    def __init__(self, rng: SimulationRNG, config: SimConfig) -> None:
        self._rng = rng
        self._config = config
        self._gst_rate = config.tax.gst_rate

    def generate_purchase(
        self,
        person: Person,
        merchants: list,
        products: list,
        on: datetime,
        current_balance: Decimal,
        is_salary_day: bool,
    ) -> PurchaseDecision | None:
        """Determine if a person makes an e-commerce purchase this hour.

        Returns a :class:`PurchaseDecision` if the person shops, ``None`` otherwise.
        """
        cfg = self._config.ecommerce

        # Base probability from config
        base_prob = cfg.shop_probability_by_profile.get(
            person.spending_profile_category, 0.1
        )

        # Salary day boost
        if is_salary_day:
            base_prob *= cfg.salary_day_boost_multiplier

        # Income bracket multiplier
        income_mults = {
            "low": cfg.income_multiplier_low,
            "lower_middle": cfg.income_multiplier_lower_middle,
            "middle": cfg.income_multiplier_middle,
            "upper_middle": cfg.income_multiplier_upper_middle,
            "high": cfg.income_multiplier_high,
        }
        income_mult = income_mults.get(
            getattr(person, "income_bracket", "middle"), 1.0
        )
        base_prob *= income_mult

        # Age group multiplier
        age_mults = {
            "18-24": cfg.age_multiplier_18_24,
            "25-34": cfg.age_multiplier_25_34,
            "35-44": cfg.age_multiplier_35_44,
            "45-54": cfg.age_multiplier_45_54,
            "55-64": cfg.age_multiplier_55_64,
            "65+": cfg.age_multiplier_65_plus,
        }
        age_mult = age_mults.get(
            getattr(person, "age_group", "35-44"), 1.0
        )
        base_prob *= age_mult

        # Check if person shops
        if not self._rng.chance(base_prob):
            return None

        # Filter to one-time products (e-commerce purchases)
        one_time_products = [
            p for p in products if p.product_type != "SUBSCRIPTION"
        ]
        if not one_time_products:
            return None

        # Check balance — must be able to afford at least the cheapest option
        min_price = min(float(p.price) for p in one_time_products)
        if float(current_balance) < min_price:
            return None

        # Select a merchant (weighted by merchant_split)
        merchant_names = list(cfg.merchant_split.keys())
        merchant_weights = list(cfg.merchant_split.values())
        chosen_merchant_name = self._rng.choices(
            merchant_names, weights=merchant_weights, k=1
        )[0]

        # Find products from the chosen merchant
        matching_products = [
            p for p in one_time_products if self._product_matches_merchant(
                p, chosen_merchant_name, merchants
            )
        ]
        if not matching_products:
            matching_products = one_time_products

        product = self._rng.choice(matching_products)

        # Sample order value bracket
        bracket = self._rng.choices(
            cfg.order_value_brackets,
            weights=[b.weight for b in cfg.order_value_brackets],
            k=1,
        )[0]
        # Draw uniform within bracket
        amount = self._rng.uniform(float(bracket.min), float(bracket.max))

        # Cap at max fraction of current balance
        balance_cap = float(current_balance) * cfg.max_order_pct_of_balance
        amount = min(amount, balance_cap)

        # Cap at max fraction of monthly salary
        salary_cap = float(person.salary) * cfg.max_order_pct_of_salary
        amount = min(amount, salary_cap)

        # Cap at product price (can't buy more than 3x the product price)
        if product.price > 0:
            amount = min(amount, float(product.price) * 3)

        if amount <= 0:
            return None

        # Apply GST — quoted amount is exclusive of tax
        gst_amount = amount * self._gst_rate
        total = amount + gst_amount

        return PurchaseDecision(
            person_id=person.person_id,
            merchant_id=product.merchant_id,
            product_id=product.product_id,
            amount=Decimal(str(total)).quantize(
                _MONEY, rounding=ROUND_HALF_UP
            ),
            decision_time=on,
            reason="salary_day" if is_salary_day else "normal",
        )

    def _product_matches_merchant(
        self, product, merchant_name: str, merchants: list
    ) -> bool:
        """Check if a product belongs to a merchant matching the given name.

        Normalises both the configured key and the merchant name by
        lower-casing and stripping whitespace/underscores so that
        ``"flip_cartel"`` matches ``"Flip Cartel"``.
        """
        def _norm(s: str) -> str:
            return s.lower().replace(" ", "").replace("_", "").replace("-", "")

        target = _norm(merchant_name)
        for m in merchants:
            if (
                _norm(m.name) == target
                and m.merchant_id == product.merchant_id
            ):
                return True
        # Fallback: prefix match on normalised name
        for m in merchants:
            if (
                m.merchant_id == product.merchant_id
                and _norm(m.name).startswith(target[:5])
            ):
                return True
        return False
