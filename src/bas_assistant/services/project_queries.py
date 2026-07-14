"""Read-oriented project query services backed by the relational store."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from sqlalchemy import func, select

from bas_assistant.auth.schemas import UserIdentity
from bas_assistant.database import (
    ArtifactObjectLinkRecord,
    ControllerRecord,
    DatabaseManager,
    DocumentRecord,
    EquipmentRecord,
    KnowledgeRecord,
    PointRecord,
    ProjectMembershipRecord,
    ProjectRecord,
    TaskRecord,
    UploadRecord,
    UserAccount,
)


@dataclass(slots=True)
class ProjectQueryScope:
    """Project filter scope derived from the current user."""

    allowed_project_ids: set[str] | None


class ProjectQueryService:
    """Build project-facing read models from structured database records."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def scope_for_user(self, user: UserIdentity | None) -> ProjectQueryScope:
        """Return the relational filter scope for a user."""
        if user is None or user.role == "admin" or not user.assigned_project_ids:
            return ProjectQueryScope(allowed_project_ids=None)
        return ProjectQueryScope(allowed_project_ids=set(user.assigned_project_ids))

    def list_project_cards(self, user: UserIdentity | None = None) -> dict[str, dict[str, object]]:
        """Return dashboard-ready project card data."""
        scope = self.scope_for_user(user)
        with self.db.session() as session:
            project_statement = select(ProjectRecord).order_by(ProjectRecord.updated_at.desc(), ProjectRecord.name)
            project_statement = self._apply_scope(project_statement, scope)
            projects = list(session.scalars(project_statement))
            return self.project_cards_for_records(session, projects)

    def summary(self, project_id: str) -> dict[str, object] | None:
        """Return a summary view for a single project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            equipment_count = session.scalar(
                select(func.count()).select_from(EquipmentRecord).where(EquipmentRecord.project_id == project.id)
            ) or 0
            point_count = session.scalar(
                select(func.count()).select_from(PointRecord).where(PointRecord.project_id == project.id)
            ) or 0
            controller_count = session.scalar(
                select(func.count()).select_from(ControllerRecord).where(ControllerRecord.project_id == project.id)
            ) or 0
            return {
                "project_id": project.project_id,
                "name": project.name,
                "client": project.client,
                "location": project.location,
                "metadata": dict(project.metadata_json or {}),
                "equipment_count": equipment_count,
                "points_count": point_count,
                "controllers_count": controller_count,
                "validation_status": project.status,
            }

    def detail_view(self, project_id: str) -> dict[str, object] | None:
        """Return a DB-backed detail view for a project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            equipment_records = list(
                session.scalars(
                    select(EquipmentRecord)
                    .where(EquipmentRecord.project_id == project.id)
                    .order_by(EquipmentRecord.equipment_key)
                )
            )
            controller_records = list(
                session.scalars(
                    select(ControllerRecord)
                    .where(ControllerRecord.project_id == project.id)
                    .order_by(ControllerRecord.controller_key)
                )
            )
            point_count = session.scalar(
                select(func.count()).select_from(PointRecord).where(PointRecord.project_id == project.id)
            ) or 0
            controller_count = session.scalar(
                select(func.count()).select_from(ControllerRecord).where(ControllerRecord.project_id == project.id)
            ) or 0
            documents = list(
                session.scalars(
                    select(DocumentRecord)
                    .where(DocumentRecord.project_id == project.id)
                    .order_by(DocumentRecord.created_at.desc())
                    .limit(8)
                )
            )
            uploads = list(
                session.scalars(
                    select(UploadRecord)
                    .where(UploadRecord.project_id == project.id)
                    .order_by(UploadRecord.created_at.desc())
                    .limit(8)
                )
            )
            knowledge = list(
                session.scalars(
                    select(KnowledgeRecord)
                    .where(KnowledgeRecord.project_id == project.id)
                    .order_by(KnowledgeRecord.created_at.desc())
                    .limit(8)
                )
            )
            tasks = list(
                session.scalars(
                    select(TaskRecord)
                    .where(TaskRecord.project_id == project.id)
                    .order_by(TaskRecord.updated_at.desc(), TaskRecord.created_at.desc())
                    .limit(8)
                )
            )
            artifact_link_count = session.scalar(
                select(func.count()).select_from(ArtifactObjectLinkRecord).where(ArtifactObjectLinkRecord.project_id == project.id)
            ) or 0
            memberships = list(
                session.execute(
                    select(UserAccount.username, ProjectMembershipRecord.access_level)
                    .join(ProjectMembershipRecord, ProjectMembershipRecord.user_id == UserAccount.id)
                    .where(ProjectMembershipRecord.project_id == project.id)
                    .order_by(UserAccount.username)
                )
            )
            point_records = list(
                session.scalars(
                    select(PointRecord)
                    .where(PointRecord.project_id == project.id)
                    .order_by(PointRecord.point_name)
                    .limit(8)
                )
            )

        return {
            "project_id": project.project_id,
            "name": project.name,
            "client": project.client,
            "location": project.location,
            "metadata": dict(project.metadata_json or {}),
            "validation_status": project.status,
            "equipment_count": len(equipment_records),
            "point_count": int(point_count),
            "controller_count": int(controller_count),
            "source_document_count": len(documents),
            "equipment": [self._detail_equipment_row(record) for record in equipment_records],
            "points": [self._point_row(record) for record in point_records],
            "controllers": [self._controller_row(record) for record in controller_records[:8]],
            "documents": [
                {
                    "name": record.name,
                    "document_type": record.document_type,
                    "created_at": record.created_at,
                }
                for record in documents
            ],
            "uploads": [
                {
                    "filename": record.filename,
                    "category": record.category,
                    "status": record.status,
                    "created_at": record.created_at,
                }
                for record in uploads
            ],
            "knowledge": [
                {
                    "source_name": record.source_name,
                    "source_type": record.source_type,
                    "status": record.status,
                    "chunk_count": record.chunk_count,
                }
                for record in knowledge
            ],
            "tasks": [
                {
                    "id": record.id,
                    "task_type": record.task_type,
                    "status": record.status,
                    "updated_at": record.updated_at,
                }
                for record in tasks
            ],
            "import_activity": self._build_import_activity(tasks),
            "engineering_status": self._build_project_engineering_status(
                equipment_records=equipment_records,
                controller_records=controller_records,
                point_count=int(point_count),
                documents=documents,
                knowledge=knowledge,
                tasks=tasks,
                artifact_link_count=int(artifact_link_count),
            ),
            "memberships": [
                {
                    "username": username,
                    "access_level": access_level,
                }
                for username, access_level in memberships
            ],
        }

    def equipment_detail(self, project_id: str, equipment_id: str) -> dict[str, object] | None:
        """Return detailed view data for an equipment object."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            record = session.scalar(
                select(EquipmentRecord).where(
                    EquipmentRecord.project_id == project.id,
                    EquipmentRecord.equipment_key == equipment_id,
                )
            )
            if record is None:
                return None
            point_records = list(
                session.scalars(
                    select(PointRecord)
                    .where(PointRecord.project_id == project.id, PointRecord.equipment_key == equipment_id)
                    .order_by(PointRecord.point_name)
                )
            )
        payload = dict(record.payload_json or {})
        review = self._build_equipment_review(payload, linked_points_count=len(point_records))
        return {
            "entity_type": "equipment",
            "project_id": project_id,
            "title": equipment_id,
            "subtitle": record.equipment_type,
            "payload": payload,
            "linked_points": [point.point_name for point in point_records],
            "review": review,
        }

    def point_detail(self, project_id: str, point_name: str) -> dict[str, object] | None:
        """Return detailed view data for a point object."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            record = session.scalar(
                select(PointRecord).where(
                    PointRecord.project_id == project.id,
                    PointRecord.point_name == point_name,
                )
            )
            if record is None:
                return None
        payload = dict(record.payload_json or {})
        related = []
        if payload.get("equipment_id"):
            related.append({"entity_type": "equipment", "entity_key": payload["equipment_id"]})
        if payload.get("controller_id"):
            related.append({"entity_type": "controller", "entity_key": payload["controller_id"]})
        review = self._build_point_review(payload)
        return {
            "entity_type": "point",
            "project_id": project_id,
            "title": point_name,
            "subtitle": record.point_kind,
            "payload": payload,
            "linked_points": [],
            "related_entities": related,
            "review": review,
        }

    def controller_detail(self, project_id: str, controller_id: str) -> dict[str, object] | None:
        """Return detailed view data for a controller object."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            record = session.scalar(
                select(ControllerRecord).where(
                    ControllerRecord.project_id == project.id,
                    ControllerRecord.controller_key == controller_id,
                )
            )
            if record is None:
                return None
        payload = dict(record.payload_json or {})
        related = [
            {"entity_type": "equipment", "entity_key": equipment_id}
            for equipment_id in payload.get("serves_equipment_ids", [])
        ]
        review = self._build_controller_review(payload)
        return {
            "entity_type": "controller",
            "project_id": project_id,
            "title": controller_id,
            "subtitle": record.controller_type or "controller",
            "payload": payload,
            "linked_points": list(payload.get("owned_point_names", [])),
            "related_entities": related,
            "review": review,
        }

    def activity_view(self, project_id: str) -> dict[str, object] | None:
        """Return project activity history including task status transitions."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            tasks = list(
                session.scalars(
                    select(TaskRecord)
                    .where(TaskRecord.project_id == project.id)
                    .order_by(TaskRecord.updated_at.desc(), TaskRecord.created_at.desc())
                    .limit(40)
                )
            )
            uploads = list(
                session.scalars(
                    select(UploadRecord)
                    .where(UploadRecord.project_id == project.id)
                    .order_by(UploadRecord.created_at.desc())
                    .limit(20)
                )
            )
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "tasks": [self._task_to_view(task) for task in tasks],
            "uploads": [
                {
                    "filename": upload.filename,
                    "category": upload.category,
                    "status": upload.status,
                    "created_at": upload.created_at,
                    "metadata": dict(upload.metadata_json or {}),
                }
                for upload in uploads
            ],
        }

    def import_status_view(self, project_id: str) -> dict[str, object] | None:
        """Return recent import and artifact-ingestion status for the import workspace."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            tasks = list(
                session.scalars(
                    select(TaskRecord)
                    .where(
                        TaskRecord.project_id == project.id,
                        TaskRecord.task_type.in_(("equipment_import", "points_import", "controllers_import", "artifact_ingestion")),
                    )
                    .order_by(TaskRecord.updated_at.desc(), TaskRecord.created_at.desc())
                    .limit(12)
                )
            )
        task_views = [self._task_to_view(task) for task in tasks]
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "tasks": task_views,
            "warning_count": sum(len(task["warning_messages"]) for task in task_views),
            "error_count": sum(len(task["error_messages"]) for task in task_views),
        }

    def memberships_view(self, project_id: str) -> dict[str, object] | None:
        """Return project membership management data."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            users = list(session.scalars(select(UserAccount).order_by(UserAccount.username)))
            memberships = list(
                session.scalars(
                    select(ProjectMembershipRecord).where(ProjectMembershipRecord.project_id == project.id)
                )
            )
        membership_map = {membership.user_id: membership.access_level for membership in memberships}
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "users": [
                {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "is_active": user.is_active,
                    "access_level": membership_map.get(user.id, ""),
                }
                for user in users
            ],
        }

    def documents_view(self, project_id: str) -> dict[str, object] | None:
        """Return document library data for a project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            documents = list(
                session.scalars(
                    select(DocumentRecord)
                    .where(DocumentRecord.project_id == project.id)
                    .order_by(DocumentRecord.created_at.desc(), DocumentRecord.name)
                )
            )
            links = list(
                session.execute(
                    select(
                        ArtifactObjectLinkRecord.document_id,
                        func.count(),
                    )
                    .where(ArtifactObjectLinkRecord.project_id == project.id)
                    .group_by(ArtifactObjectLinkRecord.document_id)
                )
            )
        link_counts = {document_id: int(count) for document_id, count in links}
        rows = []
        for document in documents:
            metadata = dict(document.metadata_json or {})
            rows.append(
                {
                    "id": document.id,
                    "name": document.name,
                    "document_type": document.document_type,
                    "created_at": document.created_at,
                    "file_path": document.file_path,
                    "linked_object_count": link_counts.get(document.id, 0),
                    "is_generated": document.document_type.startswith("generated_"),
                    "category": metadata.get("category", ""),
                    "metadata": metadata,
                }
            )
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "documents": rows,
        }

    def document_detail(self, project_id: str, document_id: int) -> dict[str, object] | None:
        """Return detail view for a specific project document."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            document = session.get(DocumentRecord, document_id)
            if document is None or document.project_id != project.id:
                return None
            links = list(
                session.execute(
                    select(
                        ArtifactObjectLinkRecord.entity_type,
                        ArtifactObjectLinkRecord.entity_key,
                        ArtifactObjectLinkRecord.relationship_type,
                        ArtifactObjectLinkRecord.parser_name,
                        ArtifactObjectLinkRecord.metadata_json,
                    )
                    .where(ArtifactObjectLinkRecord.document_id == document.id)
                    .order_by(
                        ArtifactObjectLinkRecord.entity_type,
                        ArtifactObjectLinkRecord.entity_key,
                    )
                )
            )
            knowledge = session.scalar(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.project_id == project.id,
                    KnowledgeRecord.source_name == document.name,
                    KnowledgeRecord.source_type == document.document_type,
                )
            )
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "id": document.id,
            "name": document.name,
            "document_type": document.document_type,
            "file_path": document.file_path,
            "created_at": document.created_at,
            "metadata": dict(document.metadata_json or {}),
            "linked_objects": [
                {
                    "entity_type": entity_type,
                    "entity_key": entity_key,
                    "relationship_type": relationship_type,
                    "parser_name": parser_name,
                    "metadata": dict(metadata_json or {}),
                }
                for entity_type, entity_key, relationship_type, parser_name, metadata_json in links
            ],
            "knowledge": {
                "status": knowledge.status if knowledge is not None else "not_ingested",
                "chunk_count": knowledge.chunk_count if knowledge is not None else 0,
                "metadata": dict(knowledge.metadata_json or {}) if knowledge is not None else {},
            },
        }

    def knowledge_view(self, project_id: str) -> dict[str, object] | None:
        """Return knowledge records for a project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            records = list(
                session.scalars(
                    select(KnowledgeRecord)
                    .where(KnowledgeRecord.project_id == project.id)
                    .order_by(KnowledgeRecord.created_at.desc(), KnowledgeRecord.source_name)
                )
            )
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "records": [self._knowledge_row(record) for record in records],
        }

    def search_knowledge(self, project_id: str, query: str, *, limit: int = 12) -> dict[str, object] | None:
        """Return deterministic chunk search results for project knowledge."""
        normalized_query = query.strip()
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return None
            records = list(
                session.scalars(
                    select(KnowledgeRecord)
                    .where(KnowledgeRecord.project_id == project.id)
                    .order_by(KnowledgeRecord.created_at.desc(), KnowledgeRecord.source_name)
                )
            )
        knowledge_view = {
            "project_id": project.project_id,
            "project_name": project.name,
            "records": [self._knowledge_row(record) for record in records],
        }
        if not normalized_query:
            return {
                **knowledge_view,
                "query": "",
                "results": [],
                "result_count": 0,
            }

        query_terms = self._tokenize_search_query(normalized_query)
        if not query_terms:
            return {
                **knowledge_view,
                "query": normalized_query,
                "results": [],
                "result_count": 0,
            }

        results: list[dict[str, object]] = []

        for record in records:
            metadata = dict(record.metadata_json or {})
            for chunk in metadata.get("chunks", []):
                chunk_text = str(chunk.get("text") or "").strip()
                if not chunk_text:
                    continue
                score = self._knowledge_match_score(normalized_query, query_terms, chunk_text)
                if score <= 0:
                    continue
                excerpt = self._build_knowledge_excerpt(chunk_text, query_terms)
                results.append(
                    {
                        "knowledge_id": record.id,
                        "source_name": record.source_name,
                        "source_type": record.source_type,
                        "status": record.status,
                        "created_at": record.created_at,
                        "chunk_index": chunk.get("index", 0),
                        "chunk_char_count": chunk.get("char_count", len(chunk_text)),
                        "score": score,
                        "excerpt": excerpt,
                        "content_format": metadata.get("content_format"),
                        "file_path": metadata.get("file_path"),
                    }
                )

        results.sort(
            key=lambda row: (
                -float(row["score"]),
                str(row["source_name"]).lower(),
                int(row["chunk_index"]),
            )
        )
        limited = results[:limit]
        return {
            **knowledge_view,
            "query": normalized_query,
            "results": limited,
            "result_count": len(results),
        }

    def equipment_list(self, project_id: str) -> list[dict[str, object]]:
        """Return structured equipment records for a project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return []
            records = list(
                session.scalars(
                    select(EquipmentRecord)
                    .where(EquipmentRecord.project_id == project.id)
                    .order_by(EquipmentRecord.equipment_key)
                )
            )
        return [self._equipment_row(record) for record in records]

    def points_list(self, project_id: str) -> list[dict[str, object]]:
        """Return structured point records for a project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return []
            records = list(
                session.scalars(
                    select(PointRecord)
                    .where(PointRecord.project_id == project.id)
                    .order_by(PointRecord.point_name)
                )
            )
        return [self._point_row(record) for record in records]

    def controllers_list(self, project_id: str) -> list[dict[str, object]]:
        """Return structured controller records for a project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return []
            records = list(
                session.scalars(
                    select(ControllerRecord)
                    .where(ControllerRecord.project_id == project.id)
                    .order_by(ControllerRecord.controller_key)
                )
            )
        return [self._controller_row(record) for record in records]

    def count_project_memberships(self, project_id: str) -> int:
        """Return membership count for a project."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return 0
            return session.scalar(
                select(func.count()).select_from(ProjectMembershipRecord).where(ProjectMembershipRecord.project_id == project.id)
            ) or 0

    def _apply_scope(self, statement, scope: ProjectQueryScope):
        if scope.allowed_project_ids is None:
            return statement
        return statement.where(ProjectRecord.project_id.in_(scope.allowed_project_ids))

    def project_cards_for_records(self, session, projects: list[ProjectRecord]) -> dict[str, dict[str, object]]:
        if not projects:
            return {}
        project_db_ids = [project.id for project in projects]
        equipment_counts = self._count_by_project(session, EquipmentRecord.project_id, EquipmentRecord, project_db_ids)
        point_counts = self._count_by_project(session, PointRecord.project_id, PointRecord, project_db_ids)
        controller_counts = self._count_by_project(session, ControllerRecord.project_id, ControllerRecord, project_db_ids)

        cards: dict[str, dict[str, object]] = {}
        for project in projects:
            metadata = project.metadata_json or {}
            cards[project.project_id] = {
                "project_id": project.project_id,
                "name": project.name,
                "client": project.client,
                "location": project.location,
                "status": project.status,
                "metadata": metadata,
                "equipment_count": equipment_counts.get(project.id, 0),
                "point_count": point_counts.get(project.id, 0),
                "controller_count": controller_counts.get(project.id, 0),
            }
        return cards

    def _count_by_project(self, session, column, model, project_db_ids: list[int]) -> dict[int, int]:
        rows = session.execute(
            select(column, func.count())
            .select_from(model)
            .where(column.in_(project_db_ids))
            .group_by(column)
        )
        counts: dict[int, int] = defaultdict(int)
        for project_id, count in rows:
            counts[project_id] = int(count)
        return counts

    def _task_to_view(self, task: TaskRecord) -> dict[str, object]:
        result_json = dict(task.result_json or {})
        result = dict(result_json.get("result") or {})
        import_result = dict(result.get("import_result") or {})
        parser_result = dict(result.get("parser_result") or {})
        warning_messages = list(import_result.get("warnings") or []) + list(parser_result.get("warnings") or [])
        error_messages = list(import_result.get("errors") or [])
        if result_json.get("error"):
            error_messages.append(str(result_json["error"]))
        outcome_summary = self._task_outcome_summary(task.task_type, task.payload_json or {}, result, import_result, parser_result)
        return {
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "payload": dict(task.payload_json or {}),
            "result": result,
            "error": result_json.get("error"),
            "status_history": list(result_json.get("status_history", [])),
            "artifact_diff": dict(result.get("artifact_diff") or {}),
            "generated_documents": list(result.get("generated_documents") or []),
            "outcome_summary": outcome_summary,
            "warning_messages": warning_messages,
            "error_messages": error_messages,
        }

    def _format_controller_address(self, address: dict[str, object]) -> str:
        protocol = str(address.get("protocol") or "").strip()
        raw_address = str(address.get("address") or "").strip()
        network_number = address.get("network_number")
        if network_number not in (None, ""):
            return f"{protocol} {raw_address} (net {network_number})".strip()
        return f"{protocol} {raw_address}".strip()

    def _tokenize_search_query(self, query: str) -> list[str]:
        return [term for term in re.findall(r"[A-Za-z0-9_/.-]+", query.lower()) if len(term) >= 2]

    def _knowledge_match_score(self, query: str, query_terms: list[str], chunk_text: str) -> float:
        lowered_chunk = chunk_text.lower()
        score = 0.0
        for term in query_terms:
            occurrences = lowered_chunk.count(term)
            if occurrences:
                score += 2.0 + min(occurrences, 5) * 0.5
        if query.lower() in lowered_chunk:
            score += 4.0
        return score

    def _build_knowledge_excerpt(self, chunk_text: str, query_terms: list[str], *, width: int = 220) -> str:
        lowered_chunk = chunk_text.lower()
        start = 0
        for term in query_terms:
            index = lowered_chunk.find(term)
            if index >= 0:
                start = max(0, index - 60)
                break
        excerpt = chunk_text[start:start + width].strip()
        if start > 0:
            excerpt = f"...{excerpt}"
        if start + width < len(chunk_text):
            excerpt = f"{excerpt}..."
        return excerpt

    def _build_equipment_review(self, payload: dict[str, object], *, linked_points_count: int) -> dict[str, object]:
        checks = [
            self._review_check("Assigned controller", bool(payload.get("controller_id")), payload.get("controller_id") or "Missing controller assignment"),
            self._review_check("Location context", bool(payload.get("building") or payload.get("floor") or payload.get("room")), self._join_review_values(payload.get("building"), payload.get("floor"), payload.get("room")) or "Missing building, floor, and room context"),
            self._review_check("Served area", bool(payload.get("served_area")), payload.get("served_area") or "Served area not defined"),
            self._review_check("Linked points", linked_points_count > 0, f"{linked_points_count} linked points" if linked_points_count else "No linked points"),
            self._review_check("Source provenance", bool((payload.get("provenance") or {}).get("source_name")), self._format_provenance(payload)),
        ]
        return self._finalize_review(checks, payload)

    def _build_point_review(self, payload: dict[str, object]) -> dict[str, object]:
        checks = [
            self._review_check("Equipment link", bool(payload.get("equipment_id")), payload.get("equipment_id") or "No equipment linked"),
            self._review_check("Controller link", bool(payload.get("controller_id")), payload.get("controller_id") or "No controller linked"),
            self._review_check("Units", bool(payload.get("units")), payload.get("units") or "Units not defined"),
            self._review_check("Protocol mapping", bool(payload.get("bacnet_object_type") or payload.get("modbus_register")), self._join_review_values(payload.get("bacnet_object_type"), payload.get("bacnet_instance"), payload.get("modbus_register")) or "No BACnet or Modbus mapping"),
            self._review_check("Source provenance", bool((payload.get("provenance") or {}).get("source_name")), self._format_provenance(payload)),
        ]
        return self._finalize_review(checks, payload)

    def _build_controller_review(self, payload: dict[str, object]) -> dict[str, object]:
        protocols = list(payload.get("protocols") or [])
        network_addresses = list(payload.get("network_addresses") or [])
        checks = [
            self._review_check("Protocols", bool(protocols), ", ".join(str(protocol) for protocol in protocols) if protocols else "No controller protocols"),
            self._review_check("Network addresses", bool(network_addresses), ", ".join(self._format_controller_address(address) for address in network_addresses) if network_addresses else "No network addresses"),
            self._review_check("Served equipment", bool(payload.get("serves_equipment_ids")), f"{len(payload.get('serves_equipment_ids', []))} linked equipment" if payload.get("serves_equipment_ids") else "No served equipment linked"),
            self._review_check("Owned points", bool(payload.get("owned_point_names")), f"{len(payload.get('owned_point_names', []))} owned points" if payload.get("owned_point_names") else "No owned points"),
            self._review_check("Source provenance", bool((payload.get("provenance") or {}).get("source_name")), self._format_provenance(payload)),
        ]
        return self._finalize_review(checks, payload)

    def _review_check(self, label: str, passed: bool, detail: object) -> dict[str, object]:
        return {
            "label": label,
            "status": "ready" if passed else "attention",
            "detail": str(detail),
        }

    def _finalize_review(self, checks: list[dict[str, object]], payload: dict[str, object]) -> dict[str, object]:
        ready_count = sum(1 for check in checks if check["status"] == "ready")
        total = len(checks) or 1
        score_pct = int(round((ready_count / total) * 100))
        if score_pct >= 80:
            status = "ready"
        elif score_pct >= 50:
            status = "partial"
        else:
            status = "needs_attention"
        return {
            "status": status,
            "score_pct": score_pct,
            "ready_count": ready_count,
            "total_checks": total,
            "provenance": self._format_provenance(payload),
            "checks": checks,
        }

    def _format_provenance(self, payload: dict[str, object]) -> str:
        provenance = dict(payload.get("provenance") or {})
        parser_name = provenance.get("parser")
        source_name = provenance.get("source_name")
        return self._join_review_values(parser_name, source_name) or "No explicit provenance"

    def _join_review_values(self, *values: object) -> str:
        parts = [str(value) for value in values if value not in (None, "", [], {})]
        return " · ".join(parts)

    def _build_project_engineering_status(
        self,
        *,
        equipment_records: list[EquipmentRecord],
        controller_records: list[ControllerRecord],
        point_count: int,
        documents: list[DocumentRecord],
        knowledge: list[KnowledgeRecord],
        tasks: list[TaskRecord],
        artifact_link_count: int,
    ) -> dict[str, object]:
        equipment_total = len(equipment_records)
        controllers_total = len(controller_records)
        knowledge_indexed = sum(1 for record in knowledge if record.status == "indexed")
        failed_tasks = [task for task in tasks if task.status in {"failed", "error"}]
        equipment_with_controller = sum(
            1 for record in equipment_records if (record.payload_json or {}).get("controller_id")
        )
        controllers_with_addresses = sum(
            1 for record in controller_records if (record.payload_json or {}).get("network_addresses")
        )

        checks = [
            self._project_status_check(
                "Equipment imported",
                equipment_total > 0,
                f"{equipment_total} equipment objects loaded" if equipment_total else "No equipment imported yet",
            ),
            self._project_status_check(
                "Controller assignment coverage",
                equipment_total == 0 or equipment_with_controller == equipment_total,
                self._coverage_detail(equipment_with_controller, equipment_total, "equipment assigned to controllers"),
            ),
            self._project_status_check(
                "Point coverage",
                point_count > 0,
                f"{point_count} structured points loaded" if point_count else "No points imported yet",
            ),
            self._project_status_check(
                "Controller addressing",
                controllers_total == 0 or controllers_with_addresses == controllers_total,
                self._coverage_detail(controllers_with_addresses, controllers_total, "controllers with network addresses"),
            ),
            self._project_status_check(
                "Knowledge indexed",
                not documents or knowledge_indexed > 0,
                self._coverage_detail(knowledge_indexed, len(knowledge), "knowledge records indexed"),
            ),
            self._project_status_check(
                "Artifact lineage",
                artifact_link_count > 0,
                f"{artifact_link_count} artifact links recorded" if artifact_link_count else "No artifact links recorded yet",
            ),
            self._project_status_check(
                "Task failures",
                not failed_tasks,
                f"{len(failed_tasks)} failed tasks" if failed_tasks else "No failed tasks recorded",
            ),
        ]
        ready_count = sum(1 for check in checks if check["status"] == "ready")
        score_pct = int(round((ready_count / len(checks)) * 100)) if checks else 0
        if score_pct >= 85:
            status = "ready"
        elif score_pct >= 55:
            status = "partial"
        else:
            status = "needs_attention"
        return {
            "status": status,
            "score_pct": score_pct,
            "checks": checks,
            "equipment_with_controller": equipment_with_controller,
            "equipment_total": equipment_total,
            "controllers_with_addresses": controllers_with_addresses,
            "controllers_total": controllers_total,
            "knowledge_indexed": knowledge_indexed,
            "knowledge_total": len(knowledge),
            "failed_task_count": len(failed_tasks),
            "artifact_link_count": artifact_link_count,
        }

    def _project_status_check(self, label: str, passed: bool, detail: str) -> dict[str, object]:
        return {"label": label, "status": "ready" if passed else "attention", "detail": detail}

    def _coverage_detail(self, complete: int, total: int, noun: str) -> str:
        if total == 0:
            return f"0 of 0 {noun}"
        return f"{complete} of {total} {noun}"

    def _build_import_activity(self, tasks: list[TaskRecord]) -> dict[str, object]:
        relevant_types = {"equipment_import", "points_import", "controllers_import", "artifact_ingestion"}
        import_tasks = [task for task in tasks if task.task_type in relevant_types]
        warning_items: list[dict[str, object]] = []
        completed_imports = 0

        for task in import_tasks:
            result_json = dict(task.result_json or {})
            result = dict(result_json.get("result") or {})
            filename = (task.payload_json or {}).get("filename") or task.task_type

            import_result = dict(result.get("import_result") or {})
            parser_result = dict(result.get("parser_result") or {})

            import_warnings = list(import_result.get("warnings") or [])
            import_errors = list(import_result.get("errors") or [])
            parser_warnings = list(parser_result.get("warnings") or [])

            if task.status == "completed":
                completed_imports += 1

            for warning in import_warnings + parser_warnings:
                warning_items.append(
                    {
                        "task_type": task.task_type,
                        "filename": filename,
                        "message": warning,
                        "updated_at": task.updated_at,
                    }
                )
            for error in import_errors:
                warning_items.append(
                    {
                        "task_type": task.task_type,
                        "filename": filename,
                        "message": error,
                        "updated_at": task.updated_at,
                        "severity": "error",
                    }
                )

        warning_items.sort(key=lambda item: item["updated_at"], reverse=True)
        return {
            "task_count": len(import_tasks),
            "completed_count": completed_imports,
            "warning_count": sum(1 for item in warning_items if item.get("severity") != "error"),
            "error_count": sum(1 for item in warning_items if item.get("severity") == "error"),
            "items": warning_items[:8],
        }

    def _task_outcome_summary(
        self,
        task_type: str,
        payload: dict[str, object],
        result: dict[str, object],
        import_result: dict[str, object],
        parser_result: dict[str, object],
    ) -> dict[str, object]:
        filename = str(payload.get("filename") or "")
        metrics: list[dict[str, object]] = []
        summary_text = filename or task_type

        if import_result:
            count = import_result.get("count")
            summary_text = str(import_result.get("message") or summary_text)
            metrics.append({"label": "Imported", "value": count if count not in (None, "") else "-"})
            metrics.append({"label": "Warnings", "value": len(import_result.get("warnings") or [])})
            metrics.append({"label": "Errors", "value": len(import_result.get("errors") or [])})
        elif parser_result:
            summary_text = filename or "Parsed supporting artifact"
            metrics.append({"label": "Equipment", "value": parser_result.get("equipment_added", 0)})
            metrics.append({"label": "Points", "value": parser_result.get("points_added", 0)})
            metrics.append({"label": "Controllers", "value": parser_result.get("controllers_added", 0)})
            metrics.append({"label": "Warnings", "value": len(parser_result.get("warnings") or [])})
        elif result.get("generated_documents"):
            summary_text = f"{len(result.get('generated_documents') or [])} generated documents"
            metrics.append({"label": "Generated", "value": len(result.get("generated_documents") or [])})
        elif result.get("knowledge_status"):
            summary_text = f"Knowledge status: {result.get('knowledge_status')}"
            metrics.append({"label": "Chunks", "value": result.get("chunk_count", 0)})
        else:
            summary_text = filename or task_type

        return {
            "filename": filename,
            "summary_text": summary_text,
            "metrics": metrics,
        }

    def artifact_links_for_entity(self, project_id: str, entity_type: str, entity_key: str) -> list[dict[str, object]]:
        """Return explicit artifact links for an entity."""
        with self.db.session() as session:
            project = self._project_record(session, project_id)
            if project is None:
                return []
            rows = list(
                session.execute(
                    select(
                        ArtifactObjectLinkRecord.parser_name,
                        ArtifactObjectLinkRecord.relationship_type,
                        ArtifactObjectLinkRecord.metadata_json,
                        DocumentRecord.name,
                        DocumentRecord.document_type,
                    )
                    .join(DocumentRecord, ArtifactObjectLinkRecord.document_id == DocumentRecord.id)
                    .where(
                        ArtifactObjectLinkRecord.project_id == project.id,
                        ArtifactObjectLinkRecord.entity_type == entity_type,
                        ArtifactObjectLinkRecord.entity_key == entity_key,
                    )
                    .order_by(ArtifactObjectLinkRecord.created_at.desc())
                )
            )
        return [
            {
                "parser_name": parser_name,
                "relationship_type": relationship_type,
                "metadata": dict(metadata_json or {}),
                "document_name": document_name,
                "document_type": document_type,
            }
            for parser_name, relationship_type, metadata_json, document_name, document_type in rows
        ]

    def _project_record(self, session, project_id: str) -> ProjectRecord | None:
        return session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))

    def _detail_equipment_row(self, record: EquipmentRecord) -> dict[str, object]:
        payload = dict(record.payload_json or {})
        return {
            "id": record.equipment_key,
            "type": record.equipment_type,
            "building": payload.get("building"),
            "controller_id": payload.get("controller_id"),
            "graphic_sections": ((payload.get("template") or {}).get("parameters") or {}).get("graphic_sections", ""),
            "point_count": len(payload.get("point_names", [])),
            "status": record.status,
            "provenance": dict(payload.get("provenance") or {}),
        }

    def _equipment_row(self, record: EquipmentRecord) -> dict[str, object]:
        payload = dict(record.payload_json or {})
        return {
            "id": record.equipment_key,
            "type": record.equipment_type,
            "controller": payload.get("controller_id"),
            "points": len(payload.get("point_names", [])),
            "status": record.status,
            "parent": record.parent_equipment_key,
            "source_name": (payload.get("provenance") or {}).get("source_name"),
        }

    def _point_row(self, record: PointRecord) -> dict[str, object]:
        payload = dict(record.payload_json or {})
        return {
            "name": record.point_name,
            "equipment": record.equipment_key,
            "kind": record.point_kind,
            "units": record.units,
            "controller": record.controller_key,
            "source_name": (payload.get("provenance") or {}).get("source_name"),
        }

    def _controller_row(self, record: ControllerRecord) -> dict[str, object]:
        payload = dict(record.payload_json or {})
        return {
            "id": record.controller_key,
            "type": record.controller_type,
            "protocols": list(payload.get("protocols") or ([record.protocol] if record.protocol else [])),
            "addresses": [
                self._format_controller_address(address)
                for address in payload.get("network_addresses", [])
            ],
            "equipment": len(payload.get("serves_equipment_ids", [])),
            "points": len(payload.get("owned_point_names", [])),
            "source_name": (payload.get("provenance") or {}).get("source_name"),
        }

    def _knowledge_row(self, record: KnowledgeRecord) -> dict[str, object]:
        return {
            "id": record.id,
            "source_name": record.source_name,
            "source_type": record.source_type,
            "status": record.status,
            "chunk_count": record.chunk_count,
            "content_hash": record.content_hash,
            "metadata": dict(record.metadata_json or {}),
            "created_at": record.created_at,
        }
