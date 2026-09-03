"""RecoveryMetrics — aggregates recovery outcomes into business metrics.

All metrics are derived from persisted RecoveryActionRow records.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func, case, cast, Numeric, text

from ..database import Database
from ..schema import RecoveryActionRow
from .domain import RecoveryActionType, RecoveryOutcome

logger = logging.getLogger(__name__)


@dataclass
class RecoveryMetrics:
    """Aggregated recovery metrics for a run or overall."""

    total_recovery_actions: int = 0
    retry_actions: int = 0
    stop_actions: int = 0
    link_actions: int = 0
    notification_actions: int = 0

    # Outcome counts
    successful_recoveries: int = 0
    failed_recoveries: int = 0
    stopped_recoveries: int = 0
    unknown_recoveries: int = 0

    # Financial
    total_recovered_gmv: Decimal = Decimal("0")
    total_recovery_cost: Decimal = Decimal("0")
    expected_recovery_gmv: Decimal = Decimal("0")

    # Retry behaviour
    total_retries_attempted: int = 0
    retries_successful: int = 0
    retries_failed: int = 0
    average_retries_per_intent: float = 0.0

    # Timing
    average_hours_to_recovery: Optional[float] = None
    min_hours_to_recovery: Optional[float] = None
    max_hours_to_recovery: Optional[float] = None

    # Breakdown dimensions
    by_failure_code: dict = field(default_factory=dict)
    by_payment_method: dict = field(default_factory=dict)
    by_merchant: dict = field(default_factory=dict)
    by_day: dict = field(default_factory=dict)

    # Recovery rates
    recovery_rate: float = 0.0
    retry_success_rate: float = 0.0

    # Failed-payment universe: distinct payment intents the engine acted on.
    # Used as the denominator for the "recovered / total failed payments" rate.
    total_failed_payments: int = 0
    failed_payment_recovery_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_recovery_actions": self.total_recovery_actions,
            "retry_actions": self.retry_actions,
            "stop_actions": self.stop_actions,
            "link_actions": self.link_actions,
            "notification_actions": self.notification_actions,
            "successful_recoveries": self.successful_recoveries,
            "failed_recoveries": self.failed_recoveries,
            "stopped_recoveries": self.stopped_recoveries,
            "unknown_recoveries": self.unknown_recoveries,
            "total_recovered_gmv": str(self.total_recovered_gmv),
            "total_recovery_cost": str(self.total_recovery_cost),
            "expected_recovery_gmv": str(self.expected_recovery_gmv),
            "total_retries_attempted": self.total_retries_attempted,
            "retries_successful": self.retries_successful,
            "retries_failed": self.retries_failed,
            "average_retries_per_intent": round(self.average_retries_per_intent, 2),
            "average_hours_to_recovery": (
                round(self.average_hours_to_recovery, 2)
                if self.average_hours_to_recovery is not None
                else None
            ),
            "min_hours_to_recovery": (
                round(self.min_hours_to_recovery, 2)
                if self.min_hours_to_recovery is not None
                else None
            ),
            "max_hours_to_recovery": (
                round(self.max_hours_to_recovery, 2)
                if self.max_hours_to_recovery is not None
                else None
            ),
            "by_failure_code": self.by_failure_code,
            "by_payment_method": self.by_payment_method,
            "by_merchant": self.by_merchant,
            "by_day": self.by_day,
            "recovery_rate": round(self.recovery_rate, 4),
            "retry_success_rate": round(self.retry_success_rate, 4),
            "total_failed_payments": self.total_failed_payments,
            "failed_payment_recovery_rate": round(self.failed_payment_recovery_rate, 4),
        }


class RecoveryMetricsCollector:
    """Collects and aggregates recovery metrics from the database."""

    def __init__(self, db: Database):
        self._db = db

    def collect(
        self,
        run_id: Optional[UUID] = None,
        engine_type: Optional[str] = None,
    ) -> RecoveryMetrics:
        """Aggregate recovery metrics, optionally filtered to a single run or engine type."""
        from ..schema import SimulationRunRow

        with self._db.session() as session:
            stmt = select(RecoveryActionRow)
            if run_id is not None:
                stmt = stmt.where(RecoveryActionRow.run_id == run_id)
            if engine_type is not None:
                # Get run_ids whose config_snapshot has the given engine_type
                result = session.execute(
                    text("SELECT run_id FROM simulation_runs WHERE config_snapshot->>'engine_type' = :et")
                    .params(et=engine_type)
                )
                eligible_run_ids = result.scalars().all()
                if eligible_run_ids:
                    stmt = stmt.where(RecoveryActionRow.run_id.in_(eligible_run_ids))
                else:
                    # No runs of this engine_type exist — return empty
                    stmt = stmt.where(RecoveryActionRow.run_id == None)

            rows = session.scalars(stmt).all()

            metrics = RecoveryMetrics()
            metrics.total_recovery_actions = len(rows)

            # Count by action type
            for row in rows:
                if row.action_type == RecoveryActionType.RETRY.value:
                    metrics.retry_actions += 1
                elif row.action_type == RecoveryActionType.STOP.value:
                    metrics.stop_actions += 1
                elif row.action_type == RecoveryActionType.SEND_PAYMENT_LINK.value:
                    metrics.link_actions += 1
                elif row.action_type == RecoveryActionType.SEND_NOTIFICATION.value:
                    metrics.notification_actions += 1

            # Outcome counts
            outcome_counts = {}
            for row in rows:
                outcome = row.outcome or RecoveryOutcome.UNKNOWN.value
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            metrics.successful_recoveries = outcome_counts.get(RecoveryOutcome.SUCCESS.value, 0)
            metrics.failed_recoveries = outcome_counts.get(RecoveryOutcome.FAILED.value, 0)
            metrics.stopped_recoveries = outcome_counts.get(RecoveryOutcome.STOPPED.value, 0)
            metrics.unknown_recoveries = outcome_counts.get(RecoveryOutcome.UNKNOWN.value, 0)

            # Financial: sum amounts for SUCCESS retries
            success_amounts = [
                r.amount for r in rows
                if r.outcome == RecoveryOutcome.SUCCESS.value and r.amount is not None
            ]
            metrics.total_recovered_gmv = sum(success_amounts, Decimal("0")) if success_amounts else Decimal("0")

            cost_amounts = [
                r.cost for r in rows if r.cost is not None
            ]
            metrics.total_recovery_cost = sum(cost_amounts, Decimal("0")) if cost_amounts else Decimal("0")

            expected_amounts = [
                r.expected_recovery for r in rows if r.expected_recovery is not None
            ]
            metrics.expected_recovery_gmv = sum(expected_amounts, Decimal("0")) if expected_amounts else Decimal("0")

            # Retry behaviour
            retry_rows = [r for r in rows if r.action_type == RecoveryActionType.RETRY.value]
            metrics.total_retries_attempted = len(retry_rows)
            metrics.retries_successful = sum(
                1 for r in retry_rows if r.outcome == RecoveryOutcome.SUCCESS.value
            )
            metrics.retries_failed = sum(
                1 for r in retry_rows if r.outcome in (RecoveryOutcome.FAILED.value, RecoveryOutcome.UNKNOWN.value)
            )

            # Average retries per intent
            intent_ids = set(r.payment_intent_id for r in retry_rows if r.payment_intent_id)
            if intent_ids:
                metrics.average_retries_per_intent = metrics.total_retries_attempted / len(intent_ids)

            # Total failed payments: distinct intents that the engine acted on.
            # This is the denominator of the "recovered / total failed payments"
            # rate shown on the dashboard.  Computed from all actions, not just
            # retries, so a case that only got a STOP is still counted as a
            # failed payment the system saw.
            all_intent_ids = set(
                r.payment_intent_id for r in rows if r.payment_intent_id is not None
            )
            metrics.total_failed_payments = len(all_intent_ids)

            # Timing: hours from failure to successful recovery
            from datetime import timedelta
            recovery_times = []
            for row in retry_rows:
                if (
                    row.outcome == RecoveryOutcome.SUCCESS.value
                    and row.metadata_json
                    and row.metadata_json.get("failure_timestamp")
                    and row.executed_at
                    and row.scheduled_for
                ):
                    try:
                        from datetime import datetime as dt
                        fail_ts = dt.fromisoformat(row.metadata_json["failure_timestamp"])
                        hours = (row.executed_at - fail_ts).total_seconds() / 3600
                        if hours >= 0:
                            recovery_times.append(hours)
                    except (ValueError, TypeError):
                        pass

            if recovery_times:
                metrics.average_hours_to_recovery = sum(recovery_times) / len(recovery_times)
                metrics.min_hours_to_recovery = min(recovery_times)
                metrics.max_hours_to_recovery = max(recovery_times)

            # Breakdowns
            metrics.by_failure_code = self._breakdown(
                rows, lambda r: r.failure_code or "unknown"
            )
            metrics.by_payment_method = self._breakdown(
                rows, lambda r: r.payment_method or "unknown"
            )
            metrics.by_merchant = self._breakdown(
                rows, lambda r: (r.metadata_json or {}).get("merchant_id", "unknown")
            )

            # Recovery rate: successful retries / total retries attempted
            if metrics.total_retries_attempted > 0:
                metrics.recovery_rate = (
                    metrics.retries_successful / metrics.total_retries_attempted
                )
                metrics.retry_success_rate = metrics.recovery_rate

            # Failed-payment recovery rate: successful recoveries / total failed
            # payments (denominator is the universe of failed intents, not the
            # number of retry attempts).  This is the headline rate shown on
            # the dashboard.
            if metrics.total_failed_payments > 0:
                metrics.failed_payment_recovery_rate = (
                    metrics.successful_recoveries / metrics.total_failed_payments
                )

            return metrics

    def _breakdown(
        self,
        rows: list,
        key_fn,
    ) -> dict:
        """Return {key: count} breakdown of rows by the given key function."""
        result: dict = {}
        for row in rows:
            key = key_fn(row) or "unknown"
            result[key] = result.get(key, 0) + 1
        return result
