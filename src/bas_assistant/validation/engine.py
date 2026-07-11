"""Validation engine - checks completeness, consistency, naming, engineering constraints."""

from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from ..models import (
    Project,
    Equipment,
    Point,
    Controller,
    PointKind,
    PointDirection,
    PointSource,
    ValidationSeverity,
    ValidationCategory,
    EquipmentType,
)
from ..models.points import PointValidationIssue
from ..models.equipment import EquipmentRelationship


class ValidationRule(BaseModel):
    """A validation rule definition."""

    rule_id: str
    name: str
    category: ValidationCategory
    severity: ValidationSeverity
    description: str
    applies_to: list[str] = Field(default_factory=list)  # point, equipment, controller, project
    enabled: bool = True


class ValidationResult(BaseModel):
    """Result of validating a single object."""

    object_type: str  # point, equipment, controller, project
    object_id: str
    rule_id: str
    severity: ValidationSeverity
    category: ValidationCategory
    message: str
    field: Optional[str] = None
    passed: bool


class ValidationReport(BaseModel):
    """Complete validation report for a project."""

    project_id: str
    validated_at: datetime = Field(default_factory=datetime.now)
    total_rules_run: int = 0
    total_objects_checked: int = 0
    results: list[ValidationResult] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationResult]:
        return [r for r in self.results if r.severity == ValidationSeverity.ERROR and not r.passed]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [r for r in self.results if r.severity == ValidationSeverity.WARNING and not r.passed]

    @property
    def infos(self) -> list[ValidationResult]:
        return [r for r in self.results if r.severity == ValidationSeverity.INFO and not r.passed]

    @property
    def passed(self) -> list[ValidationResult]:
        return [r for r in self.results if r.passed]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def summary(self) -> dict:
        return {
            "total_rules": self.total_rules_run,
            "total_objects": self.total_objects_checked,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "infos": len(self.infos),
            "passed": len(self.passed),
            "status": "invalid" if self.has_errors else ("warning" if self.has_warnings else "valid"),
        }

    def add_result(self, result: ValidationResult) -> None:
        self.results.append(result)
        self.total_objects_checked += 1


# Built-in validation rules
BUILTIN_RULES: list[ValidationRule] = [
    # Naming rules
    ValidationRule(
        rule_id="NAMING-001",
        name="Equipment ID format",
        category=ValidationCategory.NAMING,
        severity=ValidationSeverity.ERROR,
        description="Equipment ID must follow BAS tag style with a numeric suffix (e.g., AHU-1, VAV-203, PUMP-CHW-1)",
        applies_to=["equipment"],
    ),
    ValidationRule(
        rule_id="NAMING-002",
        name="Point name format",
        category=ValidationCategory.NAMING,
        severity=ValidationSeverity.ERROR,
        description="Point name must follow project naming convention",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="NAMING-003",
        name="Controller ID format",
        category=ValidationCategory.NAMING,
        severity=ValidationSeverity.ERROR,
        description="Controller ID must be non-empty and unique",
        applies_to=["controller"],
    ),

    # Completeness rules
    ValidationRule(
        rule_id="COMP-001",
        name="Equipment has controller",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.ERROR,
        description="Every equipment must be assigned to a controller",
        applies_to=["equipment"],
    ),
    ValidationRule(
        rule_id="COMP-002",
        name="Point has equipment",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.ERROR,
        description="Every point must reference an existing equipment",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="COMP-003",
        name="Point has controller",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.WARNING,
        description="Point should have an owning controller assigned",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="COMP-004",
        name="Controller has points",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.WARNING,
        description="Controller should own at least one point",
        applies_to=["controller"],
    ),
    ValidationRule(
        rule_id="COMP-005",
        name="Equipment has points",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.WARNING,
        description="Equipment should have at least one point",
        applies_to=["equipment"],
    ),

    # Consistency rules
    ValidationRule(
        rule_id="CONS-001",
        name="Point equipment matches controller",
        category=ValidationCategory.CONSISTENCY,
        severity=ValidationSeverity.ERROR,
        description="Point's equipment must be served by point's controller",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="CONS-002",
        name="Controller serves equipment",
        category=ValidationCategory.CONSISTENCY,
        severity=ValidationSeverity.ERROR,
        description="Controller's served equipment must exist",
        applies_to=["controller"],
    ),
    ValidationRule(
        rule_id="CONS-003",
        name="No duplicate point names",
        category=ValidationCategory.CONSISTENCY,
        severity=ValidationSeverity.ERROR,
        description="All point names must be unique within project",
        applies_to=["project"],
    ),
    ValidationRule(
        rule_id="CONS-004",
        name="No duplicate equipment IDs",
        category=ValidationCategory.CONSISTENCY,
        severity=ValidationSeverity.ERROR,
        description="All equipment IDs must be unique within project",
        applies_to=["project"],
    ),
    ValidationRule(
        rule_id="CONS-005",
        name="No duplicate controller IDs",
        category=ValidationCategory.CONSISTENCY,
        severity=ValidationSeverity.ERROR,
        description="All controller IDs must be unique within project",
        applies_to=["project"],
    ),

    # Engineering rules
    ValidationRule(
        rule_id="ENG-001",
        name="Sensor range validity",
        category=ValidationCategory.ENGINEERING,
        severity=ValidationSeverity.WARNING,
        description="Sensor points should have valid range (min < max)",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="ENG-002",
        name="Temperature units consistency",
        category=ValidationCategory.ENGINEERING,
        severity=ValidationSeverity.WARNING,
        description="Temperature points should use consistent units (degF or degC)",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="ENG-003",
        name="Pressure units for pressure points",
        category=ValidationCategory.ENGINEERING,
        severity=ValidationSeverity.WARNING,
        description="Pressure points should use pressure units (inWC, psi, Pa, kPa)",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="ENG-004",
        name="Flow units for flow points",
        category=ValidationCategory.ENGINEERING,
        severity=ValidationSeverity.WARNING,
        description="Flow points should use flow units (CFM, GPM, LPS, CFH)",
        applies_to=["point"],
    ),

    # Protocol rules
    ValidationRule(
        rule_id="PROTO-001",
        name="BACnet object type required",
        category=ValidationCategory.PROTOCOL,
        severity=ValidationSeverity.WARNING,
        description="Points on BACnet controllers should have BACnet object type",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="PROTO-002",
        name="BACnet instance unique per controller",
        category=ValidationCategory.PROTOCOL,
        severity=ValidationSeverity.ERROR,
        description="BACnet instance numbers must be unique within each controller",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="PROTO-003",
        name="Modbus register unique per controller",
        category=ValidationCategory.PROTOCOL,
        severity=ValidationSeverity.ERROR,
        description="Modbus register addresses must be unique within each controller",
        applies_to=["point"],
    ),
]


class ValidationEngine:
    """Validates BAS project models against rules."""

    def __init__(self, rules: Optional[list[ValidationRule]] = None):
        self.rules = rules or BUILTIN_RULES
        self.enabled_rules = [r for r in self.rules if r.enabled]

    def validate(self, project: Project) -> ValidationReport:
        """Run all validation rules on a project."""
        report = ValidationReport(project_id=project.metadata.project_id)
        report.total_rules_run = len(self.enabled_rules)

        # Run project-level rules
        for rule in self.enabled_rules:
            if "project" in rule.applies_to:
                self._run_project_rule(project, rule, report)

        # Run equipment rules
        for equipment in project.equipment:
            for rule in self.enabled_rules:
                if "equipment" in rule.applies_to:
                    self._run_equipment_rule(project, equipment, rule, report)

        # Run point rules
        for point in project.points:
            for rule in self.enabled_rules:
                if "point" in rule.applies_to:
                    self._run_point_rule(project, point, rule, report)

        # Run controller rules
        for controller in project.controllers:
            for rule in self.enabled_rules:
                if "controller" in rule.applies_to:
                    self._run_controller_rule(project, controller, rule, report)

        # Update project validation status
        project.validation_status = report.summary["status"]
        project.last_validated = report.validated_at

        return report

    def _run_project_rule(self, project: Project, rule: ValidationRule, report: ValidationReport) -> None:
        if rule.rule_id == "CONS-003":
            # No duplicate point names
            point_names = [p.name for p in project.points]
            duplicates = [name for name in set(point_names) if point_names.count(name) > 1]
            passed = len(duplicates) == 0
            report.add_result(ValidationResult(
                object_type="project",
                object_id=project.metadata.project_id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Duplicate point names: {duplicates}" if not passed else "All point names are unique",
                passed=passed,
            ))
        elif rule.rule_id == "CONS-004":
            # No duplicate equipment IDs
            equip_ids = [e.id for e in project.equipment]
            duplicates = [eid for eid in set(equip_ids) if equip_ids.count(eid) > 1]
            passed = len(duplicates) == 0
            report.add_result(ValidationResult(
                object_type="project",
                object_id=project.metadata.project_id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Duplicate equipment IDs: {duplicates}" if not passed else "All equipment IDs are unique",
                passed=passed,
            ))
        elif rule.rule_id == "CONS-005":
            # No duplicate controller IDs
            ctrl_ids = [c.id for c in project.controllers]
            duplicates = [cid for cid in set(ctrl_ids) if ctrl_ids.count(cid) > 1]
            passed = len(duplicates) == 0
            report.add_result(ValidationResult(
                object_type="project",
                object_id=project.metadata.project_id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Duplicate controller IDs: {duplicates}" if not passed else "All controller IDs are unique",
                passed=passed,
            ))

    def _run_equipment_rule(self, project: Project, equipment: Equipment, rule: ValidationRule, report: ValidationReport) -> None:
        if rule.rule_id == "NAMING-001":
            # Equipment ID format: BAS tag segments ending with a numeric suffix.
            import re
            pattern = r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+$"
            passed = bool(re.match(pattern, equipment.id))
            report.add_result(ValidationResult(
                object_type="equipment",
                object_id=equipment.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Equipment ID '{equipment.id}' does not match BAS tag convention" if not passed else "Equipment ID format valid",
                passed=passed,
            ))
        elif rule.rule_id == "COMP-001":
            # Equipment has controller
            passed = equipment.controller_id is not None
            report.add_result(ValidationResult(
                object_type="equipment",
                object_id=equipment.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Equipment '{equipment.id}' has no controller assigned" if not passed else "Equipment has controller",
                passed=passed,
            ))
        elif rule.rule_id == "COMP-005":
            # Equipment has points
            points = project.get_points_for_equipment(equipment.id)
            passed = len(points) > 0
            report.add_result(ValidationResult(
                object_type="equipment",
                object_id=equipment.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Equipment '{equipment.id}' has no points" if not passed else f"Equipment has {len(points)} points",
                passed=passed,
            ))

    def _run_point_rule(self, project: Project, point: Point, rule: ValidationRule, report: ValidationReport) -> None:
        if rule.rule_id == "NAMING-002":
            # Point naming convention:
            # "<equipment-id> <point-code>" where the point code is uppercase/alphanumeric
            # with optional hyphenated abbreviations such as SAT, SF-CMD, CHW-VLV-CMD.
            import re
            prefix = f"{point.equipment_id} "
            suffix = point.name[len(prefix):] if point.name.startswith(prefix) else ""
            passed = bool(
                point.name
                and point.name.startswith(prefix)
                and suffix
                and re.match(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$", suffix)
            )
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Point name '{point.name}' does not match BAS point naming convention" if not passed else "Point name format valid",
                passed=passed,
            ))
        elif rule.rule_id == "COMP-002":
            # Point has equipment
            equipment = project.get_equipment(point.equipment_id)
            passed = equipment is not None
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Point '{point.name}' references non-existent equipment '{point.equipment_id}'" if not passed else "Point references valid equipment",
                passed=passed,
            ))
        elif rule.rule_id == "COMP-003":
            # Point has controller
            passed = point.controller_id is not None
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Point '{point.name}' has no controller assigned" if not passed else "Point has controller",
                passed=passed,
            ))
        elif rule.rule_id == "CONS-001":
            # Point equipment matches controller
            if point.controller_id and point.equipment_id:
                equipment = project.get_equipment(point.equipment_id)
                controller = project.get_controller(point.controller_id)
                if equipment and controller:
                    passed = equipment.controller_id == point.controller_id
                    report.add_result(ValidationResult(
                        object_type="point",
                        object_id=point.name,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        category=rule.category,
                        message=f"Point '{point.name}' equipment controller mismatch" if not passed else "Point equipment/controller consistent",
                        passed=passed,
                    ))
        elif rule.rule_id == "ENG-001":
            # Sensor range validity
            if point.kind == PointKind.SENSOR and point.range_min is not None and point.range_max is not None:
                passed = point.range_min < point.range_max
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=f"Point '{point.name}' has invalid range: min={point.range_min} >= max={point.range_max}" if not passed else "Sensor range valid",
                    passed=passed,
                ))
            else:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message="Sensor range not specified",
                    passed=True,
                ))
        elif rule.rule_id == "ENG-002":
            # Temperature units consistency
            if point.units:
                temp_units = {"degF", "degC", "degf", "degc", "f", "c", "fahrenheit", "celsius"}
                passed = point.units.lower() in temp_units or not any(u in point.name.lower() for u in ["temp", "sat", "mat", "rat", "oat", "dat", "zt"])
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=f"Temperature point '{point.name}' units '{point.units}' may be inconsistent" if not passed else "Temperature units consistent",
                    passed=passed,
                ))
            else:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message="Point has no units specified",
                    passed=True,
                ))
        elif rule.rule_id == "ENG-003":
            # Pressure units for pressure points
            if point.kind == PointKind.SENSOR and any(p in point.name.lower() for p in ["sp", "dp", "press", "static"]):
                pressure_units = {"inwc", "wc", "inh2o", "psi", "pa", "kpa", "inwc", "in.wc"}
                passed = point.units and point.units.lower() in pressure_units
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=f"Pressure point '{point.name}' should use pressure units" if not passed else "Pressure units valid",
                    passed=passed,
                ))
            else:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message="Not a pressure point",
                    passed=True,
                ))
        elif rule.rule_id == "ENG-004":
            # Flow units for flow points
            if point.kind == PointKind.SENSOR and any(f in point.name.lower() for f in ["flow", "cfm", "gpm", "lps", "cfh"]):
                flow_units = {"cfm", "gpm", "lps", "cfh", "m3h", "m3/s", "gph"}
                passed = point.units and point.units.lower() in flow_units
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=f"Flow point '{point.name}' should use flow units" if not passed else "Flow units valid",
                    passed=passed,
                ))
            else:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message="Not a flow point",
                    passed=True,
                ))
        elif rule.rule_id == "PROTO-001":
            # BACnet object type required for BACnet controllers
            if point.controller_id:
                controller = project.get_controller(point.controller_id)
                if controller and any(p.value in ["BACnet/IP", "BACnet/MSTP"] for p in controller.protocols):
                    passed = point.bacnet_object_type is not None
                    report.add_result(ValidationResult(
                        object_type="point",
                        object_id=point.name,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        category=rule.category,
                        message=f"Point '{point.name}' on BACnet controller missing BACnet object type" if not passed else "BACnet object type present",
                        passed=passed,
                    ))
                else:
                    report.add_result(ValidationResult(
                        object_type="point",
                        object_id=point.name,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        category=rule.category,
                        message="Not on BACnet controller",
                        passed=True,
                    ))
            else:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message="Point has no controller",
                    passed=True,
                ))
        elif rule.rule_id == "PROTO-002":
            # BACnet instance unique per controller
            if point.bacnet_instance is not None and point.controller_id:
                controller_points = project.get_points_for_controller(point.controller_id)
                instances = [p.bacnet_instance for p in controller_points if p.bacnet_instance is not None]
                passed = instances.count(point.bacnet_instance) == 1
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=f"BACnet instance {point.bacnet_instance} duplicated on controller {point.controller_id}" if not passed else "BACnet instance unique",
                    passed=passed,
                ))
            else:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message="No BACnet instance assigned",
                    passed=True,
                ))
        elif rule.rule_id == "PROTO-003":
            # Modbus register unique per controller
            if point.modbus_register is not None and point.controller_id:
                controller_points = project.get_points_for_controller(point.controller_id)
                registers = [p.modbus_register for p in controller_points if p.modbus_register is not None]
                passed = registers.count(point.modbus_register) == 1
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=f"Modbus register {point.modbus_register} duplicated on controller {point.controller_id}" if not passed else "Modbus register unique",
                    passed=passed,
                ))
            else:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message="No Modbus register assigned",
                    passed=True,
                ))

    def _run_controller_rule(self, project: Project, controller: Controller, rule: ValidationRule, report: ValidationReport) -> None:
        if rule.rule_id == "NAMING-003":
            # Controller ID format
            passed = len(controller.id) > 0
            report.add_result(ValidationResult(
                object_type="controller",
                object_id=controller.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Controller ID '{controller.id}' is empty" if not passed else "Controller ID format valid",
                passed=passed,
            ))
        elif rule.rule_id == "COMP-004":
            # Controller has points
            points = project.get_points_for_controller(controller.id)
            passed = len(points) > 0
            report.add_result(ValidationResult(
                object_type="controller",
                object_id=controller.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                message=f"Controller '{controller.id}' owns no points" if not passed else f"Controller owns {len(points)} points",
                passed=passed,
            ))
        elif rule.rule_id == "CONS-002":
            # Controller serves equipment
            for equip_id in controller.serves_equipment_ids:
                equipment = project.get_equipment(equip_id)
                passed = equipment is not None
                report.add_result(ValidationResult(
                    object_type="controller",
                    object_id=controller.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=f"Controller '{controller.id}' serves non-existent equipment '{equip_id}'" if not passed else "All served equipment exist",
                    passed=passed,
                ))


__all__ = [
    "ValidationEngine",
    "ValidationRule",
    "ValidationResult",
    "ValidationReport",
    "BUILTIN_RULES",
]
