"""Point model - core BAS point definition."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator

from . import (
    PointKind,
    PointDirection,
    PointSource,
    NonEmptyStr,
    ValidationSeverity,
    ValidationCategory,
)


class PointValidationIssue(BaseModel):
    """A validation issue found on a point."""

    category: ValidationCategory
    severity: ValidationSeverity
    message: str
    rule_id: str
    field: Optional[str] = None


class Point(BaseModel):
    """Structured BAS point definition."""

    # Identity
    name: NonEmptyStr = Field(description="Point name per naming convention")
    equipment_id: NonEmptyStr = Field(description="Parent equipment ID")
    controller_id: Optional[NonEmptyStr] = Field(
        default=None, description="Owning controller ID"
    )

    # Type & Direction
    kind: PointKind = Field(description="Point kind")
    direction: PointDirection = Field(description="Direction relative to controller")

    # Engineering
    units: Optional[str] = Field(default=None, description="Engineering units")
    unit_system: Optional[str] = Field(default=None, description="IP or SI")
    range_min: Optional[float] = Field(default=None, description="Minimum expected value")
    range_max: Optional[float] = Field(default=None, description="Maximum expected value")

    # Protocol mapping
    bacnet_object_type: Optional[str] = Field(
        default=None, description="BACnet object type (AI, AO, BI, BO, AV, BV, etc.)"
    )
    bacnet_instance: Optional[int] = Field(
        default=None, description="BACnet instance number"
    )
    modbus_register: Optional[int] = Field(
        default=None, description="Modbus register address"
    )
    modbus_type: Optional[str] = Field(
        default=None, description="coil, discrete_input, holding_register, input_register"
    )

    # Source & Validation
    source: PointSource = Field(default=PointSource.POINT_LIST)
    source_reference: Optional[str] = Field(
        default=None, description="Row ID, register, or reference in source"
    )
    validation_status: str = Field(default="pending", description="pending, valid, invalid")
    validation_issues: list[PointValidationIssue] = Field(default_factory=list)

    # Metadata
    description: Optional[str] = Field(default=None)
    tags: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Point name cannot be empty")
        return v.strip()

    @field_validator("bacnet_object_type")
    @classmethod
    def validate_bacnet_object_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        valid_types = {
            "AI", "AO", "AV", "BI", "BO", "BV", "MSI", "MSO", "MSV",
            "LOOP", "SCHEDULE", "CALENDAR", "TRENDLOG", "NOTIFICATION_CLASS"
        }
        if v.upper() not in valid_types:
            raise ValueError(f"Invalid BACnet object type: {v}. Valid: {valid_types}")
        return v.upper()

    @field_validator("modbus_type")
    @classmethod
    def validate_modbus_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        valid = {"coil", "discrete_input", "holding_register", "input_register"}
        if v.lower() not in valid:
            raise ValueError(f"Invalid Modbus type: {v}. Valid: {valid}")
        return v.lower()

    def add_issue(
        self,
        category: ValidationCategory,
        severity: ValidationSeverity,
        message: str,
        rule_id: str,
        field: Optional[str] = None,
    ) -> None:
        """Add a validation issue."""
        self.validation_issues.append(
            PointValidationIssue(
                category=category,
                severity=severity,
                message=message,
                rule_id=rule_id,
                field=field,
            )
        )
        if severity == ValidationSeverity.ERROR:
            self.validation_status = "invalid"
        elif self.validation_status == "pending":
            self.validation_status = "valid"

    def has_errors(self) -> bool:
        return any(i.severity == ValidationSeverity.ERROR for i in self.validation_issues)

    def has_warnings(self) -> bool:
        return any(i.severity == ValidationSeverity.WARNING for i in self.validation_issues)


__all__ = ["Point", "PointValidationIssue"]