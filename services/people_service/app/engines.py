import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from .domain import (
    LIVING_COST,
    PENDING,
    SALARY_DEPOSIT,
    PaymentIntent,
    Person,
    Subscription,
    LedgerEntry,
    now,
)

_MONEY = Decimal("0.01")


class SalaryEngine:
    def deposit_for(
        self,
        people: list[Person],
        day_of_month: int,
        on: datetime,
    ) -> list[LedgerEntry]:
        return [
            LedgerEntry(
                entry_id=uuid4(),
                event_type=SALARY_DEPOSIT,
                from_account_id=None,
                to_account_id=person.primary_account_id,
                amount=person.salary,
                simulation_timestamp=on,
            )
            for person in people
            if person.salary_deposit_day == day_of_month
        ]


class SpendingEngine:
    def __init__(self, rng: random.Random):
        self._rng = rng

    CATEGORIES = ["groceries", "utilities", "dining", "transport", "entertainment"]

    def daily_cost(self, person: Person, on: datetime, day_type: str) -> LedgerEntry:
        percentage = self._rng.uniform(1.0, 3.0)
        amount = (
            person.salary * Decimal(str(percentage)) / Decimal(100)
        ).quantize(_MONEY, rounding=ROUND_HALF_UP)
        return LedgerEntry(
            entry_id=uuid4(),
            event_type=LIVING_COST,
            from_account_id=person.primary_account_id,
            to_account_id=None,
            amount=amount,
            simulation_timestamp=on,
            metadata_json={
                "category": self._rng.choice(self.CATEGORIES),
                "day_type": day_type,
                "percentage": round(percentage, 2),
            },
        )


class SubscriptionEngine:
    def __init__(self, rng: random.Random):
        self._rng = rng

    def due_on(self, subscriptions: list[Subscription], on_date: date) -> list[Subscription]:
        return [
            subscription
            for subscription in subscriptions
            if subscription.next_billing_date == on_date
            and subscription.status == "ACTIVE"
        ]

    def build_intent(self, subscription: Subscription, on: datetime) -> PaymentIntent:
        return PaymentIntent(
            intent_id=uuid4(),
            person_id=subscription.person_id,
            merchant_id=subscription.merchant_id,
            product_id=subscription.product_id,
            amount=subscription.amount,
            payment_method=self._rng.choice(["UPI", "CARD", "NETBANKING"]),
            status=PENDING,
            related_subscription_id=subscription.subscription_id,
            created_at=on,
            expires_at=on + timedelta(hours=1),
        )
