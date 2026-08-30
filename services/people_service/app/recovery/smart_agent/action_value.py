"""ActionValueCalculator — expected-net-value calculator for candidate actions.

For each legal candidate action, computes:

    ENPV(action) = P(recovery | context, action) × amount
                − retry_cost − incentive_cost − channel_cost
                − friction_penalty − risk_penalty

Uses :func:`failure_model.failure_probability` as the probability backbone,
adjusted per action type and failure category.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from ...failure_model import (
    FAILURE_CATEGORIES,
    STATE_MULTIPLIERS,
    failure_probability,
)
from ..context import RecoveryContext
from .feature_store import CaseFeatures

logger = logging.getLogger(__name__)

# Cost constants (configurable in production)
RETRY_COST = Decimal("2.50")       # LazerPay/ gateway fee per retry
LINK_COST = Decimal("1.00")        # Payment link generation + delivery
NOTIFICATION_COST = Decimal("0.50")  # SMS / push notification
INCENTIVE_DEFAULT = Decimal("0")   # no incentive unless merchant-configured

# Friction penalty per contact (INR) — estimated customer-annoyance cost
DEFAULT_FRICTION_PENALTY = Decimal("5.00")

# Minimum ENPV (INR) required to justify an action
DEFAULT_MIN_ENPV = Decimal("10.00")


@dataclass(frozen=True)
class CandidateAction:
    """A legal candidate action and its parameters.

    Parameters
    ----------
    action_type :
        The RecoveryActionType label (RETRY, SEND_PAYMENT_LINK, etc.).
    description :
        Human-readable description for the action menu.
    amount :
        The amount at stake.
    retry_number :
        Retry number if this is a retry (1, 2, 3); None otherwise.
    retry_after_hours :
        If set, the action should not execute until this many hours have
        passed since failure (used for WAIT / delayed-retry).
    expected_recovery :
        Expected gross recovery amount (ENPV numerator's gross term).
    """

    action_type: str
    description: str
    amount: Decimal
    retry_number: Optional[int] = None
    retry_after_hours: Optional[float] = None
    expected_recovery: Optional[Decimal] = None


@dataclass(frozen=True)
class ExpectedValue:
    """Expected-net-value calculation for a single candidate action."""

    action_type: str
    recovery_probability: float
    expected_gross_recovery: Decimal
    retry_cost: Decimal
    incentive_cost: Decimal
    channel_cost: Decimal
    friction_penalty: Decimal
    risk_penalty: Decimal
    expected_net_value: Decimal
    earliest_at: Optional[datetime] = None

    @property
    def total_cost(self) -> Decimal:
        return self.retry_cost + self.incentive_cost + self.channel_cost

    @property
    def total_penalty(self) -> Decimal:
        return self.friction_penalty + self.risk_penalty


class ActionValueCalculator:
    """Computes expected net value for candidate recovery actions.

    Parameters
    ----------
    max_retries :
        The retry budget (default 3) used to gate retry candidates.
    """

    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries

    def compute(
        self,
        candidate: CandidateAction,
        context: RecoveryContext,
        features: CaseFeatures,
    ) -> ExpectedValue:
        """Compute the expected net value for a single candidate action."""
        amount_f = float(features.amount)
        method = features.payment_method
        bank_state = features.bank_state or "NORMAL"

        # --- Determine recovery probability for this action type ---
        if candidate.action_type == "RETRY":
            p = self._retry_recovery_probability(features, candidate)
        elif candidate.action_type == "SEND_PAYMENT_LINK":
            p = self._link_recovery_probability(features, context)
        elif candidate.action_type == "SEND_NOTIFICATION":
            p = self._notification_recovery_probability(features, context)
        elif candidate.action_type == "STOP":
            p = 0.0
        else:
            p = 0.0

        # Clamp probability
        p = max(0.0, min(1.0, p))

        gross_recovery = Decimal(str(round(amount_f * p, 2)))

        # --- Compute costs ---
        if candidate.action_type == "RETRY":
            cost = RETRY_COST
        elif candidate.action_type == "SEND_PAYMENT_LINK":
            cost = LINK_COST
        elif candidate.action_type == "SEND_NOTIFICATION":
            cost = NOTIFICATION_COST
        else:
            cost = Decimal("0")

        incentive_cost = Decimal("0")  # no incentive by default

        # Friction penalty — scaled by customer fatigue
        friction = DEFAULT_FRICTION_PENALTY * Decimal(str(features.customer_fatigue_score / 100.0)) if features.customer_fatigue_score > 0 else DEFAULT_FRICTION_PENALTY

        # Risk penalty — based on bank decline / fraud risk
        risk = self._risk_penalty(features, candidate)

        # Earliest execution time
        earliest_at = None
        if candidate.retry_after_hours is not None:
            earliest_at = context.current_simulation_time + timedelta(
                hours=candidate.retry_after_hours
            )

        net_value = gross_recovery - cost - incentive_cost - friction - risk

        return ExpectedValue(
            action_type=candidate.action_type,
            recovery_probability=round(p, 4),
            expected_gross_recovery=gross_recovery,
            retry_cost=cost,
            incentive_cost=incentive_cost,
            channel_cost=Decimal("0"),
            friction_penalty=friction,
            risk_penalty=risk,
            expected_net_value=net_value.quantize(Decimal("0.01")),
            earliest_at=earliest_at,
        )

    def generate_candidates(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
    ) -> list[CandidateAction]:
        """Generate the set of legal candidate actions for this context.

        This produces candidates only — the PolicyValidator later filters
        them against stop rules and budgets.
        """
        candidates: list[CandidateAction] = []
        retries_remaining = features.retries_remaining

        # RETRY candidates — one per remaining retry slot
        if retries_remaining > 0:
            next_retry = features.retry_count + 1
            delay = self._retry_delay(features, context.current_simulation_time)
            candidates.append(CandidateAction(
                action_type="RETRY",
                description=f"Safe retry (attempt #{next_retry}) after {delay}h",
                amount=features.amount,
                retry_number=next_retry,
                retry_after_hours=delay,
            ))

        # SEND_PAYMENT_LINK — always a candidate (customer can pay via link)
        candidates.append(CandidateAction(
            action_type="SEND_PAYMENT_LINK",
            description="Send payment link to customer",
            amount=features.amount,
        ))

        # SEND_NOTIFICATION — softer nudge
        candidates.append(CandidateAction(
            action_type="SEND_NOTIFICATION",
            description="Send notification reminder",
            amount=features.amount,
        ))

        # STOP — always a candidate (the policy validator decides)
        candidates.append(CandidateAction(
            action_type="STOP",
            description="Stop recovery — expected value is negative",
            amount=features.amount,
        ))

        return candidates

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _retry_delay(self, features: CaseFeatures, current_time: datetime | None = None) -> float:
        """Compute the recommended delay before the next retry.

        - Infrastructure failures: short delay (10-30 min) — transient issues resolve quickly.
        - Bank declines: moderate delay (1-2 hours) — gives the bank time to clear.
        - Customer-state issues (insufficient funds): long delay (12+ hours) —
          wait for next salary deposit.
        - Normal: 12 hours (baseline interval).
        """
        if features.is_transient:
            # Infrastructure: 10 minutes to 1 hour
            if features.bank_state in ("DEGRADED", "OUTAGE"):
                return 2.0
            return 1.0
        if features.is_bank_decline:
            return 1.0
        if features.is_customer_state:
            if features.is_sufficient_balance:
                return 1.0
            # People DB provides the salary day/hour. Retry the day after the
            # next deposit, not immediately before the balance is available.
            now = current_time or datetime(2024, 1, 1, features.hour_of_day)
            target = now.date()
            for _ in range(370):
                target += timedelta(days=1)
                if target.day == features.salary_deposit_day:
                    retry_at = datetime.combine(
                        target + timedelta(days=1),
                        datetime.min.time().replace(hour=features.salary_deposit_hour),
                    ).replace(tzinfo=now.tzinfo)
                    return max(1.0, (retry_at - now).total_seconds() / 3600.0)
            return 48.0
        if features.is_merchant_config:
            # Method switch needed, short delay
            return 1.0
        return 1.0

    def _retry_recovery_probability(
        self, features: CaseFeatures, candidate: CandidateAction
    ) -> float:
        """P(recovery | retry) — adjusted failure probability after retry."""
        retry_num = candidate.retry_number or 1
        amount_f = float(features.amount)
        balance_f = float(features.balance)
        method = features.payment_method
        bank_state = features.bank_state or "NORMAL"

        # If bank is degraded/outage, retry probability is very low
        if bank_state in ("DEGRADED", "OUTAGE"):
            base_p_fail = failure_probability(
                method, bank_state=bank_state,
                amount=amount_f, balance=balance_f,
            )
            # High failure probability during degradation — retry is risky
            return max(0.05, 1.0 - base_p_fail)

        # If insufficient balance, retry won't help unless balance increases
        if features.failure_code == "INSUFFICIENT_FUNDS":
            if not features.is_sufficient_balance:
                # A retry before a known balance event is almost always waste.
                # Reserve the attempt for the post-salary window.
                funded_balance = max(balance_f, amount_f * 2.0)
                post_salary_fail_p = failure_probability(
                    method,
                    bank_state="NORMAL",
                    amount=amount_f,
                    balance=funded_balance,
                    hour=features.salary_deposit_hour,
                )
                return max(0.70, 1.0 - post_salary_fail_p)

        # Hard method/configuration failures should not burn a retry budget.
        if features.is_payment_method_expired or features.is_merchant_config:
            base_p_fail = failure_probability(
                method,
                bank_state="NORMAL",
                amount=amount_f,
                balance=max(balance_f, amount_f),
                hour=features.hour_of_day,
            )
            return max(0.55, 1.0 - (base_p_fail * (0.65 ** max(retry_num - 1, 0))))

        # Issuer declines are better handled by a fresh payment path than by
        # hammering the same authorization request.
        if features.is_bank_decline:
            base_p_fail = failure_probability(
                method,
                bank_state="NORMAL",
                amount=amount_f,
                balance=max(balance_f, amount_f),
                hour=features.hour_of_day,
            )
            return max(0.60, 1.0 - (base_p_fail * 0.4 * (0.6 ** (retry_num - 1))))

        # Transient infrastructure failures: high recovery on retry
        if features.is_transient:
            # Base success probability from failure model
            base_p_fail = failure_probability(
                method, bank_state="NORMAL",
                amount=amount_f, balance=balance_f,
                hour=features.hour_of_day,
            )
            # Retry improves odds — infrastructure failures are transient
            retry_success_p = min(0.95, 0.85 + 0.05 * (retry_num - 1))
            return retry_success_p

        # Standard retry — halve failure probability per retry
        base_p_fail = failure_probability(
            method, bank_state="NORMAL",
            amount=amount_f, balance=balance_f,
            hour=features.hour_of_day,
        )
        retry_adjustment = 0.5 ** (retry_num - 1)
        adjusted_p_fail = base_p_fail * retry_adjustment
        return max(0.0, 1.0 - adjusted_p_fail)

    def _link_recovery_probability(
        self, features: CaseFeatures, context: RecoveryContext
    ) -> float:
        """P(recovery | payment link).

        A payment link gives the customer a clean path to pay directly,
        bypassing the original payment method.  Success rate is based on
        the customer behavior profile's response rate.
        """
        # Base response rate from feature store.  The action-value model adds
        # cause-specific intent: a link is materially better when the original
        # rail or payment method is the suspected fault.
        base_rate = features.behavior_profile.response_rate

        if features.is_bank_decline or features.is_payment_method_expired or features.is_merchant_config:
            base_rate *= 8.0
        elif features.is_customer_state:
            base_rate *= 3.0 if features.is_sufficient_balance else 2.0
        elif features.is_transient:
            base_rate *= 0.6

        # Boost for sufficient balance
        if features.is_sufficient_balance:
            base_rate *= 1.5

        # Reduce if customer has already declined
        if features.customer_declined:
            base_rate *= 0.1

        # Reduce for high fatigue
        if features.customer_fatigue_score > 70:
            base_rate *= 0.3

        return min(0.95, base_rate)

    def _notification_recovery_probability(
        self, features: CaseFeatures, context: RecoveryContext
    ) -> float:
        """P(recovery | notification).

        Notifications are softer than payment links — lower recovery rate
        but also lower friction cost.
        """
        link_p = self._link_recovery_probability(features, context)
        # Notifications have ~50% of the link's recovery probability
        return link_p * 0.5

    def _risk_penalty(self, features: CaseFeatures, candidate: CandidateAction) -> Decimal:
        """Compute risk penalty based on failure type and action.

        - Bank declines carry fraud/dispute risk (higher penalty)
        - During degraded rail, retries carry higher risk of duplicate
        - Method-expired retries carry moderate risk
        """
        penalty = Decimal("0")

        if candidate.action_type == "RETRY":
            if features.is_bank_decline:
                penalty += Decimal("1.00")
            if features.bank_state in ("DEGRADED", "OUTAGE"):
                penalty += Decimal("5.00")
            if features.failure_code == "EXPIRED_PAYMENT_METHOD":
                penalty += Decimal("1.00")

        if features.is_merchant_config and candidate.action_type == "RETRY":
            penalty += Decimal("1.00")

        return penalty
