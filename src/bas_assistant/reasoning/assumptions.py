"""Assumptions Tracking - Documents and traces assumptions made during design."""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import json


class AssumptionStatus(str, Enum):
    """Status of an assumption."""
    PENDING = "pending"           # Not yet verified
    VERIFIED = "verified"         # Confirmed true
    INVALIDATED = "invalidated"   # Proven false
    DEFERRED = "deferred"         # Deferred to later phase
    ACCEPTED = "accepted"         # Accepted as design basis


class AssumptionCategory(str, Enum):
    """Categories of assumptions."""
    DESIGN = "design"                 # Design parameters
    EQUIPMENT = "equipment"           # Equipment capabilities
    SEQUENCE = "sequence"             # Sequence of operation
    CODE = "code"                     # Code compliance
    SITE = "site"                     # Site conditions
    CLIENT = "client"                 # Client requirements
    COORDINATION = "coordination"     # Inter-discipline coordination
    BUDGET = "budget"                 # Budget constraints
    SCHEDULE = "schedule"             # Schedule constraints


@dataclass
class Assumption:
    """A documented assumption with traceability."""
    assumption_id: str
    category: AssumptionCategory
    title: str
    description: str
    rationale: str = ""
    status: AssumptionStatus = AssumptionStatus.PENDING
    source: str = ""  # Who made the assumption
    created_at: datetime = field(default_factory=datetime.now)
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    related_objects: list[str] = field(default_factory=list)  # equipment IDs, point names, etc.
    dependencies: list[str] = field(default_factory=list)  # Other assumption IDs this depends on
    impacts: list[str] = field(default_factory=list)  # What breaks if this is wrong
    verification_method: str = ""  # How to verify
    verification_evidence: str = ""  # Evidence of verification
    notes: str = ""

    def verify(self, verified_by: str, evidence: str = "") -> None:
        """Mark assumption as verified."""
        self.status = AssumptionStatus.VERIFIED
        self.verified_at = datetime.now()
        self.verified_by = verified_by
        self.verification_evidence = evidence

    def invalidate(self, reason: str) -> None:
        """Mark assumption as invalidated."""
        self.status = AssumptionStatus.INVALIDATED
        self.notes += f"\n[INVALIDATED] {reason} - {datetime.now().isoformat()}"

    def defer(self, reason: str) -> None:
        """Defer assumption to later phase."""
        self.status = AssumptionStatus.DEFERRED
        self.notes += f"\n[DEFERRED] {reason} - {datetime.now().isoformat()}"

    def accept(self) -> None:
        """Accept as design basis."""
        self.status = AssumptionStatus.ACCEPTED


@dataclass
class AssumptionSet:
    """A collection of assumptions for a project or phase."""
    project_id: str
    name: str
    description: str = ""
    assumptions: list[Assumption] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def add(self, assumption: Assumption) -> None:
        self.assumptions.append(assumption)
        self.updated_at = datetime.now()

    def get_by_id(self, assumption_id: str) -> Optional[Assumption]:
        return next((a for a in self.assumptions if a.assumption_id == assumption_id), None)

    def get_by_category(self, category: AssumptionCategory) -> list[Assumption]:
        return [a for a in self.assumptions if a.category == category]

    def get_by_status(self, status: AssumptionStatus) -> list[Assumption]:
        return [a for a in self.assumptions if a.status == status]

    def get_pending_verification(self) -> list[Assumption]:
        return [a for a in self.assumptions if a.status == AssumptionStatus.PENDING]

    def get_invalidated(self) -> list[Assumption]:
        return [a for a in self.assumptions if a.status == AssumptionStatus.INVALIDATED]

    def summary(self) -> dict:
        by_status = {}
        by_category = {}
        for a in self.assumptions:
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
            by_category[a.category.value] = by_category.get(a.category.value, 0) + 1

        return {
            "total": len(self.assumptions),
            "by_status": by_status,
            "by_category": by_category,
            "pending_verification": len(self.get_pending_verification()),
            "invalidated": len(self.get_invalidated()),
        }


class AssumptionTracker:
    """Manages assumptions for a project."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.assumption_sets: dict[str, AssumptionSet] = {}
        self._counter = 0

    def _new_id(self, prefix: str = "ASM") -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"

    def create_set(self, name: str, description: str = "") -> AssumptionSet:
        asm_set = AssumptionSet(
            project_id=self.project_id,
            name=name,
            description=description,
        )
        self.assumption_sets[name] = asm_set
        return asm_set

    def add_assumption(
        self,
        category: AssumptionCategory,
        title: str,
        description: str,
        rationale: str = "",
        source: str = "",
        related_objects: list[str] = None,
        dependencies: list[str] = None,
        impacts: list[str] = None,
        verification_method: str = "",
        set_name: str = "default",
    ) -> Assumption:
        """Add a new assumption to a set."""
        if set_name not in self.assumption_sets:
            self.create_set(set_name)

        asm = Assumption(
            assumption_id=self._new_id(),
            category=category,
            title=title,
            description=description,
            rationale=rationale,
            source=source,
            related_objects=related_objects or [],
            dependencies=dependencies or [],
            impacts=impacts or [],
            verification_method=verification_method,
        )

        self.assumption_sets[set_name].add(asm)
        return asm

    def verify_assumption(self, assumption_id: str, verified_by: str, evidence: str = "") -> bool:
        """Verify an assumption by ID."""
        for asm_set in self.assumption_sets.values():
            asm = asm_set.get_by_id(assumption_id)
            if asm:
                asm.verify(verified_by, evidence)
                return True
        return False

    def invalidate_assumption(self, assumption_id: str, reason: str) -> bool:
        """Invalidate an assumption."""
        for asm_set in self.assumption_sets.values():
            asm = asm_set.get_by_id(assumption_id)
            if asm:
                asm.invalidate(reason)
                return True
        return False

    def get_assumption(self, assumption_id: str) -> Optional[Assumption]:
        for asm_set in self.assumption_sets.values():
            asm = asm_set.get_by_id(assumption_id)
            if asm:
                return asm
        return None

    def export_to_json(self, output_path: Path) -> None:
        """Export all assumptions to JSON."""
        data = {
            "project_id": self.project_id,
            "exported_at": datetime.now().isoformat(),
            "sets": {},
        }
        for name, asm_set in self.assumption_sets.items():
            data["sets"][name] = {
                "name": asm_set.name,
                "description": asm_set.description,
                "created_at": asm_set.created_at.isoformat(),
                "updated_at": asm_set.updated_at.isoformat(),
                "assumptions": [
                    {
                        "assumption_id": a.assumption_id,
                        "category": a.category.value,
                        "title": a.title,
                        "description": a.description,
                        "rationale": a.rationale,
                        "status": a.status.value,
                        "source": a.source,
                        "created_at": a.created_at.isoformat(),
                        "verified_at": a.verified_at.isoformat() if a.verified_at else None,
                        "verified_by": a.verified_by,
                        "related_objects": a.related_objects,
                        "dependencies": a.dependencies,
                        "impacts": a.impacts,
                        "verification_method": a.verification_method,
                        "verification_evidence": a.verification_evidence,
                        "notes": a.notes,
                    }
                    for a in asm_set.assumptions
                ],
            }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

    def import_from_json(self, input_path: Path) -> None:
        """Import assumptions from JSON."""
        with open(input_path) as f:
            data = json.load(f)

        for name, set_data in data.get("sets", {}).items():
            asm_set = self.create_set(set_data["name"], set_data.get("description", ""))
            asm_set.created_at = datetime.fromisoformat(set_data["created_at"])
            asm_set.updated_at = datetime.fromisoformat(set_data["updated_at"])

            for a_data in set_data["assumptions"]:
                asm = Assumption(
                    assumption_id=a_data["assumption_id"],
                    category=AssumptionCategory(a_data["category"]),
                    title=a_data["title"],
                    description=a_data["description"],
                    rationale=a_data.get("rationale", ""),
                    status=AssumptionStatus(a_data["status"]),
                    source=a_data.get("source", ""),
                    created_at=datetime.fromisoformat(a_data["created_at"]),
                    verified_at=datetime.fromisoformat(a_data["verified_at"]) if a_data.get("verified_at") else None,
                    verified_by=a_data.get("verified_by"),
                    related_objects=a_data.get("related_objects", []),
                    dependencies=a_data.get("dependencies", []),
                    impacts=a_data.get("impacts", []),
                    verification_method=a_data.get("verification_method", ""),
                    verification_evidence=a_data.get("verification_evidence", ""),
                    notes=a_data.get("notes", ""),
                )
                asm_set.add(asm)


# Built-in assumption templates for BAS projects
BAS_ASSUMPTION_TEMPLATES = [
    {
        "category": AssumptionCategory.DESIGN,
        "title": "Design Weather Data",
        "description": "Design dry-bulb and wet-bulb temperatures based on ASHRAE 0.4%/1%/2% climate data for project location",
        "rationale": "Equipment sizing depends on accurate design conditions",
        "verification_method": "Verify against ASHRAE Climatic Design Information",
        "impacts": ["Equipment sizing", "Coil selection", "Plant capacity"],
    },
    {
        "category": AssumptionCategory.DESIGN,
        "title": "Indoor Design Conditions",
        "description": "Space temperature and humidity setpoints per ASHRAE 55 and project requirements",
        "rationale": "Defines control setpoints and load calculations",
        "verification_method": "Confirm with owner/architect",
        "impacts": ["Zone setpoints", "Reheat coil sizing", "Humidification capacity"],
    },
    {
        "category": AssumptionCategory.DESIGN,
        "title": "Diversity Factors",
        "description": "Diversity factors applied to equipment sizing per ASHRAE guidelines",
        "rationale": "Avoids oversizing plant equipment",
        "verification_method": "Review load calculation methodology",
        "impacts": ["Chiller/boiler sizing", "Pump sizing", "Electrical service"],
    },
    {
        "category": AssumptionCategory.EQUIPMENT,
        "title": "Equipment Manufacturer Selections",
        "description": "Specific manufacturer/model selections for major equipment",
        "rationale": "Controls integration depends on specific equipment capabilities",
        "verification_method": "Confirm with mechanical engineer and submittals",
        "impacts": ["BACnet object mapping", "Control sequences", "Graphics"],
    },
    {
        "category": AssumptionCategory.EQUIPMENT,
        "title": "VFD Availability",
        "description": "All pumps and fans specified with VFDs unless constant volume required",
        "rationale": "Energy code compliance and control flexibility",
        "verification_method": "Review equipment schedules",
        "impacts": ["Control sequences", "Graphics", "Electrical coordination"],
    },
    {
        "category": AssumptionCategory.SEQUENCE,
        "title": "Occupancy Schedule Source",
        "description": "Occupancy schedules from architectural program or owner requirements",
        "rationale": "Drives unit enable/disable and setback logic",
        "verification_method": "Confirm with owner/architect",
        "impacts": ["Unit scheduling", "Setback temperatures", "Optimal start"],
    },
    {
        "category": AssumptionCategory.SEQUENCE,
        "title": "Economizer High Limit Strategy",
        "description": "Differential dry-bulb or enthalpy economizer changeover per climate zone and code",
        "rationale": "Code compliance and energy optimization",
        "verification_method": "Verify against ASHRAE 90.1 and local code",
        "impacts": ["OA damper sequence", "Energy performance", "Commissioning"],
    },
    {
        "category": AssumptionCategory.SEQUENCE,
        "title": "Demand Control Ventilation",
        "description": "CO2-based DCV for high-occupancy spaces per ASHRAE 62.1/90.1",
        "rationale": "Energy code requirement for spaces >500 sqft and >25 people/1000 sqft",
        "verification_method": "Review space classifications and occupancy",
        "impacts": ["OA flow setpoints", "CO2 sensor locations", "Sequence logic"],
    },
    {
        "category": AssumptionCategory.CODE,
        "title": "Energy Code Compliance",
        "description": "Project complies with ASHRAE 90.1-2019 (or local equivalent)",
        "rationale": "Dictates economizer, energy recovery, DCV, and control requirements",
        "verification_method": "Code analysis by engineer of record",
        "impacts": ["All control sequences", "Equipment selection", "Documentation"],
    },
    {
        "category": AssumptionCategory.CODE,
        "title": "Fire/Smoke Damper Integration",
        "description": "Fire alarm system provides shutdown signals to BAS per IFC/NFPA",
        "rationale": "Life safety requirement",
        "verification_method": "Coordinate with fire protection engineer",
        "impacts": ["Fan shutdown sequences", "Damper control", "Graphics/alarms"],
    },
    {
        "category": AssumptionCategory.SITE,
        "title": "Existing Building Conditions",
        "description": "Existing equipment, controls, and infrastructure conditions verified",
        "rationale": "Retrofit projects depend on accurate existing conditions",
        "verification_method": "Site survey and point-to-point verification",
        "impacts": ["Equipment reuse", "Control panel locations", "Network topology"],
    },
    {
        "category": AssumptionCategory.COORDINATION,
        "title": "Electrical Coordination",
        "description": "VFD locations, power requirements, and disconnects coordinated with electrical",
        "rationale": "Controls power and signal wiring depends on electrical design",
        "verification_method": "Review electrical drawings and coordination meetings",
        "impacts": ["Controller locations", "Network topology", "Power budgets"],
    },
    {
        "category": AssumptionCategory.COORDINATION,
        "title": "Network Infrastructure",
        "description": "IT provides BACnet/IP network infrastructure (VLANs, switches, routers)",
        "rationale": "BAS communication depends on network availability",
        "verification_method": "Coordinate with IT/owner",
        "impacts": ["Controller IP addressing", "BBMD configuration", "Remote access"],
    },
    {
        "category": AssumptionCategory.CLIENT,
        "title": "Owner Training Requirements",
        "description": "Level of owner training and documentation specified",
        "rationale": "Affects deliverables and project closeout",
        "verification_method": "Confirm with owner during design",
        "impacts": ["Training scope", "O&M manuals", "Graphics complexity"],
    },
    {
        "category": AssumptionCategory.CLIENT,
        "title": "Remote Access Requirements",
        "description": "Owner remote access method (VPN, cloud, dedicated line) defined",
        "rationale": "Affects network architecture and security",
        "verification_method": "IT coordination meeting",
        "impacts": ["Network design", "Security", "Commissioning"],
    },
]


def create_bas_assumptions(project_id: str) -> AssumptionTracker:
    """Create a pre-populated assumption tracker for a BAS project."""
    tracker = AssumptionTracker(project_id)
    default_set = tracker.create_set("design_basis", "Design Basis Assumptions")

    for template in BAS_ASSUMPTION_TEMPLATES:
        tracker.add_assumption(
            category=template["category"],
            title=template["title"],
            description=template["description"],
            rationale=template["rationale"],
            verification_method=template["verification_method"],
            impacts=template["impacts"],
            set_name="design_basis",
        )

    return tracker


__all__ = [
    "AssumptionTracker",
    "AssumptionSet",
    "Assumption",
    "AssumptionStatus",
    "AssumptionCategory",
    "BAS_ASSUMPTION_TEMPLATES",
    "create_bas_assumptions",
]