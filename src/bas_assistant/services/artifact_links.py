"""Artifact linkage and reimport diff services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select

from bas_assistant.database import ArtifactObjectLinkRecord, DatabaseManager, DocumentRecord, ProjectRecord


@dataclass(slots=True)
class ArtifactEntityLink:
    """Explicit mapping from an artifact to a structured BAS object."""

    entity_type: str
    entity_key: str
    relationship_type: str = "source"
    parser_name: str | None = None
    metadata: dict[str, Any] | None = None


class ArtifactLinkService:
    """Manage explicit artifact-to-object links and reimport diffs."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def replace_links_for_document(
        self,
        *,
        project_id: str,
        document_id: int | None,
        upload_id: int | None,
        parser_name: str | None,
        links: list[ArtifactEntityLink],
    ) -> None:
        """Replace all links for a specific document."""
        if document_id is None:
            return
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            project_db_id = project.id if project is not None else None
            session.execute(delete(ArtifactObjectLinkRecord).where(ArtifactObjectLinkRecord.document_id == document_id))
            deduped_links: dict[tuple[str, str, str], ArtifactEntityLink] = {}
            for link in links:
                deduped_links[(link.entity_type, link.entity_key, link.relationship_type)] = link
            for link in deduped_links.values():
                session.add(
                    ArtifactObjectLinkRecord(
                        project_id=project_db_id,
                        document_id=document_id,
                        upload_id=upload_id,
                        entity_type=link.entity_type,
                        entity_key=link.entity_key,
                        relationship_type=link.relationship_type,
                        parser_name=link.parser_name or parser_name,
                        metadata_json=dict(link.metadata or {}),
                    )
                )

    def diff_against_previous_document(
        self,
        *,
        document_id: int | None,
    ) -> dict[str, list[str]]:
        """Return added, removed, and unchanged entity keys compared with the previous same-named document."""
        if document_id is None:
            return {"added": [], "removed": [], "unchanged": []}
        with self.db.session() as session:
            current = session.get(DocumentRecord, document_id)
            if current is None:
                return {"added": [], "removed": [], "unchanged": []}
            previous = session.scalar(
                select(DocumentRecord)
                .where(
                    DocumentRecord.project_id == current.project_id,
                    DocumentRecord.name == current.name,
                    DocumentRecord.document_type == current.document_type,
                    DocumentRecord.id != current.id,
                )
                .order_by(DocumentRecord.created_at.desc())
            )
            current_links = list(
                session.scalars(
                    select(ArtifactObjectLinkRecord)
                    .where(ArtifactObjectLinkRecord.document_id == current.id)
                )
            )
            previous_links = []
            if previous is not None:
                previous_links = list(
                    session.scalars(
                        select(ArtifactObjectLinkRecord)
                        .where(ArtifactObjectLinkRecord.document_id == previous.id)
                    )
                )

        current_keys = {f"{link.entity_type}:{link.entity_key}" for link in current_links}
        previous_keys = {f"{link.entity_type}:{link.entity_key}" for link in previous_links}
        return {
            "added": sorted(current_keys - previous_keys),
            "removed": sorted(previous_keys - current_keys),
            "unchanged": sorted(current_keys & previous_keys),
        }

    def links_for_entity(self, *, project_id: str, entity_type: str, entity_key: str) -> list[dict[str, Any]]:
        """Return linked artifacts for a structured entity."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return []
            rows = list(
                session.execute(
                    select(
                        ArtifactObjectLinkRecord.entity_type,
                        ArtifactObjectLinkRecord.entity_key,
                        ArtifactObjectLinkRecord.relationship_type,
                        ArtifactObjectLinkRecord.parser_name,
                        ArtifactObjectLinkRecord.metadata_json,
                        DocumentRecord.name,
                        DocumentRecord.document_type,
                        DocumentRecord.file_path,
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
                "relationship_type": relationship_type,
                "parser_name": parser_name,
                "metadata": dict(metadata_json or {}),
                "document_name": document_name,
                "document_type": document_type,
                "file_path": file_path,
            }
            for _entity_type, _entity_key, relationship_type, parser_name, metadata_json, document_name, document_type, file_path in rows
        ]
