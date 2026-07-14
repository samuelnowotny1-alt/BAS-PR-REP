"""Project model - top-level BAS project structure."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from . import NonEmptyStr, UnitSystem
from .controller import Controller
from .equipment import Equipment
from .points import Point
from .station_sync import StationConnectionConfig


class ProjectMetadata(BaseModel):
    """Project metadata and identification."""

    project_id: NonEmptyStr
    name: NonEmptyStr
    number: str | None = None
    client: str | None = None
    location: str | None = None
    timezone: str | None = None
    unit_system: UnitSystem = UnitSystem.IP

    # Dates
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    design_phase: str | None = None  # SD, DD, CD, CA

    # Standards
    naming_standard: str | None = None
    bacnet_network_number: int | None = None

    # Team
    engineer_of_record: str | None = None
    programmer: str | None = None
    commissioning_agent: str | None = None


class SourceDocument(BaseModel):
    """Reference to a source document."""

    id: NonEmptyStr
    name: str
    type: str = Field(description="point_list, equipment_schedule, sequence, drawing, submittal")
    path: str | None = None
    version: str | None = None
    imported_at: datetime = Field(default_factory=datetime.now)
    hash: str | None = None  # For change detection


class ReviewDecisionType(str, Enum):
    """Kinds of durable review decisions."""

    GAP = "gap"
    ASSUMPTION = "assumption"
    MAPPING = "mapping"
    APPROVAL = "approval"


class ReviewDecisionStatus(str, Enum):
    """Decision state attached to a review subject."""

    PENDING = "pending"
    RESOLVED = "resolved"
    ACCEPTED = "accepted"
    VERIFIED = "verified"
    INVALIDATED = "invalidated"
    DEFERRED = "deferred"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewAssumptionRecord(BaseModel):
    """Serializable assumption record that survives project reloads."""

    assumption_id: NonEmptyStr
    category: str
    title: str
    description: str
    rationale: str = ""
    status: str = ReviewDecisionStatus.PENDING.value
    source: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    verified_at: datetime | None = None
    verified_by: str | None = None
    related_objects: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    impacts: list[str] = Field(default_factory=list)
    verification_method: str = ""
    verification_evidence: str = ""
    notes: str = ""


class GapReviewDecision(BaseModel):
    """Resolution record for a discovered gap."""

    gap_id: NonEmptyStr
    status: str = ReviewDecisionStatus.PENDING.value
    resolution_notes: str = ""
    decided_by: str | None = None
    decided_at: datetime = Field(default_factory=datetime.now)


class MappingReviewDecision(BaseModel):
    """Canonical slot for explicit mapping decisions."""

    mapping_key: NonEmptyStr
    mapped_to: str
    status: str = ReviewDecisionStatus.ACCEPTED.value
    notes: str = ""
    decided_by: str | None = None
    decided_at: datetime = Field(default_factory=datetime.now)


class ApprovalReviewDecision(BaseModel):
    """Project-level approvals that downstream generation can rely on."""

    approval_key: NonEmptyStr
    status: str = ReviewDecisionStatus.APPROVED.value
    notes: str = ""
    approved_by: str | None = None
    approved_at: datetime = Field(default_factory=datetime.now)


class ProjectReviewState(BaseModel):
    """Durable review decisions for a project."""

    assumptions: list[ReviewAssumptionRecord] = Field(default_factory=list)
    gap_decisions: list[GapReviewDecision] = Field(default_factory=list)
    mapping_decisions: list[MappingReviewDecision] = Field(default_factory=list)
    approvals: list[ApprovalReviewDecision] = Field(default_factory=list)


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

    # Durable review decisions
    review_state: ProjectReviewState = Field(default_factory=ProjectReviewState)

    # Station sync
    station_connection: StationConnectionConfig | None = None

    # Validation state
    validation_status: str = Field(default="pending", description="pending, valid, invalid")
    last_validated: datetime | None = None

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

    def get_equipment(self, equipment_id: str) -> Equipment | None:
        return next((e for e in self.equipment if e.id == equipment_id), None)

    def get_point(self, point_name: str) -> Point | None:
        return next((p for p in self.points if p.name == point_name), None)

    def get_controller(self, controller_id: str) -> Controller | None:
        return next((c for c in self.controllers if c.id == controller_id), None)

    def get_points_for_equipment(self, equipment_id: str) -> list[Point]:
        return [p for p in self.points if p.equipment_id == equipment_id]

    def get_points_for_controller(self, controller_id: str) -> list[Point]:
        return [p for p in self.points if p.controller_id == controller_id]

    def get_equipment_for_controller(self, controller_id: str) -> list[Equipment]:
        return [e for e in self.equipment if e.controller_id == controller_id]

    def update_timestamp(self) -> None:
        self.metadata.updated_at = datetime.now()

__all__ = [
    "ApprovalReviewDecision",
    "GapReviewDecision",
    "MappingReviewDecision",
    "Project",
    "ProjectMetadata",
    "ProjectReviewState",
    "ReviewAssumptionRecord",
    "ReviewDecisionStatus",
    "ReviewDecisionType",
    "SourceDocument",
]
