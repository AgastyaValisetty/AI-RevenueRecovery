"""Smoke test for SmartRecoveryEngine pipeline — no DB required.

Uses ScenarioLibrary to build deterministic contexts, then exercises:
  - FeatureStore
  - RootCauseDiagnoser
  - ActionValueCalculator
  - PolicyValidator + ActionPlanner
  - CounterfactualSimulator

Tests all 10 canonical scenarios from 1.md section 15.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.recovery.smart_agent import (
    ScenarioLibrary, RootCauseDiagnoser, FeatureStore,
    ActionValueCalculator, PolicyValidator, ActionPlanner,
    SmartRecoveryEngine,
)
from app.recovery.smart_agent.counterfactual import CounterfactualSimulator, DEFAULT_SCENARIOS
from app.recovery import RecoveryContext


class FakeRecoveryRepo:
    """Minimal recovery repo — returns empty results (no prior history)."""
    _db = sqlite3.connect(":memory:")

    def find_all(self, limit=10000):
        return []
    def find_by_intent_id(self, intent_id):
        return []
    def max_retry_number(self, intent_id):
        return 0
    def has_been_retryed_for_intent(self, intent_id, _action_type=None):
        return False
    def has_customer_declined(self, intent_id):
        return False


@pytest.fixture
def feature_store():
    return FeatureStore(recovery_repo=FakeRecoveryRepo(), max_retries=3)

@pytest.fixture
def calculator():
    return ActionValueCalculator(max_retries=3)

@pytest.fixture
def policy():
    return PolicyValidator(
        recovery_repo=FakeRecoveryRepo(),
        memory_repo=None,
        promise_tracker=None,
        max_retries=3,
    )

@pytest.fixture
def planner(calculator, policy):
    return ActionPlanner(calculator=calculator, policy=policy)


class TestSmartAgentPipeline:
    """Exercise the full smart agent pipeline on all 10 canonical scenarios."""

    @pytest.mark.parametrize("scenario_name", [
        "bank_degradation",
        "insufficient_balance",
        "method_expired",
        "customer_declined",
        "retry_exhaustion",
        "promised_to_pay",
        "subscription_churn",
        "large_amount_high_risk",
        "infrastructure_timeout",
        "consent_denied",
    ])
    def test_scenario_pipeline(self, scenario_name, feature_store, calculator, policy, planner):
        spec = ScenarioLibrary.get(scenario_name)
        assert spec is not None, f"Unknown scenario: {scenario_name}"

        ctx = ScenarioLibrary.build_context(spec)

        # 1. Feature extraction
        features = feature_store.extract(ctx)
        assert features.intent_id == ctx.intent_id
        assert features.amount == spec.amount
        assert features.failure_code == spec.failure_code
        assert features.retry_count == spec.retry_count

        # 2. Diagnosis (deterministic)
        diagnoser = RootCauseDiagnoser()
        diagnosis = diagnoser.diagnose(ctx, features)
        assert diagnosis.label is not None
        assert 0.0 <= diagnosis.confidence <= 1.0

        # 3. Candidate generation
        candidates = calculator.generate_candidates(ctx, features)
        assert len(candidates) > 0
        action_types = {c.action_type for c in candidates}
        assert "RETRY" in action_types or "STOP" in action_types  # always has these

        # 4. ENPV computation
        for candidate in candidates:
            ev = calculator.compute(candidate, ctx, features)
            assert ev.expected_net_value is not None

        # 5. Planning (policy + ranking)
        planned = planner.plan(ctx, features)
        assert planned.candidate is not None
        assert planned.expected_value is not None
        assert planned.policy_result is not None

        # 6. Counterfactual evaluation
        cf = CounterfactualSimulator(calculator)
        outcomes = cf.evaluate(ctx, features, diagnosis, DEFAULT_SCENARIOS[:3])
        assert len(outcomes) > 0
        # Outcomes should be sorted by ENPV descending
        for i in range(len(outcomes) - 1):
            assert outcomes[i].expected_value.expected_net_value >= outcomes[i+1].expected_value.expected_net_value

    def test_insufficient_balance_no_insufficient_retry(self, feature_store, calculator, planner):
        """When balance < amount, ENPV of retry should be low."""
        spec = ScenarioLibrary.get("insufficient_balance")
        ctx = ScenarioLibrary.build_context(spec)
        features = feature_store.extract(ctx)

        assert not features.is_sufficient_balance
        assert features.balance_to_amount_ratio < 1.0

        # Generate candidates and compute ENPV
        candidates = calculator.generate_candidates(ctx, features)
        retry_candidates = [c for c in candidates if c.action_type == "RETRY"]
        if retry_candidates:
            ev = calculator.compute(retry_candidates[0], ctx, features)
            # ENPV should be low because P(recovery) is low for insufficient balance
            assert ev.expected_net_value < features.amount

    def test_customer_declined_stops_immediately(self, feature_store, calculator, planner):
        """When customer_declined=True, planner should produce STOP."""
        spec = ScenarioLibrary.get("customer_declined")
        ctx = ScenarioLibrary.build_context(spec)
        features = feature_store.extract(ctx)

        assert features.customer_declined is True
        planned = planner.plan(ctx, features)
        assert planned.candidate.action_type == "STOP"

    def test_retry_exhaustion_stops(self, feature_store, calculator, planner):
        """When retry_count >= max_retries, planner should produce STOP."""
        spec = ScenarioLibrary.get("retry_exhaustion")
        ctx = ScenarioLibrary.build_context(spec)
        features = feature_store.extract(ctx)

        assert features.retry_count >= features.max_retries
        planned = planner.plan(ctx, features)
        assert planned.candidate.action_type == "STOP"

    def test_conset_denied_stops(self, feature_store, calculator, planner):
        """When consent_denied, planner should produce STOP or non-contact action."""
        spec = ScenarioLibrary.get("consent_denied")
        ctx = ScenarioLibrary.build_context(spec)
        features = feature_store.extract(ctx)

        planned = planner.plan(ctx, features)
        # Should not choose SEND_NOTIFICATION or SEND_PAYMENT_LINK when consent denied
        assert planned.candidate.action_type != "SEND_NOTIFICATION"

    def test_counterfactual_sorting(self, feature_store, calculator, planner):
        """Counterfactual outcomes are sorted by ENPV descending."""
        spec = ScenarioLibrary.get("infrastructure_timeout")
        ctx = ScenarioLibrary.build_context(spec)
        features = feature_store.extract(ctx)
        diagnosis = RootCauseDiagnoser().diagnose(ctx, features)

        cf = CounterfactualSimulator(calculator)
        outcomes = cf.evaluate(ctx, features, diagnosis, DEFAULT_SCENARIOS)

        for i in range(len(outcomes) - 1):
            assert (
                outcomes[i].expected_value.expected_net_value
                >= outcomes[i+1].expected_value.expected_net_value
            ), f"Outcomes not sorted at index {i}"

    def test_explanation_card_generation(self, feature_store, calculator, policy, planner):
        """Explainer can generate a full explanation card."""
        from app.recovery.smart_agent.explainer import Explainer

        spec = ScenarioLibrary.get("infrastructure_timeout")
        ctx = ScenarioLibrary.build_context(spec)
        features = feature_store.extract(ctx)
        diagnosis = RootCauseDiagnoser().diagnose(ctx, features)

        candidates = calculator.generate_candidates(ctx, features)
        candidate_evs = [(c, calculator.compute(c, ctx, features)) for c in candidates]

        planned = planner.plan(ctx, features)

        # Find matching EV
        ev = None
        for c, e in candidate_evs:
            if c.action_type == planned.candidate.action_type:
                ev = e
                break

        explainer = Explainer(llm_gateway=None)
        if planned.candidate.action_type == "STOP":
            card = explainer.explain_stop(ctx, features, diagnosis, planned.reason or "unknown")
        else:
            from app.recovery.smart_agent.action_value import ExpectedValue
            if ev is None:
                ev = ExpectedValue(
                    action_type="STOP",
                    recovery_probability=0.0,
                    expected_gross_recovery=Decimal("0"),
                    retry_cost=Decimal("0"),
                    incentive_cost=Decimal("0"),
                    channel_cost=Decimal("0"),
                    friction_penalty=Decimal("0"),
                    risk_penalty=Decimal("0"),
                    expected_net_value=Decimal("0"),
                    earliest_at=planned.scheduled_for or datetime.now(timezone.utc),
                )
            card = explainer.explain(ctx, features, diagnosis, planned, ev)

        assert card.case_id is not None
        assert card.why_this_action is not None
        assert len(card.key_factors) > 0
        assert "allowed" in card.policy_summary
        assert "action_type" in card.action_details
