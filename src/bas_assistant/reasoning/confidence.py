"""Confidence Scoring - Quantifies reliability of AI-generated outputs."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ConfidenceLevel(str, Enum):
    """Confidence level categories."""
    VERY_HIGH = "very_high"    # 0.9-1.0
    HIGH = "high"              # 0.75-0.9
    MEDIUM = "medium"          # 0.5-0.75
    LOW = "low"                # 0.25-0.5
    VERY_LOW = "very_low"      # 0.0-0.25


class ConfidenceFactor(str, Enum):
    """Factors that affect confidence."""
    DATA_COMPLETENESS = "data_completeness"
    DATA_QUALITY = "data_quality"
    MODEL_CERTAINTY = "model_certainty"
    VALIDATION_STATUS = "validation_status"
    SOURCE_RELIABILITY = "source_reliability"
    CROSS_REFERENCE = "cross_reference"
    ENGINEERING_RULES = "engineering_rules"
    HISTORICAL_ACCURACY = "historical_accuracy"


@dataclass
class ConfidenceScore:
    """A confidence score with contributing factors."""
    overall: float  # 0.0 - 1.0
    level: ConfidenceLevel
    factors: dict[ConfidenceFactor, float] = field(default_factory=dict)
    reasoning: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.overall >= 0.9:
            self.level = ConfidenceLevel.VERY_HIGH
        elif self.overall >= 0.75:
            self.level = ConfidenceLevel.HIGH
        elif self.overall >= 0.5:
            self.level = ConfidenceLevel.MEDIUM
        elif self.overall >= 0.25:
            self.level = ConfidenceLevel.LOW
        else:
            self.level = ConfidenceLevel.VERY_LOW


@dataclass
class ScoredOutput:
    """An output with its confidence score."""
    output_id: str
    output_type: str  # logic, graphics, checkout, report, sequence
    content: dict
    confidence: ConfidenceScore
    generated_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


class ConfidenceScorer:
    """Scores confidence of AI-generated outputs based on multiple factors."""

    def __init__(self):
        self.factor_weights = {
            ConfidenceFactor.DATA_COMPLETENESS: 0.25,
            ConfidenceFactor.DATA_QUALITY: 0.20,
            ConfidenceFactor.MODEL_CERTAINTY: 0.15,
            ConfidenceFactor.VALIDATION_STATUS: 0.15,
            ConfidenceFactor.SOURCE_RELIABILITY: 0.10,
            ConfidenceFactor.CROSS_REFERENCE: 0.10,
            ConfidenceFactor.ENGINEERING_RULES: 0.05,
        }

    def score_logic_generation(
        self,
        project,
        equipment_id: str,
        logic_diagram,
        validation_report,
    ) -> ConfidenceScore:
        """Score confidence of generated control logic."""
        factors = {}
        reasoning = []
        warnings = []

        # 1. Data completeness - do we have all required points?
        equip = project.get_equipment(equipment_id)
        if equip:
            points = project.get_points_for_equipment(equip.id)
            required_kinds = {"sensor", "actuator", "setpoint", "status"}
            have_kinds = {p.kind.value for p in points}
            missing = required_kinds - have_kinds
            completeness = 1.0 - (len(missing) / len(required_kinds))
            factors[ConfidenceFactor.DATA_COMPLETENESS] = completeness
            if missing:
                reasoning.append(f"Missing point kinds: {missing}")
                warnings.append(f"Logic may be incomplete without: {missing}")

        # 2. Data quality - validation status
        if validation_report:
            error_rate = len(validation_report.errors) / max(validation_report.total_checks, 1)
            quality = 1.0 - min(error_rate * 2, 1.0)
            factors[ConfidenceFactor.DATA_QUALITY] = quality
            if validation_report.has_errors:
                warnings.append(f"Validation errors present: {len(validation_report.errors)}")

        # 3. Model certainty - equipment type support
        if equip:
            supported_types = {"AHU", "RTU", "VAV", "CHILLER", "BOILER", "COOLING_TOWER", "PUMP_HW", "PUMP_CHW", "PUMP_CW"}
            model_certainty = 1.0 if equip.type.value in supported_types else 0.6
            factors[ConfidenceFactor.MODEL_CERTainty] = model_certainty
            if equip.type.value not in supported_types:
                warnings.append(f"Equipment type {equip.type.value} has limited logic templates")

        # 4. Validation status
        validation_score = 1.0
        if validation_report:
            if validation_report.has_errors:
                validation_score = 0.3
            elif validation_report.has_warnings:
                validation_score = 0.7
        factors[ConfidenceFactor.VALIDATION_STATUS] = validation_score

        # 5. Source reliability - are points from approved sources?
        source_score = 0.8  # Default
        if equip:
            points = project.get_points_for_equipment(equip.id)
            source_types = {p.source.value for p in points}
            if "point_list" in source_types:
                source_score = 0.9
            if "manual" in source_types:
                source_score = 0.5
        factors[ConfidenceFactor.SOURCE_RELIABILITY] = source_score

        # 6. Cross-reference - do points match between equipment/controller?
        cross_ref = 0.9
        if equip and equip.controller_id:
            ctrl = project.get_controller(equip.controller_id)
            if ctrl:
                equip_points = set(p.name for p in project.get_points_for_equipment(equip.id))
                ctrl_points = set(ctrl.owned_point_names)
                if equip_points and ctrl_points:
                    overlap = equip_points & ctrl_points
                    cross_ref = len(overlap) / len(equip_points | ctrl_points) if (equip_points | ctrl_points) else 0
        factors[ConfidenceFactor.CROSS_REFERENCE] = cross_ref

        # 7. Engineering rules compliance
        eng_score = 0.8
        # Could check against engineering rules
        factors[ConfidenceFactor.ENGINEERING_RULES] = eng_score

        # Calculate weighted overall score
        overall = sum(
            factors.get(factor, 0.5) * weight
            for factor, weight in self.factor_weights.items()
        )

        return ConfidenceScore(
            overall=overall,
            level=ConfidenceLevel.MEDIUM,  # Will be set in __post_init__
            factors=factors,
            reasoning=reasoning,
            warnings=warnings,
        )

    def score_graphics_generation(
        self,
        project,
        equipment_id: str,
        graphics_def,
    ) -> ConfidenceScore:
        """Score confidence of generated graphics."""
        factors = {}
        reasoning = []
        warnings = []

        equip = project.get_equipment(equipment_id)
        if not equip:
            return ConfidenceScore(overall=0.1, level=ConfidenceLevel.VERY_LOW,
                                   warnings=["Equipment not found"])

        points = project.get_points_for_equipment(equip.id)

        # Data completeness - points with bindings
        bound_points = sum(1 for p in points if p.bacnet_object_type or p.modbus_register)
        factors[ConfidenceFactor.DATA_COMPLETENESS] = bound_points / len(points) if points else 0

        # Data quality - validation
        factors[ConfidenceFactor.DATA_QUALITY] = 0.8

        # Model certainty - template availability
        template_available = equip.type.value in {"AHU", "RTU", "VAV", "CHILLER", "BOILER", "COOLING_TOWER", "PUMP_HW", "PUMP_CHW", "PUMP_CW"}
        factors[ConfidenceFactor.MODEL_CERTAINTY] = 1.0 if template_available else 0.5

        # Cross reference - points have controller assignments
        ctrl_assigned = sum(1 for p in points if p.controller_id)
        factors[ConfidenceFactor.CROSS_REFERENCE] = ctrl_assigned / len(points) if points else 0

        overall = sum(factors.get(f, 0.5) * 0.25 for f in factors)
        return ConfidenceScore(overall=overall, level=ConfidenceLevel.MEDIUM, factors=factors, reasoning=reasoning, warnings=warnings)

    def score_checkout_generation(
        self,
        project,
        equipment_id: str,
        checkout_sheet,
    ) -> ConfidenceScore:
        """Score confidence of generated checkout sheet."""
        factors = {}
        reasoning = []
        warnings = []

        equip = project.get_equipment(equipment_id)
        if not equip:
            return ConfidenceScore(overall=0.1, level=ConfidenceLevel.VERY_LOW,
                                   warnings=["Equipment not found"])

        points = project.get_points_for_equipment(equip.id)

        # Completeness - points with ranges for calibration
        calibratable = sum(1 for p in points if p.kind.value == "sensor" and p.range_min is not None and p.range_max is not None)
        sensor_count = sum(1 for p in points if p.kind.value == "sensor")
        factors[ConfidenceFactor.DATA_COMPLETENESS] = calibratable / sensor_count if sensor_count else 0

        # Quality - controller assigned
        factors[ConfidenceFactor.DATA_QUALITY] = 0.8

        # Cross reference - controller matches
        if equip.controller_id:
            ctrl = project.get_controller(equip.controller_id)
            if ctrl:
                factors[ConfidenceFactor.CROSS_REFERENCE] = 1.0
            else:
                factors[ConfidenceFactor.CROSS_REFERENCE] = 0.5
                warnings.append("Equipment controller not found")

        overall = sum(factors.get(f, 0.5) * 0.33 for f in factors)
        return ConfidenceScore(overall=overall, level=ConfidenceLevel.MEDIUM, factors=factors, reasoning=reasoning, warnings=warnings)

    def score_report_generation(
        self,
        project,
        report_type: str,
    ) -> ConfidenceScore:
        """Score confidence of generated report."""
        factors = {}

        # Data completeness - all required data present
        equip_count = len(project.equipment)
        point_count = len(project.points)
        ctrl_count = len(project.controllers)

        factors[ConfidenceFactor.DATA_COMPLETENESS] = 1.0 if (equip_count and point_count) else 0.5
        factors[ConfidenceFactor.DATA_QUALITY] = 0.8
        factors[ConfidenceFactor.VALIDATION_STATUS] = 0.9 if project.validation_status == "valid" else 0.5
        factors[ConfidenceFactor.CROSS_REFERENCE] = 0.8

        overall = sum(factors.values()) / len(factors)
        return ConfidenceScore(overall=overall, level=ConfidenceLevel.MEDIUM, factors=factors)


def score_confidence(scorer: ConfidenceScorer, **kwargs) -> ConfidenceScore:
    """Convenience function to score based on output type."""
    output_type = kwargs.get("output_type", "logic")

    if output_type == "logic":
        return scorer.score_logic_generation(
            kwargs["project"],
            kwargs["equipment_id"],
            kwargs.get("logic_diagram"),
            kwargs.get("validation_report"),
        )
    if output_type == "graphics":
        return scorer.score_graphics_generation(
            kwargs["project"],
            kwargs["equipment_id"],
            kwargs.get("graphics_def"),
        )
    if output_type == "checkout":
        return scorer.score_checkout_generation(
            kwargs["project"],
            kwargs["equipment_id"],
            kwargs.get("checkout_sheet"),
        )
    if output_type == "report":
        return scorer.score_report_generation(
            kwargs["project"],
            kwargs.get("report_type", "submittal"),
        )
    return ConfidenceScore(overall=0.5, level=ConfidenceLevel.MEDIUM)


__all__ = [
    "ConfidenceFactor",
    "ConfidenceLevel",
    "ConfidenceScore",
    "ConfidenceScorer",
    "ScoredOutput",
    "score_confidence",
]
