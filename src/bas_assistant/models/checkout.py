"""Checkout model - structured checkout and commissioning data."""

from datetime import datetime

from pydantic import BaseModel, Field

from . import NonEmptyStr


class CheckoutItem(BaseModel):
    """A single checkout test item."""

    item_id: NonEmptyStr = Field(description="Unique item identifier")
    equipment_id: NonEmptyStr = Field(description="Parent equipment ID")
    point_name: NonEmptyStr | None = Field(default=None, description="Associated point name")
    test_type: str = Field(description="visual, continuity, calibration, functional, trend, stroke, simulation")
    description: str = Field(description="Test description")
    expected_result: str = Field(description="Expected result")
    acceptance_criteria: str = Field(description="Acceptance criteria")
    tools_required: list[str] = Field(default_factory=list)
    reference_doc: str | None = None
    status: str = Field(default="not_started", description="not_started, in_progress, passed, failed, na")
    observed_result: str | None = None
    technician: str | None = None
    timestamp: datetime | None = None
    evidence: list[str] = Field(default_factory=list)
    notes: str | None = None


class CheckoutSheet(BaseModel):
    """Complete checkout sheet for one equipment."""

    equipment_id: NonEmptyStr
    equipment_type: str
    location: str
    controller_id: str
    generated_at: datetime = Field(default_factory=datetime.now)
    generated_by: str = "BAS Assistant"
    items: list[CheckoutItem] = Field(default_factory=list)

    def add_item(self, item: CheckoutItem) -> None:
        self.items.append(item)


class CheckoutReport(BaseModel):
    """Complete checkout report for a project."""

    project_id: NonEmptyStr
    project_name: str
    generated_at: datetime = Field(default_factory=datetime.now)
    sheets: list[CheckoutSheet] = Field(default_factory=list)


__all__ = ["CheckoutItem", "CheckoutReport", "CheckoutSheet"]
