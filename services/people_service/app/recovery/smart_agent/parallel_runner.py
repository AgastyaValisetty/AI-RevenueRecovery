"""ParallelExperimentRunner — runs baseline and Smart Agent simultaneously.

Spawns two orchestrators on separate PostgreSQL schemas (schema-scoped databases)
sharing the same seed → identical population + payment failures.  Both engines
run in parallel threads for the same time window, then metrics are collected
from each schema and compared.

Usage::

    runner = ParallelExperimentRunner(db, settings)
    report = runner.run(people_count=200, hours=72, seed=42)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import UUID

from ...config import LLMConfig, Settings
from ...container import build_orchestrator
from ...database import Database, SchemaScopedDatabase
from ...sim_config import SimConfig
from sqlalchemy import text
from .. import BaselineRecoveryEngine, RecoveryEngineType
from ..domain import RecoveryDecision
from ..repository import RecoveryActionRepository
from .agent import SmartRecoveryEngine
from .evaluation import ExperimentEvaluator, LiftReport, RunMetrics


class AuditedBaselineRecoveryEngine(BaselineRecoveryEngine):
    """Baseline control with the same immutable decision trace as SARA."""

    def __init__(self, db):
        self._baseline_auditor = None
        from .audit import AuditEventWriter
        from ...schema import BaselineAuditEventRow
        self._baseline_auditor = AuditEventWriter(db, row_model=BaselineAuditEventRow)

    def decide(self, context) -> RecoveryDecision:
        decision = super().decide(context)
        from .audit import AuditEvent, hash_input_snapshot
        snapshot = {
            "intent_id": context.intent_id,
            "amount": str(context.intent_amount),
            "failure_code": context.failure_code,
            "bank_state": context.bank_state,
            "retry_count": context.retry_count,
            "customer_declined": context.customer_declined,
            "simulation_timestamp": context.current_simulation_time.isoformat(),
        }
        self._baseline_auditor.write(AuditEvent.build(
            case_id=UUID(context.intent_id),
            actor="baseline",
            event_type="decision",
            agent_version="baseline-1.0.0",
            policy_version="baseline-policy-1.0.0",
            decision={
                "action_type": decision.action.value,
                "scheduled_for": decision.scheduled_for.isoformat() if decision.scheduled_for else None,
                "reason": decision.reason,
                "retry_number": decision.retry_number,
            },
            evidence_refs={"features": ["failure_code", "bank_state", "retry_count"]},
            policy_checks={"baseline_rules": {"passed": True, "detail": "fixed retry policy"}},
            outcome=decision.action.value,
            idempotency_key=hash_input_snapshot(snapshot)[:32],
            input_snapshot=snapshot,
        ))
        return decision

logger = logging.getLogger(__name__)

EXPERIMENT_OUTPUT_DIR = Path(
    os.getenv("EXPERIMENT_OUTPUT_DIR", "./experiments")
)


@dataclass
class ParallelRunResult:
    """Result of one engine's parallel run."""
    engine_type: RecoveryEngineType
    schema_name: str
    run_id: Optional[UUID]
    recovery_run_id: Optional[UUID]
    error: Optional[str] = None


@dataclass
class ParallelExperimentConfig:
    """Configuration for a parallel experiment run."""
    people_count: int
    hours: int
    seed: int


class ParallelExperimentRunner:
    """Runs baseline and Smart Agent in parallel on isolated schemas.

    Both engines share the same PostgreSQL server and seed but operate in
    separate schemas, ensuring:

    - Identical starting population (same seed → same RNG streams).
    - No cross-engine data leakage.
    - Fast schema creation/drop (vs full DB dump/restore).

    Parameters
    ----------
    db : Database
        The master database connection (used to create/drop schemas).
    settings : Settings
        Application settings (LLM config, service URLs, etc.).
    """

    # Class-level default so the runner can be used without __init__
    # (e.g. by API endpoints that only need settings for read-only ops).
    _schema_prefix: str = "exp"

    def __init__(self, db: Database, settings: Settings):
        self._master_db = db
        self._settings = settings
        self._schema_prefix = "exp"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run(
        self,
        people_count: int = 200,
        hours: int = 72,
        seed: int = 42,
        keep_schemas: bool = True,
    ) -> LiftReport:
        """Run a parallel experiment and return the lift report.

        Steps:
          1. Create two schema-scoped databases (baseline_run, smart_run).
          2. Boot two orchestrators with the same seed — one baseline, one smart.
          3. Run both in parallel threads for the same number of hours.
          4. Collect metrics from each schema.
          5. Compare and return the lift report.
        """
        experiment_id = uuid.uuid4().hex[:8]
        baseline_schema = f"{self._schema_prefix}_{experiment_id}_baseline"
        smart_schema = f"{self._schema_prefix}_{experiment_id}_smart"

        config = ParallelExperimentConfig(
            people_count=people_count, hours=hours, seed=seed
        )

        logger.info(
            "Parallel experiment %s: %d people, %d hours, seed=%d, "
            "schemas=[%s, %s]",
            experiment_id, people_count, hours, seed,
            baseline_schema, smart_schema,
        )

        # --- Create schema-scoped databases ---
        baseline_db = SchemaScopedDatabase(
            settings=self._settings, schema_name=baseline_schema
        )
        smart_db = SchemaScopedDatabase(
            settings=self._settings, schema_name=smart_schema
        )

        # Create tables in both schemas
        baseline_db.create_schema()
        smart_db.create_schema()

        # --- Build orchestrators ---
        baseline_engine = AuditedBaselineRecoveryEngine(baseline_db)
        smart_engine = self._build_smart_engine(smart_db)

        baseline_orch = build_orchestrator(
            db=baseline_db,
            seed=seed,
            settings=self._settings,
            enable_recovery=True,
            recovery_engine=baseline_engine,
            config=SimConfig.defaults(),
        )

        smart_orch = build_orchestrator(
            db=smart_db,
            seed=seed,
            settings=self._settings,
            enable_recovery=True,
            recovery_engine=smart_engine,
            config=SimConfig.defaults(),
        )

        # --- Run both engines in parallel threads ---
        results: dict[str, ParallelRunResult] = {}

        def _run_baseline():
            try:
                baseline_orch.initialize(config.people_count, seed=config.seed)
                baseline_orch.run_hours(config.hours)
                results["baseline"] = ParallelRunResult(
                    engine_type=RecoveryEngineType.BASELINE,
                    schema_name=baseline_schema,
                    run_id=baseline_orch._current_run.run_id
                    if baseline_orch._current_run else None,
                    recovery_run_id=baseline_orch._recovery_run_id,
                )
            except Exception as exc:
                logger.exception("Baseline run failed")
                results["baseline"] = ParallelRunResult(
                    engine_type=RecoveryEngineType.BASELINE,
                    schema_name=baseline_schema,
                    run_id=None,
                    recovery_run_id=None,
                    error=str(exc),
                )

        def _run_smart():
            try:
                smart_orch.initialize(config.people_count, seed=config.seed)
                smart_orch.run_hours(config.hours)
                results["smart"] = ParallelRunResult(
                    engine_type=RecoveryEngineType.AI_AGENT,
                    schema_name=smart_schema,
                    run_id=smart_orch._current_run.run_id
                    if smart_orch._current_run else None,
                    recovery_run_id=smart_orch._recovery_run_id,
                )
            except Exception as exc:
                logger.exception("Smart agent run failed")
                results["smart"] = ParallelRunResult(
                    engine_type=RecoveryEngineType.AI_AGENT,
                    schema_name=smart_schema,
                    run_id=None,
                    recovery_run_id=None,
                    error=str(exc),
                )

        # Run both in parallel
        baseline_thread = threading.Thread(target=_run_baseline, name="baseline-run")
        smart_thread = threading.Thread(target=_run_smart, name="smart-run")

        baseline_thread.start()
        smart_thread.start()

        baseline_thread.join()
        smart_thread.join()

        # Check for errors
        baseline_result = results.get("baseline")
        smart_result = results.get("smart")

        errors = []
        if baseline_result and baseline_result.error:
            errors.append(f"Baseline error: {baseline_result.error}")
        if smart_result and smart_result.error:
            errors.append(f"Smart Agent error: {smart_result.error}")

        # --- Collect metrics from both schemas ---
        # Collect metrics from baseline schema
        if baseline_result and baseline_result.recovery_run_id:
            baseline_metrics = self._collect_metrics(
                baseline_db, baseline_result.recovery_run_id,
                engine_type=RecoveryEngineType.BASELINE,
            )
        else:
            baseline_metrics = self._empty_metrics(RecoveryEngineType.BASELINE)

        # Collect metrics from smart schema
        if smart_result and smart_result.recovery_run_id:
            smart_metrics = self._collect_metrics(
                smart_db, smart_result.recovery_run_id,
                engine_type=RecoveryEngineType.AI_AGENT,
            )
        else:
            smart_metrics = self._empty_metrics(RecoveryEngineType.AI_AGENT)

        # --- Build comparison report ---
        evaluator = ExperimentEvaluator(RecoveryActionRepository(smart_db))
        report = self._build_report(
            baseline_metrics=baseline_metrics,
            smart_metrics=smart_metrics,
            baseline_schema=baseline_schema,
            smart_schema=smart_schema,
            config=config,
            experiment_id=experiment_id,
            errors=errors,
            evaluator=evaluator,
        )

        # --- Save report ---
        self._last_experiment_id = experiment_id
        self._save_report(report, experiment_id)

        # --- Cleanup: drop schemas (unless keep_schemas=True) ---
        if not keep_schemas:
            self._cleanup_schema(baseline_db, baseline_schema)
            self._cleanup_schema(smart_db, smart_schema)
        else:
            logger.info(
                "Schemas kept alive for experiment %s: [%s, %s]",
                experiment_id, baseline_schema, smart_schema,
            )

        return report

    def get_experiment_cases(
        self,
        experiment_id: str,
        engine: str = "smart",
        limit: int = 100,
        status: Optional[str] = None,
    ) -> list[dict]:
        """Retrieve recovery cases for a specific experiment run.

        Parameters
        ----------
        experiment_id :
            The experiment identifier (first 8 chars of the UUID).
        engine :
            Which engine's schema to query ('baseline' or 'smart').
        limit :
            Maximum number of cases to return.
        status :
            Filter by outcome status (SUCCESS, FAILED, UNKNOWN, PENDING).
        """
        schema_name = (
            f"{self._schema_prefix}_{experiment_id}_baseline"
            if engine == "baseline"
            else f"{self._schema_prefix}_{experiment_id}_smart"
        )

        db = SchemaScopedDatabase(settings=self._settings, schema_name=schema_name)

        try:
            repo = RecoveryActionRepository(db)
            actions = repo.find_all(limit=limit)

            if status:
                actions = [a for a in actions if a.outcome and a.outcome.value == status]

            return [self._case_to_dict(a, engine) for a in actions]
        finally:
            db._engine.dispose()

    def get_experiment_metrics(self, experiment_id: str, engine: str = "smart") -> dict:
        """Return lifetime recovery metrics from one preserved experiment schema."""
        from ...recovery.metrics import RecoveryMetricsCollector

        schema_name = (
            f"{self._schema_prefix}_{experiment_id}_baseline"
            if engine == "baseline"
            else f"{self._schema_prefix}_{experiment_id}_smart"
        )
        db = SchemaScopedDatabase(settings=self._settings, schema_name=schema_name)
        try:
            metrics = RecoveryMetricsCollector(db).collect()
            return metrics.to_dict()
        finally:
            db._engine.dispose()

    def get_experiment_retries(
        self,
        experiment_id: str,
        engine: str = "smart",
        limit: int = 5000,
        status: Optional[str] = None,
    ) -> list[dict]:
        """Return only retry actions from one preserved experiment schema."""
        schema_name = (
            f"{self._schema_prefix}_{experiment_id}_baseline"
            if engine == "baseline"
            else f"{self._schema_prefix}_{experiment_id}_smart"
        )
        db = SchemaScopedDatabase(settings=self._settings, schema_name=schema_name)
        try:
            repo = RecoveryActionRepository(db)
            actions = repo.find_all(limit=limit, action_type="RETRY")
            if status:
                actions = [a for a in actions if a.outcome and a.outcome.value == status]
            return [self._case_to_dict(a, engine) for a in actions]
        finally:
            db._engine.dispose()

    def get_experiment_case_detail(
        self, experiment_id: str, case_id: str, engine: str = "smart"
    ) -> dict:
        """Retrieve full details for a single recovery case.

        For the smart agent, includes diagnosis, policy checks, and explanation
        from the audit trail.
        """
        from .audit import AuditEventWriter
        from ...schema import BaselineAuditEventRow

        schema_name = (
            f"{self._schema_prefix}_{experiment_id}_baseline"
            if engine == "baseline"
            else f"{self._schema_prefix}_{experiment_id}_smart"
        )

        db = SchemaScopedDatabase(settings=self._settings, schema_name=schema_name)

        try:
            repo = RecoveryActionRepository(db)
            action = repo.find(UUID(case_id))

            if action is None:
                return {"error": f"Case not found: {case_id}"}

            result = self._case_to_dict(action, engine)

            # Both agents expose their own physical audit table.  Keeping the
            # response shape identical makes side-by-side replay simple.
            if engine == "smart":
                auditor = AuditEventWriter(db)
            else:
                auditor = AuditEventWriter(db, row_model=BaselineAuditEventRow)
            if engine in ("smart", "baseline"):
                audit_events = auditor.find_for_case(action.action_id)

                decision_event = None
                diagnosis_event = None
                for evt in audit_events:
                    if evt.event_type == "decision":
                        decision_event = evt
                    elif evt.event_type == "llm_diagnosis":
                        diagnosis_event = evt

                result["diagnosis"] = (
                    diagnosis_event.decision_json if diagnosis_event else None
                )
                result["decision"] = (
                    decision_event.decision_json if decision_event else None
                )
                result["policy_checks"] = (
                    decision_event.policy_checks if decision_event else None
                )
                result["audit_trail"] = [
                    {
                        "event_id": str(evt.event_id),
                        "timestamp": evt.timestamp.isoformat(),
                        "event_type": evt.event_type,
                        "actor": evt.actor,
                        "outcome": evt.outcome,
                    }
                    for evt in audit_events
                ]

                # Prior actions for the same intent
                if engine == "smart" and action.payment_intent_id:
                    prior = repo.find_by_intent_id(action.payment_intent_id)
                    result["prior_actions"] = [
                        self._action_to_dict(a) for a in prior
                    ]

            return result
        finally:
            db._engine.dispose()

    def get_experiment_audit(self, experiment_id: str, engine: str = "smart", limit: int = 200) -> list[dict]:
        """Return the decision audit stream for one side of an experiment."""
        from .audit import AuditEventWriter
        from ...schema import AuditEventRow, BaselineAuditEventRow
        schema_name = f"{self._schema_prefix}_{experiment_id}_{'baseline' if engine == 'baseline' else 'smart'}"
        db = SchemaScopedDatabase(settings=self._settings, schema_name=schema_name)
        try:
            model = BaselineAuditEventRow if engine == "baseline" else None
            events = AuditEventWriter(db, row_model=model or AuditEventRow).find_all(limit)
            return [{
                "event_id": str(evt.event_id), "case_id": str(evt.case_id) if evt.case_id else None,
                "timestamp": evt.timestamp.isoformat(), "agent_version": evt.agent_version,
                "policy_version": evt.policy_version, "actor": evt.actor, "event_type": evt.event_type,
                "input_snapshot_hash": evt.input_snapshot_hash, "decision_json": evt.decision_json,
                "policy_checks": evt.policy_checks, "outcome": evt.outcome,
            } for evt in events]
        finally:
            db._engine.dispose()

    def list_experiments(self, limit: int = 20) -> list[dict]:
        """List previously saved experiment reports from the output directory."""
        reports = []
        if not EXPERIMENT_OUTPUT_DIR.exists():
            return reports

        for json_path in sorted(
            EXPERIMENT_OUTPUT_DIR.glob("parallel_*.json"),
            reverse=True,
        )[:limit]:
            try:
                with open(json_path) as f:
                    data = json.load(f)
                reports.append({
                    "experiment_id": data.get("experiment_id"),
                    "file": json_path.name,
                    "baseline_cases": data.get("baseline", {}).get("total_cases", 0),
                    "smart_cases": data.get("smart", {}).get("total_cases", 0),
                    "lift": data.get("incremental_recovered_value", "0"),
                })
            except Exception:
                continue

        return reports

    def nuke_all(self) -> dict:
        """Drop every preserved parallel-experiment schema + delete its
        on-disk report files. Used by ``/api/simulation/nuke`` so a
        full DB reset wipes SARA's preserved experiments too — otherwise
        ``list_experiments`` keeps returning the old JSON reports after
        the public schema is reset and the SARA Attempts tab shows stale
        retries.

        Returns a small summary dict for the API response.
        """
        deleted_files = 0
        dropped_schemas: set[str] = set()

        # 1. Discover schemas to drop from the report files + a best-effort
        #    glob for any extras the report index missed.
        report_experiments: set[str] = set()
        if EXPERIMENT_OUTPUT_DIR.exists():
            for json_path in EXPERIMENT_OUTPUT_DIR.glob("parallel_*.json"):
                try:
                    data = json.loads(json_path.read_text())
                    eid = data.get("experiment_id")
                    if eid:
                        report_experiments.add(str(eid))
                except Exception:
                    continue

        # 2. Drop matching schemas. Each preserved experiment owns two
        #    schemas: <prefix>_<id>_baseline and <prefix>_<id>_smart.
        schema_prefix = self._schema_prefix
        try:
            with self._master_db._engine.begin() as conn:
                rows = conn.execute(text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name LIKE :pat"
                ), {"pat": f"{schema_prefix}_%"}).fetchall()
                for (sname,) in rows:
                    if sname in dropped_schemas:
                        continue
                    conn.execute(text(f"DROP SCHEMA IF EXISTS {sname} CASCADE"))
                    dropped_schemas.add(sname)
        except Exception as e:
            logger.warning("nuke_all: schema drop iteration failed: %s", e)

        # 3. Delete the on-disk report files. Without this, list_experiments
        #    keeps returning reports for schemas we just dropped and the
        #    frontend's "use latest experiment" fallback re-fetches them.
        if EXPERIMENT_OUTPUT_DIR.exists():
            for path in EXPERIMENT_OUTPUT_DIR.glob("parallel_*"):
                try:
                    path.unlink()
                    deleted_files += 1
                except Exception:
                    continue

        return {
            "dropped_schemas": sorted(dropped_schemas),
            "deleted_report_files": deleted_files,
            "report_experiments_seen": sorted(report_experiments),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_smart_engine(
        self, db: Database
    ) -> SmartRecoveryEngine:
        """Build a fully-wired SmartRecoveryEngine with all dependencies.

        Mirrors ExperimentRunner._build_smart_engine() but uses the given
        schema-scoped database for all sub-components.
        """
        from .llm_gateway import LLMGateway
        from .memory import RecoveryMemoryRepository
        from .promise_tracker import PromiseTracker
        from .audit import AuditEventWriter

        recovery_repo = RecoveryActionRepository(db)

        llm_config = LLMConfig.from_env()
        llm_gateway = LLMGateway(llm_config, db=db)

        memory_repo = RecoveryMemoryRepository(db, recovery_repo)
        promise_tracker = PromiseTracker(db)
        auditor = AuditEventWriter(db)

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

    def _collect_metrics(
        self, db: Database, recovery_run_id: UUID,
        engine_type: RecoveryEngineType = RecoveryEngineType.AI_AGENT,
    ) -> RunMetrics:
        """Collect RunMetrics for a given recovery run_id from a schema-scoped DB."""
        repo = RecoveryActionRepository(db)
        evaluator = ExperimentEvaluator(repo)
        return evaluator.compute_metrics(recovery_run_id, engine_type.value)

    def _empty_metrics(self, engine_type: RecoveryEngineType) -> RunMetrics:
        """Create zeroed RunMetrics for error fallback cases."""
        zero_uuid = UUID(int=0)
        return RunMetrics(
            run_id=zero_uuid,
            engine_type=engine_type.value,
            total_cases=0,
            recovered_cases=0,
            total_recovered_value=Decimal("0"),
            total_retries=0,
            wasted_retries=0,
            total_outreach=0,
            mean_time_to_recovery_hours=None,
            stop_count=0,
            correct_stops=0,
            duplicate_risk_incidents=0,
            total_cost=Decimal("0"),
            incentive_cost=Decimal("0"),
            net_recovered_value=Decimal("0"),
        )

    def _build_report(
        self,
        baseline_metrics: RunMetrics,
        smart_metrics: RunMetrics,
        baseline_schema: str,
        smart_schema: str,
        config: ParallelExperimentConfig,
        experiment_id: str,
        errors: list[str],
        evaluator: ExperimentEvaluator,
    ) -> LiftReport:
        """Build the final lift report from both engines' metrics."""
        report = evaluator.compare(baseline_metrics, smart_metrics)

        # Augment notes with experiment metadata
        from dataclasses import replace
        existing_notes = report.notes
        new_notes = (
            f"Parallel experiment {experiment_id}: "
            f"schemas=[{baseline_schema}, {smart_schema}], "
            f"seed={config.seed}, people={config.people_count}, hours={config.hours}. "
        )
        if errors:
            new_notes += "Errors: " + "; ".join(errors)
        else:
            new_notes += "Both engines completed successfully."
        new_notes += f" {existing_notes}"

        report = replace(report, notes=new_notes)
        return report

    def _case_to_dict(self, action, engine: str) -> dict:
        """Convert a RecoveryAction to a dict for the API response."""
        result = {
            "action_id": str(action.action_id),
            "intent_id": str(action.payment_intent_id) if action.payment_intent_id else None,
            "payment_intent_id": str(action.payment_intent_id) if action.payment_intent_id else None,
            "engine": engine,
            "action_type": action.action_type.value if hasattr(action.action_type, 'value') else str(action.action_type),
            "reason": action.reason,
            "schedule_reason": action.schedule_reason,
            "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
            "executed_at": action.executed_at.isoformat() if action.executed_at else None,
            "outcome": action.outcome.value if action.outcome else "PENDING",
            "retry_number": action.retry_number,
            "failure_code": action.failure_code,
            "failure_reason": action.failure_reason,
            "customer_declined": action.customer_declined,
            "amount": str(action.amount) if action.amount else None,
            "payment_method": action.payment_method,
            "cost": str(action.cost) if action.cost else None,
            "expected_recovery": str(action.expected_recovery) if action.expected_recovery else None,
        }
        return result

    def _action_to_dict(self, action) -> dict:
        """Convert a RecoveryAction to a minimal dict for prior_actions."""
        return {
            "action_id": str(action.action_id),
            "action_type": action.action_type.value if hasattr(action.action_type, 'value') else str(action.action_type),
            "retry_number": action.retry_number,
            "outcome": action.outcome.value if action.outcome else None,
            "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
            "reason": action.reason,
        }

    def _save_report(self, report: LiftReport, experiment_id: str) -> None:
        """Save the experiment report to disk as JSON + human-readable text."""
        EXPERIMENT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_path = EXPERIMENT_OUTPUT_DIR / f"parallel_{experiment_id}_{timestamp}.json"
        text_path = EXPERIMENT_OUTPUT_DIR / f"parallel_{experiment_id}_{timestamp}.txt"

        # Save JSON report (includes experiment_id for later lookup)
        report_dict = report.to_dict()
        report_dict["experiment_id"] = experiment_id
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, default=str)

        # Save human-readable report
        text_report = self._format_text_report(report, experiment_id)
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(text_report)

        logger.info(
            "Parallel experiment report saved to %s and %s",
            json_path, text_path,
        )

    def _format_text_report(self, report: LiftReport, experiment_id: str) -> str:
        """Format the lift report as a human-readable text summary."""
        b = report.baseline
        s = report.smart

        lines = []
        lines.append("=" * 72)
        lines.append(f"SARA Parallel Experiment Report — ID: {experiment_id}")
        lines.append("=" * 72)
        lines.append("")

        def _fmt_metrics(label: str, m: RunMetrics) -> None:
            lines.append(label)
            lines.append(f"  Cases:              {m.total_cases}")
            lines.append(f"  Recovered:          {m.recovered_cases}")
            lines.append(f"  Recovery value:     {m.total_recovered_value} INR")
            rate = (m.recovered_cases / max(m.total_cases, 1) * 100) if m.total_cases else 0
            lines.append(f"  Recovery rate:      {rate:.2f}%")
            lines.append(f"  Retries:            {m.total_retries}")
            lines.append(f"  Wasted retries:     {m.wasted_retries}")
            lines.append(f"  Outreach actions:   {m.total_outreach}")
            ttr = m.mean_time_to_recovery_hours
            lines.append(f"  Mean TTR:           {ttr if ttr else 'N/A'} h")
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
        lines.append(f"  Incremental:        {report.incremental_recovered_value} INR")
        lines.append(f"  Rate lift:          {report.incremental_recovery_rate:+.2f} pp")
        lines.append(f"  Wasted retry reduction: {report.wasted_retry_reduction}")
        ttr_imp = report.time_to_recovery_improvement
        lines.append(f"  TTR improvement:    {ttr_imp or 'N/A'} h")
        lines.append(f"  Stop precision lift: {report.stop_precision_improvement:+.4f}")
        lines.append(f"  Cost savings:       {report.total_cost_savings} INR")
        lines.append(f"  Duplicate risk delta: {report.duplicate_risk_delta}")
        lines.append("")
        lines.append(f"Notes: {report.notes}")
        lines.append("")
        lines.append("=" * 72)

        return "\n".join(lines)

    def _cleanup_schema(
        self, db: SchemaScopedDatabase, schema_name: str
    ) -> None:
        """Drop the schema (including all objects) after collecting metrics."""
        try:
            db.drop_schema_only()
            logger.info("Cleaned up schema: %s", schema_name)
        except Exception as exc:
            logger.warning("Failed to clean up schema %s: %s", schema_name, exc)
