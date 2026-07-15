"""System-wide audit ledger services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from bas_assistant.database import DatabaseManager, ProjectRecord, SystemLedgerRecord, TaskRecord


@dataclass(slots=True)
class LedgerEventSnapshot:
    """Read model for durable change history."""

    id: int
    project_id: str | None
    project_name: str | None
    task_id: int | None
    event_type: str
    entity_type: str | None
    entity_key: str | None
    summary: str
    payload: dict[str, Any]
    created_at: datetime


class LedgerService:
    """Persist durable audit events for system and project updates."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def record_event(
        self,
        *,
        event_type: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        project_id: str | None = None,
        task_id: int | None = None,
        entity_type: str | None = None,
        entity_key: str | None = None,
    ) -> int:
        """Persist a ledger entry and return its database ID."""
        with self.db.session() as session:
            project_record = None
            if project_id is not None:
                project_record = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            task_record = session.get(TaskRecord, task_id) if task_id is not None else None
            record = SystemLedgerRecord(
                project_id=project_record.id if project_record is not None else None,
                task_id=task_record.id if task_record is not None else None,
                event_type=event_type,
                entity_type=entity_type,
                entity_key=entity_key,
                summary=summary,
                payload_json=payload or {},
            )
            session.add(record)
            session.flush()
            return int(record.id)

    def list_recent(
        self,
        *,
        limit: int = 100,
        project_id: str | None = None,
        event_type: str = "",
        entity_type: str = "",
    ) -> list[LedgerEventSnapshot]:
        """Return recent ledger entries with optional filters."""
        with self.db.session() as session:
            statement = (
                select(SystemLedgerRecord, ProjectRecord.project_id, ProjectRecord.name)
                .select_from(SystemLedgerRecord)
                .outerjoin(ProjectRecord, ProjectRecord.id == SystemLedgerRecord.project_id)
                .order_by(desc(SystemLedgerRecord.created_at), desc(SystemLedgerRecord.id))
                .limit(limit)
            )
            if project_id:
                statement = statement.where(ProjectRecord.project_id == project_id)
            if event_type:
                statement = statement.where(SystemLedgerRecord.event_type == event_type)
            if entity_type:
                statement = statement.where(SystemLedgerRecord.entity_type == entity_type)
            rows = list(session.execute(statement))
        return [
            LedgerEventSnapshot(
                id=record.id,
                project_id=public_project_id,
                project_name=project_name,
                task_id=record.task_id,
                event_type=record.event_type,
                entity_type=record.entity_type,
                entity_key=record.entity_key,
                summary=record.summary,
                payload=dict(record.payload_json or {}),
                created_at=record.created_at,
            )
            for record, public_project_id, project_name in rows
        ]
