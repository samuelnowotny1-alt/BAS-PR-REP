"""Core models package for BAS Assistant."""

# Types & Enums (from types module)
from .types import (
    PointKind,
    PointDirection,
    PointSource,
    EquipmentType,
    Protocol,
    ValidationSeverity,
    ValidationCategory,
    UnitSystem,
    NonEmptyStr,
    PositiveFloat,
    NonNegInt,
)

# Model classes
from .project import Project, ProjectMetadata, SourceDocument
from .equipment import Equipment, EquipmentRelationship, EquipmentTemplateRef
from .points import Point, PointValidationIssue
from .controller import Controller, ControllerNetworkAddress, ControllerIOCapacity
from .checkout import CheckoutItem, CheckoutSheet, CheckoutReport
from .logic import LogicSignal, LogicParameter, LogicConnection, LogicBlock, LogicDiagram
from .graphics import GraphicElement, GraphicBinding, GraphicNavigation, GraphicDefinition

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