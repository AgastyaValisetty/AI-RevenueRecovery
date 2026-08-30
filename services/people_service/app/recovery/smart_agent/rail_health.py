"""RailHealthMonitor — correlates bank/route degradation across payments.

The "rail" is the payment network (bank + method + route).  When a bank
transitions to DEGRADED or OUTAGE, recovery actions on that rail become
unreliable: a RETRY now is likely to fail and may risk duplicate charges
if the upstream system later catches up.

Design goals
------------
* **Deterministic given observable inputs.**  The monitor aggregates failure
  outcomes from the shared DB (RecoveryActionRow and PaymentIntent rows).
  It does NOT read hidden simulator state.
* **Cache-friendly polling.**  In live mode it calls ``bank_service:/api/status``
  via HTTP.  In simulation/replay mode the bank state is passed through the
  ``RecoveryContext.bank_state`` field by the context builder, so no HTTP call
  is needed.
* **Do-not-retry windows.**  While a rail is degraded, the monitor can advise
  skipping retries on that method for a cool-off period.

The bank_service ``/api/status`` endpoint returns:
    bank.current_state   "NORMAL" | "PEAK" | "DEGRADED" | "OUTAGE"
    bank.success_rate_1min
    bank.failure_rate_1min
    bank.transactions_last_minute
    bank.failures_last_minute
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from urllib.parse import urljoin

import httpx

from ...config import Settings
from ...database import Database
from ...failure_model import STATE_MULTIPLIERS

logger = logging.getLogger(__name__)

# State thresholds for determining "rail health"
HEALTHY_STATES = {"NORMAL", "PEAK"}
DEGRADED_STATES = {"DEGRADED", "OUTAGE"}

# Cool-off period (hours) to wait after a rail exits degradation before resuming retries
DEGRADATION_COOLDOWN_HOURS = 2

# Minimum failure count to trigger a health check
MIN_FAILURE_SAMPLE_SIZE = 5


@dataclass(frozen=True)
class RailHealth:
    """Aggregated health signal for a payment rail (method + bank).

    Parameters
    ----------
    method :
        Payment method (UPI, CARD, NETBANKING).
    bank_state :
        Current bank state string from bank_service.
    rail_health_score :
        0.0 (outage) → 1.0 (healthy).
    is_degraded :
        True if bank_state is DEGRADED or OUTAGE.
    failure_rate_window :
        Failure rate observed in the recent window (0–1).
    sample_size_window :
        Number of attempts in the recent window.
    do_not_retry_until :
        If set, the rail is in a cool-off window and retries should be skipped.
    last_updated :
        When this health snapshot was computed.
    """

    method: str
    bank_state: str
    rail_health_score: float
    is_degraded: bool
    failure_rate_window: float
    sample_size_window: int
    do_not_retry_until: Optional[datetime] = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RailHealthMonitor:
    """Monitors bank/route degradation and advises on retry eligibility.

    Parameters
    ----------
    db :
        Database for querying historical failure patterns.
    settings :
        Application settings (for bank_service URL in live mode).
    """

    def __init__(self, db: Database, settings: Optional[Settings] = None):
        self._db = db
        self._settings = settings
        # In-memory cache of recent bank states for simulation/replay
        self._cached_state: dict[str, str] = {}
        self._cached_health: dict[str, RailHealth] = {}

    def get_rail_health(
        self,
        method: str,
        bank_state: Optional[str] = None,
        current_time: Optional[datetime] = None,
        *,
        force_refresh: bool = False,
    ) -> RailHealth:
        """Compute the health signal for a given payment method + bank state.

        Parameters
        ----------
        method :
            Payment method (UPI, CARD, NETBANKING).
        bank_state :
            If provided (from RecoveryContext), uses this directly — no HTTP call.
            If None and settings has a bank_url, fetches from bank_service.
        current_time :
            Simulation clock time (for deterministic windowing).
        force_refresh :
            Bypass cache and re-fetch / recompute.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        cache_key = f"{method}:{bank_state or 'unknown'}"

        if not force_refresh and cache_key in self._cached_health:
            cached = self._cached_health[cache_key]
            # Invalidate cache after 5 minutes
            if current_time - cached.last_updated < timedelta(minutes=5):
                return cached

        # Determine bank state — prefer passed-in, fall back to live polling
        state = bank_state
        if state is None:
            state = self._poll_bank_state(method)

        # Compute failure rate from recent history (last 10 minutes of transactions)
        failure_rate, sample_size = self._compute_recent_failure_rate(
            method, state, current_time
        )

        # Compute health score
        is_degraded = state in DEGRADED_STATES
        rail_health_score = self._compute_health_score(state, failure_rate, sample_size)

        # Do-not-retry window
        do_not_retry_until = self._compute_dnt_window(state, current_time)

        health = RailHealth(
            method=method,
            bank_state=state,
            rail_health_score=rail_health_score,
            is_degraded=is_degraded,
            failure_rate_window=failure_rate,
            sample_size_window=sample_size,
            do_not_retry_until=do_not_retry_until,
            last_updated=current_time,
        )

        self._cached_health[cache_key] = health
        return health

    def should_skip_retry(
        self,
        method: str,
        bank_state: Optional[str] = None,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """Quick check: should we skip retrying on this rail right now?

        Returns True if the rail is degraded (OUTAGE) or in a cool-off window.
        """
        health = self.get_rail_health(method, bank_state, current_time)
        if health.bank_state == "OUTAGE":
            return True
        if health.do_not_retry_until is not None:
            now = current_time or datetime.now(timezone.utc)
            if now < health.do_not_retry_until:
                return True
        return False

    def get_degraded_rails(
        self, current_time: Optional[datetime] = None
    ) -> list[str]:
        """Return list of payment methods currently in a degraded state.

        Used by the planner to avoid routing retries through degraded rails.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        degraded: list[str] = []
        for method in ("UPI", "CARD", "NETBANKING"):
            health = self.get_rail_health(method, None, current_time)
            if health.is_degraded:
                degraded.append(method)
        return degraded

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _poll_bank_state(self, method: str) -> str:
        """Fetch current bank state from bank_service (live mode only).

        Falls back to cached state if the bank service is unreachable.
        """
        if self._settings is None or not self._settings.bank_url:
            return self._cached_state.get(method, "NORMAL")

        try:
            url = urljoin(self._settings.bank_url, "/api/status")
            with httpx.Client(timeout=self._settings.http_timeout_seconds) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
                bank = data.get("bank", {})
                state = bank.get("current_state", "NORMAL")
                self._cached_state[method] = state
                return state
        except Exception as exc:
            logger.warning(
                "Failed to poll bank_service for %s: %s. Using cached state.",
                method,
                exc,
            )
            return self._cached_state.get(method, "NORMAL")

    def _compute_recent_failure_rate(
        self, method: str, bank_state: str, current_time: datetime
    ) -> tuple[float, int]:
        """Compute failure rate for this method in the recent window.

        Queries the recovery_actions table for payment intents that used
        this method and were processed within the last 10 minutes of
        simulation time.
        """
        from sqlalchemy import select, func
        from ...schema import PaymentIntentRow, RecoveryActionRow

        window_start = current_time - timedelta(minutes=10)

        with self._db.session() as session:
            # Count attempts (recovery actions) for this method in the window
            total = session.scalar(
                select(func.count())
                .select_from(RecoveryActionRow)
                .where(
                    RecoveryActionRow.action_type == "RETRY",
                    RecoveryActionRow.metadata_json.op("->>")(
                        "payment_method"
                    ) == method,
                    RecoveryActionRow.scheduled_for >= window_start,
                )
            ) or 0

            # Count failures (FAILED outcome)
            failures = session.scalar(
                select(func.count())
                .select_from(RecoveryActionRow)
                .where(
                    RecoveryActionRow.action_type == "RETRY",
                    RecoveryActionRow.metadata_json.op("->>")(
                        "payment_method"
                    ) == method,
                    RecoveryActionRow.scheduled_for >= window_start,
                    RecoveryActionRow.outcome.in_(
                        ("FAILED", "UNKNOWN")
                    ),
                )
            ) or 0

        if total == 0:
            return (0.0, 0)

        return (failures / total if total > 0 else 0.0, total)

    def _compute_health_score(
        self, bank_state: str, failure_rate: float, sample_size: int
    ) -> float:
        """Compute a 0–1 health score for the rail.

        - Bank state contributes the largest factor (via state multiplier).
        - Recent failure rate adjusts further (when we have enough samples).
        - Small samples default to state-based score.
        """
        multiplier = STATE_MULTIPLIERS.get(bank_state, 1.0)

        # Base score from state: NORMAL=1.0, PEAK=0.9, DEGRADED=0.4, OUTAGE=0.05
        state_scores = {
            "NORMAL": 1.0,
            "PEAK": 0.9,
            "DEGRADED": 0.4,
            "OUTAGE": 0.05,
        }
        base = state_scores.get(bank_state, 0.9)

        # Adjust by observed failure rate if we have enough samples
        if sample_size >= MIN_FAILURE_SAMPLE_SIZE:
            # Higher failure rate → lower score
            rate_adjustment = 1.0 - (failure_rate * 2.0)  # weight failure rate
            base = base * rate_adjustment * 0.3 + base * 0.7  # blend

        return max(0.0, min(1.0, round(base, 4)))

    def _compute_dnt_window(
        self, bank_state: str, current_time: datetime
    ) -> Optional[datetime]:
        """Compute the do-not-retry window if the rail is currently degraded.

        If the bank is DEGRADED or OUTAGE, we advise a cool-off of
        ``DEGRADATION_COOLDOWN_HOURS`` from now.
        """
        if bank_state in DEGRADED_STATES:
            return current_time + timedelta(hours=DEGRADATION_COOLDOWN_HOURS)
        return None
