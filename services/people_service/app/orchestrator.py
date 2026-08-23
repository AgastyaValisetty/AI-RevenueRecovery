from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from .domain import Bank
from .ports import (
    BankRepository,
    LedgerRepository,
    MerchantRepository,
    PaymentIntentRepository,
    PersonRepository,
    ProductRepository,
    SubscriptionRepository,
)

SIMULATION_START = date(2024, 1, 1)


class SimulationClock:
    def __init__(self, start_date: date = SIMULATION_START):
        self._start = start_date

    def date_for(self, day_index: int) -> date:
        return self._start + timedelta(days=day_index)

    def is_salary_day(self, on_date: date) -> bool:
        return on_date.day == 1


class Orchestrator:
    def __init__(
        self,
        *,
        bank_repo: BankRepository,
        person_repo: PersonRepository,
        merchant_repo: MerchantRepository,
        product_repo: ProductRepository,
        subscription_repo: SubscriptionRepository,
        intent_repo: PaymentIntentRepository,
        ledger_repo: LedgerRepository,
        person_generator,
        merchant_generator,
        subscription_generator,
        salary_engine,
        spending_engine,
        subscription_engine,
        clock: SimulationClock,
    ) -> None:
        self._bank_repo = bank_repo
        self._person_repo = person_repo
        self._merchant_repo = merchant_repo
        self._product_repo = product_repo
        self._subscription_repo = subscription_repo
        self._intent_repo = intent_repo
        self._ledger_repo = ledger_repo
        self._person_generator = person_generator
        self._merchant_generator = merchant_generator
        self._subscription_generator = subscription_generator
        self._salary_engine = salary_engine
        self._spending_engine = spending_engine
        self._subscription_engine = subscription_engine
        self._clock = clock

    def initialize(self, people_count: int) -> None:
        bank = self._bank_repo.find_by_name("RupeeBank")
        if bank is None:
            bank = self._bank_repo.add(self._rupeebank())

        if self._merchant_repo.count() == 0:
            merchants, products = self._merchant_generator.generate(bank.bank_id)
            self._merchant_repo.add(merchants)
            self._product_repo.add(products)

        if self._person_repo.count() == 0:
            people, accounts = self._person_generator.generate(
                people_count, bank.bank_id
            )
            self._person_repo.add_people_with_accounts(people, accounts)
            subscriptions = self._subscription_generator.generate(
                people,
                self._product_repo.subscription_products(),
                self._clock.date_for(0),
            )
            self._subscription_repo.add(subscriptions)

    def run_days(self, days: int) -> None:
        for day_index in range(days):
            on_date = self._clock.date_for(day_index)
            self._deposit_salaries(on_date)
            self._apply_living_costs(on_date)
            self._bill_due_subscriptions(on_date)

    def summary(self) -> dict:
        return {
            "people": self._person_repo.count(),
            "merchants": self._merchant_repo.count(),
            "subscriptions": self._subscription_repo.count(),
            "payment_intents": self._intent_repo.count(),
            "ledger_entries": self._ledger_repo.count(),
        }

    def balance_of(self, account_id) -> Decimal:
        return self._ledger_repo.balance_of(account_id)

    def person_by_id(self, person_id):
        return self._person_repo.find_by_id(person_id)

    def people(self) -> list:
        return self._person_repo.find_all()

    def merchants(self) -> list:
        return self._merchant_repo.find_all()

    def _deposit_salaries(self, on_date: date) -> None:
        if not self._clock.is_salary_day(on_date):
            return
        people = self._person_repo.find_all()
        timestamp = self._at_time(on_date, 9)
        self._ledger_repo.append(
            self._salary_engine.deposit_for(people, on_date.day, timestamp)
        )

    def _apply_living_costs(self, on_date: date) -> None:
        people = self._person_repo.find_all()
        timestamp = self._at_time(on_date, 12)
        day_type = "weekend" if on_date.weekday() >= 5 else "weekday"
        entries = [
            self._spending_engine.daily_cost(person, timestamp, day_type)
            for person in people
        ]
        self._ledger_repo.append(entries)

    def _bill_due_subscriptions(self, on_date: date) -> None:
        subscriptions = self._subscription_repo.find_due_on(on_date)
        if not subscriptions:
            return
        timestamp = self._at_time(on_date, 10)
        intents = [
            self._subscription_engine.build_intent(subscription, timestamp)
            for subscription in subscriptions
        ]
        self._intent_repo.add(intents)

    @staticmethod
    def _at_time(on_date: date, hour: int) -> datetime:
        return datetime(
            on_date.year, on_date.month, on_date.day, hour, tzinfo=timezone.utc
        )

    @staticmethod
    def _rupeebank() -> Bank:
        return Bank(
            bank_id=uuid4(),
            name="RupeeBank",
            authorization_success_rate=Decimal("99.1"),
            timeout_rate=Decimal("0.3"),
            issuer_decline_rate=Decimal("0.4"),
            network_error_rate=Decimal("0.2"),
            current_state="NORMAL",
            state_multipliers_json={
                "NORMAL": 1.0,
                "PEAK": 2.0,
                "DEGRADED": 5.0,
                "OUTAGE": 50.0,
            },
        )
