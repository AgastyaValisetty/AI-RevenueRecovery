"""AuditEventWriter — persists immutable audit trail for smart-agent decisions.

Every decision, policy check, execution, and outcome is recorded as an
AuditEvent for full traceability and replay.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from ...database import Database
from ...domain import ConsentState
from ..domain import RecoveryOutcome
from ...schema import AuditEventRow

logger = logging.getLogger(__name__)

AGENT_VERSION = "sara-1.0.0"
POLICY_VERSION = "policy-1.0.0"


def hash_input_snapshot(data: dict) -> str:
    """Compute a deterministic SHA-256 hash of an input snapshot dict.

    The dict is serialized with sorted keys and no whitespace so that
    identical inputs always produce the same hash (required for replay).
    """
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    """An immutable record of one agent decision / execution event.

    All fields map directly to columns in the ``audit_events`` table.
    """

    event_id: UUID
    case_id: Optional[UUID]
    run_id: Optional[UUID]
    timestamp: datetime
    agent_version: str
    policy_version: str
    actor: str  # "system" | "agent" | "human"
    event_type: str  # "decision" | "policy_check" | "execution" | "outcome" | "llm_call"
    input_snapshot_hash: str
    evidence_refs: dict  # {"context_version": "...", "features": [...], "diagnosis": [...]}
    decision_json: dict  # full decision payload
    policy_checks: dict  # {"retry_budget": {"passed": true, "detail": "..."}, ...}
    idempotency_key: Optional[str] = None
    execution_result: Optional[dict] = None
    outcome: Optional[str] = None  # "SUCCESS" | "FAILED" | "STOPPED" | "PENDING"

    @classmethod
    def build(
        cls,
        case_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        actor: str = "agent",
        event_type: str = "decision",
        decision: Optional[dict] = None,
        policy_checks: Optional[dict] = None,
        evidence_refs: Optional[dict] = None,
        execution_result: Optional[dict] = None,
        outcome: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        input_snapshot: Optional[dict] = None,
        agent_version: str = AGENT_VERSION,
        policy_version: str = POLICY_VERSION,
    ) -> "AuditEvent":
        """Build an AuditEvent with deterministic hash from input_snapshot."""
        snapshot = input_snapshot or {}
        snapshot_hash = hash_input_snapshot(snapshot)

        return cls(
            event_id=uuid4(),
            case_id=case_id,
            run_id=run_id,
            timestamp=datetime.now(snapshot.get("tz", datetime.now().astimezone().tzinfo)),
            agent_version=agent_version,
            policy_version=policy_version,
            actor=actor,
            event_type=event_type,
            input_snapshot_hash=snapshot_hash,
            evidence_refs=evidence_refs or {},
            decision_json=decision or {},
            policy_checks=policy_checks or {},
            idempotency_key=idempotency_key,
            execution_result=execution_result,
            outcome=outcome,
        )


class AuditEventWriter:
    """Persists AuditEvent records to the audit_events table."""

    def __init__(self, db: Database, row_model=AuditEventRow):
        self._db = db
        self._row_model = row_model

    def write(self, event: AuditEvent) -> None:
        """Persist an AuditEvent.  Each event is immutable — never update."""
        with self._db.session() as session:
            row = self._row_model(
                event_id=event.event_id,
                case_id=event.case_id,
                run_id=event.run_id,
                timestamp=event.timestamp,
                agent_version=event.agent_version,
                policy_version=event.policy_version,
                actor=event.actor,
                event_type=event.event_type,
                input_snapshot_hash=event.input_snapshot_hash,
                evidence_refs=event.evidence_refs,
                decision_json=event.decision_json,
                policy_checks=event.policy_checks,
                idempotency_key=event.idempotency_key,
                execution_result=event.execution_result,
                outcome=event.outcome,
            )
            session.add(row)
        logger.debug(
            "Audit event written: %s case=%s type=%s",
            event.event_id,
            event.case_id,
            event.event_type,
        )

    def find_for_case(self, case_id: UUID) -> list[AuditEvent]:
        """Return all audit events for a given case, chronological."""
        from sqlalchemy import select
        with self._db.session() as session:
            rows = session.scalars(
                select(self._row_model)
                .where(self._row_model.case_id == case_id)
                .order_by(self._row_model.timestamp.asc())
            ).all()
            return [self._row_to_event(r) for r in rows]

    def find_for_run(self, run_id: UUID) -> list[AuditEvent]:
        """Return all audit events for a given run, chronological."""
        from sqlalchemy import select
        with self._db.session() as session:
            rows = session.scalars(
                select(self._row_model)
                .where(self._row_model.run_id == run_id)
                .order_by(self._row_model.timestamp.asc())
            ).all()
            return [self._row_to_event(r) for r in rows]

    def find_all(self, limit: int = 200) -> list[AuditEvent]:
        """Return the newest immutable events for an experiment explorer."""
        from sqlalchemy import select
        with self._db.session() as session:
            rows = session.scalars(
                select(self._row_model)
                .order_by(self._row_model.timestamp.desc())
                .limit(limit)
            ).all()
            return [self._row_to_event(r) for r in rows]

    def find_by_idempotency_key(self, idempotency_key: str) -> Optional[AuditEvent]:
        """Check if an idempotency key has already been used.

        Returns the existing event if found — allows callers to skip
        re-executing an action that was already performed.
        """
        from sqlalchemy import select
        with self._db.session() as session:
            row = session.scalars(
                select(self._row_model)
                .where(self._row_model.idempotency_key == idempotency_key)
                .order_by(self._row_model.timestamp.desc())
            ).first()
            return self._row_to_event(row) if row else None

    @staticmethod
    def _row_to_event(row: AuditEventRow) -> AuditEvent:
        return AuditEvent(
            event_id=row.event_id,
            case_id=row.case_id,
            run_id=row.run_id,
            timestamp=row.timestamp,
            agent_version=row.agent_version,
            policy_version=row.policy_version,
            actor=row.actor,
            event_type=row.event_type,
            input_snapshot_hash=row.input_snapshot_hash,
            evidence_refs=row.evidence_refs or {},
            decision_json=row.decision_json or {},
            policy_checks=row.policy_checks or {},
            idempotency_key=row.idempotency_key,
            execution_result=row.execution_result,
            outcome=row.outcome,
        )
