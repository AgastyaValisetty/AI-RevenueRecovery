"""ExperimentRunner — paired baseline vs Smart Agent comparison.

Runs a paired experiment on cloned DB state:

  1. Build orchestrator with BaselineRecoveryEngine, seed simulation, run hours.
  2. Compute baseline metrics from the recovery run.
  3. Reset DB state (drop + recreate schema).
  4. Build orchestrator with SmartRecoveryEngine, seed simulation, run hours.
  5. Compute smart metrics from the recovery run.
  6. Compare metrics and output JSON + human-readable report.

Both runs use the same seed so the simulation population + payment failures
are identical, ensuring a fair comparison.  The only variable is the
recovery decision engine injected into the orchestrator.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from ...config import LLMConfig, Settings
from ...container import build_orchestrator
from ...database import Database
from ...sim_config import SimConfig
from .. import BaselineRecoveryEngine, RecoveryActionType
from ..repository import RecoveryActionRepository
from .agent import SmartRecoveryEngine
from .evaluation import ExperimentEvaluator, LiftReport, RunMetrics

logger = logging.getLogger(__name__)

# Path to the experiment result files
EXPERIMENT_OUTPUT_DIR = Path(os.getenv("EXPERIMENT_OUTPUT_DIR", "./experiments"))


@dataclass
class ExperimentConfig:
    """Configuration for an experiment run.

    Parameters
    ----------
    people_count :
        Number of people to simulate (population size).
    hours :
        Number of simulation hours to run.
    seed :
        Root seed for deterministic reproducibility.
    """

    people_count: int
    hours: int
    seed: int


class ExperimentRunner:
    """Runs paired experiments comparing baseline vs Smart Agent.

    Both runs share the same database and seed.  After the baseline run
    completes, the schema is dropped and recreated so the Smart Agent run
    starts from a clean state with an identical population (same seed).

    Parameters
    ----------
    db :
        Database connection.  Must have schema already created.
    settings :
        Application settings (contains llm config, lazerpay_url, etc.).
    config :
        Simulation configuration (optional; defaults to SimConfig.defaults()).
    """

    def __init__(
        self,
        db: Database,
        settings: Settings,
        config: Optional[SimConfig] = None,
    ):
        self._db = db
        self._settings = settings
        self._config = config or SimConfig.defaults()

    def run(
        self,
        people_count: int = 100,
        hours: int = 72,
        seed: int = 42,
    ) -> LiftReport:
        """Run a paired experiment and return the lift report.

        Strategy:
          1. Run a full simulation with the BaselineRecoveryEngine.
          2. Compute baseline metrics.
          3. Reset the DB schema.
          4. Run a full simulation with the SmartRecoveryEngine (same seed).
          5. Compute smart metrics.
          6. Compare and return the lift report.
        """
        logger.info(
            "Starting experiment: people=%d, hours=%d, seed=%d",
            people_count, hours, seed,
        )

        # --- Phase 1: Run baseline simulation + recovery ---
        baseline_run_id = self._run_simulation(
            engine=BaselineRecoveryEngine(),
            people_count=people_count,
            hours=hours,
            seed=seed,
        )
        logger.info("Baseline run complete. Recovery run ID: %s", baseline_run_id)

        # --- Phase 2: Compute baseline metrics ---
        evaluator = ExperimentEvaluator(RecoveryActionRepository(self._db))
        baseline_metrics = evaluator.compute_metrics(baseline_run_id, "BASELINE")
        logger.info(
            "Baseline metrics: %d cases, %d recovered, %.2f INR net",
            baseline_metrics.total_cases,
            baseline_metrics.recovered_cases,
            float(baseline_metrics.net_recovered_value),
        )

        # --- Phase 3: Reset DB state ---
        self._reset_db()

        # --- Phase 4: Run Smart Agent simulation + recovery ---
        smart_engine = self._build_smart_engine(RecoveryActionRepository(self._db))
        smart_run_id = self._run_simulation(
            engine=smart_engine,
            people_count=people_count,
            hours=hours,
            seed=seed,
        )
        logger.info("Smart Agent run complete. Recovery run ID: %s", smart_run_id)

        # --- Phase 5: Compute smart metrics ---
        smart_metrics = evaluator.compute_metrics(smart_run_id, "AI_AGENT")
        logger.info(
            "Smart metrics: %d cases, %d recovered, %.2f INR net",
            smart_metrics.total_cases,
            smart_metrics.recovered_cases,
            float(smart_metrics.net_recovered_value),
        )

        # --- Phase 6: Compare ---
        report = evaluator.compare(baseline_metrics, smart_metrics)

        # --- Phase 7: Save output ---
        self._save_report(report, baseline_run_id)

        return report

    # ------------------------------------------------------------------ #
    # Internal phases
    # ------------------------------------------------------------------ #

    def _run_simulation(
        self,
        engine,
        people_count: int,
        hours: int,
        seed: int,
    ) -> UUID:
        """Build an orchestrator with the given engine, run the simulation,
        and return the recovery run_id for metrics collection.
        """
        orch = build_orchestrator(
            db=self._db,
            seed=seed,
            settings=self._settings,
            enable_recovery=True,
            recovery_engine=engine,
            config=self._config,
        )

        # initialize() creates both a simulation run and a recovery run,
        # storing the recovery run_id as orch._recovery_run_id.
        sim_run_id = orch.initialize(people_count, seed=seed)
        orch.run_hours(hours)

        recovery_run_id = orch._recovery_run_id
        if recovery_run_id is None:
            logger.error("Orchestrator did not create a recovery run_id")
            raise RuntimeError("Failed to obtain recovery run_id from orchestrator")

        return recovery_run_id

    def _build_smart_engine(
        self, recovery_repo: RecoveryActionRepository
    ) -> SmartRecoveryEngine:
        """Build a fully-wired SmartRecoveryEngine with all dependencies.

        The SmartRecoveryEngine constructor accepts all sub-components as
        optional keyword arguments.  We explicitly construct the ones that
        need database access or LLM config; the rest are built from defaults.
        """
        from .llm_gateway import LLMGateway
        from .memory import RecoveryMemoryRepository
        from .promise_tracker import PromiseTracker
        from .audit import AuditEventWriter

        llm_config = LLMConfig.from_env()
        llm_gateway = LLMGateway(llm_config, db=self._db)

        memory_repo = RecoveryMemoryRepository(self._db, recovery_repo)
        promise_tracker = PromiseTracker(self._db)
        auditor = AuditEventWriter(self._db)

        engine = SmartRecoveryEngine(
            recovery_repo=recovery_repo,
            settings=self._settings,
            llm_gateway=llm_gateway,
            memory_repo=memory_repo,
            promise_tracker=promise_tracker,
            auditor=auditor,
            max_retries=10,
            min_enpv=Decimal("0.00"),
        )
        return engine

    def _reset_db(self) -> None:
        """Drop and recreate the database schema for a clean second run."""
        logger.info("Resetting database schema for second run")
        self._db.drop_schema()
        self._db.create_schema()

    def _save_report(self, report: LiftReport, seed_run_id: UUID) -> None:
        """Save the experiment report to disk as JSON + human-readable text."""
        EXPERIMENT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_path = EXPERIMENT_OUTPUT_DIR / f"experiment_{seed_run_id}_{timestamp}.json"
        text_path = EXPERIMENT_OUTPUT_DIR / f"experiment_{seed_run_id}_{timestamp}.txt"

        # Save JSON report
        with open(json_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)

        # Save human-readable report
        report_text = self._format_text_report(report)
        with open(text_path, "w") as f:
            f.write(report_text)

        logger.info("Experiment report saved to %s and %s", json_path, text_path)

    def _format_text_report(self, report: LiftReport) -> str:
        """Format the lift report as a human-readable text summary."""
        b = report.baseline
        s = report.smart

        lines = []
        lines.append("=" * 72)
        lines.append("SARA Experiment Report — Baseline vs Smart Agent")
        lines.append("=" * 72)
        lines.append("")

        def _fmt_metrics(label: str, m: RunMetrics) -> None:
            lines.append(label)
            lines.append(f"  Cases:              {m.total_cases}")
            lines.append(f"  Recovered:          {m.recovered_cases}")
            lines.append(f"  Recovery value:     {m.total_recovered_value} INR")
            lines.append(f"  Recovery rate:      {m.recovered_cases / max(m.total_cases, 1) * 100:.2f}%")
            lines.append(f"  Retries:            {m.total_retries}")
            lines.append(f"  Wasted retries:     {m.wasted_retries}")
            lines.append(f"  Outreach actions:   {m.total_outreach}")
            ttr = m.mean_time_to_recovery_hours
            lines.append(f"  Mean TTR:           {ttr or 'N/A'} h")
            lines.append(f"  Stops:              {m.stop_count}")
            lines.append(f"  Correct stops:      {m.correct_stops}")
            lines.append(f"  Duplicate risks:    {m.duplicate_risk_incidents}")
            lines.append(f"  Total cost:         {m.total_cost} INR")
            lines.append(f"  Incentive cost:     {m.incentive_cost} INR")
            lines.append(f"  Net recovered:      {m.net_recovered_value} INR")
            lines.append("")

        _fmt_metrics("BASELINE RUN", b)
        _fmt_metrics("SMART AGENT RUN", s)

        lines.append("LIFT")
        lines.append(f"  Increment:          {report.incremental_recovered_value} INR")
        lines.append(f"  Rate lift:          {report.incremental_recovery_rate:+.2f} pp")
        lines.append(f"  Wasted retry reduction: {report.wasted_retry_reduction}")
        ttr_imp = report.time_to_recovery_improvement
        lines.append(f"  TTR improvement:    {ttr_imp or 'N/A'} h")
        lines.append(f"  Stop precision lift: {report.stop_precision_improvement:+.4f}")
        lines.append(f"  Cost savings:       {report.total_cost_savings} INR")
        lines.append(f"  Duplicate risk delta: {report.duplicate_risk_delta}")
        lines.append("")
        lines.append("Notes:")
        lines.append(f"  {report.notes}")
        lines.append("")
        lines.append("=" * 72)

        return "\n".join(lines)
