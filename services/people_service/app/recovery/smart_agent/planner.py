"""ActionPlanner — next-best-action sequencer for the Smart Recovery Agent.

Ranks candidate actions by expected net value (ENPV), applies policy gates,
and returns the single best legal next action.  Enforces ordering constraints:

  - Wait before retrying during rail degradation.
  - STOP is always the last-resort candidate (it has ENPV = 0 but no cost).
  - If the best candidate is blocked by policy, try the next-best.

The planner is purely deterministic — it does not call the LLM directly.
The LLM is consulted separately by the agent for diagnosis and explanation;
the planner handles the optimization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from ..context import RecoveryContext
from ..domain import RecoveryActionType, RecoveryDecision
from .action_value import ActionValueCalculator, CandidateAction, ExpectedValue
from .feature_store import CaseFeatures
from .policy import PolicyValidator, PolicyResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannedAction:
    """The single next-best action after ranking + policy filtering.

    Attributes
    ----------
    candidate :
        The original candidate action.
    expected_value :
        The computed expected value for this action.
    policy_result :
        The result of the policy validation (all checks).
    scheduled_for :
        When the action should execute (may be delayed by policy constraints).
    reason :
        Machine-readable explanation for why this action was chosen.
    """

    candidate: CandidateAction
    expected_value: ExpectedValue
    policy_result: PolicyResult
    scheduled_for: Optional[datetime]
    reason: str


class ActionPlanner:
    """Ranks candidate actions and selects the next-best legal action.

    Parameters
    ----------
    calculator :
        ActionValueCalculator for computing ENPV of candidates.
    policy :
        PolicyValidator that filters candidates against stop rules.
    """

    def __init__(
        self,
        calculator: ActionValueCalculator,
        policy: PolicyValidator,
    ):
        self._calculator = calculator
        self._policy = policy

    def plan(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
    ) -> PlannedAction:
        """Rank all candidate actions and return the best legal one.

        Strategy:
          1. Generate all candidates (RETRY, LINK, NOTIFICATION, STOP).
          2. Compute ENPV for each.
          3. Sort by ENPV descending.
          4. Validate each against policy (starting with best).
          5. Return the first allowed action, or STOP if all are blocked.
        """
        now_ts = context.current_simulation_time

        # Step 1: Generate candidates
        candidates = self._calculator.generate_candidates(context, features)

        # Step 2: Compute ENPV for each candidate
        candidate_ev: list[tuple[CandidateAction, ExpectedValue]] = []
        for candidate in candidates:
            ev = self._calculator.compute(candidate, context, features)
            candidate_ev.append((candidate, ev))

        # Step 3: Sort by expected net value descending
        # STOP should always be last unless it's the only option
        candidate_ev.sort(
            key=lambda x: (x[1].expected_net_value, x[0].action_type == "STOP"),
            reverse=True,
        )
        # Ensure STOP is at the end
        non_stop = [x for x in candidate_ev if x[0].action_type != "STOP"]
        stop_ev = [x for x in candidate_ev if x[0].action_type == "STOP"]
        candidate_ev = non_stop + stop_ev

        # Step 4: Validate each against policy
        for candidate, ev in candidate_ev:
            policy_result = self._policy.validate(candidate, context, features, ev)

            if policy_result.should_stop:
                # A hard stop rule fired — return STOP immediately
                stop_candidate = CandidateAction(
                    action_type="STOP",
                    description=f"Stop recovery — {policy_result.stop_reason}",
                    amount=features.amount,
                )
                stop_ev = ExpectedValue(
                    action_type="STOP",
                    recovery_probability=0.0,
                    expected_gross_recovery=Decimal("0"),
                    retry_cost=Decimal("0"),
                    incentive_cost=Decimal("0"),
                    channel_cost=Decimal("0"),
                    friction_penalty=Decimal("0"),
                    risk_penalty=Decimal("0"),
                    expected_net_value=Decimal("0"),
                    earliest_at=now_ts,
                )
                return PlannedAction(
                    candidate=stop_candidate,
                    expected_value=stop_ev,
                    policy_result=policy_result,
                    scheduled_for=now_ts,
                    reason=f"stop_rule:{policy_result.stop_reason}",
                )

            if policy_result.allowed:
                # This candidate is allowed — schedule it
                scheduled_for = self._compute_schedule_time(
                    candidate, ev, features, now_ts
                )
                reason = self._build_reason(candidate, ev, features)
                return PlannedAction(
                    candidate=candidate,
                    expected_value=ev,
                    policy_result=policy_result,
                    scheduled_for=scheduled_for,
                    reason=reason,
                )

        # Step 5: All non-STOP candidates blocked — return STOP as last resort
        stop_candidate = CandidateAction(
            action_type="STOP",
            description="Stop recovery — all candidates blocked by policy",
            amount=features.amount,
        )
        stop_ev = ExpectedValue(
            action_type="STOP",
            recovery_probability=0.0,
            expected_gross_recovery=Decimal("0"),
            retry_cost=Decimal("0"),
            incentive_cost=Decimal("0"),
            channel_cost=Decimal("0"),
            friction_penalty=Decimal("0"),
            risk_penalty=Decimal("0"),
            expected_net_value=Decimal("0"),
            earliest_at=now_ts,
        )
        fallback_policy = PolicyResult(
            allowed=True,
            should_stop=False,
            checks=[],
        )
        return PlannedAction(
            candidate=stop_candidate,
            expected_value=stop_ev,
            policy_result=fallback_policy,
            scheduled_for=now_ts,
            reason="stop_all_candidates_blocked",
        )

    def to_recovery_decision(self, planned: PlannedAction) -> RecoveryDecision:
        """Convert a PlannedAction into a RecoveryDecision for the scheduler."""
        candidate = planned.candidate
        # The ExpectedValue computed for this candidate is the canonical ENPV —
        # what we'd expect to net if we executed this action. Carry it through
        # to the scheduler so the persisted RecoveryAction records it; the
        # SARA Attempts Ledger reads it from metadata_json to render the
        # "Expected Net Profit Value" column. (Stored in metadata_json rather
        # than a dedicated column to avoid a schema migration.)
        enpv = planned.expected_value.expected_net_value

        if candidate.action_type == "STOP":
            return RecoveryDecision(
                action=RecoveryActionType.STOP,
                scheduled_for=planned.scheduled_for,
                reason=planned.reason,
                retry_number=candidate.retry_number,
                expected_net_value=enpv,
            )

        # Determine retry number
        retry_number = candidate.retry_number

        # Schedule for the earliest allowed time
        scheduled_for = planned.scheduled_for or datetime.now(timezone.utc)

        return RecoveryDecision(
            action=RecoveryActionType(candidate.action_type),
            scheduled_for=scheduled_for,
            reason=planned.reason,
            retry_number=retry_number,
            expected_net_value=enpv,
        )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_schedule_time(
        candidate: CandidateAction,
        ev: ExpectedValue,
        features: CaseFeatures,
        now_ts: datetime,
    ) -> datetime:
        """Determine when the action should execute.

        - If ENPV has an earliest_at (delayed retry), use that.
        - If candidate has retry_after_hours, use that.
        - Otherwise, execute immediately.
        """
        if ev.earliest_at is not None:
            return ev.earliest_at
        if candidate.retry_after_hours is not None:
            return now_ts + timedelta(hours=candidate.retry_after_hours)
        return now_ts

    @staticmethod
    def _build_reason(candidate: CandidateAction, ev: ExpectedValue, features: CaseFeatures) -> str:
        """Build a machine-readable reason string for the action."""
        parts = [
            f"action={candidate.action_type}",
            f"enpv={ev.expected_net_value}",
            f"p_recovery={ev.recovery_probability}",
        ]

        if candidate.retry_number is not None:
            parts.append(f"retry={candidate.retry_number}")

        if features.failure_category:
            parts.append(f"category={features.failure_category}")

        if features.bank_state:
            parts.append(f"bank_state={features.bank_state}")

        return " ".join(parts)
