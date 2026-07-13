"""Equipment model - structured equipment definitions."""


from pydantic import BaseModel, Field, field_validator

from . import EquipmentType, NonEmptyStr


class EquipmentRelationship(BaseModel):
    """Relationship between equipment."""

    type: str = Field(description="feeds, serves, controls, monitors, contains")
    target_equipment_id: NonEmptyStr
    description: str | None = None


class EquipmentTemplateRef(BaseModel):
    """Reference to an equipment template."""

    template_name: NonEmptyStr
    parameters: dict[str, str] = Field(default_factory=dict)


class Equipment(BaseModel):
    """Structured equipment definition."""

    # Identity
    id: NonEmptyStr = Field(description="Unique equipment ID (e.g., AHU-1, VAV-203)")
    type: EquipmentType = Field(description="Equipment type")
    subtype: str | None = Field(default=None, description="Subtype (e.g., VAV-Reheat)")

    # Location & Context
    building: str | None = None
    floor: str | None = None
    room: str | None = None
    served_area: str | None = Field(default=None, description="Area served by this equipment")

    # Relationships
    parent_equipment_id: NonEmptyStr | None = None
    child_equipment_ids: list[NonEmptyStr] = Field(default_factory=list)
    relationships: list[EquipmentRelationship] = Field(default_factory=list)

    # Controller & Points
    controller_id: NonEmptyStr | None = None
    point_names: list[NonEmptyStr] = Field(default_factory=list, description="Point names belonging to this equipment")

    # Template & Sequence
    template: EquipmentTemplateRef | None = None
    sequence_ref: str | None = Field(default=None, description="Reference to sequence of operation")

    # Design Data
    design_cfm: float | None = None
    design_tonnage: float | None = None
    design_gpm: float | None = None
    design_kw: float | None = None
    voltage: str | None = None
    phase: int | None = None

    # Status
    status: str = Field(default="design", description="design, installed, commissioned, operational")

    # Metadata
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict)

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
