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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from .recovery import (
    BaselineRecoveryEngine,
    CustomerResponseSimulator,
    RecoveryActionExecutor,
    RecoveryActionRepository,
    RecoveryActionType,
    RecoveryContextBuilder,
    RecoveryOutcome,
    RecoveryRunMetadata,
    RecoveryRunTracker,
    RecoveryScheduler,
    RecoveryEngineType,
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
        recovery_repo: RecoveryActionRepository | None = None,
        settings=None,
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
        # Recovery system (optional — baseline is a no-op if not wired)
        self._recovery_repo = recovery_repo
        self._settings = settings
        self._recovery_run_id: UUID | None = None
        if recovery_repo is not None:
            self._recovery_engine = BaselineRecoveryEngine()
            self._recovery_context_builder = RecoveryContextBuilder(
                person_repo=person_repo,
                merchant_repo=merchant_repo,
                subscription_repo=subscription_repo,
                intent_repo=intent_repo,
                ledger_repo=ledger_repo,
                recovery_repo=recovery_repo,
            )
            self._recovery_scheduler = RecoveryScheduler(recovery_repo)
            response_rng = self._rng.spawn("customer_response")
            self._customer_response_sim = CustomerResponseSimulator(response_rng)
            retry_rng = self._rng.spawn("recovery_retry")
            self._recovery_executor = RecoveryActionExecutor(
                settings=settings,
                recovery_repo=recovery_repo,
                customer_response_sim=self._customer_response_sim,
                intent_repo=intent_repo,
                ledger_repo=ledger_repo,
                subscription_repo=subscription_repo,
                rng=retry_rng,
            )
        else:
            self._recovery_engine = None
            self._recovery_context_builder = None
            self._recovery_scheduler = None
            self._recovery_executor = None
            self._customer_response_sim = None

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

        # Create a recovery run for traceability — persist it to simulation_runs
        # so that the FK constraint on recovery_actions.run_id is satisfied.
        if self._recovery_repo is not None:
            recovery_run = RecoveryRunMetadata(
                run_id=uuid4(),
                seed=self._rng.seed or 42,
                engine_type=RecoveryEngineType.BASELINE,
                start_time=now(),
                max_retries=3,
                retry_interval_hours=12,
                config_snapshot={"version": getattr(self._config, "version", "1.0.0")},
            )
            recovery_tracker = RecoveryRunTracker(self._recovery_repo._db)
            persisted = recovery_tracker.create(
                seed=recovery_run.seed,
                engine_type=recovery_run.engine_type,
                max_retries=recovery_run.max_retries,
                retry_interval_hours=recovery_run.retry_interval_hours,
            )
            self._recovery_run_id = persisted.run_id

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

                # Phase: recovery processing (every hour)
                if self._recovery_repo is not None:
                    self._process_recovery(current_dt)

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
    # Recovery phase
    # ------------------------------------------------------------------

    def _process_recovery(self, current_dt: datetime) -> None:
        """Run one hour of the recovery system.

        Two steps:
        1. Execute due RETRY actions (scheduled_for <= current time).
           HTTP calls to LazerPay are parallelized via ThreadPoolExecutor.
        2. Detect new FAILED intents from this hour's settlement,
           run the engine, and schedule new recovery actions.
        """
        if self._recovery_repo is None:
            return

        # Step 1: execute due retry actions (parallel HTTP calls)
        due_actions = self._recovery_scheduler.find_due_actions(current_dt)
        if due_actions:
            with ThreadPoolExecutor(max_workers=min(12, len(due_actions))) as pool:
                futures = [
                    pool.submit(self._recovery_executor.execute, action, current_dt)
                    for action in due_actions
                ]
                for future in as_completed(futures):
                    future.result()

        # Step 2: detect new failures and create recovery actions
        self._detect_and_schedule_failures(current_dt)

    def _detect_and_schedule_failures(self, current_dt: datetime) -> None:
        """Scan for FAILED payment intents and schedule recovery actions.

        Optimized to avoid N+1 DB queries:
        - Pre-fetches prior recovery actions for ALL failed intents in one query
          (instead of find_by_intent_id per-intent).
        - Caches all people and merchants once per call (instead of querying
          per-intent inside build_for_intent).
        - Batch-fetches balances in a single query.
        - Skips intents with STOP/SUCCESS actions before building context.
        """
        if self._recovery_repo is None or self._recovery_engine is None:
            return

        # Find FAILED payment intents that still need recovery work.
        failed_intents = self._intent_repo.find_actionable_failed()
        if not failed_intents:
            return

        # Build a lookup index of failed ledger entries keyed by
        # (person_id, merchant_id, amount, payment_method) — avoids O(n*m)
        # scan on every intent.
        failed_entries = self._ledger_repo.find_failed(limit=200)
        ledger_index: dict[tuple, LedgerEntry] = {}
        for entry in failed_entries:
            meta = entry.metadata_json or {}
            key = (
                meta.get("person_id"),
                meta.get("merchant_id"),
                str(meta.get("amount", "")),
                meta.get("payment_method"),
            )
            # First match wins (earliest failure entry for this intent).
            if key not in ledger_index:
                ledger_index[key] = entry

        # --- BATCH pre-fetch: prior recovery actions for all intents at once ---
        intent_ids = [i.intent_id for i in failed_intents]
        prior_actions_map = self._recovery_repo.find_by_intent_ids(intent_ids)

        # --- BATCH pre-fetch: all people and merchants (cached for context build) ---
        all_people = self._person_repo.find_all()
        person_cache = {p.person_id: p for p in all_people}
        all_merchants = self._merchant_repo.find_all()
        merchant_cache = {m.merchant_id: m for m in all_merchants}

        # --- BATCH pre-fetch: balances for all people in a single query ---
        account_ids = [p.primary_account_id for p in all_people]
        balance_cache_raw = self._ledger_repo.balances_for_accounts(account_ids) if account_ids else {}
        balance_cache = {
            p.person_id: balance_cache_raw.get(p.primary_account_id, Decimal("0"))
            for p in all_people
        }

        for intent in failed_intents:
            # Check prior actions from the pre-fetched batch map (no per-intent DB query)
            existing = prior_actions_map.get(intent.intent_id, [])

            # Skip if a RETRY is already scheduled but not yet executed (avoid duplicates)
            if any(
                a.outcome == RecoveryOutcome.PENDING
                and a.action_type == RecoveryActionType.RETRY
                for a in existing
            ):
                continue
            # Skip if already stopped (customer declined or max retries)
            if any(a.action_type == RecoveryActionType.STOP for a in existing):
                continue
            # Skip if already recovered successfully — no further retries needed
            if any(a.outcome == RecoveryOutcome.SUCCESS for a in existing):
                continue

            # Look up the ledger entry from the pre-built index.
            lookup_key = (
                str(intent.person_id),
                str(intent.merchant_id),
                str(intent.amount),
                intent.payment_method,
            )
            entry = ledger_index.get(lookup_key)

            failure_code = None
            failure_reason = None
            failure_ts = current_dt
            attempt_id = None
            bank_state = "NORMAL"

            if entry is not None:
                meta = entry.metadata_json or {}
                failure_code = meta.get("failure_code")
                failure_reason = meta.get("failure_reason")
                failure_ts = entry.simulation_timestamp
                attempt_id = meta.get("attempt_id") or entry.related_attempt_id
                bank_state = meta.get("bank_state", "NORMAL")

            # Build context and decide — pass pre-fetched caches to avoid N+1 queries
            attempt_info = None
            if attempt_id:
                from .recovery.context import AttemptInfo
                attempt_info = AttemptInfo(
                    attempt_id=attempt_id,
                    intent_id=str(intent.intent_id),
                    attempt_number=1,
                    person_id=str(intent.person_id),
                    merchant_id=str(intent.merchant_id),
                    amount=intent.amount,
                    payment_method=intent.payment_method,
                    status="FAILED",
                    failure_code=failure_code,
                    failure_reason=failure_reason,
                    source_account_id=str(intent.person_id),
                    simulation_timestamp=failure_ts,
                    bank_state=bank_state,
                    bank_response_time_ms=None,
                    gateway_latency_ms=None,
                    failed_at=failure_ts,
                )

            context = self._recovery_context_builder.build_for_intent(
                intent=intent,
                current_simulation_time=current_dt,
                failure_code=failure_code,
                failure_reason=failure_reason,
                bank_state=bank_state,
                failure_timestamp=failure_ts,
                attempt_info=attempt_info,
                person_cache=person_cache,
                merchant_cache=merchant_cache,
                balance_cache=balance_cache,
                prior_actions_cache=prior_actions_map,
            )

            decision = self._recovery_engine.decide(context)
            self._recovery_scheduler.schedule(decision, context, self._recovery_run_id)

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

        Uses ThreadPoolExecutor with per-person deterministic RNG seeds so
        each person's spending decision is reproducible yet independent.
        """
        people = self._person_repo.find_all()
        if not people:
            return

        account_ids = [p.primary_account_id for p in people]
        balances = self._ledger_repo.balances_for_accounts(account_ids)

        # Pre-generate per-person RNG seeds (sequential, thread-safe)
        person_seeds = [
            self._rng.spawn(f"living_cost_{p.person_id}") for p in people
        ]

        # Parallel execution — each worker gets its own deterministic RNG
        with ThreadPoolExecutor(max_workers=min(12, len(people))) as pool:
            futures = [
                pool.submit(
                    self._spending_engine.daily_cost,
                    person, current_dt, day_type,
                    current_balance=balances.get(person.primary_account_id, Decimal("0")),
                    rng=seed,
                )
                for person, seed in zip(people, person_seeds)
            ]
            # Preserve original order for deterministic downstream processing
            entries = [f.result() for f in futures if f.result() is not None]

        if entries:
            self._ledger_repo.append(entries)

    def _bill_due_subscriptions(self, on_date: date, current_dt: datetime) -> None:
        """Create and settle PaymentIntents for due subscriptions.

        GST (18%) is applied to each subscription amount by the
        :class:`~engines.SubscriptionEngine`.  Intents are settled inline
        — if the person has sufficient balance the intent is ``SETTLED``,
        otherwise it ``FAILED``.  Subscriptions that fail consecutively
        are cancelled.

        Uses ThreadPoolExecutor with per-subscription RNG seeds so each
        intent's payment-method selection is reproducible yet independent.
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

        # Pre-generate per-subscription RNG seeds (sequential, thread-safe)
        sub_seeds = [
            self._rng.spawn(f"sub_bill_{s.subscription_id}") for s in subscriptions
        ]

        # Build intents in parallel (GST applied inside SubscriptionEngine.build_intent)
        with ThreadPoolExecutor(max_workers=min(12, len(subscriptions))) as pool:
            futures = [
                pool.submit(
                    self._subscription_engine.build_intent,
                    sub, current_dt, prefs.get(sub.person_id), rng=seed
                )
                for sub, seed in zip(subscriptions, sub_seeds)
            ]
            # Preserve original order for deterministic downstream processing
            intents = [f.result() for f in futures]

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

        Uses ThreadPoolExecutor with per-person deterministic RNG seeds so
        each person's purchase decision is reproducible yet independent.
        """
        if self._ecommerce_engine is None:
            return

        people = self._person_repo.find_all()
        if not people:
            return

        merchants = self._merchant_repo.find_all()
        products = self._product_repo.find_all_products()
        account_ids = [p.primary_account_id for p in people]
        balances = self._ledger_repo.balances_for_accounts(account_ids)

        is_salary_day = self._is_salary_day(current_dt.date())

        # Pre-generate per-person RNG seeds (sequential, thread-safe)
        person_seeds = [
            self._rng.spawn(f"ecom_{p.person_id}") for p in people
        ]
        # Pre-generate intent seeds too (avoids non-deterministic spawn ordering
        # from as_completed which would break reproducibility).
        intent_seed_map = {
            p.person_id: self._rng.spawn(f"ecom_intent_{p.person_id}") for p in people
        }

        intents = []
        # Parallel execution — each worker gets its own deterministic RNG
        with ThreadPoolExecutor(max_workers=min(12, len(people))) as pool:
            future_to_person = {}
            for person, seed in zip(people, person_seeds):
                balance = balances.get(person.primary_account_id, Decimal("0"))
                future = pool.submit(
                    self._ecommerce_engine.generate_purchase,
                    person,
                    merchants,
                    products,
                    current_dt,
                    balance,
                    is_salary_day,
                    rng=seed,
                )
                future_to_person[future] = person

            # Preserve original order for deterministic downstream processing
            for future, person in future_to_person.items():
                decision = future.result()
                if decision is not None:
                    intent = self._subscription_engine.build_intent_from_decision(
                        decision, current_dt, person.payment_preferences_json,
                        rng=intent_seed_map[person.person_id],
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

        Uses ThreadPoolExecutor with per-intent deterministic RNG seeds so
        each intent's failure draw is reproducible yet independent.
        """
        from dataclasses import replace

        if not intents:
            return

        # Only fetch people relevant to these intents (not ALL people).
        person_ids = list({intent.person_id for intent in intents})
        people = self._person_repo.find_by_ids(person_ids)
        people_dict = {p.person_id: p for p in people}

        # Batch-fetch balances in a single query (instead of one per person).
        account_ids = [p.primary_account_id for p in people]
        balances = self._ledger_repo.balances_for_accounts(account_ids) if account_ids else {}

        # Bank state feeds P(failure) (degraded/outage banks fail more).
        bank = self._bank_repo.find_by_name("RupeeBank")
        bank_state = bank.current_state if bank else "NORMAL"

        # Pre-generate per-intent RNG seeds (sequential, thread-safe)
        intent_seeds = [
            self._rng.spawn(f"intent_{i.intent_id}") for i in intents
        ]

        # Parallelize the per-intent failure decision
        results: list[tuple[PaymentIntent, str, str | None]] = []

        def _decide(intent: PaymentIntent, intent_rng: SimulationRNG) -> tuple[PaymentIntent, str, str | None]:
            person = people_dict.get(intent.person_id)
            balance = balances.get(person.primary_account_id, Decimal("0")) if person else Decimal("0")
            amount_f = float(intent.amount)
            balance_f = float(balance)

            if balance < intent.amount:
                # Real insolvency — deterministic, dominant CUSTOMER_STATE bucket.
                return intent, INTENT_FAILED, "INSUFFICIENT_FUNDS"
            elif intent_rng.random() < failure_probability(
                intent.payment_method,
                bank_state=bank_state,
                amount=amount_f,
                balance=balance_f,
                hour=current_dt.hour,
            ):
                status = INTENT_FAILED
                failure_code, _cat = classify_failure(
                    intent_rng, method=intent.payment_method, bank_state=bank_state
                )
                return intent, status, failure_code
            else:
                return intent, INTENT_SETTLED, None

        with ThreadPoolExecutor(max_workers=min(12, len(intents))) as pool:
            futures = [
                pool.submit(_decide, intent, seed)
                for intent, seed in zip(intents, intent_seeds)
            ]
            # Preserve original order for deterministic downstream processing
            results = [f.result() for f in futures]

        # Build ledger entries and update intents (sequential DB writes)
        ledger_entries = []
        updated_intents = []
        for intent, status, failure_code in results:
            person = people_dict.get(intent.person_id)
            debit_account = str(person.primary_account_id) if person else None

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
                # Note: no attempt_id is set — inline-failed payments have no
                # LazerPay attempt_id.  The recovery executor handles these
                # via inline settlement fallback when related_attempt_id is None.
            # A FAILED payment never debits the person's account — the funds are
            # simply not moved.  Only a SETTLED payment debits.  This keeps
            # balances from drifting below zero on failed transactions.
            debit_from = debit_account if status == INTENT_SETTLED else None
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
            self._intent_repo.save_many(updated_intents)
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
