"""Orchestrator — drives the synthetic financial simulation on an hourly clock.

The simulation clock operates at hourly granularity.  Each call to
:meth:`Orchestrator.run_hours` advances the clock by one hour and dispatches
phase logic keyed on the hour-of-day:

- **09:00** on salary days → deposit salaries (minus 30% income tax)
- **12:00** daily → apply living costs (spending, +18% GST)
- **10:00** on billing dates → bill due subscriptions → create + settle PaymentIntents
- **10–20** business hours → e-commerce shopping decisions → create + settle PaymentIntents

Payment intents are settled inline during the simulation (balance-aware).  If
the person's account balance covers the amount the intent is ``SETTLED``;
otherwise it ``FAILED``.  This keeps the simulation self-contained — revenue
flows to merchants and money circulates through the ledger.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from .domain import (
    Bank,
    FAILURE_REASONS,
    FAILURE_CATEGORIES,
    LedgerEntry,
    LIVING_COST,
    ORDER_PURCHASE,
    PAYMENT_SETTLED,
    PAYMENT_FAILED,
    PENDING,
    SALARY_DEPOSIT,
    SETTLED,
    FAILED,
    INTENT_SETTLED,
    INTENT_FAILED,
    PaymentIntent,
    SimulationRun,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    now,
)
from .ports import (
    BankRepository,
    LedgerRepository,
    MerchantRepository,
    PaymentIntentRepository,
    PersonRepository,
    ProductRepository,
    SimulationRunRepository,
    SubscriptionRepository,
)
from .failure_model import classify_failure, failure_probability
from .rng import SimulationRNG
from .sim_config import SimConfig

logger = logging.getLogger(__name__)

SIMULATION_START = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class SimulationClock:
    """Hourly-granularity simulation clock.

    Wraps a virtual start datetime and an hour counter.  All time advances
    happen in 1-hour increments via :meth:`advance`.
    """

    def __init__(self, start_datetime: datetime | None = None):
        self._start = start_datetime or SIMULATION_START
        self._current_hour_index: int = 0

    def sync_to_timestamp(self, latest_timestamp: datetime | None) -> None:
        """Jump the clock forward to match the latest ledger entry timestamp."""
        if latest_timestamp is None:
            return
        # SQLite may return naive datetimes (no tzinfo); normalize to UTC-aware
        if latest_timestamp.tzinfo is None:
            latest_timestamp = latest_timestamp.replace(tzinfo=timezone.utc)
        if latest_timestamp >= self._start:
            hours = int(
                (latest_timestamp - self._start).total_seconds() // 3600
            )
            if hours > self._current_hour_index:
                self._current_hour_index = hours

    @property
    def current_datetime(self) -> datetime:
        return self._start + timedelta(hours=self._current_hour_index)

    @property
    def current_date(self) -> date:
        return self.current_datetime.date()

    @property
    def current_hour(self) -> int:
        return self._current_hour_index

    @property
    def current_hour_of_day(self) -> int:
        return self._current_hour_index % 24

    @property
    def current_day_index(self) -> int:
        return self._current_hour_index // 24

    @property
    def day_of_week(self) -> int:
        """0 = Monday, 6 = Sunday."""
        return self.current_datetime.weekday()

    @property
    def is_weekend(self) -> bool:
        return self.day_of_week >= 5

    def date_for_hour(self, hour_index: int) -> date:
        return (self._start + timedelta(hours=hour_index)).date()

    def advance(self) -> datetime:
        """Advance the clock by one hour. Returns the new datetime."""
        self._current_hour_index += 1
        return self.current_datetime


class Orchestrator:
    """Coordinates simulation phases across all repositories and engines."""

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
        ecommerce_engine=None,
        rng: SimulationRNG | None = None,
        sim_config: SimConfig | None = None,
        sim_run_repo: SimulationRunRepository | None = None,
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
        self._ecommerce_engine = ecommerce_engine
        self._clock = clock
        self._rng = rng or SimulationRNG(42)
        self._config = sim_config
        self._sim_run_repo = sim_run_repo
        self._current_run: SimulationRun | None = None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, people_count: int, seed: int | None = None) -> UUID | None:
        """Initialize simulation data (bank, merchants, people, subscriptions).

        If ``seed`` is provided, a new ``SimulationRNG`` is created with that
        seed.  A ``SimulationRun`` record is created if a run repository is
        available.  Returns the run_id (or None if no run repo).
        """
        if seed is not None:
            self._rng = SimulationRNG(seed)

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
                self._clock.current_date,
            )
            self._subscription_repo.add(subscriptions)

        # Create a SimulationRun record for traceability
        run_id = None
        if self._sim_run_repo is not None:
            config_snapshot = (
                {"version": self._config.version} if self._config else {}
            )
            run = SimulationRun(
                run_id=uuid4(),
                seed=self._rng.seed or 42,
                config_snapshot=config_snapshot,
                people_count=people_count,
                status=STATUS_RUNNING,
                started_at=now(),
            )
            self._sim_run_repo.create(run)
            self._current_run = run
            run_id = run.run_id

        return run_id

    # ------------------------------------------------------------------
    # Main loop — hourly
    # ------------------------------------------------------------------

    def run_hours(self, hours: int) -> None:
        """Run the simulation forward by ``hours`` hours.

        Each hour advances the clock and dispatches phase logic based on
        the hour-of-day and date.  Payment intents created during subscription
        billing or e-commerce phases are settled inline immediately.

        - Hour 09 → salary deposit (minus 30% income tax)
        - Hour 12 → living costs (spending, +18% GST) for all people
        - Hour 10 → subscription billing (on due dates) → create + settle intents
        - Hours 10–20 → e-commerce shopping decisions → create + settle intents
        """
        self._sync_clock()

        if self._current_run is not None and self._sim_run_repo is not None:
            self._sim_run_repo.update_status(
                self._current_run.run_id, STATUS_RUNNING
            )

        try:
            for _ in range(hours):
                current_dt = self._clock.advance()
                on_date = current_dt.date()
                day_type = "weekend" if self._clock.is_weekend else "weekday"

                # Phase: salary deposit at 09:00 on deposit day
                if current_dt.hour == 9:
                    self._deposit_salaries(on_date, current_dt)

                # Phase: living costs at 12:00 daily
                if current_dt.hour == 12:
                    self._apply_living_costs(on_date, current_dt, day_type)

                # Phase: subscription billing at 10:00 on due dates
                if current_dt.hour == 10:
                    self._bill_due_subscriptions(on_date, current_dt)

                # Phase: e-commerce purchases during business hours (10-20)
                if 10 <= current_dt.hour <= 20:
                    self._generate_ecommerce_purchases(current_dt, day_type)

            # Update run status to COMPLETED
            if self._current_run is not None and self._sim_run_repo is not None:
                self._sim_run_repo.update_status(
                    self._current_run.run_id,
                    STATUS_COMPLETED,
                    hours_run=self._clock.current_hour,
                )
                self._current_run = None

        except Exception as exc:
            logger.exception("Simulation failed")
            if self._current_run is not None and self._sim_run_repo is not None:
                self._sim_run_repo.update_status(
                    self._current_run.run_id,
                    STATUS_FAILED,
                    error_message=str(exc),
                    hours_run=self._clock.current_hour,
                )
            raise

    # Backward compatibility — converts days to hours
    def run_days(self, days: int) -> None:
        self.run_hours(days * 24)

    # ------------------------------------------------------------------
    # Summary and queries
    # ------------------------------------------------------------------

    def _sync_clock(self) -> None:
        latest = self._ledger_repo.latest_simulation_timestamp()
        if latest:
            self._clock.sync_to_timestamp(latest)

    def summary(self) -> dict:
        self._sync_clock()
        result = {
            "current_day": self._clock.current_day_index,
            "current_date": str(self._clock.current_date),
            "current_hour": self._clock.current_hour,
            "current_datetime": self._clock.current_datetime.isoformat(),
            "people": self._person_repo.count(),
            "merchants": self._merchant_repo.count(),
            "subscriptions": self._subscription_repo.count(),
            "payment_intents": self._intent_repo.count(),
            "ledger_entries": self._ledger_repo.count(),
        }
        if self._current_run is not None:
            result["latest_run_id"] = str(self._current_run.run_id)
            result["latest_run_seed"] = self._current_run.seed
            result["latest_run_status"] = self._current_run.status
        elif self._sim_run_repo is not None:
            latest = self._sim_run_repo.find_latest()
            if latest:
                result["latest_run_id"] = str(latest.run_id)
                result["latest_run_seed"] = latest.seed
                result["latest_run_status"] = latest.status
        return result

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

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    def _deposit_salaries(self, on_date: date, current_dt: datetime) -> None:
        """Deposit salaries (net of income tax) for people whose deposit day matches.

        Delegates to :class:`~engines.SalaryEngine` which returns both the
        net salary deposit (70% after 30% tax) and a separate ``INCOME_TAX``
        ledger entry for the deducted tax.
        """
        people = self._person_repo.find_all()
        deposits = self._salary_engine.deposit_for(people, on_date.day, current_dt)
        if deposits:
            self._ledger_repo.append(deposits)

    def _apply_living_costs(
        self, on_date: date, current_dt: datetime, day_type: str
    ) -> None:
        """Apply daily living costs for all people (one entry per person per day).

        The SpendingEngine computes a conditional spend amount that depends on:
        - person's income bracket, age group, spending profile
        - time of day, day type (weekday/weekend)
        - current balance (balance-aware scaling)
        """
        people = self._person_repo.find_all()
        account_ids = [p.primary_account_id for p in people]
        balances = self._ledger_repo.balances_for_accounts(account_ids)

        entries = []
        for person in people:
            balance = balances.get(person.primary_account_id, Decimal("0"))
            entry = self._spending_engine.daily_cost(
                person, current_dt, day_type, current_balance=balance
            )
            if entry is not None:
                entries.append(entry)
        if entries:
            self._ledger_repo.append(entries)

    def _bill_due_subscriptions(self, on_date: date, current_dt: datetime) -> None:
        """Create and settle PaymentIntents for due subscriptions.

        GST (18%) is applied to each subscription amount by the
        :class:`~engines.SubscriptionEngine`.  Intents are settled inline
        — if the person has sufficient balance the intent is ``SETTLED``,
        otherwise it ``FAILED``.  Subscriptions that fail consecutively
        are cancelled.
        """
        subscriptions = self._subscription_repo.find_due_on(on_date)
        if not subscriptions:
            return

        # Build a person lookup so intents use each person's payment-method
        # preferences (UPI-dominated) instead of a uniform roll.
        prefs = {
            p.person_id: p.payment_preferences_json
            for p in self._person_repo.find_all()
        }

        # Build intents (GST applied inside SubscriptionEngine.build_intent)
        intents = [
            self._subscription_engine.build_intent(
                sub, current_dt, prefs.get(sub.person_id)
            )
            for sub in subscriptions
        ]
        self._intent_repo.add(intents)

        # Advance billing dates for all due subscriptions (monthly cycle)
        self._subscription_repo.advance_billing_date(
            [s.subscription_id for s in subscriptions], days=30
        )

        # Settle inline
        self._settle_payment_intents(intents, current_dt)

        # Cancel subscriptions that just failed
        self._cancel_failed_subscriptions(intents)

    def _generate_ecommerce_purchases(
        self, current_dt: datetime, day_type: str
    ) -> None:
        """Generate and settle e-commerce purchase PaymentIntents.

        During business hours the EcommerceEngine decides whether each person
        shops.  The PurchaseDecision amount already includes 18% GST (applied
        in the engine).  Intents are settled inline immediately.
        """
        if self._ecommerce_engine is None:
            return

        people = self._person_repo.find_all()
        merchants = self._merchant_repo.find_all()
        products = self._product_repo.find_all_products()
        account_ids = [p.primary_account_id for p in people]
        balances = self._ledger_repo.balances_for_accounts(account_ids)

        is_salary_day = self._is_salary_day(current_dt.date())

        intents = []
        for person in people:
            balance = balances.get(person.primary_account_id, Decimal("0"))
            decision = self._ecommerce_engine.generate_purchase(
                person,
                merchants,
                products,
                current_dt,
                balance,
                is_salary_day,
            )
            if decision is not None:
                intent = self._subscription_engine.build_intent_from_decision(
                    decision, current_dt, person.payment_preferences_json
                )
                intents.append(intent)

        if intents:
            self._intent_repo.add(intents)
            # Settle inline — money debits the person's account immediately
            self._settle_payment_intents(intents, current_dt)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_salary_day(self, on_date: date) -> bool:
        """Check if any person has a salary deposit on this date."""
        people = self._person_repo.find_all()
        return any(p.salary_deposit_day == on_date.day for p in people)

    def _settle_payment_intents(
        self, intents: list[PaymentIntent], current_dt: datetime
    ) -> None:
        """Settle payment intents inline during the simulation.

        For each intent:
        - If the person's balance >= intent amount → ``SETTLED``
          (debit the person's account, record a ``PAYMENT_SETTLED`` ledger
          entry).  The credit side goes to ``to_account_id=None`` — money
          leaves the simulation's circulating pool and enters the merchant's
          settlement account via the Bank Service in a real deployment.
        - If the balance is insufficient → ``FAILED``
          (record a ``PAYMENT_FAILED`` ledger entry, debit the amount
          regardless to accurately reflect the attempted deduction).

        Updated intents are persisted so revenue queries see ``SETTLED``
        intents.
        """
        from dataclasses import replace

        account_ids = [intent.person_id for intent in intents]
        people = self._person_repo.find_all()
        balance_map = {}
        for p in people:
            balance_map[p.person_id] = self._ledger_repo.balance_of(
                p.primary_account_id
            )

        # Bank state feeds P(failure) (degraded/outage banks fail more).
        bank = self._bank_repo.find_by_name("RupeeBank")
        bank_state = bank.current_state if bank else "NORMAL"

        ledger_entries = []
        updated_intents = []
        for intent in intents:
            balance = balance_map.get(intent.person_id, Decimal("0"))
            person = next(
                (p for p in people if p.person_id == intent.person_id), None
            )
            debit_account = (
                str(person.primary_account_id) if person else None
            )

            amount_f = float(intent.amount)
            balance_f = float(balance)

            failure_code = None
            if balance < intent.amount:
                # Real insolvency — deterministic, dominant CUSTOMER_STATE bucket.
                status = INTENT_FAILED
                failure_code = "INSUFFICIENT_FUNDS"
            elif self._rng.random() < failure_probability(
                intent.payment_method,
                bank_state=bank_state,
                amount=amount_f,
                balance=balance_f,
                hour=current_dt.hour,
            ):
                status = INTENT_FAILED
                failure_code, _cat = classify_failure(
                    self._rng, method=intent.payment_method, bank_state=bank_state
                )
            else:
                status = INTENT_SETTLED

            updated = replace(intent, status=status)
            updated_intents.append(updated)

            event_type = PAYMENT_SETTLED if status == INTENT_SETTLED else PAYMENT_FAILED
            metadata: dict = {
                "payment_method": intent.payment_method,
                "amount": str(intent.amount),
                "person_id": str(intent.person_id),
                "merchant_id": str(intent.merchant_id),
                "settled_inline": True,
            }
            # Every inline failure carries its real reason + category.
            if status == INTENT_FAILED:
                metadata["failure_code"] = failure_code
                metadata["failure_reason"] = FAILURE_REASONS[failure_code]
                metadata["failure_category"] = FAILURE_CATEGORIES[failure_code]
            # A FAILED payment never debits the person's account — the funds are
            # simply not moved.  Only a SETTLED payment debits.  This keeps
            # balances from drifting below zero on failed transactions.
            if status == INTENT_SETTLED:
                debit_from = debit_account
            else:
                debit_from = None  # no money leaves the account on failure
            ledger_entries.append(LedgerEntry(
                entry_id=uuid4(),
                event_type=event_type,
                from_account_id=debit_from,
                to_account_id=None,
                amount=intent.amount,
                simulation_timestamp=current_dt,
                related_attempt_id=None,
                related_subscription_id=intent.related_subscription_id,
                metadata_json=metadata,
            ))

        if updated_intents:
            for ui in updated_intents:
                self._intent_repo.save(ui)
        if ledger_entries:
            self._ledger_repo.append(ledger_entries)

    def _cancel_failed_subscriptions(
        self, intents: list[PaymentIntent]
    ) -> None:
        """Increment failure count / cancel subscriptions linked to failed intents.

        If a subscription's payment intent failed and it hits the failure
        threshold, its status is set to ``CANCELLED``.
        """
        from dataclasses import replace

        failed_sub_ids = [
            i.related_subscription_id
            for i in intents
            if i.status == INTENT_FAILED and i.related_subscription_id is not None
        ]
        if not failed_sub_ids:
            return
        for sub_id in failed_sub_ids:
            sub = self._subscription_repo.find(sub_id)
            if sub is None or sub.status != "ACTIVE":
                continue
            new_failures = sub.consecutive_failures + 1
            new_status = "CANCELLED" if new_failures >= 3 else sub.status
            updated = replace(
                sub,
                consecutive_failures=new_failures,
                status=new_status,
                cancelled_at=now() if new_status == "CANCELLED" else sub.cancelled_at,
            )
            self._subscription_repo.save(updated)

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
