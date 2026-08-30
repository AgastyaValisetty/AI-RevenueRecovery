"""CounterfactualSimulator — runs "what-if" scenarios before acting.

Estimates the impact of alternative actions without actually executing them:

  - "What if we wait 30 minutes before retrying?"
  - "What if we send a payment link instead of retrying?"
  - "What if we stop now?"

Each scenario is evaluated by simulating the expected outcome using the
deterministic failure model and expected-value calculator.  Results are
returned as a ranked list so the planner can make an informed choice.

This is a *lightweight* counterfactual — it reuses the existing failure model
and ENPV calculator rather than running a full simulation.  The full paired
experiment comparison is handled by ``experiment_runner.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from ...failure_model import failure_probability, STATE_MULTIPLIERS
from ..context import RecoveryContext
from .action_value import ActionValueCalculator, ExpectedValue, CandidateAction
from .feature_store import CaseFeatures
from .diagnosis import Diagnosis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CounterfactualScenario:
    """A single "what-if" scenario for evaluation.

    Parameters
    ----------
    name :
        Human-readable name for the scenario.
    description :
        What this scenario tests.
    action_type :
        The hypothetical action type (RETRY, SEND_PAYMENT_LINK, STOP).
    delay_hours :
        How long to wait before taking the action.
    bank_state :
        Hypothetical bank state (e.g., "NORMAL" if we assume recovery).
    """

    name: str
    description: str
    action_type: str
    delay_hours: float = 0.0
    bank_state: str = "NORMAL"


@dataclass(frozen=True)
class ScenarioOutcome:
    """The evaluated outcome of a counterfactual scenario.

    Parameters
    ----------
    scenario :
        The scenario that was evaluated.
    expected_value :
        The computed ENPV for this scenario.
    recovery_probability :
        P(recovery) under this scenario.
    risk_notes :
        Any risk considerations specific to this scenario.
    """

    scenario: CounterfactualScenario
    expected_value: ExpectedValue
    recovery_probability: float
    risk_notes: list[str]


# Standard scenarios evaluated for every case
DEFAULT_SCENARIOS: list[CounterfactualScenario] = [
    CounterfactualScenario(
        name="retry_now",
        description="Retry immediately with current conditions",
        action_type="RETRY",
        delay_hours=0.0,
        bank_state="NORMAL",
    ),
    CounterfactualScenario(
        name="retry_30min",
        description="Wait 30 minutes, then retry (transient failures may resolve)",
        action_type="RETRY",
        delay_hours=0.5,
        bank_state="NORMAL",
    ),
    CounterfactualScenario(
        name="retry_2h",
        description="Wait 2 hours (gives bank time to clear peak load)",
        action_type="RETRY",
        delay_hours=2.0,
        bank_state="NORMAL",
    ),
    CounterfactualScenario(
        name="send_link",
        description="Send a payment link instead of retrying",
        action_type="SEND_PAYMENT_LINK",
        delay_hours=0.0,
        bank_state="NORMAL",
    ),
    CounterfactualScenario(
        name="wait_salary",
        description="Wait until next salary deposit window (for insufficient-funds cases)",
        action_type="RETRY",
        delay_hours=12.0,
        bank_state="NORMAL",
    ),
    CounterfactualScenario(
        name="stop_now",
        description="Stop recovery entirely",
        action_type="STOP",
        delay_hours=0.0,
        bank_state="NORMAL",
    ),
]


class CounterfactualSimulator:
    """Evaluates counterfactual scenarios against the failure model.

    Parameters
    ----------
    calculator :
        ActionValueCalculator used to compute ENPV for each scenario.
    """

    def __init__(self, calculator: ActionValueCalculator):
        self._calculator = calculator

    def evaluate(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
        scenarios: Optional[list[CounterfactualScenario]] = None,
    ) -> list[ScenarioOutcome]:
        """Evaluate all scenarios and return ranked outcomes.

        Returns outcomes sorted by expected_net_value (descending).
        """
        if scenarios is None:
            scenarios = self._filter_scenarios(features, diagnosis)

        outcomes: list[ScenarioOutcome] = []

        for scenario in scenarios:
            candidate = CandidateAction(
                action_type=scenario.action_type,
                description=f"{scenario.name}: {scenario.description}",
                amount=features.amount,
                retry_number=features.retry_count + 1 if scenario.action_type == "RETRY" else None,
                retry_after_hours=scenario.delay_hours if scenario.action_type == "RETRY" else None,
            )

            # Temporarily adjust features for the scenario's bank_state
            scenario_features = self._adjust_features(features, scenario, context)

            ev = self._calculator.compute(candidate, scenario_features_context(context, scenario), scenario_features)

            risk_notes = self._compute_risk_notes(scenario, features)

            outcomes.append(ScenarioOutcome(
                scenario=scenario,
                expected_value=ev,
                recovery_probability=ev.recovery_probability,
                risk_notes=risk_notes,
            ))

        # Sort by expected net value descending
        outcomes.sort(key=lambda o: o.expected_value.expected_net_value, reverse=True)
        return outcomes

    def get_best_scenario(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
    ) -> Optional[ScenarioOutcome]:
        """Return the highest-ENPV scenario outcome."""
        outcomes = self.evaluate(context, features, diagnosis)
        return outcomes[0] if outcomes else None

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _filter_scenarios(
        features: CaseFeatures, diagnosis: Diagnosis
    ) -> list[CounterfactualScenario]:
        """Filter the default scenarios based on context.

        - Skip 'wait_salary' if not an insufficient-balance case.
        - Skip 'retry_30min' / 'retry_2h' if infrastructure failures are unlikely to resolve.
        """
        filtered = []

        for s in DEFAULT_SCENARIOS:
            if s.name == "wait_salary" and not features.is_customer_state:
                continue
            if s.name == "retry_30min" and not features.is_transient:
                continue
            if s.name == "retry_2h" and not features.is_transient and not features.is_bank_decline:
                continue
            filtered.append(s)

        return filtered

    @staticmethod
    def _adjust_features(
        features: CaseFeatures, scenario: CounterfactualScenario, context: RecoveryContext
    ) -> CaseFeatures:
        """Create adjusted features for the scenario's hypothetical bank state."""
        from dataclasses import replace
        # Adjust bank_state for the scenario
        return replace(
            features,
            bank_state=scenario.bank_state,
            hours_since_failure=int(scenario.delay_hours + features.hours_since_failure),
        )

    @staticmethod
    def _compute_risk_notes(
        scenario: CounterfactualScenario, features: CaseFeatures
    ) -> list[str]:
        """Compute risk notes specific to a scenario."""
        notes = []

        if scenario.action_type == "RETRY":
            if features.customer_fatigue_score > 70:
                notes.append("High fatigue — customer may ignore/block retries")
            if scenario.bank_state in ("DEGRADED", "OUTAGE"):
                notes.append("Rail still degraded — retry may fail again")
            if features.failure_code == "INSUFFICIENT_FUNDS" and not features.is_sufficient_balance:
                notes.append("Balance insufficient — retry unlikely to succeed unless deposit occurs")
            if features.is_merchant_config:
                notes.append("Merchant config issue — retrying won't help")

        if scenario.action_type == "SEND_PAYMENT_LINK":
            if features.customer_declined:
                notes.append("Customer previously declined — link may be ignored")

        if scenario.delay_hours > 12:
            notes.append(f"Long delay ({scenario.delay_hours}h) — may miss recovery window")

        if not notes:
            notes.append("No significant risks identified")

        return notes


def scenario_features_context(context: RecoveryContext, scenario: CounterfactualScenario) -> RecoveryContext:
    """Return a modified RecoveryContext for a scenario (e.g., adjusted bank_state)."""
    # We don't modify the context itself — the calculator uses features.bank_state
    # which we already adjusted.  This is a no-op passthrough since features
    # carry the bank_state independently.
    return context
