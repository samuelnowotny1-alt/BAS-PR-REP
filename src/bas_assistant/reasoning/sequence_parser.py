"""Sequence Parsing - Parses natural language sequences into structured logic requirements."""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import re

from ..models import (
    Project, Equipment, Point, PointKind, EquipmentType,
    LogicDiagram, LogicBlock, LogicSignal, LogicParameter, LogicConnection
)


class SequenceSection(str, Enum):
    """Sections of a sequence of operation."""
    GENERAL = "general"
    OCCUPANCY = "occupancy"
    FAN_CONTROL = "fan_control"
    TEMP_CONTROL = "temp_control"
    ECONOMIZER = "economizer"
    HEATING = "heating"
    COOLING = "cooling"
    HUMIDIFICATION = "humidification"
    DEHUMIDIFICATION = "dehumidification"
    SAFETIES = "safeties"
    ALARMS = "alarms"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    OPTIMIZATION = "optimization"
    CUSTOM = "custom"


class LogicRequirementType(str, Enum):
    """Types of logic requirements extracted from sequences."""
    MODE = "mode"
    PID = "pid"
    START_STOP = "start_stop"
    INTERLOCK = "interlock"
    ALARM = "alarm"
    SCHEDULE = "schedule"
    RESET = "reset"
    LIMIT = "limit"
    ECONOMIZER = "economizer"
    HEAT_RECOVERY = "heat_recovery"
    STAGING = "staging"
    LEAD_LAG = "lead_lag"
    OVERRIDE = "override"
    CALCULATION = "calculation"


@dataclass
class LogicRequirement:
    """A logic requirement extracted from a sequence."""
    req_id: str
    requirement_type: LogicRequirementType
    section: SequenceSection
    description: str
    source_text: str
    equipment_types: list[EquipmentType] = field(default_factory=list)
    points_referenced: list[str] = field(default_factory=list)
    setpoints_mentioned: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1 confidence score
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedSequence:
    """A parsed sequence of operation."""
    sequence_id: str
    equipment_type: Optional[EquipmentType] = None
    equipment_id: Optional[str] = None
    raw_text: str = ""
    sections: dict[SequenceSection, str] = field(default_factory=dict)
    requirements: list[LogicRequirement] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class SequenceParser:
    """Parses natural language sequences into structured logic requirements."""

    # Keywords that indicate specific logic types
    KEYWORDS = {
        LogicRequirementType.MODE: [
            "mode", "occupied", "unoccupied", "warmup", "cooldown",
            "startup", "shutdown", "enable", "disable", "off",
        ],
        LogicRequirementType.PID: [
            "pid", "proportional", "integral", "derivative", "control loop",
            "maintain", "setpoint", "modulate", "adjust",
        ],
        LogicRequirementType.START_STOP: [
            "start", "stop", "run", "enable", "disable", "command",
            "proof", "status", "interlock",
        ],
        LogicRequirementType.INTERLOCK: [
            "interlock", "safety", "proof", "permissive", "protect",
            "freeze", "high limit", "low limit", "smoke", "fire",
        ],
        LogicRequirementType.ALARM: [
            "alarm", "alert", "notify", "warning", "fault", "failure",
            "high", "low", "limit", "exceed", "below", "above",
        ],
        LogicRequirementType.SCHEDULE: [
            "schedule", "time", "occupied hours", "unoccupied hours",
            "holiday", "weekend", "weekday",
        ],
        LogicRequirementType.RESET: [
            "reset", "trim and respond", "setpoint reset", "adjust setpoint",
        ],
        LogicRequirementType.LIMIT: [
            "limit", "maximum", "minimum", "clamp", "constrain",
        ],
        LogicRequirementType.ECONOMIZER: [
            "economizer", "free cooling", "outside air", "enthalpy",
            "differential", "high limit", "dry bulb",
        ],
        LogicRequirementType.HEAT_RECOVERY: [
            "heat recovery", "energy recovery", "wheel", "plate",
            "runaround", "heat pipe",
        ],
        LogicRequirementType.STAGING: [
            "stage", "staging", "lead", "lag", "sequencing",
        ],
        LogicRequirementType.LEAD_LAG: [
            "lead", "lag", "rotation", "alternate", "equal runtime",
        ],
    }

    # Equipment type keywords
    EQUIP_KEYWORDS = {
        EquipmentType.AHU: ["air handling", "ahu", "air handler"],
        EquipmentType.RTU: ["rooftop", "rtu", "packaged"],
        EquipmentType.VAV: ["vav", "variable air volume", "box"],
        EquipmentType.CHILLER: ["chiller", "chilled water plant"],
        EquipmentType.BOILER: ["boiler", "hot water plant", "steam"],
        EquipmentType.COOLING_TOWER: ["cooling tower", "ct ", "condenser water"],
        EquipmentType.PUMP_CHW: ["chilled water pump", "chw pump"],
        EquipmentType.PUMP_HW: ["hot water pump", "hw pump"],
        EquipmentType.PUMP_CW: ["condenser water pump", "cw pump"],
    }

    def __init__(self):
        self._req_counter = 0

    def _new_req_id(self) -> str:
        self._req_counter += 1
        return f"REQ-{self._req_counter:04d}"

    def parse(self, text: str, equipment_id: Optional[str] = None) -> ParsedSequence:
        """Parse a sequence of operation text."""
        sequence = ParsedSequence(
            sequence_id=f"seq_{equipment_id or 'unknown'}",
            equipment_id=equipment_id,
            raw_text=text,
        )

        # Detect equipment type from text
        sequence.equipment_type = self._detect_equipment_type(text)

        # Split into sections
        sequence.sections = self._split_into_sections(text)

        # Extract requirements from each section
        for section_type, section_text in sequence.sections.items():
            reqs = self._extract_requirements(section_type, section_text)
            sequence.requirements.extend(reqs)

        # Calculate confidence scores
        for req in sequence.requirements:
            req.confidence = self._calculate_confidence(req, text)

        return sequence

    def _detect_equipment_type(self, text: str) -> Optional[EquipmentType]:
        """Detect equipment type from sequence text."""
        text_lower = text.lower()
        for equip_type, keywords in self.EQUIP_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return equip_type
        return None

    def _split_into_sections(self, text: str) -> dict[SequenceSection, str]:
        """Split sequence text into sections based on headers/keywords."""
        sections = {}
        text_lower = text.lower()

        # Common section headers
        section_patterns = {
            SequenceSection.GENERAL: ["general", "overview", "description", "scope"],
            SequenceSection.OCCUPANCY: ["occupancy", "occupied", "unoccupied", "schedule"],
            SequenceSection.FAN_CONTROL: ["fan", "supply fan", "return fan", "exhaust fan"],
            SequenceSection.TEMP_CONTROL: ["temperature", "temp control", "sat", "dat", "zat"],
            SequenceSection.ECONOMIZER: ["economizer", "free cooling", "outside air", "oa "],
            SequenceSection.HEATING: ["heating", "preheat", "reheat", "hot water"],
            SequenceSection.COOLING: ["cooling", "cooling coil", "chilled water", "dx "],
            SequenceSection.HUMIDIFICATION: ["humidif", "humidity"],
            SequenceSection.DEHUMIDIFICATION: ["dehumidif", "dehumidification"],
            SequenceSection.SAFETIES: ["safety", "freeze", "high limit", "low limit", "smoke", "fire", "protect"],
            SequenceSection.ALARMS: ["alarm", "alarm ", "notification"],
            SequenceSection.STARTUP: ["startup", "start-up", "initialization"],
            SequenceSection.SHUTDOWN: ["shutdown", "shut down", "shut-down"],
            SequenceSection.OPTIMIZATION: ["optimization", "trim and respond", "reset", "efficiency"],
        }

        # Simple split by common headers
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        current_section = SequenceSection.GENERAL
        for para in paragraphs:
            para_lower = para.lower()

            # Check if paragraph starts with a section header
            found_section = False
            for section, keywords in section_patterns.items():
                for kw in keywords:
                    if para_lower.startswith(kw) or para_lower.startswith(kw + ":"):
                        current_section = section
                        found_section = True
                        break
                if found_section:
                    break

            if current_section not in sections:
                sections[current_section] = ""
            sections[current_section] += para + "\n\n"

        # If no sections found, put everything in general
        if not sections:
            sections[SequenceSection.GENERAL] = text

        return sections

    def _extract_requirements(self, section: SequenceSection, text: str) -> list[LogicRequirement]:
        """Extract logic requirements from a section of text."""
        requirements = []
        text_lower = text.lower()

        for req_type, keywords in self.KEYWORDS.items():
            # Check if any keywords for this requirement type appear in the section
            matches = [kw for kw in keywords if kw in text_lower]
            if matches:
                # Extract sentences containing keywords
                sentences = self._extract_sentences(text, matches)
                for sent in sentences:
                    req = LogicRequirement(
                        req_id=self._new_req_id(),
                        requirement_type=req_type,
                        section=section,
                        description=sent.strip(),
                        source_text=text[:200],
                        points_referenced=self._extract_point_refs(sent),
                        setpoints_mentioned=self._extract_setpoints(sent),
                        conditions=self._extract_conditions(sent),
                        actions=self._extract_actions(sent),
                        metadata={"keywords_matched": matches},
                    )
                    requirements.append(req)

        return requirements

    def _extract_sentences(self, text: str, keywords: list[str]) -> list[str]:
        """Extract sentences containing keywords."""
        sentences = re.split(r'[.!?]+', text)
        matched = []
        for sent in sentences:
            sent_lower = sent.lower()
            if any(kw in sent_lower for kw in keywords):
                matched.append(sent.strip())
        return matched

    def _extract_point_refs(self, text: str) -> list[str]:
        """Extract potential point references from text."""
        # Common BAS point patterns
        patterns = [
            r'\b[A-Z]{2,4}-\d+\s+[A-Z]{2,4}\b',  # AHU-1 SAT
            r'\b[A-Z]{2,4}-\d+\s+[A-Z]{2,4}\s+[A-Z]{2,4}\b',  # AHU-1 SAT SP
            r'\b(SAT|MAT|RAT|OAT|ZAT|DAT|SAP|RAP|ZSP|CSP|HSP)\b',
            r'\b(SP|SPT|SPC|SPH|SPL|SPV|SPD|SPE)\b',
            r'\b(CMD|STATUS|ALM|FLT|PRF|SPD|SPD)\b',
        ]
        refs = []
        for pattern in patterns:
            refs.extend(re.findall(pattern, text, re.IGNORECASE))
        return list(set(refs))

    def _extract_setpoints(self, text: str) -> list[str]:
        """Extract setpoint references."""
        setpoints = re.findall(
            r'\b(\d+\.?\d*)\s*(degF|degC|F|C|%|PSI|inWC|CFM|GPM)\b',
            text, re.IGNORECASE
        )
        return [f"{v} {u}" for v, u in setpoints]

    def _extract_conditions(self, text: str) -> list[str]:
        """Extract conditional statements."""
        conditions = []
        cond_patterns = [
            r'if\s+.+?(?=then|,|\.|$)',
            r'when\s+.+?(?=then|,|\.|$)',
            r'whenever\s+.+?(?=then|,|\.|$)',
            r'above\s+\d+',
            r'below\s+\d+',
            r'exceeds\s+\d+',
            r'less than\s+\d+',
            r'greater than\s+\d+',
        ]
        for pattern in cond_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            conditions.extend([m if isinstance(m, str) else m[0] for m in matches])
        return conditions

    def _extract_actions(self, text: str) -> list[str]:
        """Extract action statements."""
        actions = []
        action_patterns = [
            r'shall\s+\w+',
            r'must\s+\w+',
            r'will\s+\w+',
            r'command\s+\w+',
            r'enable\s+\w+',
            r'disable\s+\w+',
            r'modulate\s+\w+',
            r'open\s+\w+',
            r'close\s+\w+',
            r'start\s+\w+',
            r'stop\s+\w+',
            r'reset\s+\w+',
        ]
        for pattern in action_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            actions.extend(matches)
        return actions

    def _calculate_confidence(self, req: LogicRequirement, full_text: str) -> float:
        """Calculate confidence score for a requirement."""
        confidence = 0.5  # Base confidence

        # Boost for specific keywords
        if req.metadata.get("keywords_matched"):
            confidence += min(len(req.metadata["keywords_matched"]) * 0.1, 0.3)

        # Boost for point references
        if req.points_referenced:
            confidence += min(len(req.points_referenced) * 0.05, 0.2)

        # Boost for setpoints
        if req.setpoints_mentioned:
            confidence += min(len(req.setpoints_mentioned) * 0.05, 0.1)

        # Boost for conditions/actions
        if req.conditions or req.actions:
            confidence += 0.1

        # Penalty for very short descriptions
        if len(req.description) < 20:
            confidence -= 0.1

        return max(0.0, min(1.0, confidence))

    def parse_file(self, file_path: Path) -> ParsedSequence:
        """Parse a sequence file."""
        with open(file_path) as f:
            text = f.read()
        return self.parse(text)

    def parse_multiple(self, texts: dict[str, str]) -> dict[str, ParsedSequence]:
        """Parse multiple sequences."""
        return {equip_id: self.parse(text, equip_id) for equip_id, text in texts.items()}


def parse_sequence(text: str, equipment_id: Optional[str] = None) -> ParsedSequence:
    """Convenience function to parse a sequence."""
    parser = SequenceParser()
    return parser.parse(text, equipment_id)


__all__ = [
    "SequenceParser",
    "ParsedSequence",
    "LogicRequirement",
    "SequenceSection",
    "LogicRequirementType",
    "parse_sequence",
]