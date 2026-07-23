"""Dashboard aggregation services."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from bas_assistant.auth.schemas import UserIdentity
from bas_assistant.database import (
    ControllerRecord,
    ConversationRecord,
    DatabaseManager,
    DocumentRecord,
    EquipmentRecord,
    KnowledgeRecord,
    PointRecord,
    ProjectRecord,
    TaskRecord,
)
from bas_assistant.emulation import BasEmulationLab
from bas_assistant.runtime import build_health_report

from .projects import JsonProjectRepository
from .project_queries import ProjectQueryService
from .uploads import UploadService


@dataclass(slots=True)
class DashboardSnapshot:
    """Snapshot of dashboard state for the engineering home page."""

    project_count: int
    equipment_count: int
    point_count: int
    controller_count: int
    document_count: int
    knowledge_count: int
    conversation_count: int
    open_task_count: int
    recent_uploads: list[dict[str, object]]
    health: dict[str, object]
    projects: dict[str, dict[str, object]]
    total_object_count: int
    points_per_equipment: float
    controllers_per_project: float
    featured_project: dict[str, object] | None
    top_projects: list[dict[str, object]]
    featured_project_live: dict[str, object] | None


class DashboardService:
    """Build dashboard view models from persisted services."""

    def __init__(
        self,
        *,
        db: DatabaseManager,
        project_repository: JsonProjectRepository,
        project_queries: ProjectQueryService,
        upload_service: UploadService,
        health_report_factory,
    ) -> None:
        self.db = db
        self.project_repository = project_repository
        self.project_queries = project_queries
        self.upload_service = upload_service
        self.health_report_factory = health_report_factory

    def snapshot(self, user: UserIdentity | None = None) -> DashboardSnapshot:
        """Return the current dashboard snapshot."""
        scope = self.project_queries.scope_for_user(user)
        with self.db.session() as session:
            project_filter = (
                ProjectRecord.project_id.in_(scope.allowed_project_ids)
                if scope.allowed_project_ids is not None
                else None
            )
            project_statement = select(ProjectRecord).order_by(ProjectRecord.updated_at.desc(), ProjectRecord.name)
            if project_filter is not None:
                project_statement = project_statement.where(project_filter)
            project_records = list(session.scalars(project_statement))
            project_db_ids = [project.id for project in project_records]
            project_count = len(project_records)
            equipment_count = self._count_related(session, EquipmentRecord, project_db_ids)
            point_count = self._count_related(session, PointRecord, project_db_ids)
            controller_count = self._count_related(session, ControllerRecord, project_db_ids)
            document_count = self._count_related(session, DocumentRecord, project_db_ids)
            knowledge_count = self._count_related(session, KnowledgeRecord, project_db_ids)
            conversation_count = session.scalar(select(func.count()).select_from(ConversationRecord)) or 0
            open_task_count = session.scalar(
                select(func.count()).select_from(TaskRecord).where(TaskRecord.status != "completed")
            ) or 0
            projects = self.project_queries.project_cards_for_records(session, project_records)
        recent_uploads = [
            {
                "filename": upload.filename,
                "category": upload.category,
                "status": upload.status,
                "stored_path": upload.stored_path,
                "created_at": upload.created_at,
            }
            for upload in self.upload_service.list_recent_uploads(
                project_ids=sorted(scope.allowed_project_ids) if scope.allowed_project_ids is not None else None,
                limit=8,
            )
        ]
        available_projects = {
            project_id: card
            for project_id, card in projects.items()
            if self.project_repository.get(project_id) is not None
        }
        project_cards = list(available_projects.values())
        total_object_count = equipment_count + point_count + controller_count
        points_per_equipment = round(point_count / equipment_count, 1) if equipment_count else 0.0
        controllers_per_project = round(controller_count / project_count, 1) if project_count else 0.0
        featured_project = project_cards[0] if project_cards else None
        top_projects = sorted(
            project_cards,
            key=lambda card: (
                int(card.get("point_count", 0)),
                int(card.get("equipment_count", 0)),
                int(card.get("controller_count", 0)),
                str(card.get("name", "")),
            ),
            reverse=True,
        )[:3]
        featured_project_live = self._featured_project_live_snapshot(featured_project)
        return DashboardSnapshot(
            project_count=project_count,
            equipment_count=equipment_count,
            point_count=point_count,
            controller_count=controller_count,
            document_count=document_count,
            knowledge_count=knowledge_count,
            conversation_count=conversation_count,
            open_task_count=open_task_count,
            recent_uploads=recent_uploads,
            health=self.health_report_factory(),
            projects=available_projects,
            total_object_count=total_object_count,
            points_per_equipment=points_per_equipment,
            controllers_per_project=controllers_per_project,
            featured_project=featured_project,
            top_projects=top_projects,
            featured_project_live=featured_project_live,
        )

    def _count_related(self, session, model, project_db_ids: list[int]) -> int:
        if not project_db_ids:
            return 0
        return session.scalar(
            select(func.count()).select_from(model).where(model.project_id.in_(project_db_ids))
        ) or 0

    def _featured_project_live_snapshot(self, featured_project: dict[str, object] | None) -> dict[str, object] | None:
        if not featured_project:
            return None
        project_id = str(featured_project.get("project_id") or "").strip()
        if not project_id:
            return None
        project = self.project_repository.get(project_id)
        if project is None:
            return None

        snapshot = BasEmulationLab(project=project).snapshot()
        weather = dict(snapshot.weather)
        station = dict(snapshot.station)
        points = [point for device in snapshot.devices for point in device.points]

        def analog_value(*tokens: str) -> float | None:
            token_set = tuple(self._normalize_token(token) for token in tokens)
            for point in points:
                normalized_name = self._normalize_token(point.point_name)
                if any(token in normalized_name for token in token_set) and isinstance(point.present_value, (int, float)):
                    return float(point.present_value)
            return None

        def percent_value(*tokens: str) -> str:
            value = analog_value(*tokens)
            return f"{round(value, 1):g}%" if value is not None else "--"

        supply_air_temp = analog_value("AHU-1 SAT", "AHU-1 DAT", "SUPPLY AIR TEMP")
        return_air_temp = analog_value("AHU-1 RAT", "RETURN AIR TEMP")
        mixed_air_temp = analog_value("AHU-1 MAT", "MIXED AIR TEMP")
        zone_temp = self._average_matching_points(points, "ZNT", "ZONE TEMP", "SPACE TEMP")
        supply_static = analog_value("DUCT SP", "STATIC PRESSURE", "FILTER DP")

        return {
            "weather": weather,
            "station": station,
            "outdoor_air_temp": self._format_value(weather.get("outdoor_air_temp"), "degF"),
            "outdoor_air_humidity": self._format_value(weather.get("outdoor_air_humidity"), "%"),
            "wind_mph": self._format_value(weather.get("wind_mph"), "mph"),
            "conditions": str(weather.get("conditions") or "unknown").replace("_", " ").title(),
            "supply_air_temp": self._format_value(supply_air_temp, "degF"),
            "return_air_temp": self._format_value(return_air_temp, "degF"),
            "mixed_air_temp": self._format_value(mixed_air_temp, "degF"),
            "avg_zone_temp": self._format_value(zone_temp, "degF"),
            "supply_static": self._format_value(supply_static, "inWC"),
            "cooling_valve": percent_value("CLG VALVE", "COOLING VALVE"),
            "heating_valve": percent_value("HTG VALVE", "HEATING VALVE"),
            "outside_air_damper": percent_value("OA DAMPER", "OUTSIDE AIR DAMPER"),
        }

    def _average_matching_points(self, points, *tokens: str) -> float | None:
        token_set = tuple(self._normalize_token(token) for token in tokens)
        values: list[float] = []
        for point in points:
            normalized_name = self._normalize_token(point.point_name)
            if any(token in normalized_name for token in token_set) and isinstance(point.present_value, (int, float)):
                values.append(float(point.present_value))
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    def _format_value(self, value: object, units: str = "") -> str:
        if not isinstance(value, (int, float)):
            return "--"
        if units == "%":
            return f"{round(float(value), 1):g}%"
        if units:
            decimals = 2 if units in {"inWC", "psi"} else 1
            numeric = f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")
            return f"{numeric} {units}"
        return f"{float(value):.1f}"

    def _normalize_token(self, value: str) -> str:
        return "".join(ch for ch in value.upper() if ch.isalnum())
