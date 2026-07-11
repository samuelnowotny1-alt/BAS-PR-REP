"""Controller model - BAS controller definitions."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator

from . import NonEmptyStr, Protocol


class ControllerNetworkAddress(BaseModel):
    """Network address for a controller."""

    protocol: Protocol
    address: NonEmptyStr = Field(description="IP address, MAC, or device ID")
    network_number: Optional[int] = None
    subnet_mask: Optional[str] = None
    gateway: Optional[str] = None


class ControllerIOCapacity(BaseModel):
    """I/O capacity of a controller."""

    universal_inputs: int = 0
    digital_inputs: int = 0
    analog_outputs: int = 0
    digital_outputs: int = 0
    total_points: int = 0

    @property
    def used_points(self) -> int:
        return self.universal_inputs + self.digital_inputs + self.analog_outputs + self.digital_outputs

    def utilization_pct(self) -> float:
        if self.total_points == 0:
            return 0.0
        return (self.used_points / self.total_points) * 100


class Controller(BaseModel):
    """Structured controller definition."""

    # Identity
    id: NonEmptyStr = Field(description="Controller ID (e.g., MPC-1, VAV-203)")
    name: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None

    # Type & Capabilities
    type: str = Field(default="generic", description="Controller type (MPC, VAV, FCU, etc.)")
    protocols: list[Protocol] = Field(default_factory=list)
    network_addresses: list[ControllerNetworkAddress] = Field(default_factory=list)
    io_capacity: Optional[ControllerIOCapacity] = None

    # Equipment served
    serves_equipment_ids: list[NonEmptyStr] = Field(default_factory=list)

    # Point ownership
    owned_point_names: list[NonEmptyStr] = Field(default_factory=list)

    # Location
    panel_location: Optional[str] = None
    electrical_panel: Optional[str] = None
    circuit: Optional[str] = None

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
            raise ValueError("Controller ID cannot be empty")
        return v

    def add_equipment(self, equipment_id: str) -> None:
        """Add equipment served by this controller."""
        if equipment_id not in self.serves_equipment_ids:
            self.serves_equipment_ids.append(equipment_id)

    def add_point(self, point_name: str) -> None:
        """Add a point owned by this controller."""
        if point_name not in self.owned_point_names:
            self.owned_point_names.append(point_name)

    def utilization_pct(self) -> Optional[float]:
        """Get I/O utilization percentage."""
        if self.io_capacity:
            total_points = self.io_capacity.total_points
            if total_points == 0:
                return 0.0
            used_points = len(self.owned_point_names)
            return (used_points / total_points) * 100
        return None


__all__ = ["Controller", "ControllerNetworkAddress", "ControllerIOCapacity"]
