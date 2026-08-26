"""RecoveryRunMetadata — tracks a single baseline recovery run.

A "run" is a coordinated execution of the recovery system over a simulation
window.  It records which engine was used (BASELINE vs AI_AGENT), the seed,
the time window, and an optional reference to the parent SimulationRun.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from ..database import Database
from ..schema import RecoveryActionRow, SimulationRunRow
from .domain import RecoveryEngineType

logger = logging.getLogger(__name__)


@dataclass
class RecoveryRunMetadata:
    """Metadata for a single recovery run.

    Stored as a SimulationRunRow (reusing the existing table) with
    config_snapshot that records the engine type and recovery parameters.
    """

    run_id: UUID
    seed: int
    engine_type: RecoveryEngineType
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "PENDING"
    max_retries: int = 3
    retry_interval_hours: int = 12
    total_intents_processed: int = 0
    total_recovery_actions: int = 0
    successful_recoveries: int = 0
    failed_recoveries: int = 0
    stopped_recoveries: int = 0
    recovered_gmv: float = 0.0
    error_message: Optional[str] = None
    config_snapshot: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now())

    def to_config_snapshot(self) -> dict:
        """Build the config_snapshot dict that gets stored in simulation_runs."""
        return {
            "engine_type": self.engine_type.value,
            "max_retries": self.max_retries,
            "retry_interval_hours": self.retry_interval_hours,
            "total_intents_processed": self.total_intents_processed,
            "total_recovery_actions": self.total_recovery_actions,
            "successful_recoveries": self.successful_recoveries,
            "failed_recoveries": self.failed_recoveries,
            "stopped_recoveries": self.stopped_recoveries,
            "recovered_gmv": str(self.recovered_gmv),
        }


class RecoveryRunTracker:
    """Creates and persists RecoveryRunMetadata records.

    Reuses the SimulationRunRow table — recovery runs are a type of
    simulation run identified by engine_type=BASELINE in the config_snapshot.
    """

    def __init__(self, db: Database):
        self._db = db

    def create(
        self,
        seed: int,
        engine_type: RecoveryEngineType = RecoveryEngineType.BASELINE,
        max_retries: int = 3,
        retry_interval_hours: int = 12,
    ) -> RecoveryRunMetadata:
        """Create a new recovery run metadata record (persisted)."""
        now_ts = datetime.now(self._now_tz())
        run_id = uuid4()

        metadata = RecoveryRunMetadata(
            run_id=run_id,
            seed=seed,
            engine_type=engine_type,
            start_time=now_ts,
            max_retries=max_retries,
            retry_interval_hours=retry_interval_hours,
            config_snapshot={},
        )

        with self._db.session() as session:
            row = SimulationRunRow(
                run_id=run_id,
                seed=seed,
                config_snapshot=metadata.to_config_snapshot(),
                people_count=None,
                hours_run=0,
                status="RUNNING",
                started_at=now_ts,
                created_at=now_ts,
            )
            session.add(row)

        logger.info(
            "Created recovery run %s (engine=%s, max_retries=%d)",
            run_id,
            engine_type.value,
            max_retries,
        )
        return metadata

    def update(
        self,
        run_id: UUID,
        *,
        status: Optional[str] = None,
        total_intents_processed: Optional[int] = None,
        total_recovery_actions: Optional[int] = None,
        successful_recoveries: Optional[int] = None,
        failed_recoveries: Optional[int] = None,
        stopped_recoveries: Optional[int] = None,
        recovered_gmv: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update a recovery run's metadata."""
        from dataclasses import replace

        with self._db.session() as session:
            row = session.get(SimulationRunRow, run_id)
            if row is None:
                logger.warning("Recovery run %s not found for update", run_id)
                return

            if status is not None:
                row.status = status
                if status in ("COMPLETED", "FAILED"):
                    row.completed_at = datetime.now(self._now_tz())
            if total_intents_processed is not None:
                pass  # stored in config_snapshot
            if total_recovery_actions is not None:
                pass
            if successful_recoveries is not None:
                pass
            if error_message is not None:
                row.error_message = error_message

            # Update config_snapshot with latest metrics
            snapshot = dict(row.config_snapshot or {})
            if total_intents_processed is not None:
                snapshot["total_intents_processed"] = total_intents_processed
            if total_recovery_actions is not None:
                snapshot["total_recovery_actions"] = total_recovery_actions
            if successful_recoveries is not None:
                snapshot["successful_recoveries"] = successful_recoveries
            if failed_recoveries is not None:
                snapshot["failed_recoveries"] = failed_recoveries
            if stopped_recoveries is not None:
                snapshot["stopped_recoveries"] = stopped_recoveries
            if recovered_gmv is not None:
                snapshot["recovered_gmv"] = str(recovered_gmv)
            row.config_snapshot = snapshot

    def find(self, run_id: UUID) -> Optional[RecoveryRunMetadata]:
        """Find a recovery run by ID."""
        with self._db.session() as session:
            row = session.get(SimulationRunRow, run_id)
            if row is None:
                return None
            snapshot = row.config_snapshot or {}
            return RecoveryRunMetadata(
                run_id=row.run_id,
                seed=row.seed,
                engine_type=RecoveryEngineType(snapshot.get("engine_type", "BASELINE")),
                start_time=row.started_at or row.created_at,
                end_time=row.completed_at,
                status=row.status,
                max_retries=snapshot.get("max_retries", 3),
                retry_interval_hours=snapshot.get("retry_interval_hours", 12),
                total_intents_processed=snapshot.get("total_intents_processed", 0),
                total_recovery_actions=snapshot.get("total_recovery_actions", 0),
                successful_recoveries=snapshot.get("successful_recoveries", 0),
                failed_recoveries=snapshot.get("failed_recoveries", 0),
                stopped_recoveries=snapshot.get("stopped_recoveries", 0),
                recovered_gmv=float(snapshot.get("recovered_gmv", "0")),
                error_message=row.error_message,
                config_snapshot=snapshot,
                created_at=row.created_at,
            )

    @staticmethod
    def _now_tz() -> timezone:
        from datetime import timezone
        return timezone.utc
