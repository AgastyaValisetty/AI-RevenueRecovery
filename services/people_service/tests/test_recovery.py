"""Tests for the recovery subsystem.

Covers:
  - BaselineRecoveryEngine decision logic (RETRY / STOP / max retries / decline)
  - RecoveryContextBuilder assembly from repositories
  - RecoveryScheduler persistence
  - RecoveryActionRepository CRUD
  - CustomerResponseSimulator distributions
  - RecoveryMetrics aggregation
  - RecoveryRunTracker lifecycle
  - End-to-end orchestrator integration with recovery
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.container import build_orchestrator
from app.database import Database
from app.domain import (
    INTENT_FAILED,
    INTENT_SETTLED,
    PAYMENT_FAILED,
    PAYMENT_SETTLED,
    PaymentIntent,
    LedgerEntry,
)
from app.recovery import (
    AttemptInfo,
    BalanceInfo,
    BaselineRecoveryEngine,
    CustomerResponse,
    CustomerResponseSimulator,
    MerchantInfo,
    PersonInfo,
    PriorRecovery,
    RecoveryAction,
    RecoveryActionExecutor,
    RecoveryActionRepository,
    RecoveryContext,
    RecoveryContextBuilder,
    RecoveryDecision,
    RecoveryDecisionEngine,
    RecoveryEngineType,
    RecoveryMetrics,
    RecoveryMetricsCollector,
    RecoveryOutcome,
    RecoveryRunMetadata,
    RecoveryRunTracker,
    RecoveryScheduler,
    SubscriptionInfo,
    RecoveryActionType,
)
from app.recovery.domain import MAX_RETRIES, RETRY_INTERVAL_HOURS
from app.repositories import (
    BankRepository,
    LedgerRepository,
    MerchantRepository,
    PaymentIntentRepository,
    PersonRepository,
    ProductRepository,
    SubscriptionRepository,
)
from app.config import Settings
from app.rng import SimulationRNG

SIM_TS = datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_person_info(pid: str = "person-1") -> PersonInfo:
    return PersonInfo(
        person_id=pid,
        name="Test User",
        age=30,
        salary=Decimal("50000"),
        salary_deposit_day=1,
        salary_deposit_hour=9,
        spending_profile_category="young_professional",
        income_bracket="middle",
        age_group="25-34",
        employment_type="salaried",
        primary_account_id="account-1",
    )


TestIntentId = "12345678-1234-5678-1234-567812345678"


def _make_context(
    retry_count: int = 0,
    customer_declined: bool = False,
    failure_code: str = "ISSUER_DECLINE",
) -> RecoveryContext:
    return RecoveryContext(
        attempt=None,
        intent_id=TestIntentId,
        intent_amount=Decimal("1000"),
        intent_payment_method="UPI",
        intent_status="FAILED",
        person=_make_person_info(),
        balance=BalanceInfo(account_id="account-1", current_balance=Decimal("500")),
        merchant=MerchantInfo(
            merchant_id="merchant-1", name="Test Merchant", merchant_type="ECOMMERCE"
        ),
        subscription=None,
        failure_code=failure_code,
        failure_reason="Issuer declined",
        failure_timestamp=SIM_TS - timedelta(hours=1),
        bank_state="NORMAL",
        prior_recoveries=[],
        retry_count=retry_count,
        customer_declined=customer_declined,
        current_simulation_time=SIM_TS,
    )


def _make_intent(status: str = INTENT_FAILED) -> PaymentIntent:
    return PaymentIntent(
        intent_id=uuid4(),
        person_id=uuid4(),
        merchant_id=uuid4(),
        product_id=uuid4(),
        amount=Decimal("1000.00"),
        payment_method="UPI",
        status=status,
        related_subscription_id=None,
        created_at=SIM_TS,
        expires_at=SIM_TS + timedelta(hours=1),
    )


# --------------------------------------------------------------------------- #
# BaselineRecoveryEngine
# --------------------------------------------------------------------------- #

class TestBaselineRecoveryEngine:
    """Verify the decision logic of the baseline engine."""

    def test_first_failure_schedules_retry_1(self):
        engine = BaselineRecoveryEngine()
        ctx = _make_context(retry_count=0)
        decision = engine.decide(ctx)

        assert decision.action == RecoveryActionType.RETRY
        assert decision.retry_number == 1
        assert decision.scheduled_for == SIM_TS + timedelta(hours=RETRY_INTERVAL_HOURS)
        assert decision.reason == "retry_scheduled"

    def test_second_failure_schedules_retry_2(self):
        engine = BaselineRecoveryEngine()
        ctx = _make_context(retry_count=1)
        decision = engine.decide(ctx)

        assert decision.action == RecoveryActionType.RETRY
        assert decision.retry_number == 2

    def test_third_failure_schedules_retry_3(self):
        engine = BaselineRecoveryEngine()
        ctx = _make_context(retry_count=2)
        decision = engine.decide(ctx)

        assert decision.action == RecoveryActionType.RETRY
        assert decision.retry_number == 3

    def test_max_retries_exhausted_stops(self):
        engine = BaselineRecoveryEngine()
        ctx = _make_context(retry_count=3)
        decision = engine.decide(ctx)

        assert decision.action == RecoveryActionType.STOP
        assert decision.reason == "max_retries_exhausted"

    def test_customer_declined_stops(self):
        engine = BaselineRecoveryEngine()
        ctx = _make_context(customer_declined=True, retry_count=0)
        decision = engine.decide(ctx)

        assert decision.action == RecoveryActionType.STOP
        assert decision.reason == "customer_declined"

    def test_retry_interval_is_12_hours(self):
        engine = BaselineRecoveryEngine()
        assert engine.retry_interval_hours == 12

    def test_max_retries_is_3(self):
        engine = BaselineRecoveryEngine()
        assert engine.max_retries == 3


# --------------------------------------------------------------------------- #
# RecoveryContextBuilder
# --------------------------------------------------------------------------- #

class TestRecoveryContextBuilder:
    """Verify context assembly from repositories."""

    @pytest.fixture
    def repos(self, db):
        return {
            "person_repo": PersonRepository(db),
            "merchant_repo": MerchantRepository(db),
            "subscription_repo": SubscriptionRepository(db),
            "intent_repo": PaymentIntentRepository(db),
            "ledger_repo": LedgerRepository(db),
            "recovery_repo": RecoveryActionRepository(db),
        }

    def test_build_context_for_failed_intent(self, repos):
        intent = _make_intent()
        repos["intent_repo"].add([intent])

        builder = RecoveryContextBuilder(
            person_repo=repos["person_repo"],
            merchant_repo=repos["merchant_repo"],
            subscription_repo=repos["subscription_repo"],
            intent_repo=repos["intent_repo"],
            ledger_repo=repos["ledger_repo"],
            recovery_repo=repos["recovery_repo"],
        )

        ctx = builder.build_for_intent(
            intent=intent,
            current_simulation_time=SIM_TS,
            failure_code="ISSUER_DECLINE",
            failure_reason="Issuer declined",
            bank_state="NORMAL",
            failure_timestamp=SIM_TS - timedelta(hours=5),
        )

        assert ctx.intent_id == str(intent.intent_id)
        assert ctx.intent_amount == intent.amount
        assert ctx.intent_payment_method == intent.payment_method
        assert ctx.failure_code == "ISSUER_DECLINE"
        assert ctx.retry_count == 0
        assert ctx.customer_declined is False

    def test_context_tracks_prior_recoveries(self, repos):
        intent = _make_intent()
        repos["intent_repo"].add([intent])

        # Create a prior recovery action
        from uuid import uuid4 as _uuid
        prior_action = RecoveryAction(
            action_id=_uuid(),
            run_id=None,
            related_attempt_id="ATT_prior",
            payment_intent_id=intent.intent_id,
            retry_number=1,
            action_type=RecoveryActionType.RETRY,
            reason="retry_scheduled",
            schedule_reason="retry_scheduled",
            scheduled_for=SIM_TS - timedelta(hours=12),
            executed_at=SIM_TS - timedelta(hours=11),
            outcome=RecoveryOutcome.FAILED,
            failure_code="ISSUER_DECLINE",
            failure_reason="Issuer declined",
            amount=intent.amount,
            payment_method=intent.payment_method,
            metadata_json={"intent_id": str(intent.intent_id)},
            created_at=SIM_TS - timedelta(hours=12),
        )
        repos["recovery_repo"].add(prior_action)

        builder = RecoveryContextBuilder(
            person_repo=repos["person_repo"],
            merchant_repo=repos["merchant_repo"],
            subscription_repo=repos["subscription_repo"],
            intent_repo=repos["intent_repo"],
            ledger_repo=repos["ledger_repo"],
            recovery_repo=repos["recovery_repo"],
        )

        ctx = builder.build_for_intent(
            intent=intent,
            current_simulation_time=SIM_TS,
        )

        assert ctx.retry_count == 1
        assert len(ctx.prior_recoveries) == 1
        assert ctx.prior_recoveries[0].retry_number == 1


# --------------------------------------------------------------------------- #
# RecoveryScheduler
# --------------------------------------------------------------------------- #

class TestRecoveryScheduler:
    """Verify scheduler creates and persists actions correctly."""

    @pytest.fixture
    def scheduler(self, db):
        repo = RecoveryActionRepository(db)
        return RecoveryScheduler(repo), repo

    def test_schedule_retry_creates_action(self, scheduler):
        sched, repo = scheduler
        ctx = _make_context(retry_count=0)
        decision = RecoveryDecision(
            action=RecoveryActionType.RETRY,
            scheduled_for=SIM_TS + timedelta(hours=12),
            reason="retry_scheduled",
            retry_number=1,
        )

        action = sched.schedule(decision, ctx, run_id=None)

        assert action.action_type == RecoveryActionType.RETRY
        assert action.retry_number == 1
        assert action.scheduled_for == SIM_TS + timedelta(hours=12)
        assert action.outcome == RecoveryOutcome.PENDING
        assert action.failure_code == "ISSUER_DECLINE"
        assert action.payment_intent_id == UUID(ctx.intent_id)

        # Verify it was persisted
        stored = repo.find(action.action_id)
        assert stored is not None
        assert stored.action_type == RecoveryActionType.RETRY

    def test_schedule_stop_creates_action(self, scheduler):
        sched, repo = scheduler
        ctx = _make_context(customer_declined=True)
        decision = RecoveryDecision(
            action=RecoveryActionType.STOP,
            reason="customer_declined",
        )

        action = sched.schedule(decision, ctx, run_id=None)

        assert action.action_type == RecoveryActionType.STOP
        assert action.customer_declined is True
        assert action.outcome == RecoveryOutcome.PENDING

    def test_find_due_actions(self, scheduler):
        sched, repo = scheduler
        ctx = _make_context()

        # Schedule two actions: one due now, one future
        now = SIM_TS
        past_action = sched.schedule(
            RecoveryDecision(
                action=RecoveryActionType.RETRY,
                scheduled_for=now - timedelta(hours=1),
                reason="retry_scheduled",
                retry_number=1,
            ),
            ctx,
        )
        future_action = sched.schedule(
            RecoveryDecision(
                action=RecoveryActionType.RETRY,
                scheduled_for=now + timedelta(hours=20),
                reason="retry_scheduled",
                retry_number=2,
            ),
            ctx,
        )

        due = sched.find_due_actions(now)
        due_ids = [a.action_id for a in due]
        assert past_action.action_id in due_ids
        assert future_action.action_id not in due_ids


# --------------------------------------------------------------------------- #
# RecoveryActionRepository
# --------------------------------------------------------------------------- #

class TestRecoveryActionRepository:

    @pytest.fixture
    def repo(self, db):
        return RecoveryActionRepository(db)

    def test_add_and_find(self, repo):
        action = RecoveryAction(
            action_id=uuid4(),
            run_id=None,
            related_attempt_id="ATT_123",
            payment_intent_id=uuid4(),
            retry_number=1,
            action_type=RecoveryActionType.RETRY,
            reason="retry_scheduled",
            schedule_reason="retry_scheduled",
            scheduled_for=SIM_TS + timedelta(hours=12),
            executed_at=None,
            outcome=RecoveryOutcome.PENDING,
            failure_code="ISSUER_DECLINE",
            failure_reason="Issuer declined",
            amount=Decimal("1000.00"),
            payment_method="UPI",
            metadata_json={"intent_id": "test"},
            created_at=SIM_TS,
        )
        repo.add(action)

        found = repo.find(action.action_id)
        assert found is not None
        assert found.action_type == RecoveryActionType.RETRY
        assert found.retry_number == 1
        assert found.failure_code == "ISSUER_DECLINE"

    def test_find_by_intent_id(self, repo):
        intent_id = uuid4()
        for i in range(3):
            repo.add(RecoveryAction(
                action_id=uuid4(),
                run_id=None,
                related_attempt_id=f"ATT_{i}",
                payment_intent_id=intent_id,
                retry_number=i + 1,
                action_type=RecoveryActionType.RETRY,
                reason="retry_scheduled",
                schedule_reason="retry_scheduled",
                scheduled_for=SIM_TS + timedelta(hours=12 * (i + 1)),
                executed_at=None,
                outcome=RecoveryOutcome.PENDING,
                amount=Decimal("1000.00"),
                payment_method="UPI",
                metadata_json={},
                created_at=SIM_TS,
            ))

        actions = repo.find_by_intent_id(intent_id)
        assert len(actions) == 3
        assert actions[0].retry_number == 1
        assert actions[2].retry_number == 3

    def test_max_retry_number(self, repo):
        intent_id = uuid4()
        for i in range(3):
            repo.add(RecoveryAction(
                action_id=uuid4(),
                run_id=None,
                related_attempt_id=f"ATT_{i}",
                payment_intent_id=intent_id,
                retry_number=i + 1,
                action_type=RecoveryActionType.RETRY,
                reason="retry_scheduled",
                schedule_reason="retry_scheduled",
                scheduled_for=SIM_TS + timedelta(hours=12 * (i + 1)),
                executed_at=None,
                outcome=RecoveryOutcome.PENDING,
                amount=Decimal("1000.00"),
                payment_method="UPI",
                metadata_json={},
                created_at=SIM_TS,
            ))

        assert repo.max_retry_number(intent_id) == 3

    def test_has_customer_declined(self, repo):
        intent_id = uuid4()
        repo.add(RecoveryAction(
            action_id=uuid4(),
            run_id=None,
            related_attempt_id=None,
            payment_intent_id=intent_id,
            retry_number=None,
            action_type=RecoveryActionType.STOP,
            reason="customer_declined",
            schedule_reason=None,
            scheduled_for=SIM_TS,
            executed_at=None,
            outcome=RecoveryOutcome.PENDING,
            amount=Decimal("1000.00"),
            payment_method="UPI",
            customer_declined=True,
            metadata_json={},
            created_at=SIM_TS,
        ))

        assert repo.has_customer_declined(intent_id) is True

    def test_has_customer_declined_false(self, repo):
        intent_id = uuid4()
        # No STOP with customer_declined=True
        assert repo.has_customer_declined(intent_id) is False

    def test_save_updates_outcome(self, repo):
        action = RecoveryAction(
            action_id=uuid4(),
            run_id=None,
            related_attempt_id="ATT_123",
            payment_intent_id=uuid4(),
            retry_number=1,
            action_type=RecoveryActionType.RETRY,
            reason="retry_scheduled",
            schedule_reason="retry_scheduled",
            scheduled_for=SIM_TS,
            executed_at=None,
            outcome=RecoveryOutcome.PENDING,
            amount=Decimal("1000.00"),
            payment_method="UPI",
            metadata_json={},
            created_at=SIM_TS,
        )
        repo.add(action)

        from dataclasses import replace
        updated = replace(
            action,
            outcome=RecoveryOutcome.SUCCESS,
            executed_at=SIM_TS + timedelta(hours=12),
            retry_attempt_id="ATT_new",
            metadata_json={"lazerpay_status": "SETTLED"},
        )
        repo.save(updated)

        found = repo.find(action.action_id)
        assert found.outcome == RecoveryOutcome.SUCCESS
        # SQLite may strip tzinfo — compare naive datetimes
        expected = (SIM_TS + timedelta(hours=12)).replace(tzinfo=None)
        actual = found.executed_at.replace(tzinfo=None) if found.executed_at else None
        assert actual == expected
        assert found.retry_attempt_id == "ATT_new"

    def test_count_by_outcome(self, repo):
        for outcome in [RecoveryOutcome.SUCCESS, RecoveryOutcome.SUCCESS, RecoveryOutcome.FAILED]:
            repo.add(RecoveryAction(
                action_id=uuid4(),
                run_id=None,
                related_attempt_id=None,
                payment_intent_id=uuid4(),
                retry_number=None,
                action_type=RecoveryActionType.RETRY,
                reason="retry",
                schedule_reason=None,
                scheduled_for=SIM_TS,
                executed_at=SIM_TS,
                outcome=outcome,
                amount=Decimal("1000.00"),
                payment_method="UPI",
                metadata_json={},
                created_at=SIM_TS,
            ))

        counts = repo.count_by_outcome()
        assert counts.get(RecoveryOutcome.SUCCESS.value, 0) == 2
        assert counts.get(RecoveryOutcome.FAILED.value, 0) == 1


# --------------------------------------------------------------------------- #
# CustomerResponseSimulator
# --------------------------------------------------------------------------- #

class TestCustomerResponseSimulator:

    def test_ignore_is_most_common(self):
        rng = SimulationRNG(42)
        sim = CustomerResponseSimulator(rng)
        responses = [sim.simulate() for _ in range(1000)]

        counts = {}
        for r in responses:
            counts[r] = counts.get(r, 0) + 1

        # Ignore should dominate
        assert counts.get(CustomerResponse.IGNORE, 0) > 900
        # Very few declines
        assert counts.get(CustomerResponse.DECLINE, 0) < 30

    def test_custom_rates(self):
        rng = SimulationRNG(42)
        sim = CustomerResponseSimulator(
            rng,
            ignore_rate=0.5,
            respond_rate=0.45,
            decline_rate=0.05,
        )
        assert abs(sim.ignore_rate - 0.5) < 0.01
        assert abs(sim.respond_rate - 0.45) < 0.01
        assert abs(sim.decline_rate - 0.05) < 0.01

    def test_zero_rates_fallback(self):
        rng = SimulationRNG(42)
        sim = CustomerResponseSimulator(
            rng, ignore_rate=0, respond_rate=0, decline_rate=0
        )
        # Should use defaults
        assert sim.ignore_rate == 0.985

    def test_deterministic(self):
        rng1 = SimulationRNG(123)
        rng2 = SimulationRNG(123)
        sim1 = CustomerResponseSimulator(rng1)
        sim2 = CustomerResponseSimulator(rng2)

        results1 = [sim1.simulate().value for _ in range(100)]
        results2 = [sim2.simulate().value for _ in range(100)]
        assert results1 == results2


# --------------------------------------------------------------------------- #
# RecoveryMetrics
# --------------------------------------------------------------------------- #

class TestRecoveryMetrics:

    @pytest.fixture
    def collector_and_repo(self, db):
        from app.recovery.repository import RecoveryActionRepository
        repo = RecoveryActionRepository(db)
        collector = RecoveryMetricsCollector(db)
        return collector, repo

    def test_metrics_aggregation(self, collector_and_repo):
        collector, repo = collector_and_repo
        intent_id = uuid4()

        # 2 successes, 1 failure
        repo.add_many([
            RecoveryAction(
                action_id=uuid4(), run_id=None, related_attempt_id="ATT1",
                payment_intent_id=intent_id, retry_number=1,
                action_type=RecoveryActionType.RETRY,
                reason="retry_scheduled", schedule_reason="retry_scheduled",
                scheduled_for=SIM_TS + timedelta(hours=12),
                executed_at=SIM_TS + timedelta(hours=12),
                outcome=RecoveryOutcome.SUCCESS,
                cost=Decimal("10"), expected_recovery=None,
                failure_code="ISSUER_DECLINE", failure_reason="decline",
                amount=Decimal("1000.00"), payment_method="UPI",
                retry_attempt_id="ATT_new1", customer_declined=False,
                metadata_json={
                    "intent_id": str(intent_id),
                    "failure_timestamp": (SIM_TS - timedelta(hours=1)).isoformat(),
                },
                created_at=SIM_TS,
            ),
            RecoveryAction(
                action_id=uuid4(), run_id=None, related_attempt_id="ATT2",
                payment_intent_id=intent_id, retry_number=2,
                action_type=RecoveryActionType.RETRY,
                reason="retry_scheduled", schedule_reason="retry_scheduled",
                scheduled_for=SIM_TS + timedelta(hours=24),
                executed_at=SIM_TS + timedelta(hours=24),
                outcome=RecoveryOutcome.SUCCESS,
                cost=Decimal("10"), expected_recovery=None,
                failure_code="ISSUER_DECLINE", failure_reason="decline",
                amount=Decimal("1000.00"), payment_method="UPI",
                retry_attempt_id="ATT_new2", customer_declined=False,
                metadata_json={
                    "intent_id": str(intent_id),
                    "failure_timestamp": (SIM_TS - timedelta(hours=1)).isoformat(),
                },
                created_at=SIM_TS,
            ),
            RecoveryAction(
                action_id=uuid4(), run_id=None, related_attempt_id="ATT3",
                payment_intent_id=intent_id, retry_number=3,
                action_type=RecoveryActionType.RETRY,
                reason="retry_scheduled", schedule_reason="retry_scheduled",
                scheduled_for=SIM_TS + timedelta(hours=36),
                executed_at=SIM_TS + timedelta(hours=36),
                outcome=RecoveryOutcome.FAILED,
                cost=Decimal("10"), expected_recovery=None,
                failure_code="ISSUER_DECLINE", failure_reason="decline",
                amount=Decimal("1000.00"), payment_method="UPI",
                retry_attempt_id="ATT_new3", customer_declined=False,
                metadata_json={
                    "intent_id": str(intent_id),
                    "failure_timestamp": (SIM_TS - timedelta(hours=1)).isoformat(),
                },
                created_at=SIM_TS,
            ),
        ])

        metrics = collector.collect()
        assert metrics.total_recovery_actions == 3
        assert metrics.retry_actions == 3
        assert metrics.successful_recoveries == 2
        assert metrics.failed_recoveries == 1
        assert metrics.recovery_rate == pytest.approx(2 / 3, abs=0.01)
        assert metrics.total_recovered_gmv == Decimal("2000.00")
        assert metrics.total_recovery_cost == Decimal("30")
        assert metrics.by_payment_method.get("UPI", 0) == 3
        assert metrics.by_failure_code.get("ISSUER_DECLINE", 0) == 3


# --------------------------------------------------------------------------- #
# RecoveryRunTracker
# --------------------------------------------------------------------------- #

class TestRecoveryRunTracker:

    def test_create_and_find(self, db):
        tracker = RecoveryRunTracker(db)

        meta = tracker.create(
            seed=42,
            engine_type=RecoveryEngineType.BASELINE,
            max_retries=3,
            retry_interval_hours=12,
        )

        found = tracker.find(meta.run_id)
        assert found is not None
        assert found.seed == 42
        assert found.engine_type == RecoveryEngineType.BASELINE
        assert found.max_retries == 3


# --------------------------------------------------------------------------- #
# End-to-end: Orchestrator integration with recovery
# --------------------------------------------------------------------------- #

class TestRecoveryEndToEnd:
    """Verify that the recovery system works within the orchestrator loop."""

    @pytest.fixture
    def settings(self):
        return Settings(
            db_host="localhost",
            db_port=5433,
            db_user="test",
            db_password="test",
            db_name="test",
            lazerpay_url="http://lazerpay_service:8001",
        )

    def test_recovery_repo_wired_in_orchestrator(self, db, settings, config):
        """The orchestrator should have recovery components when enable_recovery=True."""
        orch = build_orchestrator(
            db, seed=42, config=config, settings=settings, enable_recovery=True
        )
        assert orch._recovery_repo is not None
        assert orch._recovery_engine is not None
        assert orch._recovery_scheduler is not None
        assert orch._recovery_executor is not None
        assert orch._recovery_context_builder is not None

    def test_no_recovery_when_disabled(self, db, settings, config):
        """When enable_recovery=False, no recovery components are wired."""
        orch = build_orchestrator(
            db, seed=42, config=config, settings=settings, enable_recovery=False
        )
        assert orch._recovery_repo is None
        assert orch._recovery_engine is None

    def test_failed_intent_triggers_recovery_action(self, db, settings, config):
        """A FAILED payment intent should produce a RECOVERY RETRY action."""
        from uuid import uuid4 as _uuid

        # Seed a failed payment intent + ledger entry
        intent = PaymentIntent(
            intent_id=_uuid(),
            person_id=_uuid(),
            merchant_id=_uuid(),
            product_id=_uuid(),
            amount=Decimal("1000.00"),
            payment_method="UPI",
            status=INTENT_FAILED,
            related_subscription_id=None,
            created_at=SIM_TS,
            expires_at=SIM_TS + timedelta(hours=1),
        )
        PaymentIntentRepository(db).add([intent])

        LedgerRepository(db).append([
            LedgerEntry(
                entry_id=_uuid(),
                event_type=PAYMENT_FAILED,
                from_account_id=None,
                to_account_id=None,
                amount=Decimal("1000.00"),
                simulation_timestamp=SIM_TS,
                related_attempt_id=None,
                metadata_json={
                    "payment_method": "UPI",
                    "amount": "1000.00",
                    "person_id": str(intent.person_id),
                    "merchant_id": str(intent.merchant_id),
                    "settled_inline": True,
                    "failure_code": "ISSUER_DECLINE",
                    "failure_reason": "Issuer declined",
                    "failure_category": "BANK_DECLINE",
                },
            )
        ])

        orch = build_orchestrator(
            db, seed=42, config=config, settings=settings, enable_recovery=True
        )
        orch.initialize(people_count=10, seed=42)
        orch.run_hours(1)  # One hour to trigger recovery detection

        # The clock syncs to SIM_TS (ledger timestamp), then advances 1 hour,
        # so the recovery is detected at SIM_TS + 1h and scheduled 12h later.
        expected_scheduled = (SIM_TS + timedelta(hours=13)).replace(tzinfo=None)

        # Should have a recovery action for the failed intent
        recovery_repo = RecoveryActionRepository(db)
        actions = recovery_repo.find_by_intent_id(intent.intent_id)
        assert len(actions) > 0
        assert actions[0].action_type == RecoveryActionType.RETRY
        assert actions[0].retry_number == 1
        # SQLite strips timezone info on datetime round-trip
        actual = actions[0].scheduled_for
        actual_naive = actual.replace(tzinfo=None) if actual else None
        assert actual_naive == expected_scheduled

    def test_max_3_retries_enforced(self, db, settings, config):
        """After 3 retries, the engine should STOP, not schedule more."""
        from uuid import uuid4 as _uuid

        intent_id = _uuid()
        repo = RecoveryActionRepository(db)

        # Pre-seed 3 failed retry actions
        for i in range(1, 4):
            action = RecoveryAction(
                action_id=_uuid(),
                run_id=None,
                related_attempt_id=f"ATT_{i}",
                payment_intent_id=intent_id,
                retry_number=i,
                action_type=RecoveryActionType.RETRY,
                reason="retry_scheduled",
                schedule_reason="retry_scheduled",
                scheduled_for=SIM_TS + timedelta(hours=12 * i),
                executed_at=SIM_TS + timedelta(hours=12 * i),
                outcome=RecoveryOutcome.FAILED,
                cost=Decimal("10"),
                expected_recovery=None,
                failure_code="ISSUER_DECLINE",
                failure_reason="Issuer declined",
                amount=Decimal("1000.00"),
                payment_method="UPI",
                retry_attempt_id=f"NEW_ATT_{i}",
                customer_declined=False,
                metadata_json={
                    "intent_id": str(intent_id),
                    "failure_timestamp": (SIM_TS - timedelta(hours=1)).isoformat(),
                },
                created_at=SIM_TS,
            )
            repo.add(action)

        # Seed the failed intent
        intent = PaymentIntent(
            intent_id=intent_id,
            person_id=_uuid(),
            merchant_id=_uuid(),
            product_id=_uuid(),
            amount=Decimal("1000.00"),
            payment_method="UPI",
            status=INTENT_FAILED,
            related_subscription_id=None,
            created_at=SIM_TS,
            expires_at=SIM_TS + timedelta(hours=1),
        )
        PaymentIntentRepository(db).add([intent])

        orch = build_orchestrator(
            db, seed=42, config=config, settings=settings, enable_recovery=True
        )
        orch.initialize(people_count=10, seed=42)
        orch.run_hours(1)

        # The engine should see retry_count=3 and STOP
        actions = repo.find_by_intent_id(intent_id)
        retry_actions = [a for a in actions if a.action_type == RecoveryActionType.RETRY]
        stop_actions = [a for a in actions if a.action_type == RecoveryActionType.STOP]
        assert len(stop_actions) == 1
        assert stop_actions[0].reason == "max_retries_exhausted"

    def test_customer_decline_stops_recovery(self, db, settings, config):
        """A prior customer_decline STOP should prevent further retries."""
        from uuid import uuid4 as _uuid

        intent_id = _uuid()
        repo = RecoveryActionRepository(db)

        # Seed a STOP with customer_declined=True
        repo.add(RecoveryAction(
            action_id=_uuid(),
            run_id=None,
            related_attempt_id=None,
            payment_intent_id=intent_id,
            retry_number=None,
            action_type=RecoveryActionType.STOP,
            reason="customer_declined",
            schedule_reason=None,
            scheduled_for=SIM_TS,
            executed_at=SIM_TS,
            outcome=RecoveryOutcome.STOPPED,
            cost=None,
            expected_recovery=None,
            failure_code="ISSUER_DECLINE",
            failure_reason="Issuer declined",
            amount=Decimal("1000.00"),
            payment_method="UPI",
            retry_attempt_id=None,
            customer_declined=True,
            metadata_json={},
            created_at=SIM_TS,
        ))

        # Seed the failed intent
        intent = PaymentIntent(
            intent_id=intent_id,
            person_id=_uuid(),
            merchant_id=_uuid(),
            product_id=_uuid(),
            amount=Decimal("1000.00"),
            payment_method="UPI",
            status=INTENT_FAILED,
            related_subscription_id=None,
            created_at=SIM_TS,
            expires_at=SIM_TS + timedelta(hours=1),
        )
        PaymentIntentRepository(db).add([intent])

        orch = build_orchestrator(
            db, seed=42, config=config, settings=settings, enable_recovery=True
        )
        orch.initialize(people_count=10, seed=42)
        orch.run_hours(1)

        # Should NOT create a new retry action
        actions = repo.find_by_intent_id(intent_id)
        retry_actions = [a for a in actions if a.action_type == RecoveryActionType.RETRY]
        assert len(retry_actions) == 0
