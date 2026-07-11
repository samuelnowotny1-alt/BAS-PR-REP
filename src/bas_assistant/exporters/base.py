"""Base exporter classes and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List


@dataclass
class ExportResult:
    """Result of an export operation."""
    success: bool
    message: str
    files: List = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ExportContext:
    """Shared context for all exports."""
    project: object
    output_dir: Path
    timestamp: datetime = field(default_factory=datetime.now)
    options: dict = field(default_factory=dict)


class BaseExporter(ABC):
    """Abstract base class for all vendor exporters."""

    def __init__(self, project: object):
        self.project = project

    @property
    @abstractmethod
    def vendor_name(self) -> str:
        """Vendor name (e.g., 'Niagara', 'BACnet', 'JCI')."""
        pass

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """Default file extension for this vendor."""
        pass

    @abstractmethod
    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        """Export project to vendor format."""
        pass

    def _ensure_output_dir(self, output_dir: Path) -> Path:
        """Ensure output directory exists."""
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
