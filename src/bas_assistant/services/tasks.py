"""Task tracking services for ingestion and parser workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select

from bas_assistant.database import DatabaseManager, ProjectRecord, TaskRecord


@dataclass(slots=True)
class TaskSnapshot:
    """Read model for project task activity."""

    id: int
    task_type: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TaskService:
    """Persist ingestion and parser task activity."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def create_task(
        self,
        *,
        project_id: str | None,
        task_type: str,
        payload: dict[str, Any],
        created_by_user_id: int | None = None,
    ) -> int:
        """Create a new task record and return its database ID."""
        with self.db.session() as session:
            project_record = None
            if project_id is not None:
                project_record = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            task = TaskRecord(
                project_id=project_record.id if project_record is not None else None,
                created_by_user_id=created_by_user_id,
                task_type=task_type,
                status="pending",
                payload_json=payload,
                result_json={"status_history": [self._status_entry("pending", payload)]},
            )
            session.add(task)
            session.flush()
            return int(task.id)

    def mark_status(self, task_id: int, *, status: str, detail: dict[str, Any] | None = None) -> None:
        """Append a status transition to an existing task."""
        with self.db.session() as session:
            task = session.get(TaskRecord, task_id)
            if task is None:
                return
            task.status = status
            task.updated_at = datetime.now(timezone.utc)
            result_json = dict(task.result_json or {})
            history = list(result_json.get("status_history", []))
            history.append(self._status_entry(status, detail or {}))
            result_json["status_history"] = history
            task.result_json = result_json

    def complete_task(self, task_id: int, *, result: dict[str, Any]) -> None:
        """Mark a task completed and store its result payload."""
        with self.db.session() as session:
            task = session.get(TaskRecord, task_id)
            if task is None:
                return
            task.status = "completed"
            task.updated_at = datetime.now(timezone.utc)
            result_json = dict(task.result_json or {})
            history = list(result_json.get("status_history", []))
            history.append(self._status_entry("completed", result))
            result_json["status_history"] = history
            result_json["result"] = result
            task.result_json = result_json

    def fail_task(self, task_id: int, *, error: str, detail: dict[str, Any] | None = None) -> None:
        """Mark a task failed and store the error context."""
        payload = {"error": error, **(detail or {})}
        with self.db.session() as session:
            task = session.get(TaskRecord, task_id)
            if task is None:
                return
            task.status = "failed"
            task.updated_at = datetime.now(timezone.utc)
            result_json = dict(task.result_json or {})
            history = list(result_json.get("status_history", []))
            history.append(self._status_entry("failed", payload))
            result_json["status_history"] = history
            result_json["error"] = payload
            task.result_json = result_json

    def list_recent_for_project(self, project_id: str, *, limit: int = 10) -> list[TaskSnapshot]:
        """Return recent tasks for a project."""
        with self.db.session() as session:
            project_record = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project_record is None:
                return []
            records = list(
                session.scalars(
                    select(TaskRecord)
                    .where(TaskRecord.project_id == project_record.id)
                    .order_by(desc(TaskRecord.updated_at), desc(TaskRecord.created_at))
                    .limit(limit)
                )
            )
        return [
            TaskSnapshot(
                id=record.id,
                task_type=record.task_type,
                status=record.status,
                payload=dict(record.payload_json or {}),
                result=dict(record.result_json or {}),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ]

    def _status_entry(self, status: str, detail: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": status,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
