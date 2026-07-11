"""Project model - top-level BAS project structure."""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from . import NonEmptyStr, UnitSystem
from .equipment import Equipment
from .points import Point
from .controller import Controller


class ProjectMetadata(BaseModel):
    """Project metadata and identification."""

    project_id: NonEmptyStr
    name: NonEmptyStr
    number: Optional[str] = None
    client: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    unit_system: UnitSystem = UnitSystem.IP

    # Dates
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    design_phase: Optional[str] = None  # SD, DD, CD, CA

    # Standards
    naming_standard: Optional[str] = None
    bacnet_network_number: Optional[int] = None

    # Team
    engineer_of_record: Optional[str] = None
    programmer: Optional[str] = None
    commissioning_agent: Optional[str] = None


class SourceDocument(BaseModel):
    """Reference to a source document."""

    id: NonEmptyStr
    name: str
    type: str = Field(description="point_list, equipment_schedule, sequence, drawing, submittal")
    path: Optional[str] = None
    version: Optional[str] = None
    imported_at: datetime = Field(default_factory=datetime.now)
    hash: Optional[str] = None  # For change detection


class Project(BaseModel):
    """Top-level BAS project container."""

    # Metadata
    metadata: ProjectMetadata

    # Core models
    equipment: list[Equipment] = Field(default_factory=list)
    points: list[Point] = Field(default_factory=list)
    controllers: list[Controller] = Field(default_factory=list)

    # Source documents
    source_documents: list[SourceDocument] = Field(default_factory=list)

    # Validation state
    validation_status: str = Field(default="pending", description="pending, valid, invalid")
    last_validated: Optional[datetime] = None

    def add_equipment(self, equipment: Equipment) -> None:
        """Add equipment to project."""
        # Check for duplicate ID
        existing = next((e for e in self.equipment if e.id == equipment.id), None)
        if existing:
            raise ValueError(f"Equipment with ID '{equipment.id}' already exists")
        self.equipment.append(equipment)

    def add_point(self, point: Point) -> None:
        """Add point to project."""
        existing = next((p for p in self.points if p.name == point.name), None)
        if existing:
            raise ValueError(f"Point with name '{point.name}' already exists")
        self.points.append(point)

    def add_controller(self, controller: Controller) -> None:
        """Add controller to project."""
        existing = next((c for c in self.controllers if c.id == controller.id), None)
        if existing:
            raise ValueError(f"Controller with ID '{controller.id}' already exists")
        self.controllers.append(controller)

    def get_equipment(self, equipment_id: str) -> Optional[Equipment]:
        return next((e for e in self.equipment if e.id == equipment_id), None)

    def get_point(self, point_name: str) -> Optional[Point]:
        return next((p for p in self.points if p.name == point_name), None)

    def get_controller(self, controller_id: str) -> Optional[Controller]:
        return next((c for c in self.controllers if c.id == controller_id), None)

    def get_points_for_equipment(self, equipment_id: str) -> list[Point]:
        return [p for p in self.points if p.equipment_id == equipment_id]

    def get_points_for_controller(self, controller_id: str) -> list[Point]:
        return [p for p in self.points if p.controller_id == controller_id]

    def get_equipment_for_controller(self, controller_id: str) -> list[Equipment]:
        return [e for e in self.equipment if e.controller_id == controller_id]

    def update_timestamp(self) -> None:
        self.metadata.updated_at = datetime.now()


__all__ = ["Project", "ProjectMetadata", "SourceDocument"]