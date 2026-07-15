"""Validation engine - checks completeness, consistency, naming, engineering constraints."""

from datetime import datetime
import re
from pathlib import Path

from pydantic import BaseModel, Field

from ..models import (
    Controller,
    Equipment,
    Point,
    PointKind,
    PointSource,
    Project,
    SourceDocument,
    ValidationCategory,
    ValidationSeverity,
)

EQUIPMENT_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+$")
CONTROLLER_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
POINT_CODE_PATTERN = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
TEMPERATURE_TOKENS = {"temp", "sat", "mat", "rat", "oat", "eat", "lat", "dat", "zt"}
PRESSURE_TOKENS = {"press", "pressure", "static", "dp"}
FLOW_TOKENS = {"flow", "cfm", "gpm", "lps", "cfh", "m3h", "m3s"}
POINT_REF_ALIAS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bSUPPLY AIR TEMPERATURE SETPOINT\b"), "SAT-SP"),
    (re.compile(r"\bSUPPLY AIR TEMP SETPOINT\b"), "SAT-SP"),
    (re.compile(r"\bDISCHARGE AIR TEMPERATURE SETPOINT\b"), "DAT-SP"),
    (re.compile(r"\bDISCHARGE AIR TEMP SETPOINT\b"), "DAT-SP"),
    (re.compile(r"\bDISCH AIR TEMPERATURE SETPOINT\b"), "DAT-SP"),
    (re.compile(r"\bDISCH AIR TEMP SETPOINT\b"), "DAT-SP"),
    (re.compile(r"\bSUPPLY FAN STATUS\b"), "SF-STS"),
    (re.compile(r"\bSUPPLY FAN PROOF\b"), "SF-STS"),
    (re.compile(r"\bSUPPLY FAN RUN STATUS\b"), "SF-STS"),
    (re.compile(r"\bSUPPLY FAN RUN PROOF\b"), "SF-STS"),
    (re.compile(r"\bSUPPLY FAN COMMAND\b"), "SF-CMD"),
    (re.compile(r"\bSUPPLY FAN START COMMAND\b"), "SF-CMD"),
    (re.compile(r"\bSUPPLY FAN ENABLE\b"), "SF-CMD"),
    (re.compile(r"\bFAN STATUS\b"), "SF-STS"),
    (re.compile(r"\bFAN PROOF\b"), "SF-STS"),
    (re.compile(r"\bFAN COMMAND\b"), "SF-CMD"),
    (re.compile(r"\bFAN ENABLE\b"), "SF-CMD"),
    (re.compile(r"\bRUN STATUS\b"), "STS"),
    (re.compile(r"\bRUN PROOF\b"), "PRF"),
    (re.compile(r"\bENABLE COMMAND\b"), "CMD"),
    (re.compile(r"\bOCCUPIED MODE\b"), "OCC-MODE"),
    (re.compile(r"\bUNOCCUPIED MODE\b"), "UNOCC-MODE"),
    (re.compile(r"\bOCCUPANCY MODE\b"), "OCC-MODE"),
    (re.compile(r"\bOCCUPIED COMMAND\b"), "OCC-CMD"),
    (re.compile(r"\bOCCUPANCY COMMAND\b"), "OCC-CMD"),
    (re.compile(r"\bTIME SCHEDULE\b"), "SCH"),
    (re.compile(r"\bSCHEDULE STATUS\b"), "SCH-STS"),
    (re.compile(r"\bSCHEDULE COMMAND\b"), "SCH-CMD"),
    (re.compile(r"\bMODE STATUS\b"), "MODE-STS"),
    (re.compile(r"\bVALVE COMMAND\b"), "VLV-CMD"),
    (re.compile(r"\bVALVE POSITION COMMAND\b"), "VLV-CMD"),
    (re.compile(r"\bREHEAT VALVE COMMAND\b"), "HTG-CMD"),
    (re.compile(r"\bHEATING VALVE COMMAND\b"), "HTG-CMD"),
    (re.compile(r"\bREHEAT COMMAND\b"), "HTG-CMD"),
    (re.compile(r"\bREHEAT VALVE POSITION\b"), "HTG-POS"),
    (re.compile(r"\bHEATING VALVE POSITION\b"), "HTG-POS"),
    (re.compile(r"\bDAMPER COMMAND\b"), "DMP-CMD"),
    (re.compile(r"\bDAMPER POSITION COMMAND\b"), "DMP-CMD"),
    (re.compile(r"\bDAMPER POSITION FEEDBACK\b"), "DMP-POS"),
    (re.compile(r"\bDAMPER FEEDBACK\b"), "DMP-POS"),
    (re.compile(r"\bDAMPER POSITION\b"), "DMP-POS"),
    (re.compile(r"\bECONOMIZER DAMPERS\b"), "DMP-CMD"),
    (re.compile(r"\bECONOMIZER DAMPER\b"), "DMP-CMD"),
    (re.compile(r"\bLEAD LAG\b"), "LEAD-LAG"),
    (re.compile(r"\bLEAD-LAG\b"), "LEAD-LAG"),
    (re.compile(r"\bSTAGING\b"), "STAGE-CMD"),
    (re.compile(r"\bSUPPLY AIR TEMPERATURE\b"), "SAT"),
    (re.compile(r"\bSUPPLY AIR TEMP\b"), "SAT"),
    (re.compile(r"\bDISCHARGE AIR TEMPERATURE\b"), "DAT"),
    (re.compile(r"\bDISCHARGE AIR TEMP\b"), "DAT"),
    (re.compile(r"\bDISCH AIR TEMPERATURE\b"), "DAT"),
    (re.compile(r"\bDISCH AIR TEMP\b"), "DAT"),
    (re.compile(r"\bMIXED AIR TEMPERATURE\b"), "MAT"),
    (re.compile(r"\bMIXED AIR TEMP\b"), "MAT"),
    (re.compile(r"\bRETURN AIR TEMPERATURE\b"), "RAT"),
    (re.compile(r"\bRETURN AIR TEMP\b"), "RAT"),
    (re.compile(r"\bOUTSIDE AIR TEMPERATURE\b"), "OAT"),
    (re.compile(r"\bOUTSIDE AIR TEMP\b"), "OAT"),
    (re.compile(r"\bOUTDOOR AIR TEMPERATURE\b"), "OAT"),
    (re.compile(r"\bOUTDOOR AIR TEMP\b"), "OAT"),
    (re.compile(r"\bZONE AIR TEMPERATURE SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bZONE AIR TEMP SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bZONE TEMPERATURE SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bZONE TEMP SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bROOM TEMPERATURE SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bROOM TEMP SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bSPACE TEMPERATURE SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bSPACE TEMP SETPOINT\b"), "ZN-SP"),
    (re.compile(r"\bZONE AIR TEMPERATURE\b"), "ZN-T"),
    (re.compile(r"\bZONE AIR TEMP\b"), "ZN-T"),
    (re.compile(r"\bZONE TEMPERATURE\b"), "ZN-T"),
    (re.compile(r"\bZONE TEMP\b"), "ZN-T"),
    (re.compile(r"\bROOM TEMPERATURE\b"), "ZN-T"),
    (re.compile(r"\bROOM TEMP\b"), "ZN-T"),
    (re.compile(r"\bSPACE TEMPERATURE\b"), "ZN-T"),
    (re.compile(r"\bSPACE TEMP\b"), "ZN-T"),
    (re.compile(r"\bAIRFLOW SETPOINT\b"), "FLOW-SP"),
    (re.compile(r"\bFLOW SETPOINT\b"), "FLOW-SP"),
    (re.compile(r"\bCFM SETPOINT\b"), "FLOW-SP"),
    (re.compile(r"\bCFM SP\b"), "FLOW-SP"),
    (re.compile(r"\bAIRFLOW\b"), "FLOW"),
]


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
    field: str | None = None
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
        description="Every equipment must resolve to an existing controller",
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
        description="Point should resolve to an existing owning controller",
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
        rule_id="COMP-006",
        name="Controller network addressing present",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.WARNING,
        description="Networked controllers should define at least one network address",
        applies_to=["controller"],
    ),
    ValidationRule(
        rule_id="COMP-007",
        name="Sequence references are represented by points",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.WARNING,
        description="Equipment sequence references should map to structured points in the project",
        applies_to=["equipment"],
    ),
    ValidationRule(
        rule_id="COMP-008",
        name="Sequence-derived points have source traceability",
        category=ValidationCategory.COMPLETENESS,
        severity=ValidationSeverity.WARNING,
        description="Points imported from sequences should retain source reference metadata",
        applies_to=["point"],
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
        rule_id="CONS-006",
        name="Sequence control intent has matching point coverage",
        category=ValidationCategory.CONSISTENCY,
        severity=ValidationSeverity.WARNING,
        description="Sequence-driven control intent should have command, status, setpoint, and alarm point coverage where referenced",
        applies_to=["equipment"],
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
    ValidationRule(
        rule_id="PROTO-004",
        name="BACnet mapping completeness",
        category=ValidationCategory.PROTOCOL,
        severity=ValidationSeverity.WARNING,
        description="BACnet points should define both object type and instance together",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="PROTO-005",
        name="Modbus mapping completeness",
        category=ValidationCategory.PROTOCOL,
        severity=ValidationSeverity.WARNING,
        description="Modbus points should define both register and register type together",
        applies_to=["point"],
    ),
    ValidationRule(
        rule_id="PROTO-006",
        name="Controller address protocol alignment",
        category=ValidationCategory.PROTOCOL,
        severity=ValidationSeverity.WARNING,
        description="Controller network addresses should align with declared controller protocols",
        applies_to=["controller"],
    ),
    ValidationRule(
        rule_id="CAP-001",
        name="Controller I/O capacity not exceeded",
        category=ValidationCategory.CAPACITY,
        severity=ValidationSeverity.ERROR,
        description="Owned points should not exceed configured controller I/O capacity",
        applies_to=["controller"],
    ),
    ValidationRule(
        rule_id="CAP-002",
        name="Controller configured utilization realistic",
        category=ValidationCategory.CAPACITY,
        severity=ValidationSeverity.WARNING,
        description="Configured I/O utilization should not exceed total points",
        applies_to=["controller"],
    ),
]


class ValidationEngine:
    """Validates BAS project models against rules."""

    def __init__(self, rules: list[ValidationRule] | None = None):
        self.rules = rules or BUILTIN_RULES
        self.enabled_rules = [r for r in self.rules if r.enabled]
        self._sequence_index: dict[str, dict[str, object]] = {}

    def validate(self, project: Project) -> ValidationReport:
        """Run all validation rules on a project."""
        report = ValidationReport(project_id=project.metadata.project_id)
        report.total_rules_run = len(self.enabled_rules)
        self._sequence_index = self._build_sequence_index(project)

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

    def _name_tokens(self, value: str) -> set[str]:
        return {
            token
            for token in re.split(r"[\s/_-]+", value.lower())
            if token
        }

    def _looks_like_temperature_point(self, point: Point) -> bool:
        return bool(self._name_tokens(point.name) & TEMPERATURE_TOKENS)

    def _looks_like_pressure_point(self, point: Point) -> bool:
        return bool(self._name_tokens(point.name) & PRESSURE_TOKENS)

    def _looks_like_flow_point(self, point: Point) -> bool:
        return bool(self._name_tokens(point.name) & FLOW_TOKENS)

    def _normalize_point_ref(self, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value.replace("_", " ").strip().upper())
        for pattern, replacement in POINT_REF_ALIAS_PATTERNS:
            normalized = pattern.sub(replacement, normalized)
        normalized = re.sub(r"\bFAULT\b", "FLT", normalized)
        normalized = re.sub(r"\bALARM\b", "ALM", normalized)
        normalized = re.sub(r"\bPROOF\b", "PRF", normalized)
        normalized = re.sub(r"\bSTATUS\b", "STS", normalized)
        normalized = re.sub(r"\bCOMMAND\b", "CMD", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _equipment_point_refs(self, project: Project, equipment_id: str) -> set[str]:
        refs: set[str] = set()
        for point in project.get_points_for_equipment(equipment_id):
            normalized = self._normalize_point_ref(point.name)
            refs.add(normalized)
            if normalized.startswith(f"{equipment_id} "):
                refs.add(normalized[len(equipment_id) + 1:])
        return refs

    def _point_suffixes(self, project: Project, equipment_id: str) -> set[str]:
        return {
            self._normalize_point_ref(point.name).split(" ", 1)[-1]
            for point in project.get_points_for_equipment(equipment_id)
        }

    def _has_suffix_family(self, point_suffixes: set[str], family: set[str]) -> bool:
        for suffix in point_suffixes:
            if suffix in family:
                return True
            if any(suffix.endswith(token) for token in family):
                return True
            if any(token in suffix for token in family if "-" in token):
                return True
        return False

    def _split_equipment_ref(self, value: str) -> tuple[str | None, str]:
        normalized = self._normalize_point_ref(value)
        parts = normalized.split(" ", 1)
        if len(parts) == 2 and EQUIPMENT_ID_PATTERN.match(parts[0]):
            return parts[0], parts[1]
        return None, normalized

    def _suffix_family_label(self, suffix: str) -> str | None:
        normalized = self._normalize_point_ref(suffix)
        if self._has_suffix_family({normalized}, {"SF-CMD", "CMD", "START-CMD", "ENABLE-CMD", "VLV-CMD", "DMP-CMD", "DPR-CMD", "HTG-CMD"}):
            return "command"
        if self._has_suffix_family({normalized}, {"SF-STS", "STATUS", "STS", "PRF", "RUN-STS", "RUN-STATUS", "MODE-STS"}):
            return "status"
        if self._has_suffix_family({normalized}, {"SP", "SETPOINT", "SAT-SP", "DAT-SP", "ZN-SP", "ZAT-SP", "FLOW-SP", "PRESS-SP"}):
            return "setpoint"
        if self._has_suffix_family({normalized}, {"ALM", "FLT", "FAULT", "ALARM"}):
            return "alarm"
        if self._has_suffix_family({normalized}, {"OCC-MODE", "UNOCC-MODE", "MODE-STS", "SCH", "SCH-STS", "SCH-CMD", "OCC-CMD"}):
            return "mode_schedule"
        if self._has_suffix_family({normalized}, {"STAGE-CMD", "LEAD-LAG", "LL-MODE", "ROTATE-CMD"}):
            return "staging"
        if self._has_suffix_family({normalized}, {"ZN-T", "ZAT"}):
            return "zone_temp"
        if self._has_suffix_family({normalized}, {"FLOW", "AIRFLOW", "CFM"}):
            return "airflow"
        if self._has_suffix_family({normalized}, {"DMP-POS", "POS", "POSITION", "FEEDBACK"}):
            return "position_feedback"
        return None

    def _refs_match(self, reference: str, candidate: str) -> bool:
        left = self._normalize_point_ref(reference)
        right = self._normalize_point_ref(candidate)
        if left == right:
            return True

        left_equipment, left_suffix = self._split_equipment_ref(left)
        right_equipment, right_suffix = self._split_equipment_ref(right)
        if left_equipment and right_equipment and left_equipment != right_equipment:
            return False

        left_family = self._suffix_family_label(left_suffix)
        right_family = self._suffix_family_label(right_suffix)
        return left_family is not None and left_family == right_family

    def _is_sequence_document(self, document: SourceDocument) -> bool:
        doc_type = str(document.type or "").lower()
        doc_name = str(document.name or "").lower()
        return "sequence" in doc_type or "sequence" in doc_name

    def _sequence_equipment_candidates(
        self,
        project: Project,
        document: SourceDocument,
        text: str,
    ) -> set[str]:
        doc_name = str(document.name or "").upper()
        doc_path = str(document.path or "").upper()
        text_upper = text.upper()
        candidates = {
            equipment.id
            for equipment in project.equipment
            if equipment.id.upper() in doc_name or equipment.id.upper() in doc_path or equipment.id.upper() in text_upper
        }
        for equipment in project.equipment:
            sequence_ref = str(equipment.sequence_ref or "").upper()
            if sequence_ref and (sequence_ref in doc_name or sequence_ref in doc_path):
                candidates.add(equipment.id)
        if not candidates and len(project.equipment) == 1:
            candidates.add(project.equipment[0].id)
        return candidates

    def _equipment_ids_in_text(self, text: str) -> set[str]:
        return {
            match.group(0).upper()
            for match in re.finditer(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+\b", text, re.IGNORECASE)
        }

    def _requirement_equipment_candidates(
        self,
        project: Project,
        document: SourceDocument,
        requirement,
        document_text: str,
    ) -> set[str]:
        candidates = set()
        requirement_text = f"{requirement.description} {requirement.source_text}"
        mentioned_ids = self._equipment_ids_in_text(requirement_text)
        project_equipment_ids = {equipment.id for equipment in project.equipment}

        candidates.update(equipment_id for equipment_id in mentioned_ids if equipment_id in project_equipment_ids)

        for reference in requirement.points_referenced:
            ref_equipment_id, _ = self._split_equipment_ref(reference)
            if ref_equipment_id and ref_equipment_id in project_equipment_ids:
                candidates.add(ref_equipment_id)

        if candidates:
            return candidates
        return self._sequence_equipment_candidates(project, document, document_text)

    def _build_sequence_index(self, project: Project) -> dict[str, dict[str, object]]:
        from ..reasoning.sequence_parser import SequenceParser

        sequence_parser = SequenceParser()
        index: dict[str, dict[str, object]] = {}
        for document in project.source_documents:
            if not self._is_sequence_document(document) or not document.path:
                continue
            file_path = Path(document.path)
            if not file_path.exists():
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            parsed = sequence_parser.parse(text)
            document_level_candidates = self._sequence_equipment_candidates(project, document, text)
            if not parsed.requirements:
                for equipment_id in document_level_candidates:
                    entry = index.setdefault(
                        equipment_id,
                        {
                            "documents": [],
                            "point_refs": set(),
                            "requirement_types": set(),
                        },
                    )
                    entry["documents"].append(document.name)
                continue

            for requirement in parsed.requirements:
                point_refs = {
                    self._normalize_point_ref(reference)
                    for reference in requirement.points_referenced
                    if reference
                }
                requirement_types = {requirement.requirement_type}
                for equipment_id in self._requirement_equipment_candidates(project, document, requirement, text):
                    entry = index.setdefault(
                        equipment_id,
                        {
                            "documents": [],
                            "point_refs": set(),
                            "requirement_types": set(),
                        },
                    )
                    entry["documents"].append(document.name)
                    entry["point_refs"].update(point_refs)
                    entry["requirement_types"].update(requirement_types)

            for equipment_id in document_level_candidates:
                if equipment_id in index:
                    continue
                entry = index.setdefault(
                    equipment_id,
                    {
                        "documents": [],
                        "point_refs": set(),
                        "requirement_types": set(),
                    },
                )
                entry["documents"].append(document.name)
        return index

    def sequence_coverage_for_equipment(
        self,
        project: Project,
        equipment_id: str,
        *,
        point_refs: set[str] | None = None,
        requirement_type_values: set[str] | None = None,
        documents: list[str] | None = None,
    ) -> dict[str, object]:
        if point_refs is None or requirement_type_values is None:
            if not self._sequence_index:
                self._sequence_index = self._build_sequence_index(project)
            sequence_data = self._sequence_index.get(equipment_id)
            if not sequence_data:
                return {
                    "equipment_id": equipment_id,
                    "status": "not_indexed",
                    "documents": [],
                    "point_refs": [],
                    "matched_refs": [],
                    "missing_refs": [],
                    "requirement_types": [],
                    "coverage_checks": [],
                    "summary": "No indexed sequence context found for this equipment.",
                }
            point_refs = set(sequence_data["point_refs"])
            requirement_type_values = {
                str(requirement_type.value)
                for requirement_type in sequence_data["requirement_types"]
            }
            documents = sorted({str(document) for document in sequence_data["documents"]})
        else:
            point_refs = {self._normalize_point_ref(reference) for reference in point_refs if reference}
            requirement_type_values = {str(value) for value in requirement_type_values if value}
            documents = sorted({str(document) for document in (documents or [])})

        equipment_refs = self._equipment_point_refs(project, equipment_id)
        matched_refs = sorted(
            reference
            for reference in point_refs
            if any(self._refs_match(reference, candidate) for candidate in equipment_refs)
        )
        missing_refs = sorted(
            reference
            for reference in point_refs
            if not any(self._refs_match(reference, candidate) for candidate in equipment_refs)
        )
        point_suffixes = self._point_suffixes(project, equipment_id)

        coverage_checks = []

        def add_check(label: str, required: bool, passed: bool, missing: str) -> None:
            coverage_checks.append(
                {
                    "label": label,
                    "required": required,
                    "passed": passed if required else True,
                    "missing": missing if required and not passed else "",
                }
            )

        requires_start_stop = "start_stop" in requirement_type_values
        requires_pid = "pid" in requirement_type_values
        requires_alarm = "alarm" in requirement_type_values
        requires_mode_schedule = "mode" in requirement_type_values or "schedule" in requirement_type_values
        requires_staging = "staging" in requirement_type_values or "lead_lag" in requirement_type_values
        command_family = {"SF-CMD", "CMD", "START-CMD", "ENABLE-CMD", "VLV-CMD", "DMP-CMD", "DPR-CMD", "HTG-CMD"}
        status_family = {"SF-STS", "STATUS", "STS", "PRF", "RUN-STS", "RUN-STATUS", "MODE-STS"}
        setpoint_family = {"SP", "SETPOINT", "SAT-SP", "DAT-SP", "ZN-SP", "ZAT-SP", "FLOW-SP", "PRESS-SP"}
        alarm_family = {"ALM", "FLT", "FAULT", "ALARM"}
        mode_schedule_family = {"OCC-MODE", "UNOCC-MODE", "MODE-STS", "SCH", "SCH-STS", "SCH-CMD", "OCC-CMD"}
        staging_family = {"STAGE-CMD", "LEAD-LAG", "LL-MODE", "ROTATE-CMD"}

        add_check(
            "Command point",
            requires_start_stop,
            self._has_suffix_family(point_suffixes, command_family),
            "Add a command point such as `SF-CMD` for sequence-driven enable/disable control.",
        )
        add_check(
            "Status/proof point",
            requires_start_stop,
            self._has_suffix_family(point_suffixes, status_family),
            "Add a status or proof point such as `SF-STS` or `PRF` for run verification.",
        )
        add_check(
            "Setpoint point",
            requires_pid,
            self._has_suffix_family(point_suffixes, setpoint_family),
            "Add a setpoint point so PID intent from the sequence is represented in structured data.",
        )
        add_check(
            "Alarm/fault point",
            requires_alarm,
            self._has_suffix_family(point_suffixes, alarm_family),
            "Add an alarm or fault point so alarm intent from the sequence is represented in structured data.",
        )
        add_check(
            "Mode/schedule point",
            requires_mode_schedule,
            self._has_suffix_family(point_suffixes, mode_schedule_family),
            "Add an occupancy mode, schedule, or related command/status point so time-based control intent is represented.",
        )
        add_check(
            "Staging/rotation point",
            requires_staging,
            self._has_suffix_family(point_suffixes, staging_family),
            "Add a staging or lead-lag command/mode point so plant rotation intent is represented.",
        )

        actionable_checks = [check for check in coverage_checks if check["required"]]
        missing_check_count = sum(1 for check in actionable_checks if not check["passed"])
        required_families = [check["label"] for check in actionable_checks]
        missing_families = [check["label"] for check in actionable_checks if not check["passed"]]
        covered_families = [check["label"] for check in actionable_checks if check["passed"]]

        if not point_refs and not actionable_checks:
            status = "not_indexed"
            summary = "No explicit point references or control intent were extracted from the available sequence context."
        elif missing_refs or missing_check_count:
            status = "attention"
            summary = (
                f"{len(missing_refs)} referenced points and {missing_check_count} control coverage checks still need work."
            )
        else:
            status = "covered"
            summary = "Structured points cover the indexed sequence references and control intent."

        return {
            "equipment_id": equipment_id,
            "status": status,
            "documents": documents,
            "point_refs": sorted(point_refs),
            "matched_refs": matched_refs,
            "missing_refs": missing_refs,
            "requirement_types": sorted(requirement_type_values),
            "coverage_checks": coverage_checks,
            "required_families": required_families,
            "covered_families": covered_families,
            "missing_families": missing_families,
            "summary": summary,
        }

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
            passed = bool(EQUIPMENT_ID_PATTERN.match(equipment.id))
            report.add_result(ValidationResult(
                object_type="equipment",
                object_id=equipment.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="id",
                message=f"Equipment ID '{equipment.id}' does not match BAS tag convention" if not passed else "Equipment ID format valid",
                passed=passed,
            ))
        elif rule.rule_id == "COMP-001":
            resolved_controller_id = project.effective_equipment_controller_id(equipment)
            resolved_controller = (
                project.get_controller(resolved_controller_id)
                if resolved_controller_id is not None
                else None
            )
            passed = resolved_controller is not None
            report.add_result(ValidationResult(
                object_type="equipment",
                object_id=equipment.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="controller_id",
                message=(
                    f"Equipment '{equipment.id}' does not resolve to an existing controller"
                    if not passed
                    else f"Equipment resolves to controller '{resolved_controller_id}'"
                ),
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
        elif rule.rule_id == "COMP-007":
            sequence_data = self._sequence_index.get(equipment.id)
            if not sequence_data or not sequence_data["point_refs"]:
                report.add_result(ValidationResult(
                    object_type="equipment",
                    object_id=equipment.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="sequence_ref",
                    message="No explicit sequence point references were indexed for this equipment",
                    passed=True,
                ))
            else:
                equipment_refs = self._equipment_point_refs(project, equipment.id)
                missing_refs = sorted(
                    reference
                    for reference in sequence_data["point_refs"]
                    if reference not in equipment_refs
                )
                passed = len(missing_refs) == 0
                report.add_result(ValidationResult(
                    object_type="equipment",
                    object_id=equipment.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="point_names",
                    message=(
                        f"Sequence references for '{equipment.id}' are missing structured points: {', '.join(missing_refs)}"
                        if not passed
                        else "Structured points cover the indexed sequence references"
                    ),
                    passed=passed,
                ))
        elif rule.rule_id == "CONS-006":
            sequence_data = self._sequence_index.get(equipment.id)
            if not sequence_data:
                report.add_result(ValidationResult(
                    object_type="equipment",
                    object_id=equipment.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="sequence_ref",
                    message="No sequence control intent was indexed for this equipment",
                    passed=True,
                ))
            else:
                points = project.get_points_for_equipment(equipment.id)
                point_suffixes = {
                    self._normalize_point_ref(point.name).split(" ", 1)[-1]
                    for point in points
                }
                missing_coverage: list[str] = []
                requirement_types = set(sequence_data["requirement_types"])
                requirement_type_values = {str(requirement_type.value) for requirement_type in requirement_types}
                if "start_stop" in requirement_type_values and not any(token in point_suffixes for token in {"SF-CMD", "CMD", "START-CMD"}):
                    missing_coverage.append("command point")
                if "start_stop" in requirement_type_values and not any(token in point_suffixes for token in {"SF-STS", "STATUS", "STS", "PRF"}):
                    missing_coverage.append("status/proof point")
                if "pid" in requirement_type_values and not any(token.endswith("SP") or token.endswith("SETPOINT") for token in point_suffixes):
                    missing_coverage.append("setpoint point")
                if "alarm" in requirement_type_values and not any("ALM" in token or "FLT" in token for token in point_suffixes):
                    missing_coverage.append("alarm/fault point")
                passed = len(missing_coverage) == 0
                report.add_result(ValidationResult(
                    object_type="equipment",
                    object_id=equipment.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="point_names",
                    message=(
                        f"Sequence control intent for '{equipment.id}' is missing {', '.join(missing_coverage)} coverage"
                        if not passed
                        else "Structured points cover indexed sequence control intent"
                    ),
                    passed=passed,
                ))

    def _run_point_rule(self, project: Project, point: Point, rule: ValidationRule, report: ValidationReport) -> None:
        if rule.rule_id == "NAMING-002":
            effective_equipment_id = project.effective_point_equipment_id(point)
            prefix = f"{effective_equipment_id} " if effective_equipment_id else ""
            suffix = point.name[len(prefix):] if point.name.startswith(prefix) else ""
            passed = bool(
                point.name
                and effective_equipment_id
                and point.name.startswith(prefix)
                and suffix
                and POINT_CODE_PATTERN.match(suffix)
            )
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="name",
                message=(
                    f"Point name '{point.name}' does not match BAS point naming convention"
                    if not passed
                    else "Point name format valid"
                ),
                passed=passed,
            ))
        elif rule.rule_id == "COMP-002":
            resolved_equipment_id = project.effective_point_equipment_id(point)
            equipment = project.get_equipment(resolved_equipment_id) if resolved_equipment_id else None
            passed = equipment is not None
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="equipment_id",
                message=(
                    f"Point '{point.name}' references non-existent equipment '{resolved_equipment_id or point.equipment_id}'"
                    if not passed
                    else f"Point references equipment '{resolved_equipment_id}'"
                ),
                passed=passed,
            ))
        elif rule.rule_id == "COMP-003":
            resolved_controller_id = project.effective_point_controller_id(point)
            controller = project.get_controller(resolved_controller_id) if resolved_controller_id else None
            passed = controller is not None
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="controller_id",
                message=(
                    f"Point '{point.name}' does not resolve to an existing controller"
                    if not passed
                    else f"Point resolves to controller '{resolved_controller_id}'"
                ),
                passed=passed,
            ))
        elif rule.rule_id == "COMP-008":
            if point.source != PointSource.SEQUENCE:
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="source_reference",
                    message="Point is not sequence-derived",
                    passed=True,
                ))
            else:
                passed = bool(point.source_reference)
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="source_reference",
                    message=(
                        f"Sequence-derived point '{point.name}' is missing source reference traceability"
                        if not passed
                        else "Sequence-derived point retains source reference traceability"
                    ),
                    passed=passed,
                ))
        elif rule.rule_id == "CONS-001":
            resolved_equipment_id = project.effective_point_equipment_id(point)
            resolved_controller_id = project.effective_point_controller_id(point)
            equipment = project.get_equipment(resolved_equipment_id) if resolved_equipment_id else None
            controller = project.get_controller(resolved_controller_id) if resolved_controller_id else None
            expected_controller_id = (
                project.effective_equipment_controller_id(equipment)
                if equipment is not None
                else None
            )
            passed = (
                equipment is not None
                and controller is not None
                and expected_controller_id == resolved_controller_id
            )
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="controller_id",
                message=(
                    f"Point '{point.name}' controller '{resolved_controller_id}' does not match equipment controller '{expected_controller_id}'"
                    if not passed
                    else "Point equipment/controller consistent"
                ),
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
                passed = point.units.lower() in temp_units or not self._looks_like_temperature_point(point)
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="units",
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
            if point.kind == PointKind.SENSOR and self._looks_like_pressure_point(point):
                pressure_units = {"inwc", "wc", "inh2o", "psi", "pa", "kpa", "inwc", "in.wc"}
                passed = point.units and point.units.lower() in pressure_units
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="units",
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
            if point.kind == PointKind.SENSOR and self._looks_like_flow_point(point):
                flow_units = {"cfm", "gpm", "lps", "cfh", "m3h", "m3/s", "gph"}
                passed = point.units and point.units.lower() in flow_units
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="units",
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
            resolved_controller_id = project.effective_point_controller_id(point)
            if resolved_controller_id:
                controller = project.get_controller(resolved_controller_id)
                if controller and any(protocol.value in ["BACnet/IP", "BACnet/MSTP"] for protocol in controller.protocols):
                    passed = point.bacnet_object_type is not None
                    report.add_result(ValidationResult(
                        object_type="point",
                        object_id=point.name,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        category=rule.category,
                        field="bacnet_object_type",
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
            resolved_controller_id = project.effective_point_controller_id(point)
            if point.bacnet_instance is not None and resolved_controller_id:
                controller_points = project.get_points_for_controller(resolved_controller_id)
                instances = [p.bacnet_instance for p in controller_points if p.bacnet_instance is not None]
                passed = instances.count(point.bacnet_instance) == 1
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="bacnet_instance",
                    message=f"BACnet instance {point.bacnet_instance} duplicated on controller {resolved_controller_id}" if not passed else "BACnet instance unique",
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
            resolved_controller_id = project.effective_point_controller_id(point)
            if point.modbus_register is not None and resolved_controller_id:
                controller_points = project.get_points_for_controller(resolved_controller_id)
                registers = [p.modbus_register for p in controller_points if p.modbus_register is not None]
                passed = registers.count(point.modbus_register) == 1
                report.add_result(ValidationResult(
                    object_type="point",
                    object_id=point.name,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="modbus_register",
                    message=f"Modbus register {point.modbus_register} duplicated on controller {resolved_controller_id}" if not passed else "Modbus register unique",
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
        elif rule.rule_id == "PROTO-004":
            has_type = point.bacnet_object_type is not None
            has_instance = point.bacnet_instance is not None
            passed = has_type == has_instance
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="bacnet_object_type",
                message=(
                    f"Point '{point.name}' should define BACnet object type and instance together"
                    if not passed
                    else "BACnet mapping fields are complete"
                ),
                passed=passed,
            ))
        elif rule.rule_id == "PROTO-005":
            has_register = point.modbus_register is not None
            has_type = point.modbus_type is not None
            passed = has_register == has_type
            report.add_result(ValidationResult(
                object_type="point",
                object_id=point.name,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="modbus_register",
                message=(
                    f"Point '{point.name}' should define Modbus register and register type together"
                    if not passed
                    else "Modbus mapping fields are complete"
                ),
                passed=passed,
            ))

    def _run_controller_rule(self, project: Project, controller: Controller, rule: ValidationRule, report: ValidationReport) -> None:
        if rule.rule_id == "NAMING-003":
            passed = bool(CONTROLLER_ID_PATTERN.match(controller.id))
            report.add_result(ValidationResult(
                object_type="controller",
                object_id=controller.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="id",
                message=f"Controller ID '{controller.id}' does not match BAS controller naming convention" if not passed else "Controller ID format valid",
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
        elif rule.rule_id == "COMP-006":
            requires_network = any(
                protocol.value in {"BACnet/IP", "BACnet/MSTP", "Modbus/TCP", "Modbus/RTU", "OPC-UA", "MQTT"}
                for protocol in controller.protocols
            )
            passed = not requires_network or len(controller.network_addresses) > 0
            report.add_result(ValidationResult(
                object_type="controller",
                object_id=controller.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="network_addresses",
                message=(
                    f"Controller '{controller.id}' declares network protocols but has no network addresses"
                    if not passed
                    else "Controller network addressing is present"
                ),
                passed=passed,
            ))
        elif rule.rule_id == "CONS-002":
            served_equipment_ids = project.effective_controller_serves_equipment_ids(controller)
            if not served_equipment_ids:
                report.add_result(ValidationResult(
                    object_type="controller",
                    object_id=controller.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="serves_equipment_ids",
                    message="Controller has no served equipment assignments to validate",
                    passed=True,
                ))
            for equip_id in served_equipment_ids:
                equipment = project.get_equipment(equip_id)
                passed = equipment is not None
                report.add_result(ValidationResult(
                    object_type="controller",
                    object_id=controller.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="serves_equipment_ids",
                    message=f"Controller '{controller.id}' serves non-existent equipment '{equip_id}'" if not passed else f"Controller serves existing equipment '{equip_id}'",
                    passed=passed,
                ))
        elif rule.rule_id == "PROTO-006":
            allowed_protocols = {protocol.value for protocol in controller.protocols}
            mismatched = [
                address.protocol.value
                for address in controller.network_addresses
                if address.protocol.value not in allowed_protocols
            ]
            passed = len(mismatched) == 0
            report.add_result(ValidationResult(
                object_type="controller",
                object_id=controller.id,
                rule_id=rule.rule_id,
                severity=rule.severity,
                category=rule.category,
                field="network_addresses",
                message=(
                    f"Controller '{controller.id}' has network addresses for undeclared protocols: {', '.join(mismatched)}"
                    if not passed
                    else "Controller address protocols align with declared protocols"
                ),
                passed=passed,
            ))
        elif rule.rule_id == "CAP-001":
            owned_points = project.get_points_for_controller(controller.id)
            if controller.io_capacity is None or controller.io_capacity.total_points == 0:
                report.add_result(ValidationResult(
                    object_type="controller",
                    object_id=controller.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="io_capacity.total_points",
                    message="Controller capacity is not configured",
                    passed=True,
                ))
            else:
                passed = len(owned_points) <= controller.io_capacity.total_points
                report.add_result(ValidationResult(
                    object_type="controller",
                    object_id=controller.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="io_capacity.total_points",
                    message=(
                        f"Controller '{controller.id}' owns {len(owned_points)} points but capacity is {controller.io_capacity.total_points}"
                        if not passed
                        else f"Controller owns {len(owned_points)} points within capacity {controller.io_capacity.total_points}"
                    ),
                    passed=passed,
                ))
        elif rule.rule_id == "CAP-002":
            if controller.io_capacity is None or controller.io_capacity.total_points == 0:
                report.add_result(ValidationResult(
                    object_type="controller",
                    object_id=controller.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="io_capacity.total_points",
                    message="Controller utilization cannot be evaluated without capacity totals",
                    passed=True,
                ))
            else:
                configured_used_points = controller.io_capacity.used_points
                passed = configured_used_points <= controller.io_capacity.total_points
                report.add_result(ValidationResult(
                    object_type="controller",
                    object_id=controller.id,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    field="io_capacity.total_points",
                    message=(
                        f"Controller '{controller.id}' configured usage {configured_used_points} exceeds total capacity {controller.io_capacity.total_points}"
                        if not passed
                        else f"Controller configured utilization is {configured_used_points}/{controller.io_capacity.total_points}"
                    ),
                    passed=passed,
                ))


__all__ = [
    "BUILTIN_RULES",
    "ValidationEngine",
    "ValidationReport",
    "ValidationResult",
    "ValidationRule",
]
