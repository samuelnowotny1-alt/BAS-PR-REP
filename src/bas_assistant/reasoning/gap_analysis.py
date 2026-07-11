"""Gap Analysis - Analyzes project data for completeness and consistency."""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

from ..models import (
    Project, Equipment, Point, Controller, PointKind, EquipmentType,
    ValidationSeverity, ValidationCategory
)
from ..validation import ValidationEngine, ValidationReport


class GapSeverity(str, Enum):
    """Severity of a gap."""
    CRITICAL = "critical"    # Must fix before generation
    HIGH = "high"            # Should fix before generation
    MEDIUM = "medium"        # Recommended to fix
    LOW = "low"              # Nice to have
    INFO = "info"            # Informational


class GapCategory(str, Enum):
    """Category of gap."""
    MISSING_DATA = "missing_data"
    INCOMPLETE_EQUIPMENT = "incomplete_equipment"
    INCONSISTENT_CONFIG = "inconsistent_config"
    VALIDATION_ERROR = "validation_error"
    GENERATION_BLOCKER = "generation_blocker"
    BEST_PRACTICE = "best_practice"


@dataclass
class Gap:
    """A single gap found in the project data."""
    gap_id: str
    category: GapCategory
    severity: GapSeverity
    title: str
    description: str
    affected_object_type: str  # equipment, point, controller, project
    affected_object_id: str
    recommendation: str
    auto_fixable: bool = False
    fix_suggestion: Optional[str] = None
    related_gaps: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class GapAnalysisReport:
    """Complete gap analysis report."""
    project_id: str
    project_name: str
    analyzed_at: datetime = field(default_factory=datetime.now)
    gaps: list[Gap] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for g in self.gaps if g.severity == GapSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for g in self.gaps if g.severity == GapSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for g in self.gaps if g.severity == GapSeverity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for g in self.gaps if g.severity == GapSeverity.LOW)

    @property
    def info_count(self) -> int:
        return sum(1 for g in self.gaps if g.severity == GapSeverity.INFO)

    @property
    def total_count(self) -> int:
        return len(self.gaps)

    @property
    def generation_ready(self) -> bool:
        """True if no critical or high severity gaps."""
        return self.critical_count == 0 and self.high_count == 0

    @property
    def gaps_by_category(self) -> dict[GapCategory, list[Gap]]:
        """Gaps grouped by category for UI rendering."""
        grouped: dict[GapCategory, list[Gap]] = {}
        for gap in self.gaps:
            grouped.setdefault(gap.category, []).append(gap)
        return grouped

    def get_gaps_by_category(self, category: GapCategory) -> list[Gap]:
        return [g for g in self.gaps if g.category == category]

    def get_gaps_by_severity(self, severity: GapSeverity) -> list[Gap]:
        return [g for g in self.gaps if g.severity == severity]

    def get_gaps_for_object(self, object_type: str, object_id: str) -> list[Gap]:
        return [g for g in self.gaps 
                if g.affected_object_type == object_type and g.affected_object_id == object_id]

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "analyzed_at": self.analyzed_at.isoformat(),
            "summary": {
                "total": self.total_count,
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
                "info": self.info_count,
                "generation_ready": self.generation_ready,
            },
            "gaps": [
                {
                    "gap_id": g.gap_id,
                    "category": g.category.value,
                    "severity": g.severity.value,
                    "title": g.title,
                    "description": g.description,
                    "affected_object_type": g.affected_object_type,
                    "affected_object_id": g.affected_object_id,
                    "recommendation": g.recommendation,
                    "auto_fixable": g.auto_fixable,
                    "fix_suggestion": g.fix_suggestion,
                    "related_gaps": g.related_gaps,
                    "metadata": g.metadata,
                }
                for g in self.gaps
            ]
        }


class GapAnalyzer:
    """Analyzes project data for gaps and inconsistencies."""

    def __init__(self, project: Project):
        self.project = project
        self.gaps: list[Gap] = []
        self._gap_counter = 0

    def _new_gap_id(self) -> str:
        self._gap_counter += 1
        return f"GAP-{self._gap_counter:04d}"

    def _add_gap(self, gap: Gap) -> None:
        self.gaps.append(gap)

    def analyze(self) -> GapAnalysisReport:
        """Run complete gap analysis."""
        self.gaps = []
        self._gap_counter = 0

        # Run all analysis checks
        self._analyze_project_metadata()
        self._analyze_equipment()
        self._analyze_points()
        self._analyze_controllers()
        self._analyze_relationships()
        self._analyze_validation_results()
        self._analyze_generation_readiness()

        return GapAnalysisReport(
            project_id=self.project.metadata.project_id,
            project_name=self.project.metadata.name,
            gaps=self.gaps,
        )

    def _analyze_project_metadata(self) -> None:
        """Check project-level metadata completeness."""
        meta = self.project.metadata

        required_fields = {
            "client": "Client name",
            "location": "Project location",
            "engineer_of_record": "Engineer of record",
            "programmer": "Programmer assigned",
            "commissioning_agent": "Commissioning agent",
        }

        for field, label in required_fields.items():
            value = getattr(meta, field, None)
            if not value:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.MEDIUM,
                    title=f"Missing {label}",
                    description=f"Project metadata field '{field}' is not set",
                    affected_object_type="project",
                    affected_object_id=self.project.metadata.project_id,
                    recommendation=f"Set {label} in project metadata",
                    fix_suggestion=f"project.metadata.{field} = '...'",
                    auto_fixable=True,
                    metadata={"field": field},
                ))

        # Check design phase
        if not meta.design_phase:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.MISSING_DATA,
                severity=GapSeverity.LOW,
                title="Design phase not specified",
                description="Project design phase (SD/DD/CD/CA) not set",
                affected_object_type="project",
                affected_object_id=self.project.metadata.project_id,
                recommendation="Set design phase to track project progress",
                fix_suggestion="project.metadata.design_phase = 'CD'",
                auto_fixable=True,
            ))

    def _analyze_equipment(self) -> None:
        """Analyze equipment for completeness."""
        if not self.project.equipment:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.INCOMPLETE_EQUIPMENT,
                severity=GapSeverity.CRITICAL,
                title="No equipment defined",
                description="Project has no equipment - cannot generate any outputs",
                affected_object_type="project",
                affected_object_id=self.project.metadata.project_id,
                recommendation="Import equipment schedule or manually add equipment",
                fix_suggestion="Run 'bas import-data' with equipment schedule CSV",
            ))
            return

        for equip in self.project.equipment:
            # Missing controller assignment
            if not equip.controller_id:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCOMPLETE_EQUIPMENT,
                    severity=GapSeverity.HIGH,
                    title=f"Equipment {equip.id} has no controller",
                    description=f"Equipment '{equip.id}' ({equip.type.value}) is not assigned to a controller",
                    affected_object_type="equipment",
                    affected_object_id=equip.id,
                    recommendation="Assign equipment to a controller",
                    fix_suggestion=f"equip.controller_id = 'MPC-1'",
                    auto_fixable=True,
                    metadata={"equipment_type": equip.type.value},
                ))

            # Missing served area
            if not equip.served_area:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.MEDIUM,
                    title=f"Equipment {equip.id} missing served area",
                    description=f"No served area defined for '{equip.id}'",
                    affected_object_type="equipment",
                    affected_object_id=equip.id,
                    recommendation="Add served area for documentation and graphics",
                    fix_suggestion=f"equip.served_area = 'Floor 1 West'",
                    auto_fixable=True,
                ))

            # Missing design data
            missing_design = []
            if equip.type in (EquipmentType.AHU, EquipmentType.RTU, EquipmentType.VAV) and not equip.design_cfm:
                missing_design.append("CFM")
            if equip.type in (EquipmentType.CHILLER, EquipmentType.AHU, EquipmentType.RTU) and not equip.design_tonnage:
                missing_design.append("Tonnage")
            if equip.type in (EquipmentType.CHILLER, EquipmentType.BOILER, EquipmentType.PUMP_CHW, EquipmentType.PUMP_HW) and not equip.design_gpm:
                missing_design.append("GPM")
            if equip.type in (EquipmentType.BOILER, EquipmentType.CHILLER) and not equip.design_kw:
                missing_design.append("kW")

            if missing_design:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.MEDIUM,
                    title=f"Equipment {equip.id} missing design data",
                    description=f"Missing design parameters: {', '.join(missing_design)}",
                    affected_object_type="equipment",
                    affected_object_id=equip.id,
                    recommendation="Add design data for proper sizing validation",
                    fix_suggestion=f"equip.design_cfm = 10000",
                    auto_fixable=True,
                    metadata={"missing": missing_design},
                ))

            # No points assigned
            if not equip.point_names:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCOMPLETE_EQUIPMENT,
                    severity=GapSeverity.HIGH,
                    title=f"Equipment {equip.id} has no points",
                    description=f"No points associated with equipment '{equip.id}'",
                    affected_object_type="equipment",
                    affected_object_id=equip.id,
                    recommendation="Add points to equipment or import point list",
                    fix_suggestion="Run point import with equipment ID matching",
                    metadata={"equipment_type": equip.type.value},
                ))

    def _analyze_points(self) -> None:
        """Analyze points for completeness and consistency."""
        if not self.project.points:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.MISSING_DATA,
                severity=GapSeverity.CRITICAL,
                title="No points defined",
                description="Project has no points - cannot generate logic, graphics, or checkout",
                affected_object_type="project",
                affected_object_id=self.project.metadata.project_id,
                recommendation="Import point list CSV",
                fix_suggestion="Run 'bas import-data' with point list CSV",
            ))
            return

        for point in self.project.points:
            # Missing controller
            if not point.controller_id:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCOMPLETE_EQUIPMENT,
                    severity=GapSeverity.HIGH,
                    title=f"Point {point.name} has no controller",
                    description=f"Point '{point.name}' is not assigned to a controller",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Assign point to a controller",
                    fix_suggestion=f"point.controller_id = 'MPC-1'",
                    auto_fixable=True,
                ))

            # Missing units
            if not point.units:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.MEDIUM,
                    title=f"Point {point.name} missing units",
                    description=f"Point '{point.name}' has no engineering units defined",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Add engineering units for proper display and validation",
                    fix_suggestion=f"point.units = 'degF'",
                    auto_fixable=True,
                ))

            # Missing range for sensors
            if point.kind == PointKind.SENSOR and (point.range_min is None or point.range_max is None):
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.MEDIUM,
                    title=f"Sensor {point.name} missing range",
                    description=f"Sensor point '{point.name}' has no min/max range for validation",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Add expected operating range",
                    fix_suggestion=f"point.range_min = 40; point.range_max = 120",
                    auto_fixable=True,
                ))

            # Missing BACnet config for BACnet points
            ctrl = self.project.get_controller(point.controller_id) if point.controller_id else None
            is_bacnet = ctrl and any("BACnet" in p.value for p in ctrl.protocols)
            if is_bacnet and not point.bacnet_object_type:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCONSISTENT_CONFIG,
                    severity=GapSeverity.HIGH,
                    title=f"Point {point.name} missing BACnet object type",
                    description=f"Point on BACnet controller missing BACnet object type",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Set BACnet object type (AI, AO, AV, BI, BO, BV, etc.)",
                    fix_suggestion=f"point.bacnet_object_type = 'AI'",
                    auto_fixable=True,
                ))

            if is_bacnet and point.bacnet_instance is None:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCONSISTENT_CONFIG,
                    severity=GapSeverity.HIGH,
                    title=f"Point {point.name} missing BACnet instance",
                    description=f"Point on BACnet controller missing instance number",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Assign unique BACnet instance number per controller",
                    fix_suggestion=f"point.bacnet_instance = 1",
                    auto_fixable=True,
                ))

            # Missing Modbus config for Modbus points
            is_modbus = ctrl and any("Modbus" in p.value for p in ctrl.protocols)
            if is_modbus and not point.modbus_register:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCONSISTENT_CONFIG,
                    severity=GapSeverity.HIGH,
                    title=f"Point {point.name} missing Modbus register",
                    description=f"Point on Modbus controller missing register address",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Assign Modbus register address and type",
                    fix_suggestion=f"point.modbus_register = 100; point.modbus_type = 'holding_register'",
                    auto_fixable=True,
                ))

            # Description missing
            if not point.description:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.LOW,
                    title=f"Point {point.name} missing description",
                    description=f"No description for point '{point.name}'",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Add description for documentation",
                    fix_suggestion=f"point.description = 'Supply Air Temperature'",
                    auto_fixable=True,
                ))

    def _analyze_controllers(self) -> None:
        """Analyze controllers for completeness."""
        if not self.project.controllers:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.INCOMPLETE_EQUIPMENT,
                severity=GapSeverity.CRITICAL,
                title="No controllers defined",
                description="Project has no controllers - cannot assign points or generate device configs",
                affected_object_type="project",
                affected_object_id=self.project.metadata.project_id,
                recommendation="Import controller schedule or add controllers manually",
                fix_suggestion="Run 'bas import-data' with controller schedule CSV",
            ))
            return

        for ctrl in self.project.controllers:
            # Missing protocols
            if not ctrl.protocols:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.HIGH,
                    title=f"Controller {ctrl.id} has no protocols",
                    description=f"Controller '{ctrl.id}' has no communication protocols defined",
                    affected_object_type="controller",
                    affected_object_id=ctrl.id,
                    recommendation="Add protocol (BACnet/IP, Modbus/TCP, etc.)",
                    fix_suggestion=f"ctrl.protocols = [Protocol.BACNET_IP]",
                    auto_fixable=True,
                ))

            # Missing network address
            if not ctrl.network_addresses:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.HIGH,
                    title=f"Controller {ctrl.id} has no network address",
                    description=f"Controller '{ctrl.id}' has no IP/MAC address defined",
                    affected_object_type="controller",
                    affected_object_id=ctrl.id,
                    recommendation="Add network address for communication",
                    fix_suggestion=f"ctrl.network_addresses.append(NetworkAddress(protocol=Protocol.BACNET_IP, address='192.168.1.10'))",
                    auto_fixable=True,
                ))

            # No equipment served
            if not ctrl.serves_equipment_ids:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCOMPLETE_EQUIPMENT,
                    severity=GapSeverity.MEDIUM,
                    title=f"Controller {ctrl.id} serves no equipment",
                    description=f"Controller '{ctrl.id}' is not assigned to any equipment",
                    affected_object_type="controller",
                    affected_object_id=ctrl.id,
                    recommendation="Assign equipment to controller",
                    fix_suggestion=f"ctrl.serves_equipment_ids = ['AHU-1', 'VAV-101']",
                    auto_fixable=True,
                ))

            # No points owned
            points = self.project.get_points_for_controller(ctrl.id)
            if not points:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCOMPLETE_EQUIPMENT,
                    severity=GapSeverity.HIGH,
                    title=f"Controller {ctrl.id} owns no points",
                    description=f"Controller '{ctrl.id}' has no points assigned",
                    affected_object_type="controller",
                    affected_object_id=ctrl.id,
                    recommendation="Assign points to controller",
                    fix_suggestion="Import point list with correct Controller ID column",
                ))

            # I/O capacity check
            if ctrl.io_capacity:
                util = ctrl.utilization_pct()
                if util > 90:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.INCONSISTENT_CONFIG,
                        severity=GapSeverity.HIGH,
                        title=f"Controller {ctrl.id} I/O over 90% utilized",
                        description=f"Controller I/O utilization is {util:.1f}% - may exceed capacity",
                        affected_object_type="controller",
                        affected_object_id=ctrl.id,
                        recommendation="Review I/O count, consider additional controller",
                        metadata={"utilization_pct": util},
                    ))
                elif util > 75:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.BEST_PRACTICE,
                        severity=GapSeverity.MEDIUM,
                        title=f"Controller {ctrl.id} I/O over 75% utilized",
                        description=f"Controller I/O utilization is {util:.1f}%",
                        affected_object_type="controller",
                        affected_object_id=ctrl.id,
                        recommendation="Monitor I/O usage, plan for expansion",
                        metadata={"utilization_pct": util},
                    ))

            # Missing vendor/model
            if not ctrl.vendor or not ctrl.model:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.MISSING_DATA,
                    severity=GapSeverity.MEDIUM,
                    title=f"Controller {ctrl.id} missing vendor/model",
                    description=f"Controller '{ctrl.id}' missing vendor or model info",
                    affected_object_type="controller",
                    affected_object_id=ctrl.id,
                    recommendation="Add vendor and model for documentation",
                    fix_suggestion=f"ctrl.vendor = 'JCI'; ctrl.model = 'NAE55'",
                    auto_fixable=True,
                ))

    def _analyze_relationships(self) -> None:
        """Analyze cross-object relationships for consistency."""
        # Equipment -> Controller consistency
        for equip in self.project.equipment:
            if equip.controller_id:
                ctrl = self.project.get_controller(equip.controller_id)
                if not ctrl:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.INCONSISTENT_CONFIG,
                        severity=GapSeverity.HIGH,
                        title=f"Equipment {equip.id} references non-existent controller",
                        description=f"Equipment '{equip.id}' assigned to controller '{equip.controller_id}' which doesn't exist",
                        affected_object_type="equipment",
                        affected_object_id=equip.id,
                        recommendation="Fix controller ID or add missing controller",
                        fix_suggestion=f"equip.controller_id = 'MPC-1' (existing)",
                        metadata={"referenced_controller": equip.controller_id},
                    ))
                elif equip.controller_id not in ctrl.serves_equipment_ids:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.INCONSISTENT_CONFIG,
                        severity=GapSeverity.MEDIUM,
                        title=f"Equipment {equip.id} not in controller's served list",
                        description=f"Equipment assigned to controller but controller doesn't list it",
                        affected_object_type="equipment",
                        affected_object_id=equip.id,
                        recommendation="Add equipment to controller's serves_equipment_ids",
                        fix_suggestion=f"ctrl.serves_equipment_ids.append('{equip.id}')",
                        auto_fixable=True,
                    ))

        # Point -> Equipment consistency
        for point in self.project.points:
            equip = self.project.get_equipment(point.equipment_id)
            if not equip:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCONSISTENT_CONFIG,
                    severity=GapSeverity.HIGH,
                    title=f"Point {point.name} references non-existent equipment",
                    description=f"Point '{point.name}' assigned to equipment '{point.equipment_id}' which doesn't exist",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Fix equipment ID or add missing equipment",
                    metadata={"referenced_equipment": point.equipment_id},
                ))
            elif point.controller_id and equip.controller_id != point.controller_id:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.INCONSISTENT_CONFIG,
                    severity=GapSeverity.HIGH,
                    title=f"Point {point.name} controller mismatch",
                    description=f"Point controller ({point.controller_id}) differs from equipment controller ({equip.controller_id})",
                    affected_object_type="point",
                    affected_object_id=point.name,
                    recommendation="Align point controller with equipment controller",
                    fix_suggestion=f"point.controller_id = '{equip.controller_id}'",
                    auto_fixable=True,
                ))

        # Point -> Controller consistency
        for point in self.project.points:
            if point.controller_id:
                ctrl = self.project.get_controller(point.controller_id)
                if not ctrl:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.INCONSISTENT_CONFIG,
                        severity=GapSeverity.HIGH,
                        title=f"Point {point.name} references non-existent controller",
                        description=f"Point '{point.name}' assigned to controller '{point.controller_id}' which doesn't exist",
                        affected_object_type="point",
                        affected_object_id=point.name,
                        recommendation="Fix controller ID or add missing controller",
                        metadata={"referenced_controller": point.controller_id},
                    ))
                elif point.name not in ctrl.owned_point_names:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.INCONSISTENT_CONFIG,
                        severity=GapSeverity.MEDIUM,
                        title=f"Point {point.name} not in controller's owned points",
                        description=f"Point assigned to controller but controller doesn't list it as owned",
                        affected_object_type="point",
                        affected_object_id=point.name,
                        recommendation="Add point to controller's owned_point_names",
                        fix_suggestion=f"ctrl.owned_point_names.append('{point.name}')",
                        auto_fixable=True,
                    ))

        # Controller -> Equipment consistency
        for ctrl in self.project.controllers:
            for equip_id in ctrl.serves_equipment_ids:
                equip = self.project.get_equipment(equip_id)
                if not equip:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.INCONSISTENT_CONFIG,
                        severity=GapSeverity.HIGH,
                        title=f"Controller {ctrl.id} serves non-existent equipment",
                        description=f"Controller '{ctrl.id}' lists equipment '{equip_id}' which doesn't exist",
                        affected_object_type="controller",
                        affected_object_id=ctrl.id,
                        recommendation="Fix equipment ID or add missing equipment",
                        metadata={"referenced_equipment": equip_id},
                    ))
                elif equip.controller_id != ctrl.id:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.INCONSISTENT_CONFIG,
                        severity=GapSeverity.MEDIUM,
                        title=f"Controller {ctrl.id} serves equipment with different controller",
                        description=f"Equipment '{equip_id}' served by controller '{ctrl.id}' but has controller_id '{equip.controller_id}'",
                        affected_object_type="controller",
                        affected_object_id=ctrl.id,
                        recommendation="Align equipment controller_id with serving controller",
                        fix_suggestion=f"equip.controller_id = '{ctrl.id}'",
                        auto_fixable=True,
                    ))

    def _analyze_validation_results(self) -> None:
        """Convert validation errors to gaps."""
        engine = ValidationEngine()
        report = engine.validate(self.project)

        for result in report.errors:
            severity_map = {
                ValidationSeverity.ERROR: GapSeverity.CRITICAL,
                ValidationSeverity.WARNING: GapSeverity.HIGH,
                ValidationSeverity.INFO: GapSeverity.MEDIUM,
            }
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.VALIDATION_ERROR,
                severity=severity_map.get(result.severity, GapSeverity.HIGH),
                title=f"Validation: {result.rule_id}",
                description=result.message,
                affected_object_type=result.object_type,
                affected_object_id=result.object_id,
                recommendation=f"Fix validation rule {result.rule_id}",
                metadata={"rule_id": result.rule_id, "field": result.field},
            ))

        for result in report.warnings:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.VALIDATION_ERROR,
                severity=GapSeverity.MEDIUM,
                title=f"Validation Warning: {result.rule_id}",
                description=result.message,
                affected_object_type=result.object_type,
                affected_object_id=result.object_id,
                recommendation=f"Review validation rule {result.rule_id}",
                metadata={"rule_id": result.rule_id, "field": result.field},
            ))

    def _analyze_generation_readiness(self) -> None:
        """Check if project is ready for each generator."""
        generators = {
            "checkout": self._check_checkout_readiness,
            "reports": self._check_reports_readiness,
            "graphics": self._check_graphics_readiness,
            "logic": self._check_logic_readiness,
            "exports": self._check_exports_readiness,
        }

        for gen_name, check_func in generators.items():
            try:
                check_func(gen_name)
            except Exception as e:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.GENERATION_BLOCKER,
                    severity=GapSeverity.HIGH,
                    title=f"Generator {gen_name} readiness check failed",
                    description=f"Error checking {gen_name} readiness: {e}",
                    affected_object_type="project",
                    affected_object_id=self.project.metadata.project_id,
                    recommendation="Fix data issues before generating",
                    metadata={"generator": gen_name, "error": str(e)},
                ))

    def _check_checkout_readiness(self, gen_name: str) -> None:
        """Check if checkout generation is ready."""
        if not self.project.equipment:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.GENERATION_BLOCKER,
                severity=GapSeverity.CRITICAL,
                title="Cannot generate checkout: no equipment",
                description="Checkout sheets require equipment definitions",
                affected_object_type="project",
                affected_object_id=self.project.metadata.project_id,
                recommendation="Add equipment first",
            ))

        for equip in self.project.equipment:
            points = self.project.get_points_for_equipment(equip.id)
            if not points:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.GENERATION_BLOCKER,
                    severity=GapSeverity.HIGH,
                    title=f"Equipment {equip.id} has no points for checkout",
                    description=f"Checkout for '{equip.id}' will be empty",
                    affected_object_type="equipment",
                    affected_object_id=equip.id,
                    recommendation="Add points to equipment",
                ))

    def _check_reports_readiness(self, gen_name: str) -> None:
        """Check if report generation is ready."""
        if not self.project.equipment:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.GENERATION_BLOCKER,
                severity=GapSeverity.CRITICAL,
                title="Cannot generate reports: no equipment",
                description="Equipment schedule report requires equipment definitions",
                affected_object_type="project",
                affected_object_id=self.project.metadata.project_id,
                recommendation="Add equipment first",
            ))

    def _check_graphics_readiness(self, gen_name: str) -> None:
        """Check if graphics generation is ready."""
        for equip in self.project.equipment:
            points = self.project.get_points_for_equipment(equip.id)
            if not points:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.GENERATION_BLOCKER,
                    severity=GapSeverity.HIGH,
                    title=f"Cannot generate graphic for {equip.id}: no points",
                    description=f"Equipment '{equip.id}' has no points for graphic bindings",
                    affected_object_type="equipment",
                    affected_object_id=equip.id,
                    recommendation="Add points to equipment",
                ))

    def _check_logic_readiness(self, gen_name: str) -> None:
        """Check if logic generation is ready."""
        for equip in self.project.equipment:
            if equip.type in (EquipmentType.AHU, EquipmentType.RTU, EquipmentType.VAV,
                             EquipmentType.CHILLER, EquipmentType.BOILER,
                             EquipmentType.COOLING_TOWER, EquipmentType.PUMP_HW,
                             EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW):
                points = self.project.get_points_for_equipment(equip.id)
                if not points:
                    self._add_gap(Gap(
                        gap_id=self._new_gap_id(),
                        category=GapCategory.GENERATION_BLOCKER,
                        severity=GapSeverity.HIGH,
                        title=f"Cannot generate logic for {equip.id}: no points",
                        description=f"Logic generation for '{equip.id}' requires points",
                        affected_object_type="equipment",
                        affected_object_id=equip.id,
                        recommendation="Add points to equipment",
                    ))

    def _check_exports_readiness(self, gen_name: str) -> None:
        """Check if vendor exports are ready."""
        if not self.project.controllers:
            self._add_gap(Gap(
                gap_id=self._new_gap_id(),
                category=GapCategory.GENERATION_BLOCKER,
                severity=GapSeverity.CRITICAL,
                title="Cannot export: no controllers defined",
                description="Vendor exports require controller configurations",
                affected_object_type="project",
                affected_object_id=self.project.metadata.project_id,
                recommendation="Add controllers first",
            ))

        for ctrl in self.project.controllers:
            if not ctrl.protocols:
                self._add_gap(Gap(
                    gap_id=self._new_gap_id(),
                    category=GapCategory.GENERATION_BLOCKER,
                    severity=GapSeverity.HIGH,
                    title=f"Controller {ctrl.id} has no protocols for export",
                    description=f"Vendor exports require communication protocol definitions",
                    affected_object_type="controller",
                    affected_object_id=ctrl.id,
                    recommendation="Add protocols to controller",
                ))


def analyze_gaps(project: Project) -> GapAnalysisReport:
    """Convenience function to run gap analysis."""
    analyzer = GapAnalyzer(project)
    return analyzer.analyze()


__all__ = [
    "GapAnalyzer",
    "GapAnalysisReport",
    "Gap",
    "GapSeverity",
    "GapCategory",
    "analyze_gaps",
]
