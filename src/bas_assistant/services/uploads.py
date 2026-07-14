"""Upload persistence services."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import desc, select

from bas_assistant.database import DatabaseManager, DocumentRecord, ProjectRecord, UploadRecord
from bas_assistant.models import Project, SourceDocument


@dataclass(slots=True)
class StoredUpload:
    """Persisted upload metadata returned to route handlers."""

    path: Path
    source_document: SourceDocument
    category: str
    document_type: str
    media_type: str | None
    metadata: dict[str, Any]
    upload_record_id: int | None
    document_record_id: int | None


class UploadService:
    """Persist uploaded artifacts to disk and index them in the database."""

    DOCUMENT_TYPE_BY_SUFFIX = {
        ".csv": "tabular_data",
        ".xlsx": "tabular_data",
        ".xls": "tabular_data",
        ".xlsm": "tabular_data",
        ".txt": "text_document",
        ".md": "markdown_document",
        ".markdown": "markdown_document",
        ".pdf": "pdf_document",
        ".json": "json_document",
        ".xml": "xml_document",
        ".px": "px_graphic",
        ".zip": "archive",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".gif": "image",
    }

    def __init__(self, uploads_dir: Path, db: DatabaseManager) -> None:
        self.uploads_dir = uploads_dir
        self.db = db
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    async def save_project_upload(
        self,
        *,
        project: Project,
        upload: UploadFile,
        category: str | None = None,
        document_type: str | None = None,
    ) -> StoredUpload:
        """Store an uploaded file and record it in database and project metadata."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = Path(upload.filename or f"{category}.bin").name
        suffix = Path(safe_name).suffix.lower()
        resolved_category = category or self._default_category_for_suffix(suffix)
        resolved_document_type = document_type or self.DOCUMENT_TYPE_BY_SUFFIX.get(suffix, "binary_document")
        stored_name = f"{timestamp}-{uuid4().hex[:8]}-{safe_name}"
        target_dir = self.uploads_dir / project.metadata.project_id / resolved_category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / stored_name
        content = upload.file.read()
        target_path.write_bytes(content)
        upload.file.seek(0)
        checksum = hashlib.sha256(content).hexdigest()

        source_document = SourceDocument(
            id=f"{resolved_category}-{uuid4().hex[:10]}",
            name=safe_name,
            type=resolved_document_type,
            path=str(target_path),
            hash=checksum,
        )
        existing = next(
            (doc for doc in project.source_documents if doc.name == safe_name and doc.type == resolved_document_type),
            None,
        )
        if existing is None:
            project.source_documents.append(source_document)
        else:
            existing.path = str(target_path)
            existing.imported_at = source_document.imported_at
            existing.hash = checksum

        metadata = {
            "project_id": project.metadata.project_id,
            "document_type": resolved_document_type,
            "checksum": checksum,
        }
        upload_record_id = None
        document_record_id = None
        with self.db.session() as session:
            project_record = session.scalar(
                select(ProjectRecord).where(ProjectRecord.project_id == project.metadata.project_id)
            )
            project_db_id = project_record.id if project_record is not None else None
            previous_document = session.scalar(
                select(DocumentRecord)
                .where(
                    DocumentRecord.project_id == project_db_id,
                    DocumentRecord.name == safe_name,
                    DocumentRecord.document_type == resolved_document_type,
                )
                .order_by(DocumentRecord.created_at.desc())
            )
            if previous_document is not None:
                metadata["previous_document_id"] = previous_document.id
                metadata["previous_checksum"] = previous_document.checksum
                metadata["is_reimport"] = True
                metadata["checksum_changed"] = previous_document.checksum != checksum
            upload_record = UploadRecord(
                project_id=project_db_id,
                filename=safe_name,
                media_type=upload.content_type,
                category=resolved_category,
                stored_path=str(target_path),
                status="processed",
                metadata_json=metadata,
            )
            session.add(upload_record)
            session.flush()
            upload_record_id = upload_record.id
            document_record = DocumentRecord(
                project_id=project_db_id,
                external_id=source_document.id,
                name=safe_name,
                document_type=resolved_document_type,
                file_path=str(target_path),
                checksum=checksum,
                metadata_json={**metadata, "category": resolved_category},
            )
            session.add(document_record)
            session.flush()
            document_record_id = document_record.id
        return StoredUpload(
            path=target_path,
            source_document=source_document,
            category=resolved_category,
            document_type=resolved_document_type,
            media_type=upload.content_type,
            metadata=metadata,
            upload_record_id=upload_record_id,
            document_record_id=document_record_id,
        )

    def list_recent_uploads(
        self,
        *,
        project_id: str | None = None,
        project_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[UploadRecord]:
        """Return recent uploads globally or for a project."""
        with self.db.session() as session:
            statement = select(UploadRecord)
            if project_id is not None:
                statement = statement.join(ProjectRecord, UploadRecord.project_id == ProjectRecord.id).where(
                    ProjectRecord.project_id == project_id
                )
            elif project_ids:
                statement = statement.join(ProjectRecord, UploadRecord.project_id == ProjectRecord.id).where(
                    ProjectRecord.project_id.in_(project_ids)
                )
            statement = statement.order_by(desc(UploadRecord.created_at)).limit(limit)
            return list(session.scalars(statement))

    def _default_category_for_suffix(self, suffix: str) -> str:
        if suffix in {".csv", ".xlsx", ".xls", ".xlsm"}:
            return "documents"
        if suffix in {".px", ".svg", ".png", ".jpg", ".jpeg", ".gif"}:
            return "graphics"
        if suffix in {".zip"}:
            return "archives"
        return "documents"
