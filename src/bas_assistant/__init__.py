"""BAS Assistant - Building Automation System Programming Assistant."""

from .models import (
    Project,
    ProjectMetadata,
    SourceDocument,
    Equipment,
    EquipmentType,
    EquipmentRelationship,
    EquipmentTemplateRef,
    Point,
    PointKind,
    PointDirection,
    PointSource,
    PointValidationIssue,
    Controller,
    ControllerNetworkAddress,
    ControllerIOCapacity,
    Protocol,
    ValidationSeverity,
    ValidationCategory,
    UnitSystem,
)

from .validation import (
    ValidationEngine,
    ValidationRule,
    ValidationResult,
    ValidationReport,
    BUILTIN_RULES,
)

from .importers import (
    CSVImporter,
    ImportResult,
    create_sample_csvs,
)

__version__ = "0.1.0"

__all__ = [
    # Models
    "Project",
    "ProjectMetadata",
    "SourceDocument",
    "Equipment",
    "EquipmentType",
    "EquipmentRelationship",
    "EquipmentTemplateRef",
    "Point",
    "PointKind",
    "PointDirection",
    "PointSource",
    "PointValidationIssue",
    "Controller",
    "ControllerNetworkAddress",
    "ControllerIOCapacity",
    "Protocol",
    "ValidationSeverity",
    "ValidationCategory",
    "UnitSystem",
    # Validation
    "ValidationEngine",
    "ValidationRule",
    "ValidationResult",
    "ValidationReport",
    "BUILTIN_RULES",
    # Importers
    "CSVImporter",
    "ImportResult",
    "create_sample_csvs",
]