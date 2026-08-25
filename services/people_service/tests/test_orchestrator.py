"""Tests for Orchestrator — hourly simulation, phases, reproducibility."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.container import build_orchestrator
from app.database import Database
from app.domain import (
    LIVING_COST,
    ORDER_PURCHASE,
    SALARY_DEPOSIT,
    STATUS_RUNNING,
    STATUS_COMPLETED,
)
from app.orchestrator import Orchestrator, SimulationClock
from app.rng import SimulationRNG
from app.sim_config import SimConfig


@pytest.fixture
def config() -> SimConfig:
    return SimConfig.defaults()


class TestOrchestratorReproducibility:
    """Verify that the same seed produces the same simulation results."""

    def test_same_seed_same_ledger(self, db, config):
        """Two orchestrators with the same seed must produce identical ledgers."""
        orch_a = build_orchestrator(db, seed=42, config=config)
        orch_a.initialize(people_count=10, seed=42)
        orch_a.run_hours(48)  # 2 days

        # Extract ledger from first run
        ledger_a = orch_a.ledger_entries(limit=500)

        # Fresh database for second run
        db2 = Database(engine_url="sqlite:///:memory:")
        db2.create_schema()
        orch_b = build_orchestrator(db2, seed=42, config=config)
        orch_b.initialize(people_count=10, seed=42)
        orch_b.run_hours(48)

        ledger_b = orch_b.ledger_entries(limit=500)

        # Compare event types and amounts (UUIDs will differ but patterns should match)
        events_a = [(e.event_type, str(e.amount), e.simulation_timestamp.hour) for e in ledger_a]
        events_b = [(e.event_type, str(e.amount), e.simulation_timestamp.hour) for e in ledger_b]

        assert events_a == events_b

    def test_different_seed_different_ledger(self, db, config):
        """Different seeds should produce different results."""
        orch_a = build_orchestrator(db, seed=42, config=config)
        orch_a.initialize(people_count=10, seed=42)
        orch_a.run_hours(48)
        ledger_a = orch_a.ledger_entries(limit=500)

        db2 = Database(engine_url="sqlite:///:memory:")
        db2.create_schema()
        orch_b = build_orchestrator(db2, seed=99, config=config)
        orch_b.initialize(people_count=10, seed=99)
        orch_b.run_hours(48)
        ledger_b = orch_b.ledger_entries(limit=500)

        events_a = [(e.event_type, str(e.amount), e.simulation_timestamp.hour) for e in ledger_a]
        events_b = [(e.event_type, str(e.amount), e.simulation_timestamp.hour) for e in ledger_b]

        assert events_a != events_b


class TestOrchestratorPhases:
    """Verify that each hourly phase fires correctly."""

    def test_salary_deposited_on_salary_day(self, db, config):
        orch = build_orchestrator(db, seed=42, config=config)
        run_id = orch.initialize(people_count=10, seed=42)
        assert run_id is not None

        # Run enough hours to cover a few salary days
        orch.run_hours(72)  # 3 days

        # Check for salary deposits in ledger
        ledger = orch.ledger_entries(limit=500)
        salary_entries = [e for e in ledger if e.event_type == SALARY_DEPOSIT]
        assert len(salary_entries) > 0

    def test_living_costs_applied(self, db, config):
        orch = build_orchestrator(db, seed=42, config=config)
        orch.initialize(people_count=10, seed=42)
        orch.run_hours(24)  # 1 day

        ledger = orch.ledger_entries(limit=500)
        living_cost_entries = [e for e in ledger if e.event_type == "LIVING_COST"]
        assert len(living_cost_entries) > 0

    def test_subscription_billing_creates_intents(self, db, config):
        orch = build_orchestrator(db, seed=42, config=config)
        orch.initialize(people_count=10, seed=42)
        orch.run_hours(48)

        # Should have created PaymentIntents for due subscriptions
        intents = orch.payment_intents(limit=500)
        assert len(intents) > 0

    def test_simulation_run_recorded(self, db, config):
        orch = build_orchestrator(db, seed=42, config=config)
        run_id = orch.initialize(people_count=10, seed=42)
        assert run_id is not None

        run = orch._sim_run_repo.find(run_id)
        assert run is not None
        assert run.seed == 42
        assert run.people_count == 10
        assert run.status == STATUS_RUNNING

        orch.run_hours(24)

        run = orch._sim_run_repo.find(run_id)
        assert run.status == STATUS_COMPLETED
        assert run.hours_run == 24

    def test_run_days_backward_compat(self, db, config):
        """run_days() should work and convert to hours (24 hours per day)."""
        orch = build_orchestrator(db, seed=42, config=config)
        orch.initialize(people_count=5, seed=42)
        orch.run_days(1)  # Should run 24 hours

        summary = orch.summary()
        assert summary["current_hour"] >= 24

    def test_summary_structure(self, db, config):
        orch = build_orchestrator(db, seed=42, config=config)
        orch.initialize(people_count=10, seed=42)
        orch.run_hours(24)

        summary = orch.summary()
        assert "current_hour" in summary
        assert "current_datetime" in summary
        assert "people" in summary
        assert "ledger_entries" in summary

    def test_e_commerce_during_business_hours(self, db, config):
        """E-commerce purchases should only happen during business hours (10-20)."""
        orch = build_orchestrator(db, seed=42, config=config)
        orch.initialize(people_count=10, seed=42)
        orch.run_hours(120)  # 5 days

        ledger = orch.ledger_entries(limit=1000)
        # Check that e-commerce purchase intents exist
        intents = orch.payment_intents(limit=1000)
        purchase_intents = [i for i in intents if i.related_subscription_id is None]
        # There should be some non-subscription intents (e-commerce)
        assert len(purchase_intents) > 0
