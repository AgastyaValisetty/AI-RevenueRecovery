import random as _random
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from .domain import Bank, LedgerEntry, PAYMENT_FAILED, PAYMENT_SETTLED, SETTLED, FAILED, now
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
        self._current_day_index = 0

    def sync_to_date(self, latest_date: date) -> None:
        if latest_date and latest_date >= self._start:
            days = (latest_date - self._start).days
            if days > self._current_day_index:
                self._current_day_index = days

    def current_date(self) -> date:
        return self._start + timedelta(days=self._current_day_index)

    def current_day(self) -> int:
        return self._current_day_index

    def date_for(self, day_index: int) -> date:
        return self._start + timedelta(days=day_index)

    def advance(self) -> date:
        self._current_day_index += 1
        return self.current_date()


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

    def _sync_clock(self) -> None:
        latest = self._ledger_repo.latest_simulation_date()
        if latest:
            self._clock.sync_to_date(latest)

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
        self._sync_clock()
        for _ in range(days):
            self._clock.advance()
            on_date = self._clock.current_date()
            self._deposit_salaries(on_date)
            self._apply_living_costs(on_date)
            self._bill_due_subscriptions(on_date)

    def summary(self) -> dict:
        self._sync_clock()
        return {
            "current_day": self._clock.current_day(),
            "current_date": str(self._clock.current_date()),
            "people": self._person_repo.count(),
            "merchants": self._merchant_repo.count(),
            "subscriptions": self._subscription_repo.count(),
            "payment_intents": self._intent_repo.count(),
            "ledger_entries": self._ledger_repo.count(),
        }

    def balance_of(self, account_id) -> Decimal:
        return self._ledger_repo.balance_of(account_id)

    def balance_of_all(self, account_ids: list) -> dict:
        return self._ledger_repo.balances_for_accounts(account_ids)

    def pending_payment_intents(self):
        return self._intent_repo.find_pending()

    def settle_intent(self, intent) -> None:
        self._intent_repo.save(intent)

    def revenue_by_merchant(self) -> dict:
        return self._intent_repo.revenue_by_merchant()

    def settled_transactions_for_merchant(self, merchant_id) -> list:
        return self._intent_repo.settled_by_merchant(merchant_id)

    def monthly_revenue_for_merchant(self, merchant_id) -> list:
        return self._intent_repo.monthly_revenue(merchant_id)

    def balance_of_all(self, account_ids: list) -> dict:
        return self._ledger_repo.balances_for_accounts(account_ids)

    def person_by_id(self, person_id):
        return self._person_repo.find_by_id(person_id)

    def people(self) -> list:
        return self._person_repo.find_all()

    def merchants(self) -> list:
        return self._merchant_repo.find_all()

    def ledger_entries(self, limit: int = 500) -> list:
        return self._ledger_repo.find_recent(limit=limit)

    def subscriptions(self, limit: int = 500) -> list:
        return self._subscription_repo.find_all(limit=limit)

    def payment_intents(self, limit: int = 500) -> list:
        return self._intent_repo.find_all(limit=limit)

    def _deposit_salaries(self, on_date: date) -> None:
        people = self._person_repo.find_all()
        timestamp = self._at_time(on_date, 9)
        deposits = self._salary_engine.deposit_for(people, on_date.day, timestamp)
        if deposits:
            self._ledger_repo.append(deposits)

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

        # Build a person_id → primary_account_id lookup so we can debit the
        # correct bank account in the ledger entries.
        all_people = self._person_repo.find_all()
        account_lookup = {p.person_id: p.primary_account_id for p in all_people}

        # Settle each intent inline and create ledger entries so that
        # subscription payments appear in the ledger and affect balances.
        rng = self._spending_engine._rng
        ledger_entries = []
        updated_intents = []
        for intent, sub in zip(intents, subscriptions):
            status, attempt = self._decide_settlement(intent, sub, rng)
            updated = replace(intent, status=status)
            updated_intents.append(updated)

            if status == SETTLED:
                # Person pays the subscription amount — DEBIT from person's account
                account_id = account_lookup.get(sub.person_id)
                ledger_entries.append(LedgerEntry(
                    entry_id=uuid4(),
                    event_type=PAYMENT_SETTLED,
                    from_account_id=account_id,
                    to_account_id=None,
                    amount=intent.amount,
                    simulation_timestamp=timestamp,
                    related_attempt_id=None,
                    related_subscription_id=sub.subscription_id,
                    metadata_json={
                        "payment_method": intent.payment_method,
                        "amount": str(intent.amount),
                    },
                ))
            else:
                ledger_entries.append(LedgerEntry(
                    entry_id=uuid4(),
                    event_type=PAYMENT_FAILED,
                    from_account_id=None,
                    to_account_id=None,
                    amount=intent.amount,
                    simulation_timestamp=timestamp,
                    related_attempt_id=None,
                    related_subscription_id=sub.subscription_id,
                    metadata_json={
                        "payment_method": intent.payment_method,
                        "failure_reason": "insufficient_funds" if status == FAILED else "bank_declined",
                    },
                ))

        if ledger_entries:
            self._ledger_repo.append(ledger_entries)
        for updated in updated_intents:
            self._intent_repo.save(updated)
        # Update subscription billing dates
        self._subscription_repo.advance_billing_date(
            [s.subscription_id for s in subscriptions], days=30
        )

    def _decide_settlement(self, intent, subscription, rng):
        """Decide whether a payment intent settles or fails.

        Returns (status, attempt_id) where status is SETTLED or FAILED.
        """
        bank = self._bank_repo.find_by_name("RupeeBank")
        person = self._person_repo.find_by_id(subscription.person_id)

        # Check sufficient funds
        if person:
            current_balance = self._ledger_repo.balance_of(person.primary_account_id)
            if current_balance < intent.amount:
                return FAILED, f"ATT_{str(intent.intent_id)}_{1}"

        # Probabilistic bank decision based on authorization_success_rate
        success_rate = float(bank.authorization_success_rate) if bank else 99.1
        state_multipliers = bank.state_multipliers_json if bank else {"NORMAL": 1.0}
        multiplier = state_multipliers.get(bank.current_state, 1.0) if bank else 1.0
        effective_success_rate = max(0, success_rate - (multiplier - 1.0) * 5.0)

        if rng.random() * 100 < effective_success_rate:
            return SETTLED, f"ATT_{str(intent.intent_id)}_{1}"
        else:
            return FAILED, f"ATT_{str(intent.intent_id)}_{1}"

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
