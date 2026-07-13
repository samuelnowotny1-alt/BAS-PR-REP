"""Upload persistence services."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import desc, select

from bas_assistant.database import DatabaseManager, DocumentRecord, ProjectRecord, UploadRecord
from bas_assistant.models import Project, SourceDocument


class UploadService:
    """Persist uploaded artifacts to disk and index them in the database."""

    def __init__(self, uploads_dir: Path, db: DatabaseManager) -> None:
        self.uploads_dir = uploads_dir
        self.db = db
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    async def save_project_upload(
        self,
        *,
        project: Project,
        upload: UploadFile,
        category: str,
        document_type: str,
    ) -> Path:
        """Store an uploaded file and record it in database and project metadata."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = Path(upload.filename or f"{category}.bin").name
        stored_name = f"{timestamp}-{uuid4().hex[:8]}-{safe_name}"
        target_dir = self.uploads_dir / project.metadata.project_id / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / stored_name
        content = upload.file.read()
        target_path.write_bytes(content)
        upload.file.seek(0)

        source_document = SourceDocument(
            id=f"{category}-{uuid4().hex[:10]}",
            name=safe_name,
            type=document_type,
            path=str(target_path),
        )
        existing = next((doc for doc in project.source_documents if doc.name == safe_name and doc.type == document_type), None)
        if existing is None:
            project.source_documents.append(source_document)
        else:
            existing.path = str(target_path)
            existing.imported_at = source_document.imported_at

        with self.db.session() as session:
            project_record = session.scalar(
                select(ProjectRecord).where(ProjectRecord.project_id == project.metadata.project_id)
            )
            project_db_id = project_record.id if project_record is not None else None
            session.add(
                UploadRecord(
                    project_id=project_db_id,
                    filename=safe_name,
                    media_type=upload.content_type,
                    category=category,
                    stored_path=str(target_path),
                    status="processed",
                    metadata_json={"project_id": project.metadata.project_id, "document_type": document_type},
                )
            )
            session.add(
                DocumentRecord(
                    project_id=project_db_id,
                    external_id=source_document.id,
                    name=safe_name,
                    document_type=document_type,
                    file_path=str(target_path),
                    metadata_json={"project_id": project.metadata.project_id, "category": category},
                )
            )
        return target_path

    def list_recent_uploads(self, *, project_id: str | None = None, limit: int = 10) -> list[UploadRecord]:
        """Return recent uploads globally or for a project."""
        with self.db.session() as session:
            statement = select(UploadRecord).order_by(desc(UploadRecord.created_at)).limit(limit)
            if project_id is not None:
                project_record = session.scalar(
                    select(ProjectRecord).where(ProjectRecord.project_id == project_id)
                )
                if project_record is None:
                    return []
                statement = statement.where(UploadRecord.project_id == project_record.id)
            return list(session.scalars(statement))
