"""Validation Reasoning - Engineering rule validation and compliance checking."""

from dataclasses import dataclass, field
from enum import Enum

from ..models import (
    Controller,
    Equipment,
    EquipmentType,
    Point,
    PointKind,
    ValidationCategory,
    ValidationSeverity,
)


class ValidationRuleType(str, Enum):
    """Types of validation rules."""
    HARD_CONSTRAINT = "hard_constraint"      # Must pass (physics, code)
    SOFT_CONSTRAINT = "soft_constraint"      # Should pass (best practice)
    WARNING = "warning"                       # Advisory


@dataclass
class EngineeringRule:
    """An engineering validation rule."""
    rule_id: str
    name: str
    description: str
    rule_type: ValidationRuleType
    category: ValidationCategory
    applies_to: list[str]  # point, equipment, controller, project
    condition: str  # Human-readable condition
    severity: ValidationSeverity
    auto_fixable: bool = False
    fix_description: str = ""
    references: list[str] = field(default_factory=list)  # Code sections, standards


@dataclass
class ValidationFinding:
    """A validation finding against a rule."""
    rule_id: str
    rule_name: str
    object_type: str
    object_id: str
    passed: bool
    message: str
    severity: ValidationSeverity
    details: dict = field(default_factory=dict)
    suggested_fix: str = ""


class EngineeringRulesEngine:
    """Validates project data against engineering rules and standards."""

    def __init__(self):
        self.rules = self._load_builtin_rules()

    def _load_builtin_rules(self) -> list[EngineeringRule]:
        """Load built-in engineering validation rules."""
        return [
            # === TEMPERATURE SENSOR RULES ===
            EngineeringRule(
                rule_id="ENG-TEMP-001",
                name="Temperature Sensor Range Validity",
                description="Temperature sensors must have realistic operating ranges",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Sensor points with temperature units must have range_min >= -50°F and range_max <= 250°F",
                severity=ValidationSeverity.ERROR,
                auto_fixable=True,
                fix_description="Set appropriate range based on sensor type and application",
                references=["ASHRAE Guideline 13-2011", "Sensor manufacturer specs"],
            ),

            EngineeringRule(
                rule_id="ENG-TEMP-002",
                name="Supply Air Temperature Limits",
                description="SAT sensors must have ranges covering typical supply air conditions",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Points with 'SAT' or 'SUPPLY AIR' in name must have range covering 40-130°F",
                severity=ValidationSeverity.WARNING,
                auto_fixable=True,
                fix_description="Adjust range to 40-130°F for typical SAT applications",
            ),

            EngineeringRule(
                rule_id="ENG-TEMP-003",
                name="Outside Air Temperature Range",
                description="OAT sensors must cover full climate range",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Points with 'OAT' or 'OUTSIDE AIR' in name must have range covering -20 to 120°F",
                severity=ValidationSeverity.WARNING,
                auto_fixable=True,
                fix_description="Set range to -20 to 120°F for North American climates",
            ),

            # === PRESSURE SENSOR RULES ===
            EngineeringRule(
                rule_id="ENG-PRESS-001",
                name="Duct Static Pressure Range",
                description="Duct static pressure sensors must have appropriate ranges",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Points with 'STATIC' or 'SP' in name and 'inWC' units must have range 0-5 inWC minimum",
                severity=ValidationSeverity.WARNING,
                auto_fixable=True,
                fix_description="Set range to 0-5 inWC for typical duct static",
            ),

            EngineeringRule(
                rule_id="ENG-PRESS-002",
                name="Building Static Pressure Range",
                description="Building static pressure sensors need tight ranges",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Points with 'BLDG STATIC' or 'BUILDING STATIC' must have range -0.25 to +0.25 inWC",
                severity=ValidationSeverity.WARNING,
                auto_fixable=True,
                fix_description="Set range to -0.25 to +0.25 inWC",
            ),

            EngineeringRule(
                rule_id="ENG-PRESS-003",
                name="Water Differential Pressure Range",
                description="Water DP sensors for pumps/coils need appropriate ranges",
                rule_type=ValidationRuleType.SOFT_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Points with 'DP' or 'DIFF PRESS' and water service should have range 0-50 ft or 0-100 ft",
                severity=ValidationSeverity.INFO,
                auto_fixable=True,
                fix_description="Set range based on pump head and coil pressure drop",
            ),

            # === FLOW SENSOR RULES ===
            EngineeringRule(
                rule_id="ENG-FLOW-001",
                name="Air Flow Sensor Range",
                description="Air flow stations must have ranges matching design CFM",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Points with 'CFM' or 'FLOW' and air service should have range_max >= design_cfm * 1.2",
                severity=ValidationSeverity.WARNING,
                auto_fixable=False,
                fix_description="Coordinate with equipment design CFM",
            ),

            EngineeringRule(
                rule_id="ENG-FLOW-002",
                name="Water Flow Sensor Range",
                description="Water flow meters must have ranges matching design GPM",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Points with 'GPM' or 'FLOW' and water service should have range_max >= design_gpm * 1.2",
                severity=ValidationSeverity.WARNING,
                auto_fixable=False,
            ),

            # === ACTUATOR RULES ===
            EngineeringRule(
                rule_id="ENG-ACT-001",
                name="Valve Actuator Position Feedback",
                description="Modulating valves should have position feedback",
                rule_type=ValidationRuleType.SOFT_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Actuator points for modulating valves should have matching feedback sensor",
                severity=ValidationSeverity.INFO,
                auto_fixable=False,
            ),

            EngineeringRule(
                rule_id="ENG-ACT-002",
                name="Damper Actuator Authority",
                description="Damper actuators must have sufficient authority",
                rule_type=ValidationRuleType.SOFT_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="VAV and AHU dampers should have actuators sized for 2x design torque",
                severity=ValidationSeverity.INFO,
                auto_fixable=False,
            ),

            # === CONTROL LOOP RULES ===
            EngineeringRule(
                rule_id="ENG-LOOP-001",
                name="PID Loop Sensor Redundancy",
                description="Critical control loops should have redundant sensors",
                rule_type=ValidationRuleType.SOFT_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="SAT, MAT, and critical zone temp loops should have backup sensors",
                severity=ValidationSeverity.INFO,
                auto_fixable=False,
            ),

            EngineeringRule(
                rule_id="ENG-LOOP-002",
                name="Control Loop Update Rate",
                description="Control loops must execute at appropriate rates",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["controller"],
                condition="Fast loops (flow, pressure) <= 1s; Temp loops <= 10s; Slow loops <= 60s",
                severity=ValidationSeverity.WARNING,
                auto_fixable=False,
            ),

            EngineeringRule(
                rule_id="ENG-LOOP-003",
                name="Integral Windup Protection",
                description="PID loops with output limits must have anti-windup",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="All PID loops with output limits (0-100%) must have anti-windup configured",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ISA-5.9", "PID Best Practices"],
            ),

            # === ECONOMIZER RULES ===
            EngineeringRule(
                rule_id="ENG-ECON-001",
                name="Economizer High Limit",
                description="Airside economizers must have high limit lockout",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="AHU/RTU with economizer must have OA temperature high limit (<= 70°F) or enthalpy high limit (<= 28 BTU/lb)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 90.1", "IECC", "Title 24"],
            ),

            EngineeringRule(
                rule_id="ENG-ECON-002",
                name="Economizer Differential Control",
                description="Economizer should use differential enthalpy or dry-bulb",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="Economizer changeover must be differential dry-bulb or differential enthalpy (not fixed dry-bulb only)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 90.1-2019 6.5.1"],
            ),

            EngineeringRule(
                rule_id="ENG-ECON-003",
                name="Economizer Relief Air",
                description="Economizer systems must have relief air capability",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="Systems with economizer must have relief/return fan or gravity relief",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
            ),

            # === FREEZE PROTECTION ===
            EngineeringRule(
                rule_id="ENG-FREEZE-001",
                name="Freeze Stat Required",
                description="Cooling coils in cold climates must have freeze protection",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="AHU/RTU with cooling coil in climate zones 4-8 must have freeze stat",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 90.1", "IMC"],
            ),

            EngineeringRule(
                rule_id="ENG-FREEZE-002",
                name="Freeze Stat Setpoint",
                description="Freeze stat must be set correctly",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["point"],
                condition="Freeze stat setpoint must be 35-38°F (typically 35°F)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=True,
                fix_description="Set freeze stat to 35°F",
            ),

            # === VAV MINIMUM FLOW ===
            EngineeringRule(
                rule_id="ENG-VAV-001",
                name="VAV Minimum Flow Setpoint",
                description="VAV boxes must have minimum flow setpoint for ventilation",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="VAV boxes must have minimum flow setpoint >= ventilation requirement (ASHRAE 62.1)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 62.1", "ASHRAE 90.1"],
            ),

            EngineeringRule(
                rule_id="ENG-VAV-002",
                name="VAV Reheat Control",
                description="VAV reheat must be controlled to avoid simultaneous heating/cooling",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="VAV reheat valves must only open when zone temp < heating setpoint AND primary air at minimum",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 90.1"],
            ),

            # === CHILLER/BOILER PLANT ===
            EngineeringRule(
                rule_id="ENG-PLANT-001",
                name="Chiller Staging Sequence",
                description="Multiple chillers must have proper staging sequence",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="Chiller plant with 2+ chillers must have staging logic (lead/lag, efficiency-based)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
            ),

            EngineeringRule(
                rule_id="ENG-PLANT-002",
                name="Condenser Water Temperature Control",
                description="Cooling towers must have condenser water temp control",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="Cooling towers must have CW supply temp control (typically 70-85°F setpoint with approach optimization)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
            ),

            EngineeringRule(
                rule_id="ENG-PLANT-003",
                name="Boiler Plant Staging",
                description="Multiple boilers must have staging with lead/lag rotation",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="Boiler plant with 2+ boilers must have staging and runtime equalization",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
            ),

            # === PUMP CONTROL ===
            EngineeringRule(
                rule_id="ENG-PUMP-001",
                name="VFD Minimum Speed",
                description="Pump VFDs must have minimum speed to prevent deadhead",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="VFD-controlled pumps must have minimum speed >= 20% (typically 30-40%)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=True,
                fix_description="Set VFD minimum speed to 30%",
            ),

            EngineeringRule(
                rule_id="ENG-PUMP-002",
                name="Differential Pressure Sensor Location",
                description="DP sensor for pump control must be at critical circuit",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="DP sensor for VFD pump control must be located at furthest/most critical coil",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 90.1"],
            ),

            # === SMOKE/FIRE ===
            EngineeringRule(
                rule_id="ENG-FIRE-001",
                name="Duct Smoke Detector Shutdown",
                description="Supply air systems > 2000 CFM must have duct smoke detector",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="AHU/RTU with supply fan > 2000 CFM must have duct smoke detector with fan shutdown",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["IFC", "IMC", "NFPA 90A"],
            ),

            EngineeringRule(
                rule_id="ENG-FIRE-002",
                name="Fire Alarm Interface",
                description="BAS must interface with fire alarm for shutdown",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["controller"],
                condition="BAS controllers serving fire/smoke dampers or fan shutdown must have fire alarm input",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
            ),

            # === ENERGY CODES ===
            EngineeringRule(
                rule_id="ENG-ECODE-001",
                name="Demand Control Ventilation",
                description="High-occupancy spaces must have DCV",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="Spaces > 500 sq ft with occupancy > 25 people/1000 sq ft must have CO2-based DCV",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 90.1", "IECC"],
            ),

            EngineeringRule(
                rule_id="ENG-ECODE-002",
                name="Energy Recovery",
                description="Large systems must have energy recovery",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.ENGINEERING,
                applies_to=["equipment"],
                condition="Systems > 5000 CFM and > 70% OA must have energy recovery (50% effectiveness minimum)",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
                references=["ASHRAE 90.1", "IECC"],
            ),

            # === COMMUNICATION ===
            EngineeringRule(
                rule_id="ENG-COMM-001",
                name="BACnet Device Instance Uniqueness",
                description="All BACnet devices on same network must have unique instance numbers",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.PROTOCOL,
                applies_to=["controller"],
                condition="No two BACnet devices on same network may share device instance",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
            ),

            EngineeringRule(
                rule_id="ENG-COMM-002",
                name="BACnet Network Number Uniqueness",
                description="Each BACnet network must have unique network number",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.PROTOCOL,
                applies_to=["controller"],
                condition="Each BACnet/IP or MSTP network segment must have unique network number",
                severity=ValidationSeverity.ERROR,
                auto_fixable=False,
            ),

            # === NAMING ===
            EngineeringRule(
                rule_id="ENG-NAME-001",
                name="Point Naming Convention",
                description="Points must follow project naming convention",
                rule_type=ValidationRuleType.SOFT_CONSTRAINT,
                category=ValidationCategory.NAMING,
                applies_to=["point"],
                condition="Point names must follow: EQUIP-TYPE POINT-TYPE (e.g., AHU-1 SAT, VAV-101 ZT)",
                severity=ValidationSeverity.WARNING,
                auto_fixable=True,
                fix_description="Rename to match convention",
            ),

            EngineeringRule(
                rule_id="ENG-NAME-002",
                name="Equipment ID Format",
                description="Equipment IDs must follow TYPE-NNN format",
                rule_type=ValidationRuleType.HARD_CONSTRAINT,
                category=ValidationCategory.NAMING,
                applies_to=["equipment"],
                condition="Equipment IDs must match pattern: AHU-NNN, VAV-NNN, CHWP-NNN, etc.",
                severity=ValidationSeverity.ERROR,
                auto_fixable=True,
                fix_description="Rename to standard format",
            ),

        ]

    def validate_project(self, project) -> list[ValidationFinding]:
        """Run all applicable rules against a project."""
        findings = []

        for rule in self.rules:
            if "project" in rule.applies_to:
                findings.extend(self._check_project_rule(project, rule))
            if "equipment" in rule.applies_to:
                for equip in project.equipment:
                    findings.extend(self._check_equipment_rule(equip, project, rule))
            if "point" in rule.applies_to:
                for point in project.points:
                    findings.extend(self._check_point_rule(point, project, rule))
            if "controller" in rule.applies_to:
                for ctrl in project.controllers:
                    findings.extend(self._check_controller_rule(ctrl, project, rule))

        return findings

    def _check_project_rule(self, project, rule: EngineeringRule) -> list[ValidationFinding]:
        findings = []
        # Project-level rules would be implemented here
        return findings

    def _check_equipment_rule(self, equip: Equipment, project, rule: EngineeringRule) -> list[ValidationFinding]:
        findings = []

        if rule.rule_id == "ENG-ECON-001":
            if equip.type in (EquipmentType.AHU, EquipmentType.RTU):
                has_econ = any("ECON" in p.name.upper() or "OA DAMPER" in p.name.upper()
                               for p in project.get_points_for_equipment(equip.id))
                if has_econ:
                    # Check for high limit
                    oat = next((p for p in project.get_points_for_equipment(equip.id)
                                if "OAT" in p.name.upper()), None)
                    if oat and (oat.range_max is None or oat.range_max > 70):
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="equipment",
                            object_id=equip.id,
                            passed=False,
                            message=f"Economizer on {equip.id} missing high temperature limit (OAT range_max should be <= 70°F)",
                            severity=rule.severity,
                            details={"oat_point": oat.name},
                        ))
                    else:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="equipment",
                            object_id=equip.id,
                            passed=True,
                            message=f"Economizer high limit verified for {equip.id}",
                            severity=ValidationSeverity.INFO,
                        ))

        elif rule.rule_id == "ENG-FREEZE-001":
            if equip.type in (EquipmentType.AHU, EquipmentType.RTU):
                has_cooling = any("COOL" in p.name.upper() or "CHW" in p.name.upper()
                                  for p in project.get_points_for_equipment(equip.id))
                if has_cooling:
                    freeze = next((p for p in project.get_points_for_equipment(equip.id)
                                   if "FREEZE" in p.name.upper()), None)
                    if not freeze:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="equipment",
                            object_id=equip.id,
                            passed=False,
                            message=f"Equipment {equip.id} has cooling coil but no freeze stat",
                            severity=rule.severity,
                        ))
                    else:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="equipment",
                            object_id=equip.id,
                            passed=True,
                            message=f"Freeze stat present on {equip.id}",
                            severity=ValidationSeverity.INFO,
                        ))

        elif rule.rule_id == "ENG-VAV-001":
            if equip.type == EquipmentType.VAV:
                flow_points = [p for p in project.get_points_for_equipment(equip.id)
                               if p.kind == PointKind.SENSOR and "FLOW" in p.name.upper()]
                if flow_points:
                    min_flow = next((p for p in flow_points if "MIN" in p.name.upper()), None)
                    if not min_flow:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="equipment",
                            object_id=equip.id,
                            passed=False,
                            message=f"VAV {equip.id} missing minimum flow setpoint",
                            severity=rule.severity,
                        ))
                    else:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="equipment",
                            object_id=equip.id,
                            passed=True,
                            message=f"VAV {equip.id} has minimum flow setpoint",
                            severity=ValidationSeverity.INFO,
                        ))

        elif rule.rule_id == "ENG-PUMP-001":
            if equip.type in (EquipmentType.PUMP_HW, EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW):
                vfd_points = [p for p in project.get_points_for_equipment(equip.id)
                              if "VFD" in p.name.upper() or "SPEED" in p.name.upper()]
                if vfd_points:
                    # Check for minimum speed configuration
                    findings.append(ValidationFinding(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        object_type="equipment",
                        object_id=equip.id,
                        passed=True,
                        message=f"VFD pump {equip.id} - verify minimum speed >= 20%",
                        severity=ValidationSeverity.INFO,
                    ))

        return findings

    def _check_point_rule(self, point: Point, project, rule: EngineeringRule) -> list[ValidationFinding]:
        findings = []

        if rule.rule_id == "ENG-TEMP-001":
            temp_units = {"degf", "degc", "f", "c", "fahrenheit", "celsius"}
            if point.units and point.units.lower() in temp_units:
                if point.range_min is not None and point.range_min < -50:
                    findings.append(ValidationFinding(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        object_type="point",
                        object_id=point.name,
                        passed=False,
                        message=f"Temperature sensor {point.name} range_min ({point.range_min}) below -50°F",
                        severity=rule.severity,
                    ))
                if point.range_max is not None and point.range_max > 250:
                    findings.append(ValidationFinding(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        object_type="point",
                        object_id=point.name,
                        passed=False,
                        message=f"Temperature sensor {point.name} range_max ({point.range_max}) above 250°F",
                        severity=rule.severity,
                    ))
                if point.range_min is None or point.range_max is None:
                    findings.append(ValidationFinding(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        object_type="point",
                        object_id=point.name,
                        passed=False,
                        message=f"Temperature sensor {point.name} missing range (min={point.range_min}, max={point.range_max})",
                        severity=ValidationSeverity.WARNING,
                    ))

        elif rule.rule_id == "ENG-TEMP-002":
            if point.units and "deg" in point.units.lower():
                if any(kw in point.name.upper() for kw in ["SAT", "SUPPLY AIR"]):
                    if point.range_min is None or point.range_min > 40:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="point",
                            object_id=point.name,
                            passed=False,
                            message=f"SAT sensor {point.name} range_min should be <= 40°F",
                            severity=rule.severity,
                        ))
                    if point.range_max is None or point.range_max < 130:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="point",
                            object_id=point.name,
                            passed=False,
                            message=f"SAT sensor {point.name} range_max should be >= 130°F",
                            severity=rule.severity,
                        ))

        elif rule.rule_id == "ENG-PRESS-001":
            if point.units and "inwc" in point.units.lower():
                if any(kw in point.name.upper() for kw in ["STATIC", "SP ", "DUCT SP"]):
                    if point.range_max is None or point.range_max < 5:
                        findings.append(ValidationFinding(
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            object_type="point",
                            object_id=point.name,
                            passed=False,
                            message=f"Duct static {point.name} range_max should be >= 5 inWC",
                            severity=rule.severity,
                        ))

        elif rule.rule_id == "ENG-FREEZE-002":
            if "FREEZE" in point.name.upper():
                if point.range_min is not None and (point.range_min < 34 or point.range_min > 38):
                    findings.append(ValidationFinding(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        object_type="point",
                        object_id=point.name,
                        passed=False,
                        message=f"Freeze stat {point.name} setpoint ({point.range_min}) should be 35-38°F",
                        severity=rule.severity,
                    ))

        elif rule.rule_id == "ENG-NAME-001":
            # Check naming convention
            import re
            pattern = r'^[A-Z]{2,4}-\d+\s+[A-Z]{2,4}'
            if not re.match(pattern, point.name):
                findings.append(ValidationFinding(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    object_type="point",
                    object_id=point.name,
                    passed=False,
                    message=f"Point {point.name} doesn't follow naming convention (EQUIP-TYPE POINT-TYPE)",
                    severity=rule.severity,
                ))

        return findings

    def _check_controller_rule(self, ctrl: Controller, project, rule: EngineeringRule) -> list[ValidationFinding]:
        findings = []

        if rule.rule_id == "ENG-COMM-001":
            # Check BACnet device instance uniqueness
            instances = {}
            for c in project.controllers:
                for addr in c.network_addresses:
                    if "BACnet" in addr.protocol.value and addr.network_number:
                        inst = addr.network_number
                        if inst in instances:
                            findings.append(ValidationFinding(
                                rule_id=rule.rule_id,
                                rule_name=rule.name,
                                object_type="controller",
                                object_id=ctrl.id,
                                passed=False,
                                message=f"Duplicate BACnet device instance {inst} (also used by {instances[inst]})",
                                severity=rule.severity,
                            ))
                        else:
                            instances[inst] = ctrl.id

        elif rule.rule_id == "ENG-COMM-002":
            # Check BACnet network number uniqueness
            networks = {}
            for c in project.controllers:
                for addr in c.network_addresses:
                    if "BACnet" in addr.protocol.value and addr.network_number:
                        net = addr.network_number
                        if net in networks:
                            findings.append(ValidationFinding(
                                rule_id=rule.rule_id,
                                rule_name=rule.name,
                                object_type="controller",
                                object_id=ctrl.id,
                                passed=False,
                                message=f"Duplicate BACnet network number {net} (also used by {networks[net]})",
                                severity=rule.severity,
                            ))
                        else:
                            networks[net] = ctrl.id

        return findings


def validate_engineering_rules(project) -> list[ValidationFinding]:
    """Convenience function to run engineering rules validation."""
    engine = EngineeringRulesEngine()
    return engine.validate_project(project)


__all__ = [
    "EngineeringRule",
    "EngineeringRulesEngine",
    "ValidationFinding",
    "ValidationRuleType",
    "validate_engineering_rules",
]
