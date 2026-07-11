"""Equipment model - structured equipment definitions."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator

from . import NonEmptyStr, EquipmentType


class EquipmentRelationship(BaseModel):
    """Relationship between equipment."""

    type: str = Field(description="feeds, serves, controls, monitors, contains")
    target_equipment_id: NonEmptyStr
    description: Optional[str] = None


class EquipmentTemplateRef(BaseModel):
    """Reference to an equipment template."""

    template_name: NonEmptyStr
    parameters: dict[str, str] = Field(default_factory=dict)


class Equipment(BaseModel):
    """Structured equipment definition."""

    # Identity
    id: NonEmptyStr = Field(description="Unique equipment ID (e.g., AHU-1, VAV-203)")
    type: EquipmentType = Field(description="Equipment type")
    subtype: Optional[str] = Field(default=None, description="Subtype (e.g., VAV-Reheat)")

    # Location & Context
    building: Optional[str] = None
    floor: Optional[str] = None
    room: Optional[str] = None
    served_area: Optional[str] = Field(default=None, description="Area served by this equipment")

    # Relationships
    parent_equipment_id: Optional[NonEmptyStr] = None
    child_equipment_ids: list[NonEmptyStr] = Field(default_factory=list)
    relationships: list[EquipmentRelationship] = Field(default_factory=list)

    # Controller & Points
    controller_id: Optional[NonEmptyStr] = None
    point_names: list[NonEmptyStr] = Field(default_factory=list, description="Point names belonging to this equipment")

    # Template & Sequence
    template: Optional[EquipmentTemplateRef] = None
    sequence_ref: Optional[str] = Field(default=None, description="Reference to sequence of operation")

    # Design Data
    design_cfm: Optional[float] = None
    design_tonnage: Optional[float] = None
    design_gpm: Optional[float] = None
    design_kw: Optional[float] = None
    voltage: Optional[str] = None
    phase: Optional[int] = None

    # Status
    status: str = Field(default="design", description="design, installed, commissioned, operational")

    # Metadata
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Equipment ID cannot be empty")
        # Should follow pattern like AHU-1, VAV-203, CHWP-1
        return v

    def add_point(self, point_name: str) -> None:
        """Add a point to this equipment."""
        if point_name not in self.point_names:
            self.point_names.append(point_name)

    def remove_point(self, point_name: str) -> None:
        """Remove a point from this equipment."""
        if point_name in self.point_names:
            self.point_names.remove(point_name)


__all__ = ["Equipment", "EquipmentRelationship", "EquipmentTemplateRef"]