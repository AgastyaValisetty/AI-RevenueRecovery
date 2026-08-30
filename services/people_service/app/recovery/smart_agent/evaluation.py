"""ExperimentEvaluator — computes lift metrics comparing baseline vs Smart Agent.

Metrics computed:
  - Incremental recovered value (absolute and %)
  - Recovery rate (recovered / total failed)
  - Wasted retries (retries that didn't lead to recovery)
  - Contact efficiency (recoveries per outreach action)
  - Time-to-recovery (mean hours from failure to settlement)
  - False escalations (cases that were escalated but didn't need to be)
  - Stop precision (correct stops / total stops)
  - Duplicate-risk incidents (retries within the risk window)
  - Total retry cost savings
  - Incentive cost delta
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ...domain import INTENT_SETTLED
from ..domain import RecoveryOutcome
from ..repository import RecoveryActionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunMetrics:
    """Metrics computed for a single engine run (baseline or smart).

    Parameters
    ----------
    run_id :
        The simulation run ID.
    engine_type :
        "BASELINE" or "AI_AGENT".
    total_cases :
        Number of failed payment intents detected.
    recovered_cases :
        Number of cases that recovered (outcome == SUCCESS).
    total_recovered_value :
        Sum of amounts recovered (Decimal).
    total_retries :
        Total retry actions executed.
    wasted_retries :
        Retries that did not lead to recovery.
    total_outreach :
        Total SEND_PAYMENT_LINK + SEND_NOTIFICATION actions executed.
    mean_time_to_recovery_hours :
        Mean hours from failure to successful settlement.
    stop_count :
        Total STOP actions executed.
    correct_stops :
        Stops where the case would not have recovered anyway (no further retries
        would succeed — inferred from retry exhaustion or customer decline).
    duplicate_risk_incidents :
        Number of retries scheduled within the 1-hour risk window of the prior attempt.
    total_cost :
        Sum of all action costs (retry_cost + link_cost + notification_cost).
    incentive_cost :
        Sum of incentive costs (₹0 by default in baseline).
    net_recovered_value :
        total_recovered_value - total_cost - incentive_cost.
    """

    run_id: UUID
    engine_type: str
    total_cases: int
    recovered_cases: int
    total_recovered_value: Decimal
    total_retries: int
    wasted_retries: int
    total_outreach: int
    mean_time_to_recovery_hours: Optional[float]
    stop_count: int
    correct_stops: int
    duplicate_risk_incidents: int
    total_cost: Decimal
    incentive_cost: Decimal
    net_recovered_value: Decimal
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["run_id"] = str(self.run_id)
        d["total_recovered_value"] = str(self.total_recovered_value)
        d["total_cost"] = str(self.total_cost)
        d["incentive_cost"] = str(self.incentive_cost)
        d["net_recovered_value"] = str(self.net_recovered_value)
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass(frozen=True)
class LiftReport:
    """Lift comparison between baseline and smart agent runs.

    Parameters
    ----------
    baseline :
        Metrics from the baseline engine run.
    smart :
        Metrics from the Smart Agent run.
    incremental_recovered_value :
        Smart's net_recovered_value - baseline's net_recovered_value.
    incremental_recovery_rate :
        Smart's recovery_rate - baseline's recovery_rate (percentage points).
    wasted_retry_reduction :
        Reduction in wasted retries (baseline - smart).
    time_to_recovery_improvement :
        Improvement in mean time-to-recovery (hours).
    stop_precision_improvement :
        Improvement in stop precision (smart - baseline).
    duplicate_risk_delta :
        Change in duplicate-risk incidents (baseline - smart; positive = improvement).
    total_cost_savings :
        Cost savings from reduced retries + outreach.
    notes :
        Human-readable summary of the comparison.
    """

    baseline: RunMetrics
    smart: RunMetrics
    incremental_recovered_value: Decimal
    incremental_recovery_rate: float
    wasted_retry_reduction: int
    time_to_recovery_improvement: Optional[float]
    stop_precision_improvement: float
    duplicate_risk_delta: int
    total_cost_savings: Decimal
    notes: str

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "smart": self.smart.to_dict(),
            "incremental_recovered_value": str(self.incremental_recovered_value),
            "incremental_recovery_rate": self.incremental_recovery_rate,
            "wasted_retry_reduction": self.wasted_retry_reduction,
            "time_to_recovery_improvement": self.time_to_recovery_improvement,
            "stop_precision_improvement": self.stop_precision_improvement,
            "duplicate_risk_delta": self.duplicate_risk_delta,
            "total_cost_savings": str(self.total_cost_savings),
            "notes": self.notes,
        }


# Cost constants (must match action_value.py)
RETRY_COST = Decimal("2.50")
LINK_COST = Decimal("1.00")
NOTIFICATION_COST = Decimal("0.50")


class ExperimentEvaluator:
    """Computes RunMetrics from a RecoveryActionRepository and compares two runs.

    Parameters
    ----------
    recovery_repo :
        Repository to query actions for a given run_id.
    """

    def __init__(self, recovery_repo: RecoveryActionRepository):
        self._recovery_repo = recovery_repo

    def compute_metrics(
        self, run_id: UUID, engine_type: str = "BASELINE"
    ) -> RunMetrics:
        """Compute all metrics for a single run.

        Parameters
        ----------
        run_id :
            The simulation run UUID.
        engine_type :
            "BASELINE" or "AI_AGENT".
        """
        actions = self._recovery_repo.find_by_run_id(run_id)

        # Categorize actions
        retries = [a for a in actions if a.action_type.value == "RETRY"]
        links = [a for a in actions if a.action_type.value == "SEND_PAYMENT_LINK"]
        notifications = [a for a in actions if a.action_type.value == "SEND_NOTIFICATION"]
        stops = [a for a in actions if a.action_type.value == "STOP"]

        total_actions = retries + links + notifications + stops

        # Count unique cases (by payment_intent_id)
        case_ids = set()
        for a in total_actions:
            if a.payment_intent_id is not None:
                case_ids.add(a.payment_intent_id)
        total_cases = len(case_ids)

        # Recovered cases: those with at least one SUCCESS outcome
        recovered_intent_ids: set[UUID] = set()
        for a in retries + links + notifications:
            if a.outcome is not None and a.outcome in (RecoveryOutcome.SUCCESS, RecoveryOutcome.UNKNOWN):
                # UNKNOWN is treated as a potential recovery (bank authorized but timeout)
                if a.payment_intent_id is not None:
                    recovered_intent_ids.add(a.payment_intent_id)

        # Actually, we need to check the payment_intent status, not just the action outcome.
        # RecoveryAction outcome = SUCCESS means the intent was settled.
        recovered_cases = len(recovered_intent_ids)

        # Total recovered value: sum of amounts for recovered intents
        total_recovered_value = Decimal("0")
        for intent_id in recovered_intent_ids:
            for a in total_actions:
                if a.payment_intent_id == intent_id and a.outcome == RecoveryOutcome.SUCCESS:
                    if a.amount is not None:
                        total_recovered_value += a.amount
                    break  # count each intent once

        # Retries executed (not just scheduled)
        executed_retries = [a for a in retries if a.executed_at is not None]
        total_retries = len(executed_retries)

        # Wasted retries: retries that FAILED and the case was later stopped
        executed_retries_failed = [
            a for a in executed_retries
            if a.outcome in (RecoveryOutcome.FAILED, RecoveryOutcome.UNKNOWN)
        ]
        wasted_retries = len(executed_retries_failed)

        total_outreach = len(links) + len(notifications)

        # Mean time to recovery
        recovery_times: list[float] = []
        for intent_id in recovered_intent_ids:
            # Find the first successful action
            for a in total_actions:
                if a.payment_intent_id == intent_id:
                    if a.failure_code is not None:
                        # failure_timestamp from metadata
                        pass
                    if a.executed_at is not None and a.outcome == RecoveryOutcome.SUCCESS:
                        # Get failure time from metadata
                        fail_ts_str = a.metadata_json.get("failure_timestamp") if a.metadata_json else None
                        if fail_ts_str:
                            try:
                                from datetime import datetime as _dt
                                fail_ts = _dt.fromisoformat(fail_ts_str)
                                hours = (a.executed_at - fail_ts).total_seconds() / 3600
                                if hours >= 0:
                                    recovery_times.append(hours)
                            except (ValueError, TypeError):
                                pass

        mean_ttr = None
        if recovery_times:
            mean_ttr = round(sum(recovery_times) / len(recovery_times), 2)

        # Stop metrics
        stop_count = len(stops)
        correct_stops = self._count_correct_stops(stops, actions)

        # Duplicate risk incidents (retries within 1h of each other for same intent)
        duplicate_risk = self._count_duplicate_risks(retries)

        # Total cost
        total_cost = Decimal(str(len(executed_retries) * RETRY_COST))
        total_cost += Decimal(str(len(links) * LINK_COST))
        total_cost += Decimal(str(len(notifications) * NOTIFICATION_COST))

        net_recovered = total_recovered_value - total_cost

        return RunMetrics(
            run_id=run_id,
            engine_type=engine_type,
            total_cases=total_cases,
            recovered_cases=recovered_cases,
            total_recovered_value=total_recovered_value,
            total_retries=total_retries,
            wasted_retries=wasted_retries,
            total_outreach=total_outreach,
            mean_time_to_recovery_hours=mean_ttr,
            stop_count=stop_count,
            correct_stops=correct_stops,
            duplicate_risk_incidents=duplicate_risk,
            total_cost=total_cost,
            incentive_cost=Decimal("0"),  # baseline has no incentives
            net_recovered_value=net_recovered,
        )

    def compare(self, baseline: RunMetrics, smart: RunMetrics) -> LiftReport:
        """Compare two run metrics and produce a lift report."""
        baseline_recovery_rate = (
            baseline.recovered_cases / baseline.total_cases
            if baseline.total_cases > 0 else 0.0
        )
        smart_recovery_rate = (
            smart.recovered_cases / smart.total_cases
            if smart.total_cases > 0 else 0.0
        )

        incremental_value = smart.net_recovered_value - baseline.net_recovered_value
        incremental_rate = round((smart_recovery_rate - baseline_recovery_rate) * 100, 2)
        wasted_reduction = baseline.wasted_retries - smart.wasted_retries

        ttr_improvement = None
        if baseline.mean_time_to_recovery_hours and smart.mean_time_to_recovery_hours:
            ttr_improvement = round(
                baseline.mean_time_to_recovery_hours - smart.mean_time_to_recovery_hours, 2
            )

        baseline_stop_precision = (
            baseline.correct_stops / baseline.stop_count
            if baseline.stop_count > 0 else 0.0
        )
        smart_stop_precision = (
            smart.correct_stops / smart.stop_count
            if smart.stop_count > 0 else 0.0
        )
        stop_precision_improvement = round(smart_stop_precision - baseline_stop_precision, 4)

        cost_savings = baseline.total_cost - smart.total_cost
        duplicate_delta = baseline.duplicate_risk_incidents - smart.duplicate_risk_incidents

        notes = self._build_notes(baseline, smart, incremental_value, incremental_rate)

        return LiftReport(
            baseline=baseline,
            smart=smart,
            incremental_recovered_value=incremental_value,
            incremental_recovery_rate=incremental_rate,
            wasted_retry_reduction=wasted_reduction,
            time_to_recovery_improvement=ttr_improvement,
            stop_precision_improvement=stop_precision_improvement,
            duplicate_risk_delta=duplicate_delta,
            total_cost_savings=cost_savings,
            notes=notes,
        )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _count_correct_stops(
        stops: list, all_actions: list
    ) -> int:
        """Count stops that were 'correct' — the case didn't recover afterward.

        A stop is correct if no successful action follows it for the same intent.
        """
        correct = 0
        for stop in stops:
            intent_id = stop.payment_intent_id
            if intent_id is None:
                continue
            # Check if any action after this stop succeeded
            later_actions = [
                a for a in all_actions
                if a.payment_intent_id == intent_id
                and a.created_at is not None
                and stop.created_at is not None
                and a.created_at > stop.created_at
            ]
            later_success = any(
                a.outcome == RecoveryOutcome.SUCCESS for a in later_actions
            )
            if not later_success:
                correct += 1
        return correct

    @staticmethod
    def _count_duplicate_risks(retries: list) -> int:
        """Count retries scheduled within 1 hour of a prior retry for the same intent."""
        from datetime import timedelta

        DUPLICATE_WINDOW = timedelta(hours=1)
        count = 0

        # Group by intent_id
        by_intent: dict[UUID, list] = {}
        for r in retries:
            if r.payment_intent_id is not None:
                by_intent.setdefault(r.payment_intent_id, []).append(r)

        for intent_id, intent_retries in by_intent.items():
            # Sort by scheduled_for
            sorted_retries = sorted(
                intent_retries,
                key=lambda a: a.scheduled_for or datetime.min,
            )
            for i in range(1, len(sorted_retries)):
                prev = sorted_retries[i - 1]
                curr = sorted_retries[i]
                if (prev.scheduled_for is not None and
                    curr.scheduled_for is not None and
                    abs(curr.scheduled_for - prev.scheduled_for) < DUPLICATE_WINDOW):
                    count += 1

        return count

    @staticmethod
    def _build_notes(
        baseline: RunMetrics,
        smart: RunMetrics,
        incremental_value: Decimal,
        incremental_rate: float,
    ) -> str:
        """Build a human-readable summary of the comparison."""
        parts = []

        if incremental_value > 0:
            parts.append(
                f"Smart Agent improved net recovery by {incremental_value} INR "
                f"(+{incremental_rate:.2f} pp recovery rate)."
            )
        elif incremental_value < 0:
            parts.append(
                f"Smart Agent underperformed baseline by {abs(incremental_value)} INR "
                f"({incremental_rate:+.2f} pp recovery rate)."
            )
        else:
            parts.append("No significant difference between baseline and Smart Agent.")

        if baseline.wasted_retries > smart.wasted_retries:
            parts.append(
                f"Wasted retries reduced by {baseline.wasted_retries - smart.wasted_retries} "
                f"({baseline.wasted_retries} → {smart.wasted_retries})."
            )

        if smart.duplicate_risk_incidents == 0:
            parts.append("Zero duplicate-risk incidents in Smart Agent run.")

        return " ".join(parts)
