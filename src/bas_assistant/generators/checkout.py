"""Checkout sheet generator - deterministic Markdown & Excel output."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..models import Equipment, Point, PointKind, Project
from ..validation import ValidationEngine


@dataclass
class CheckoutItem:
    """A single checkout test item."""

    item_id: str
    equipment_id: str
    point_name: str
    test_type: str  # visual, continuity, calibration, functional, trend
    description: str
    expected_result: str
    acceptance_criteria: str
    tools_required: list[str] = field(default_factory=list)
    reference_doc: str | None = None
    status: str = "not_started"  # not_started, in_progress, passed, failed, na
    observed_result: str | None = None
    technician: str | None = None
    timestamp: datetime | None = None
    evidence: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass
class CheckoutSheet:
    """A complete checkout sheet for one equipment."""

    equipment_id: str
    equipment_type: str
    location: str
    controller_id: str
    generated_at: datetime = field(default_factory=datetime.now)
    generated_by: str = "BAS Assistant"
    items: list[CheckoutItem] = field(default_factory=list)
    sequence_reference: str | None = None
    sequence_review_status: str | None = None
    sequence_missing_refs: list[str] = field(default_factory=list)
    sequence_missing_families: list[str] = field(default_factory=list)
    sequence_summary: str | None = None

    def add_item(self, item: CheckoutItem) -> None:
        self.items.append(item)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to pandas DataFrame for Excel export."""
        rows = []
        for item in self.items:
            rows.append({
                "Item ID": item.item_id,
                "Equipment": item.equipment_id,
                "Point": item.point_name,
                "Test Type": item.test_type,
                "Description": item.description,
                "Expected Result": item.expected_result,
                "Acceptance Criteria": item.acceptance_criteria,
                "Tools Required": ", ".join(item.tools_required),
                "Reference Doc": item.reference_doc or "",
                "Status": item.status,
                "Observed Result": item.observed_result or "",
                "Technician": item.technician or "",
                "Timestamp": item.timestamp.strftime("%Y-%m-%d %H:%M") if item.timestamp else "",
                "Evidence": ", ".join(item.evidence),
                "Notes": item.notes or "",
            })
        return pd.DataFrame(rows)


class CheckoutGenerator:
    """Generates checkout sheets from validated project data."""

    TEST_TYPES = {
        PointKind.SENSOR: ["visual", "continuity", "calibration", "trend"],
        PointKind.ACTUATOR: ["visual", "continuity", "functional", "stroke"],
        PointKind.SETPOINT: ["visual", "functional", "calibration"],
        PointKind.STATUS: ["visual", "continuity", "functional"],
        PointKind.ALARM: ["functional", "simulation"],
        PointKind.TREND: ["trend", "configuration"],
    }

    def __init__(self, project: Project):
        self.project = project
        self.sheets: dict[str, CheckoutSheet] = {}
        self._validation_engine = ValidationEngine()
        self._validation_engine.validate(project)

    def generate_all(self) -> dict[str, CheckoutSheet]:
        """Generate checkout sheets for all equipment."""
        for equip in self.project.equipment:
            self._generate_equipment_sheet(equip)
        return self.sheets

    def _generate_equipment_sheet(self, equip: Equipment) -> CheckoutSheet:
        """Generate checkout sheet for one equipment."""
        effective_controller_id = self.project.effective_equipment_controller_id(equip)
        controller = self.project.get_controller(effective_controller_id) if effective_controller_id else None
        points = self.project.get_points_for_equipment(equip.id)

        sheet = CheckoutSheet(
            equipment_id=equip.id,
            equipment_type=equip.type.value,
            location=f"{equip.building or ''} {equip.floor or ''} {equip.room or ''}".strip() or "Unknown",
            controller_id=effective_controller_id or "Unassigned",
        )
        sequence_review = self._validation_engine.sequence_coverage_for_equipment(self.project, equip.id)
        sheet.sequence_reference = equip.sequence_ref or None
        sheet.sequence_review_status = str(sequence_review.get("status") or "")
        sheet.sequence_missing_refs = list(sequence_review.get("missing_refs") or [])
        sheet.sequence_missing_families = list(sequence_review.get("missing_families") or [])
        sheet.sequence_summary = str(sequence_review.get("summary") or "")

        # Generate items for each point
        for idx, point in enumerate(points, 1):
            test_types = self.TEST_TYPES.get(point.kind, ["visual", "functional"])

            for test_type in test_types:
                item = self._create_checkout_item(
                    equip=equip,
                    point=point,
                    test_type=test_type,
                    sequence=idx,
                )
                sheet.add_item(item)

        # Add equipment-level items
        self._add_equipment_level_items(sheet, equip)

        self.sheets[equip.id] = sheet
        return sheet

    def _create_checkout_item(
        self,
        equip: Equipment,
        point: Point,
        test_type: str,
        sequence: int,
    ) -> CheckoutItem:
        """Create a checkout item for a point/test combination."""

        item_id = f"{equip.id}-{point.name}-{test_type[:3].upper()}-{sequence:03d}"

        templates = {
            "visual": {
                "description": f"Visual inspection of {point.name} wiring, termination, and labeling",
                "expected": "Wiring matches drawings, labels present and legible, no damage",
                "criteria": "All terminations secure, wire labels match point list, no corrosion",
                "tools": ["Flashlight", "Label maker (verify)"],
            },
            "continuity": {
                "description": f"Continuity test for {point.name} from controller to field device",
                "expected": "Continuity confirmed, resistance within spec",
                "criteria": "< 1 ohm for digital, < 10 ohm for analog (per spec)",
                "tools": ["Multimeter", "Test leads"],
            },
            "calibration": {
                "description": f"Calibration verification of {point.name} against reference standard",
                "expected": f"Reading within ±{self._calibration_tolerance(point)} of reference",
                "criteria": f"Error ≤ {self._calibration_tolerance(point)} of span",
                "tools": ["Calibrated reference instrument", "Multimeter", "Calibration adapter"],
            },
            "functional": {
                "description": f"Functional test of {point.name} through controller logic",
                "expected": "Controller reads/writes correct value, logic responds appropriately",
                "criteria": "Value matches expected state for given condition",
                "tools": ["Controller workstation", "Handheld communicator"],
            },
            "trend": {
                "description": f"Trend log verification for {point.name}",
                "expected": "Trend configured, logging at correct interval, data retrievable",
                "criteria": "Interval matches spec, duration ≥ 30 days, no gaps",
                "tools": ["Controller workstation", "Trend viewer"],
            },
            "stroke": {
                "description": f"Stroke/test actuator {point.name} through full range",
                "expected": "Actuator moves smoothly 0-100%, feedback matches command",
                "criteria": "Feedback within ±5% of command at 0%, 50%, 100%",
                "tools": ["Controller workstation", "Handheld communicator"],
            },
            "simulation": {
                "description": f"Simulate alarm condition for {point.name}",
                "expected": "Alarm triggers, annunciates, logs correctly",
                "criteria": "Alarm activates at setpoint, clears at reset point, priority correct",
                "tools": ["Controller workstation", "Signal simulator"],
            },
        }

        t = templates.get(test_type, templates["visual"])

        return CheckoutItem(
            item_id=item_id,
            equipment_id=equip.id,
            point_name=point.name,
            test_type=test_type,
            description=t["description"],
            expected_result=t["expected"],
            acceptance_criteria=t["criteria"],
            tools_required=t["tools"],
            reference_doc=f"Point List: {point.source_reference}" if point.source_reference else None,
        )

    def _calibration_tolerance(self, point: Point) -> str:
        """Get calibration tolerance based on point type."""
        if point.kind == PointKind.SENSOR:
            if point.units and any(u in point.units.lower() for u in ["degf", "degc", "temp"]):
                return "±0.5°F (±0.3°C)"
            if point.units and any(u in point.units.lower() for u in ["inwc", "wc", "psi", "pa", "kpa"]):
                return "±2% of reading"
            if point.units and any(u in point.units.lower() for u in ["cfm", "gpm", "lps", "flow"]):
                return "±5% of reading"
        return "±1% of span"

    def _add_equipment_level_items(self, sheet: CheckoutSheet, equip: Equipment) -> None:
        """Add equipment-level checkout items (not point-specific)."""

        # Power verification
        sheet.add_item(CheckoutItem(
            item_id=f"{equip.id}-POWER-001",
            equipment_id=equip.id,
            point_name="N/A (Equipment Power)",
            test_type="visual",
            description="Verify equipment power supply, disconnects, and overcurrent protection",
            expected_result="Voltage within ±10% of nameplate, breakers sized correctly",
            acceptance_criteria="Measured voltage matches nameplate ±10%, OCPD per NEC",
            tools_required=["Multimeter", "Clamp meter"],
        ))

        # Controller communication
        effective_controller_id = self.project.effective_equipment_controller_id(equip)
        if effective_controller_id:
            sheet.add_item(CheckoutItem(
                item_id=f"{equip.id}-COMM-001",
                equipment_id=equip.id,
                point_name="N/A (Controller Comm)",
                test_type="functional",
                description=f"Verify controller {effective_controller_id} communication and time sync",
                expected_result="Controller online, time synced, no comm errors",
                acceptance_criteria="Heartbeat present, time within 1 sec of NTP, no error logs",
                tools_required=["Controller workstation", "Network ping tool"],
            ))

        # Safety devices
        safety_points = [p for p in self.project.get_points_for_equipment(equip.id)
                         if p.kind == PointKind.ALARM or "safety" in p.name.lower()]
        for sp in safety_points:
            sheet.add_item(CheckoutItem(
                item_id=f"{equip.id}-SAFETY-{sp.name[-4:].upper()}",
                equipment_id=equip.id,
                point_name=sp.name,
                test_type="simulation",
                description=f"Verify safety device {sp.name} operation and alarm",
                expected_result="Safety triggers at setpoint, alarm annunciates, equipment shuts down per sequence",
                acceptance_criteria="Trip point ±2% of setpoint, alarm priority correct, sequence executes",
                tools_required=["Signal simulator", "Controller workstation"],
            ))

    # Export methods

    def to_markdown(self, output_dir: Path) -> list[Path]:
        """Export all sheets as Markdown files."""
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []

        for equip_id, sheet in self.sheets.items():
            path = output_dir / f"checkout_{equip_id.lower()}.md"
            with open(path, "w") as f:
                f.write(self._sheet_to_markdown(sheet))
            paths.append(path)

        # Also create index
        index_path = output_dir / "checkout_INDEX.md"
        with open(index_path, "w") as f:
            f.write(self._index_to_markdown())
        paths.append(index_path)

        return paths

    def _sheet_to_markdown(self, sheet: CheckoutSheet) -> str:
        lines = [
            f"# Checkout Sheet: {sheet.equipment_id}",
            "",
            f"**Equipment Type:** {sheet.equipment_type}",
            f"**Location:** {sheet.location}",
            f"**Controller:** {sheet.controller_id}",
            f"**Generated:** {sheet.generated_at.strftime('%Y-%m-%d %H:%M')}",
            f"**Generated By:** {sheet.generated_by}",
            f"**Sequence Reference:** {sheet.sequence_reference or 'N/A'}",
            f"**Sequence Review Status:** {sheet.sequence_review_status or 'not_indexed'}",
            "",
        ]
        if sheet.sequence_summary:
            lines.extend([
                f"**Sequence Review Summary:** {sheet.sequence_summary}",
            ])
        if sheet.sequence_missing_refs:
            lines.extend([
                f"**Missing Sequence Point Refs:** {', '.join(sheet.sequence_missing_refs)}",
            ])
        if sheet.sequence_missing_families:
            lines.extend([
                f"**Missing Sequence Control Families:** {', '.join(sheet.sequence_missing_families)}",
            ])
        lines.extend([
            "---",
            "",
            "| Item ID | Point | Test Type | Description | Expected Result | Acceptance Criteria | Tools | Status | Observed | Tech | Date | Evidence | Notes |",
            "|---------|-------|-----------|-------------|-----------------|---------------------|-------|--------|----------|------|------|----------|-------|",
        ])

        for item in sheet.items:
            lines.append(
                f"| {item.item_id} | {item.point_name} | {item.test_type} | "
                f"{item.description} | {item.expected_result} | {item.acceptance_criteria} | "
                f"{', '.join(item.tools_required)} | {item.status} | "
                f"{item.observed_result or ''} | {item.technician or ''} | "
                f"{item.timestamp.strftime('%Y-%m-%d') if item.timestamp else ''} | "
                f"{', '.join(item.evidence)} | {item.notes or ''} |"
            )

        return "\n".join(lines)

    def _index_to_markdown(self) -> str:
        lines = [
            "# Checkout Sheets Index",
            "",
            f"**Project:** {self.project.metadata.name} ({self.project.metadata.project_id})",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "| Equipment | Type | Location | Controller | Items | Status |",
            "| Sequence Status | Sequence Gaps |",
            "|-----------|------|----------|------------|-------|--------|-----------------|---------------|",
        ]

        for sheet in self.sheets.values():
            total = len(sheet.items)
            passed = sum(1 for i in sheet.items if i.status == "passed")
            failed = sum(1 for i in sheet.items if i.status == "failed")
            status = "✅ Complete" if passed == total and total > 0 else ("⚠️ In Progress" if passed > 0 else "⏳ Not Started")
            lines.append(
                f"| {sheet.equipment_id} | {sheet.equipment_type} | {sheet.location} | "
                f"{sheet.controller_id} | {total} | {status} | {sheet.sequence_review_status or 'not_indexed'} | "
                f"{len(sheet.sequence_missing_refs) + len(sheet.sequence_missing_families)} |"
            )

        return "\n".join(lines)

    def to_excel(self, output_path: Path) -> Path:
        """Export all sheets as a single Excel workbook with multiple tabs."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            # Summary sheet
            summary_rows = []
            for sheet in self.sheets.values():
                total = len(sheet.items)
                passed = sum(1 for i in sheet.items if i.status == "passed")
                failed = sum(1 for i in sheet.items if i.status == "failed")
                in_prog = sum(1 for i in sheet.items if i.status == "in_progress")
                summary_rows.append({
                    "Equipment": sheet.equipment_id,
                    "Type": sheet.equipment_type,
                    "Location": sheet.location,
                    "Controller": sheet.controller_id,
                    "Total Items": total,
                    "Passed": passed,
                    "Failed": failed,
                    "In Progress": in_prog,
                    "Not Started": total - passed - failed - in_prog,
                    "Completion %": round((passed / total * 100) if total > 0 else 0, 1),
                    "Sequence Review Status": sheet.sequence_review_status or "not_indexed",
                    "Sequence Missing Refs": ", ".join(sheet.sequence_missing_refs),
                    "Sequence Missing Families": ", ".join(sheet.sequence_missing_families),
                })
            pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

            # Individual sheets
            for sheet in self.sheets.values():
                sheet_name = sheet.equipment_id[:31]  # Excel sheet name limit
                sheet.to_dataframe().to_excel(writer, sheet_name=sheet_name, index=False)

        return output_path


def generate_checkout_sheets(project: Project, output_dir: Path) -> dict:
    """Convenience function to generate all checkout outputs."""
    generator = CheckoutGenerator(project)
    generator.generate_all()

    md_paths = generator.to_markdown(output_dir / "checkout_md")
    excel_path = generator.to_excel(output_dir / "checkout_sheets.xlsx")
    summaries = [
        {
            "equipment_id": sheet.equipment_id,
            "equipment_type": sheet.equipment_type,
            "controller_id": sheet.controller_id,
            "sequence_reference": sheet.sequence_reference or "",
            "sequence_review_status": sheet.sequence_review_status or "not_indexed",
            "sequence_missing_refs": list(sheet.sequence_missing_refs),
            "sequence_missing_families": list(sheet.sequence_missing_families),
            "sequence_summary": sheet.sequence_summary or "",
        }
        for sheet in generator.sheets.values()
    ]

    return {
        "markdown": md_paths,
        "excel": excel_path,
        "sheet_count": len(generator.sheets),
        "summaries": summaries,
    }


__all__ = [
    "CheckoutGenerator",
    "CheckoutItem",
    "CheckoutSheet",
    "generate_checkout_sheets",
]
