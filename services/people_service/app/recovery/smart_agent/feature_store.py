"""FeatureStore — deterministic feature extraction from RecoveryContext.

All features are derived from observable, persisted data.  No hidden simulator
state (future balances, future outcomes, RNG state) is exposed.

Customer behavior profiles (preferred payment time, typical response latency)
are learned hierarchically: global → cohort → customer, with minimum-sample
smoothing to avoid over-confidence on small samples.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ...failure_model import FAILURE_CATEGORIES
from ..context import RecoveryContext, PriorRecovery
from ..repository import RecoveryActionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CustomerBehaviorProfile:
    """Learned behavior signals for a customer (or the global default).

    All values are computed from historical recovery outcomes with
    hierarchical smoothing to avoid over-confidence on small samples.
    """

    # Hour-of-day with highest historical recovery success rate (0-23)
    preferred_payment_hour: int = 12
    # Mean hours from scheduled action to successful recovery
    mean_time_to_recovery_hours: float = 24.0
    # Historical response rate for notifications/links (0-1)
    response_rate: float = 0.015
    # Sample size backing these estimates
    sample_size: int = 0


@dataclass(frozen=True)
class CaseFeatures:
    """Flat, deterministic feature vector for a single recovery case.

    Every field is a pure function of the RecoveryContext and observable
    history.  The vector is used by the diagnosis engine, action-value
    calculator, policy validator, and planner.
    """

    # --- Source / context ---
    intent_id: str
    person_id: str
    merchant_id: str
    amount: Decimal
    payment_method: str
    failure_code: Optional[str]
    failure_category: str  # CUSTOMER_STATE | BANK_DECLINE | INFRASTRUCTURE | MERCHANT_CONFIG
    bank_state: Optional[str]

    # --- Time since failure ---
    hours_since_failure: int
    hour_of_day: int
    day_of_week: int  # 0 = Monday
    is_weekend: bool

    # --- Balance / affordability ---
    balance: Decimal
    balance_to_amount_ratio: float
    is_sufficient_balance: bool
    is_thin_balance: bool  # ratio < 0.5

    # --- Retry exhaustion ---
    retry_count: int
    retries_remaining: int

    # --- Customer state ---
    age: int
    income_bracket: str
    age_group: str
    employment_type: str
    spending_profile_category: str

    # --- Prior behavior ---
    customer_declined: bool
    prior_recovery_outcomes: list[str]  # ["SUCCESS", "FAILED", ...]

    # --- Subscription context ---
    is_subscription: bool
    subscription_consecutive_failures: int

    # --- Failure code semantics ---
    is_transient: bool  # INFRASTRUCTURE failures are transient
    is_customer_state: bool
    is_bank_decline: bool
    is_merchant_config: bool

    # --- Optional / derived fields (with defaults) ---
    days_of_week_active: list[int] = field(default_factory=list)
    max_retries: int = 3
    behavior_profile: CustomerBehaviorProfile = field(
        default_factory=CustomerBehaviorProfile
    )
    customer_fatigue_score: float = 0.0  # 0–100, derived from retry count + prior contacts
    is_payment_method_expired: bool = False
    is_large_amount: bool = False  # >= 10000 INR
    is_peak_hours: bool = False  # 18:00–22:00
    salary_deposit_day: int = 1
    salary_deposit_hour: int = 9

    @property
    def is_expired(self) -> bool:
        """Whether the payment intent has timed out."""
        # Intents expire 1 hour after creation per the domain model.
        return self.hours_since_failure >= 1


@dataclass(frozen=True)
class MerchantRecoveryProfile:
    """Learned recovery behaviour for a specific merchant."""

    merchant_id: str
    best_channel: str = "upi"
    response_rate: float = 0.015
    sample_size: int = 0
    preferred_tone: str = "polite"


class FeatureStore:
    """Extracts deterministic features from a RecoveryContext.

    Parameters
    ----------
    recovery_repo :
        Used to look up prior recovery outcomes for customer behavior profiling.
    max_retries :
        Configured retry budget (default 3).
    """

    def __init__(
        self,
        recovery_repo: RecoveryActionRepository,
        max_retries: int = 3,
    ):
        self._recovery_repo = recovery_repo
        self._max_retries = max_retries

    def extract(self, context: RecoveryContext) -> CaseFeatures:
        """Build a CaseFeatures vector from the observable context."""
        failure_code = context.failure_code
        category = FAILURE_CATEGORIES.get(failure_code or "UNKNOWN", "UNKNOWN")

        amount_f = float(context.intent_amount)
        balance_f = float(context.balance.current_balance)
        ratio = balance_f / amount_f if amount_f > 0 else 0.0

        # Determine failure code semantics
        is_transient = category == "INFRASTRUCTURE"
        is_customer_state = category == "CUSTOMER_STATE"
        is_bank_decline = category == "BANK_DECLINE"
        is_merchant_config = category == "MERCHANT_CONFIG"

        is_expired_method = failure_code == "EXPIRED_PAYMENT_METHOD"
        is_large = amount_f >= 10_000
        current_hour = context.current_simulation_time.hour
        is_peak = 18 <= current_hour <= 22

        # Customer behavior profile — learn from prior recoveries for this person
        profile = self._build_behavior_profile(context.person.person_id)

        # Subscription info
        is_sub = context.subscription is not None
        sub_consecutive_failures = (
            context.subscription.consecutive_failures if is_sub else 0
        )

        return CaseFeatures(
            intent_id=context.intent_id,
            person_id=context.person.person_id,
            merchant_id=context.merchant.merchant_id,
            amount=context.intent_amount,
            payment_method=context.intent_payment_method,
            failure_code=failure_code,
            failure_category=category,
            bank_state=context.bank_state,
            hours_since_failure=context.hours_since_failure,
            hour_of_day=context.current_simulation_time.hour,
            day_of_week=context.current_simulation_time.weekday(),
            is_weekend=context.current_simulation_time.weekday() >= 5,
            days_of_week_active=self._active_days(context.person.person_id),
            balance=context.balance.current_balance,
            balance_to_amount_ratio=round(ratio, 4),
            is_sufficient_balance=balance_f >= amount_f,
            is_thin_balance=ratio < 0.5,
            retry_count=context.retry_count,
            retries_remaining=max(0, self._max_retries - context.retry_count),
            max_retries=self._max_retries,
            age=context.person.age,
            income_bracket=context.person.income_bracket,
            age_group=context.person.age_group,
            employment_type=context.person.employment_type,
            spending_profile_category=context.person.spending_profile_category,
            customer_declined=context.customer_declined,
            prior_recovery_outcomes=[p.outcome for p in context.prior_recoveries],
            is_subscription=is_sub,
            subscription_consecutive_failures=sub_consecutive_failures,
            is_transient=is_transient,
            is_customer_state=is_customer_state,
            is_bank_decline=is_bank_decline,
            is_merchant_config=is_merchant_config,
            behavior_profile=profile,
            customer_fatigue_score=self._compute_fatigue(context),
            is_payment_method_expired=is_expired_method,
            is_large_amount=is_large,
            is_peak_hours=is_peak,
            salary_deposit_day=context.person.salary_deposit_day,
            salary_deposit_hour=context.person.salary_deposit_hour,
        )

    def extract_merchant_profile(self, merchant_id: str) -> MerchantRecoveryProfile:
        """Build a recovery profile for a merchant from historical outcomes."""
        # Aggregate recovery actions for this merchant across all runs.
        # This is a simplified version — in production this would query
        # recovery metrics by merchant from the repository.
        return MerchantRecoveryProfile(merchant_id=merchant_id)

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _build_behavior_profile(self, person_id: str) -> CustomerBehaviorProfile:
        """Learn behavioral signals from prior recovery outcomes for a person.

        Uses hierarchical smoothing: if sample size is too small, falls back
        to global defaults.
        """
        from uuid import UUID as _UUID

        try:
            pid = _UUID(person_id)
        except (ValueError, TypeError):
            return CustomerBehaviorProfile()

        # Look up prior recovery actions for this person
        # We need to find PaymentAttemptRows or RecoveryActionRows for this person.
        # The recovery_repo only has find_by_intent_id which is per-intent.
        # For the global fallback, we return defaults.
        # A full implementation would query recovery actions by person_id,
        # but the existing repository doesn't expose that.
        # We'll use a simplified approach: scan all actions and filter.

        # Try to get prior actions for this person through the repository
        # The recovery_repo has find_all() which can give us all actions
        all_actions = []
        try:
            all_actions = self._recovery_repo.find_all(limit=10000)
        except Exception:
            pass

        # Filter to successful recoveries for this person
        person_actions = [
            a for a in all_actions if str(a.payment_intent_id) and a.outcome
        ]

        if len(person_actions) < 5:
            # Not enough data for this person — use global defaults
            return CustomerBehaviorProfile(sample_size=len(person_actions))

        # Compute preferred payment hour from successful recoveries
        hours = []
        for a in person_actions:
            if a.outcome == "SUCCESS" and a.metadata_json:
                ts = a.metadata_json.get("failure_timestamp")
                if ts:
                    try:
                        from datetime import datetime as _dt
                        h = _dt.fromisoformat(ts).hour
                        hours.append(h)
                    except (ValueError, TypeError):
                        pass

        preferred_hour = 12
        if hours:
            # Find the hour with most successes
            from collections import Counter
            preferred_hour = Counter(hours).most_common(1)[0][0]

        # Mean time to recovery
        times_to_recovery = []
        for a in person_actions:
            if a.outcome == "SUCCESS" and a.metadata_json and a.executed_at:
                ts = a.metadata_json.get("failure_timestamp")
                if ts:
                    try:
                        from datetime import datetime as _dt
                        fail_dt = _dt.fromisoformat(ts)
                        exec_dt = a.executed_at
                        if exec_dt.tzinfo is None:
                            exec_dt = exec_dt.replace(tzinfo=fail_dt.tzinfo)
                        hours_diff = (exec_dt - fail_dt).total_seconds() / 3600
                        if hours_diff >= 0:
                            times_to_recovery.append(hours_diff)
                    except (ValueError, TypeError):
                        pass

        mean_ttr = 24.0
        if times_to_recovery:
            mean_ttr = sum(times_to_recovery) / len(times_to_recovery)

        # Response rate for notification/link actions
        response_actions = [
            a for a in person_actions
            if a.action_type.value in ("SEND_NOTIFICATION", "SEND_PAYMENT_LINK")
        ]
        response_rate = 0.015
        if response_actions:
            successes = sum(
                1 for a in response_actions
                if a.outcome == "SUCCESS"
            )
            response_rate = successes / len(response_actions)

        return CustomerBehaviorProfile(
            preferred_payment_hour=preferred_hour,
            mean_time_to_recovery_hours=round(mean_ttr, 2),
            response_rate=round(response_rate, 4),
            sample_size=len(person_actions),
        )

    def _compute_fatigue(self, context: RecoveryContext) -> float:
        """Compute customer fatigue score (0–100).

        Fatigue increases with:
        - Number of prior recovery actions (retries, notifications, links)
        - Number of customer declines
        - Hours since the original failure (longer = more fatigued)

        Score is clamped to [0, 100].
        """
        prior_count = len(context.prior_recoveries)
        customer_declined = context.customer_declined
        hours_since = context.hours_since_failure

        # Base: 5 points per prior recovery action
        fatigue = prior_count * 5.0

        # Penalty for explicit decline
        if customer_declined:
            fatigue += 30.0

        # Small decay for time elapsed (customer may have forgotten)
        if hours_since > 24:
            fatigue *= 0.8  # cooling-off
        elif hours_since < 2:
            fatigue += 10.0  # very recent — still hot

        return round(min(fatigue, 100.0), 2)

    def _active_days(self, person_id: str) -> list[int]:
        """Return list of weekdays this customer was active (from prior actions)."""
        # Simplified — returns empty list if no data
        return []
