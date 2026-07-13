"""Core models package for BAS Assistant."""

from .types import (
    EquipmentType,
    NonEmptyStr,
    NonNegInt,
    PointDirection,
    PointKind,
    PointSource,
    PositiveFloat,
    Protocol,
    UnitSystem,
    ValidationCategory,
    ValidationSeverity,
)

# Types & Enums (from types module)
from .checkout import CheckoutItem, CheckoutReport, CheckoutSheet
from .controller import Controller, ControllerIOCapacity, ControllerNetworkAddress
from .equipment import Equipment, EquipmentRelationship, EquipmentTemplateRef
from .graphics import GraphicBinding, GraphicDefinition, GraphicElement, GraphicNavigation
from .logic import LogicBlock, LogicConnection, LogicDiagram, LogicParameter, LogicSignal
from .points import Point, PointValidationIssue
from .station_sync import (
    StationConnectionConfig,
    StationProbeResult,
    StationSyncPlan,
    StationSyncPlanItem,
    StationSyncProtocol,
    StationSyncTarget,
)

# Model classes
from .project import Project, ProjectMetadata, SourceDocument

__all__ = [
    # Types & Enums
    "PointKind",
    "PointDirection",
    "PointSource",
    "EquipmentType",
    "Protocol",
    "ValidationSeverity",
    "ValidationCategory",
    "UnitSystem",
    "NonEmptyStr",
    "PositiveFloat",
    "NonNegInt",
    # Models
    "Project",
    "ProjectMetadata",
    "SourceDocument",
    "Equipment",
    "EquipmentRelationship",
    "EquipmentTemplateRef",
    "Point",
    "PointValidationIssue",
    "StationConnectionConfig",
    "StationProbeResult",
    "StationSyncPlan",
    "StationSyncPlanItem",
    "StationSyncProtocol",
    "StationSyncTarget",
    "Controller",
    "ControllerNetworkAddress",
    "ControllerIOCapacity",
    "CheckoutItem",
    "CheckoutSheet",
    "CheckoutReport",
    "LogicSignal",
    "LogicParameter",
    "LogicConnection",
    "LogicBlock",
    "LogicDiagram",
    "GraphicElement",
    "GraphicBinding",
    "GraphicNavigation",
    "GraphicDefinition",
]
