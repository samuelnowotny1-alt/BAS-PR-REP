"""Knowledge ingestion services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from bas_assistant.database import DatabaseManager, KnowledgeRecord, ProjectRecord
from bas_assistant.models import Project


@dataclass(slots=True)
class KnowledgeIngestionResult:
    """Outcome of a knowledge ingestion attempt."""

    status: str
    chunk_count: int
    content_hash: str | None
    metadata: dict[str, Any]


class KnowledgeIngestionService:
    """Extract and persist searchable knowledge metadata from uploaded artifacts."""

    SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".xml", ".yaml", ".yml", ".csv"}
    SUPPORTED_TABULAR_SUFFIXES = {".xlsx", ".xls", ".xlsm"}

    def __init__(self, db: DatabaseManager, *, chunk_size: int = 1200) -> None:
        self.db = db
        self.chunk_size = chunk_size

    def ingest_document(
        self,
        *,
        project: Project,
        file_path: Path,
        source_name: str,
        source_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeIngestionResult:
        """Ingest a stored document into the knowledge index."""
        file_path = Path(file_path)
        base_metadata = dict(metadata or {})
        extracted_text, status = self._extract_text(file_path)
        content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest() if extracted_text else None
        chunks = self._chunk_text(extracted_text)
        payload = {
            **base_metadata,
            "file_path": str(file_path),
            "source_name": source_name,
            "source_type": source_type,
            "char_count": len(extracted_text),
            "chunks": chunks,
        }

        with self.db.session() as session:
            project_record = session.scalar(
                select(ProjectRecord).where(ProjectRecord.project_id == project.metadata.project_id)
            )
            project_db_id = project_record.id if project_record is not None else None
            record = session.scalar(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.project_id == project_db_id,
                    KnowledgeRecord.source_name == source_name,
                    KnowledgeRecord.source_type == source_type,
                )
            )
            if record is None:
                session.add(
                    KnowledgeRecord(
                        project_id=project_db_id,
                        source_name=source_name,
                        source_type=source_type,
                        content_hash=content_hash,
                        metadata_json=payload,
                        chunk_count=len(chunks),
                        status=status,
                    )
                )
            else:
                record.content_hash = content_hash
                record.metadata_json = payload
                record.chunk_count = len(chunks)
                record.status = status
        return KnowledgeIngestionResult(
            status=status,
            chunk_count=len(chunks),
            content_hash=content_hash,
            metadata=payload,
        )

    def _extract_text(self, file_path: Path) -> tuple[str, str]:
        suffix = file_path.suffix.lower()
        if suffix in self.SUPPORTED_TEXT_SUFFIXES:
            try:
                return file_path.read_text(encoding="utf-8"), "indexed"
            except UnicodeDecodeError:
                return file_path.read_text(encoding="utf-8", errors="ignore"), "indexed"
        if suffix in self.SUPPORTED_TABULAR_SUFFIXES:
            dataframe = pd.read_excel(file_path)
            return dataframe.to_csv(index=False), "indexed"
        if suffix in {".pdf"}:
            return "", "pending_parser"
        return "", "stored"

    def _chunk_text(self, text: str) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return []
        if len(normalized) <= self.chunk_size:
            return [normalized]
        chunks: list[str] = []
        cursor = 0
        while cursor < len(normalized):
            chunk = normalized[cursor:cursor + self.chunk_size].strip()
            if chunk:
                chunks.append(chunk)
            cursor += self.chunk_size
        return chunks
