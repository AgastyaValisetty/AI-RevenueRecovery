"""PolicyValidator — deterministic policy gates for the Smart Recovery Agent.

Enforces all stopping rules, action allowlists, retry budgets, contact budgets,
incentive budgets, consent checks, and fatigue scoring.  Every decision the
LLM-based planner makes is filtered through these rules: if a rule fails, the
action is blocked or the case is stopped.

Policy checks are designed to be:
  - **Deterministic** — given the same inputs, the same pass/fail result.
  - **Composable** — each rule is independent; a list of all checks is returned
    so the audit trail shows exactly which rule blocked an action.
  - **Observable** — only uses data from RecoveryContext + persisted state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

from ...domain import ConsentState, PaymentIntent
from ..context import RecoveryContext
from ..domain import (
    RecoveryActionType,
    RecoveryOutcome,
)
from ..repository import RecoveryActionRepository
from .action_value import ExpectedValue, CandidateAction
from .feature_store import CaseFeatures
from .memory import RecoveryMemoryRepository, CustomerRecoveryMemory
from .promise_tracker import PromiseTracker

logger = logging.getLogger(__name__)


class StopReason(str, Enum):
    """Machine-readable stop reasons."""

    MAX_RETRIES_EXHAUSTED = "max_retries_exhausted"
    CUSTOMER_DECLINED = "customer_declined"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    POLICY_BLOCKED_OUTAGE = "policy_blocked_outage"
    LOW_EXPECTED_VALUE = "low_expected_value"
    CONTACT_BUDGET_EXHAUSTED = "contact_budget_exhausted"
    INTENT_EXPIRED = "intent_expired"
    INTENT_SETTLED = "intent_settled"
    CUSTOMER_FATIGUED = "customer_fatigued"
    PROMISE_ACTIVE = "promise_active"
    CONSENT_DENIED = "consent_denied"
    DUPLICATE_RISK = "duplicate_risk"


# Human-readable labels for each stop reason (for audit / UI).
STOP_REASONS: dict[str, str] = {
    StopReason.MAX_RETRIES_EXHAUSTED: "Maximum retry attempts exhausted",
    StopReason.CUSTOMER_DECLINED: "Customer explicitly declined",
    StopReason.INSUFFICIENT_BALANCE: "Balance insufficient to recover",
    StopReason.POLICY_BLOCKED_OUTAGE: "Payment rail is degraded/outage — retries blocked",
    StopReason.LOW_EXPECTED_VALUE: "Expected net value below recovery threshold",
    StopReason.CONTACT_BUDGET_EXHAUSTED: "Contact budget exhausted",
    StopReason.INTENT_EXPIRED: "Payment intent has expired",
    StopReason.INTENT_SETTLED: "Payment intent already settled",
    StopReason.CUSTOMER_FATIGUED: "Customer fatigue threshold exceeded",
    StopReason.PROMISE_ACTIVE: "Active promise-to-pay exists — no chase",
    StopReason.CONSENT_DENIED: "Customer consent denied",
    StopReason.DUPLICATE_RISK: "Duplicate retry risk detected",
}


# Action allowlists by source type — determines which actions are legal.
# Maps SourceType → set of allowed RecoveryActionType values.
ACTION_ALLOWLIST: dict[str, set[str]] = {
    "PAYMENT": {"RETRY", "SEND_PAYMENT_LINK", "SEND_NOTIFICATION", "STOP"},
    "CHECKOUT": {"RETRY", "SEND_PAYMENT_LINK", "SEND_NOTIFICATION", "STOP"},
    "SUBSCRIPTION": {"RETRY", "SEND_PAYMENT_LINK", "SEND_NOTIFICATION", "STOP"},
    "MANDATE": {"RETRY", "SEND_PAYMENT_LINK", "STOP"},
    "INVOICE": {"SEND_PAYMENT_LINK", "SEND_NOTIFICATION", "STOP"},
}

# Default action allowlist if source type is unknown.
DEFAULT_ALLOWLIST: set[str] = {"RETRY", "SEND_PAYMENT_LINK", "SEND_NOTIFICATION", "STOP"}

# Contact budget — max outreach actions per case (notifications + links)
DEFAULT_CONTACT_BUDGET = 4

# Minimum expected net value (INR) to justify a non-SUCCESS-ORIENTED action
DEFAULT_MIN_ENPV = Decimal("10.00")

# Fatigue threshold — stop after this many contacts in a case (0-100 scale)
DEFAULT_FATIGUE_SUPPRESS = 100

# Duplicate risk window (hours): if same intent had a retry within this window,
# block another to avoid duplicate risk.
DUPLICATE_RISK_WINDOW_HOURS = 1


@dataclass(frozen=True)
class PolicyCheck:
    """Result of a single policy check.

    Parameters
    ----------
    name :
        Machine-readable name of the check.
    passed :
        True if the check passed (action is allowed).
    detail :
        Human-readable explanation.
    """

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PolicyResult:
    """Aggregate result of all policy checks for a candidate action.

    If ``should_stop`` is True, the case should be stopped (no action taken).
    If ``allowed`` is False, the action is blocked but the case can continue
    with other candidates.
    """

    allowed: bool
    should_stop: bool
    stop_reason: Optional[str] = None
    decision: Optional[dict] = None
    checks: list[PolicyCheck] = field(default_factory=list)


# Registry of all stop rules — used for documentation and audit.
STOP_RULES: dict[str, str] = {
    StopReason.MAX_RETRIES_EXHAUSTED: "Maximum retry attempts exhausted",
    StopReason.CUSTOMER_DECLINED: "Customer explicitly declined",
    StopReason.INSUFFICIENT_BALANCE: "Balance insufficient to recover",
    StopReason.POLICY_BLOCKED_OUTAGE: "Payment rail is degraded/outage — retries blocked",
    StopReason.LOW_EXPECTED_VALUE: "Expected net value below recovery threshold",
    StopReason.CONTACT_BUDGET_EXHAUSTED: "Contact budget exhausted",
    StopReason.INTENT_EXPIRED: "Payment intent has expired",
    StopReason.INTENT_SETTLED: "Payment intent already settled",
    StopReason.CUSTOMER_FATIGUED: "Customer fatigue threshold exceeded",
    StopReason.PROMISE_ACTIVE: "Active promise-to-pay exists — no chase",
    StopReason.CONSENT_DENIED: "Customer consent denied",
    StopReason.DUPLICATE_RISK: "Duplicate retry risk detected",
}


class PolicyValidator:
    """Deterministic policy validator enforcing all stopping rules and budgets.

    Parameters
    ----------
    recovery_repo :
        Repository for checking prior actions (retry count, declines, duplicates).
    memory_repo :
        Repository for customer fatigue + consent state.
    promise_tracker :
        Tracker for checking active promises.
    max_retries :
        Maximum retry attempts per intent (default 3).
    min_enpv :
        Minimum expected net value to justify an action (default ₹10).
    contact_budget :
        Maximum outreach actions (notifications + links) per case (default 4).
    """

    def __init__(
        self,
        recovery_repo: RecoveryActionRepository,
        memory_repo: Optional[RecoveryMemoryRepository] = None,
        promise_tracker: Optional[PromiseTracker] = None,
        *,
        max_retries: int = 3,
        min_enpv: Decimal = DEFAULT_MIN_ENPV,
        contact_budget: int = DEFAULT_CONTACT_BUDGET,
        fatigue_suppress: int = DEFAULT_FATIGUE_SUPPRESS,
    ):
        self._recovery_repo = recovery_repo
        self._memory_repo = memory_repo
        self._promise_tracker = promise_tracker
        self._max_retries = max_retries
        self._min_enpv = min_enpv
        self._contact_budget = contact_budget
        self._fatigue_suppress = fatigue_suppress

    def validate(
        self,
        candidate: CandidateAction,
        context: RecoveryContext,
        features: CaseFeatures,
        expected_value: ExpectedValue,
    ) -> PolicyResult:
        """Validate a candidate action against all policy rules.

        Returns a PolicyResult with ``allowed`` (should we proceed?) and
        ``should_stop`` (should we stop the case entirely?).
        """
        checks: list[PolicyCheck] = []
        should_stop = False
        stop_reason: Optional[str] = None

        # --- Check 1: Intent is still actionable ---
        intent_stopped = self._check_intent_status(context, checks)
        if intent_stopped:
            should_stop = True
            stop_reason = intent_stopped
            return PolicyResult(
                allowed=False,
                should_stop=True,
                stop_reason=stop_reason,
                checks=checks,
            )

        # --- Check 2: Customer declined a previous recovery attempt ---
        if context.customer_declined:
            checks.append(PolicyCheck(
                name="customer_declined",
                passed=False,
                detail="Customer explicitly declined a previous recovery attempt",
            ))
            return PolicyResult(
                allowed=False,
                should_stop=True,
                stop_reason=StopReason.CUSTOMER_DECLINED,
                checks=checks,
            )

        # --- Check 3: Customer consent ---
        consent_blocked = self._check_consent(context, features, checks)
        if consent_blocked:
            should_stop = True
            stop_reason = consent_blocked
            return PolicyResult(
                allowed=False,
                should_stop=True,
                stop_reason=stop_reason,
                checks=checks,
            )

        # --- Check 4: Active promise-to-pay ---
        promise_blocked = self._check_promise(context, features, checks)
        if promise_blocked:
            should_stop = True
            stop_reason = promise_blocked
            return PolicyResult(
                allowed=False,
                should_stop=True,
                stop_reason=stop_reason,
                checks=checks,
            )

        # --- Check 5: Retry budget ---
        retry_blocked = self._check_retry_budget(features, checks)
        if retry_blocked:
            should_stop = True
            stop_reason = retry_blocked
            return PolicyResult(
                allowed=False,
                should_stop=True,
                stop_reason=stop_reason,
                checks=checks,
            )

        # --- Check 6: Customer fatigue ---
        fatigue_blocked = self._check_fatigue(context, features, checks)
        if fatigue_blocked:
            should_stop = True
            stop_reason = fatigue_blocked
            return PolicyResult(
                allowed=False,
                should_stop=True,
                stop_reason=stop_reason,
                checks=checks,
            )

        # --- Check 7: Rail health / outage ---
        outage_blocked = self._check_rail_health(features, candidate, checks)
        if outage_blocked:
            # Rail degradation blocks this specific action (e.g., RETRY) but
            # does NOT stop the case — fall through to non-retry candidates
            # (SEND_PAYMENT_LINK, SEND_NOTIFICATION) which bypass the rails.
            return PolicyResult(
                allowed=False,
                should_stop=False,
                checks=checks,
            )

        # --- Check 8: Duplicate retry risk ---
        dup_blocked = self._check_duplicate_risk(context, candidate, checks)
        if dup_blocked:
            return PolicyResult(
                allowed=False,
                should_stop=False,
                stop_reason=dup_blocked,
                checks=checks,
            )

        # --- Check 9: Action allowlist ---
        allowlist_blocked = self._check_action_allowlist(context, candidate, checks)
        if allowlist_blocked:
            # Action not allowed, but NOT a stop — try another candidate
            return PolicyResult(
                allowed=False,
                should_stop=False,
                checks=checks,
            )

        # --- Check 10: Contact budget ---
        contact_blocked = self._check_contact_budget(context, checks)
        if contact_blocked:
            # Contact budget exhausted — only RETRY or STOP allowed
            if candidate.action_type in ("SEND_PAYMENT_LINK", "SEND_NOTIFICATION"):
                return PolicyResult(
                    allowed=False,
                    should_stop=False,
                    checks=checks,
                )

        # --- Check 11: Expected net value threshold ---
        enpv_blocked = self._check_enpv(candidate, expected_value, checks)
        if enpv_blocked:
            # Below threshold — action blocked but not a hard stop
            # Only STOP if even the best candidate is below threshold
            return PolicyResult(
                allowed=False,
                should_stop=False,
                checks=checks,
            )

        # --- Check 12: Balance sufficiency (for RETRY) ---
        balance_blocked = self._check_balance(context, features, candidate, checks)
        if balance_blocked:
            return PolicyResult(
                allowed=False,
                should_stop=False,
                checks=checks,
            )

        return PolicyResult(
            allowed=True,
            should_stop=False,
            checks=checks,
        )

    def validate_stop_rules(self, context: RecoveryContext, features: CaseFeatures) -> Optional[str]:
        """Check if the case should be stopped regardless of actions.

        Returns a stop reason string if the case should be stopped, or None
        if no stop rules trigger.
        """
        # Intent already settled/failed
        if context.intent_status in ("SETTLED", "PAID"):
            return StopReason.INTENT_SETTLED
        if context.intent_status in ("EXPIRED",):
            return StopReason.INTENT_EXPIRED

        # Customer explicitly declined
        if context.customer_declined:
            return StopReason.CUSTOMER_DECLINED

        # Retry budget exhausted
        if features.retry_count >= self._max_retries:
            return StopReason.MAX_RETRIES_EXHAUSTED

        # Consent explicitly denied
        if self._memory_repo is not None:
            mem = self._memory_repo.get_customer_memory(context.person.person_id)
            if mem.consent_state == ConsentState.DENIED:
                return StopReason.CONSENT_DENIED

        return None

    # ------------------------------------------------------------------ #
    # Individual policy checks
    # ------------------------------------------------------------------ #

    def _check_intent_status(self, context: RecoveryContext, checks: list[PolicyCheck]) -> Optional[str]:
        """Check if the payment intent is already settled or expired."""
        passed = True
        detail = "Intent status is actionable"
        stop_reason = None

        if context.intent_status in ("SETTLED", "PAID"):
            passed = False
            detail = f"Intent already settled (status={context.intent_status})"
            stop_reason = StopReason.INTENT_SETTLED
        elif context.intent_status in ("EXPIRED",):
            passed = False
            detail = f"Intent expired (status={context.intent_status})"
            stop_reason = StopReason.INTENT_EXPIRED

        checks.append(PolicyCheck(
            name="intent_status",
            passed=passed,
            detail=detail,
        ))
        return stop_reason

    def _check_consent(self, context: RecoveryContext, features: CaseFeatures, checks: list[PolicyCheck]) -> Optional[str]:
        """Check customer consent state."""
        if self._memory_repo is None:
            checks.append(PolicyCheck(
                name="consent", passed=True, detail="No memory repo — consent not tracked"
            ))
            return None

        mem = self._memory_repo.get_customer_memory(context.person.person_id)
        passed = mem.consent_state != ConsentState.DENIED
        detail = f"Consent state: {mem.consent_state.value}"

        if not passed:
            stop_reason = StopReason.CONSENT_DENIED
        else:
            stop_reason = None

        checks.append(PolicyCheck(
            name="consent", passed=passed, detail=detail
        ))
        return stop_reason

    def _check_promise(self, context: RecoveryContext, features: CaseFeatures, checks: list[PolicyCheck]) -> Optional[str]:
        """Check if there's an active promise-to-pay — if so, don't chase."""
        if self._promise_tracker is None:
            checks.append(PolicyCheck(
                name="promise", passed=True, detail="No promise tracker configured"
            ))
            return None

        from uuid import UUID as _UUID
        try:
            pid = _UUID(context.person.person_id)
        except (ValueError, TypeError):
            pid = None

        if pid is None:
            checks.append(PolicyCheck(
                name="promise", passed=True, detail="Cannot resolve person_id for promise check"
            ))
            return None

        promise = self._promise_tracker.check_active_promise(pid)
        if promise is not None:
            passed = False
            detail = f"Active promise: {promise.amount} due {promise.due_at.isoformat()}"
            stop_reason = StopReason.PROMISE_ACTIVE
        else:
            passed = True
            detail = "No active promise"
            stop_reason = None

        checks.append(PolicyCheck(
            name="promise", passed=passed, detail=detail
        ))
        return stop_reason

    def _check_retry_budget(self, features: CaseFeatures, checks: list[PolicyCheck]) -> Optional[str]:
        """Check if retry budget is exhausted."""
        if features.retry_count >= self._max_retries:
            passed = False
            detail = f"Retry count ({features.retry_count}) >= max ({self._max_retries})"
            stop_reason = StopReason.MAX_RETRIES_EXHAUSTED
        else:
            passed = True
            detail = f"Retry count {features.retry_count} < max {self._max_retries}"
            stop_reason = None

        checks.append(PolicyCheck(
            name="retry_budget", passed=passed, detail=detail
        ))
        return stop_reason

    def _check_fatigue(self, context: RecoveryContext, features: CaseFeatures, checks: list[PolicyCheck]) -> Optional[str]:
        """Check customer fatigue — stop if above threshold."""
        if features.customer_fatigue_score >= self._fatigue_suppress:
            passed = False
            detail = f"Fatigue score {features.customer_fatigue_score} >= threshold {self._fatigue_suppress}"
            stop_reason = StopReason.CUSTOMER_FATIGUED
        else:
            passed = True
            detail = f"Fatigue score {features.customer_fatigue_score} < threshold {self._fatigue_suppress}"
            stop_reason = None

        checks.append(PolicyCheck(
            name="fatigue", passed=passed, detail=detail
        ))
        return stop_reason

    def _check_rail_health(self, features: CaseFeatures, candidate: CandidateAction, checks: list[PolicyCheck]) -> Optional[str]:
        """Use failure-time rail health as timing evidence, not a hard veto."""
        bank_state = features.bank_state or "NORMAL"
        if bank_state in ("DEGRADED", "OUTAGE"):
            detail = f"Rail was {bank_state} at failure time; delayed retry allowed"
        else:
            detail = f"Rail healthy ({bank_state})"

        checks.append(PolicyCheck(
            name="rail_health", passed=True, detail=detail
        ))
        return None

    def _check_duplicate_risk(self, context: RecoveryContext, candidate: CandidateAction, checks: list[PolicyCheck]) -> Optional[str]:
        """Check for duplicate retry risk — don't retry within a short window."""
        if candidate.action_type != "RETRY":
            checks.append(PolicyCheck(
                name="duplicate_risk", passed=True, detail="Non-retry action — no duplicate risk"
            ))
            return None

        from uuid import UUID as _UUID
        try:
            intent_id = _UUID(context.intent_id)
        except (ValueError, TypeError):
            intent_id = None

        if intent_id is None:
            checks.append(PolicyCheck(
                name="duplicate_risk", passed=True, detail="Cannot resolve intent_id for duplicate check"
            ))
            return None

        prior_actions = self._recovery_repo.find_by_intent_id(intent_id)
        candidate_at = context.current_simulation_time + timedelta(
            hours=candidate.retry_after_hours or 0
        )

        for action in prior_actions:
            if (action.action_type == RecoveryActionType.RETRY and
                action.scheduled_for is not None and
                abs(candidate_at - action.scheduled_for) < timedelta(hours=DUPLICATE_RISK_WINDOW_HOURS)):
                passed = False
                detail = f"Retry scheduled within {DUPLICATE_RISK_WINDOW_HOURS}h window — duplicate risk"
                stop_reason = StopReason.DUPLICATE_RISK
                checks.append(PolicyCheck(
                    name="duplicate_risk", passed=passed, detail=detail
                ))
                return stop_reason

        checks.append(PolicyCheck(
            name="duplicate_risk", passed=True, detail="No recent retry within risk window"
        ))
        return None

    def _check_action_allowlist(self, context: RecoveryContext, candidate: CandidateAction, checks: list[PolicyCheck]) -> Optional[str]:
        """Check if the action is allowed for this source type."""
        # Infer source type from context — use payment_method + subscription info
        if context.subscription is not None:
            source_type = "SUBSCRIPTION"
        else:
            source_type = "PAYMENT"

        allowed_actions = ACTION_ALLOWLIST.get(source_type, DEFAULT_ALLOWLIST)
        if candidate.action_type not in allowed_actions:
            passed = False
            detail = f"Action {candidate.action_type} not allowed for source_type={source_type}"
        else:
            passed = True
            detail = f"Action {candidate.action_type} allowed for source_type={source_type}"

        checks.append(PolicyCheck(
            name="action_allowlist", passed=passed, detail=detail
        ))
        return "action_not_allowed" if not passed else None  # try the next candidate

    def _check_contact_budget(self, context: RecoveryContext, checks: list[PolicyCheck]) -> Optional[str]:
        """Check if the contact budget (outreach actions) is exhausted."""
        from uuid import UUID as _UUID
        try:
            intent_id = _UUID(context.intent_id)
        except (ValueError, TypeError):
            intent_id = None

        if intent_id is None:
            checks.append(PolicyCheck(
                name="contact_budget", passed=True, detail="Cannot resolve intent_id — contact budget not checked"
            ))
            return None

        prior_actions = self._recovery_repo.find_by_intent_id(intent_id)
        outreach_count = sum(
            1 for a in prior_actions
            if a.action_type.value in ("SEND_PAYMENT_LINK", "SEND_NOTIFICATION")
        )

        if outreach_count >= self._contact_budget:
            passed = False
            detail = f"Outreach count ({outreach_count}) >= budget ({self._contact_budget})"
        else:
            passed = True
            detail = f"Outreach count ({outreach_count}) < budget ({self._contact_budget})"

        checks.append(PolicyCheck(
            name="contact_budget", passed=passed, detail=detail
        ))
        return None

    def _check_enpv(self, candidate: CandidateAction, expected_value: ExpectedValue, checks: list[PolicyCheck]) -> Optional[str]:
        """Check if expected net value meets the minimum threshold."""
        if expected_value.expected_net_value >= self._min_enpv:
            passed = True
            detail = f"ENPV {expected_value.expected_net_value} >= {self._min_enpv}"
        else:
            # STOP action always passes — it's the floor
            if candidate.action_type == "STOP":
                passed = True
                detail = "STOP action — always allowed as last resort"
            else:
                passed = False
                detail = f"ENPV {expected_value.expected_net_value} < {self._min_enpv} — action blocked"

        checks.append(PolicyCheck(
            name="min_enpv", passed=passed, detail=detail
        ))
        return None

    def _check_balance(self, context: RecoveryContext, features: CaseFeatures, candidate: CandidateAction, checks: list[PolicyCheck]) -> Optional[str]:
        """Check if balance is sufficient for a RETRY action."""
        if candidate.action_type != "RETRY":
            checks.append(PolicyCheck(
                name="balance", passed=True, detail="Non-retry action — balance check skipped"
            ))
            return None

        if features.is_sufficient_balance:
            passed = True
            detail = f"Balance {features.balance} >= amount {features.amount}"
        elif features.failure_code == "INSUFFICIENT_FUNDS" and candidate.retry_after_hours:
            passed = True
            detail = (
                f"Current balance {features.balance} < amount {features.amount}; "
                f"salary-timed retry allowed after {candidate.retry_after_hours:.1f}h"
            )
        else:
            passed = False
            detail = f"Balance {features.balance} < amount {features.amount} — retry unlikely to succeed"

        checks.append(PolicyCheck(
            name="balance", passed=passed, detail=detail
        ))
        return None
