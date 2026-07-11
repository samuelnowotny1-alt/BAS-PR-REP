"""Reasoning package - AI reasoning, gap analysis, sequence parsing, troubleshooting, confidence, validation."""

from .gap_analysis import (
    GapAnalyzer,
    GapAnalysisReport,
    Gap,
    GapSeverity,
    GapCategory,
    analyze_gaps,
)

from .sequence_parser import (
    SequenceParser,
    ParsedSequence,
    LogicRequirement,
    SequenceSection,
    LogicRequirementType,
    parse_sequence,
)

from .troubleshooting import (
    TroubleshootingAssistant,
    TrendAnalyzer,
    AlarmAnalyzer,
    ControlLoopAnalyzer,
    TroubleshootingReport,
    TroubleshootingIssue,
    TrendData,
    TrendPoint,
    AlarmEvent,
    IssueSeverity,
    IssueCategory,
    analyze_trends,
    analyze_alarms,
)

from .confidence import (
    ConfidenceScorer,
    ConfidenceScore,
    ScoredOutput,
    ConfidenceLevel,
    ConfidenceFactor,
    score_confidence,
)

from .validation import (
    EngineeringRulesEngine,
    EngineeringRule,
    ValidationFinding,
    ValidationRuleType,
    validate_engineering_rules,
)

from .assumptions import (
    AssumptionTracker,
    AssumptionSet,
    Assumption,
    AssumptionStatus,
    AssumptionCategory,
    BAS_ASSUMPTION_TEMPLATES,
    create_bas_assumptions,
)

__all__ = [
    # Gap Analysis
    "GapAnalyzer",
    "GapAnalysisReport",
    "Gap",
    "GapSeverity",
    "GapCategory",
    "analyze_gaps",
    # Sequence Parsing
    "SequenceParser",
    "ParsedSequence",
    "LogicRequirement",
    "SequenceSection",
    "LogicRequirementType",
    "parse_sequence",
    # Troubleshooting
    "TroubleshootingAssistant",
    "TrendAnalyzer",
    "AlarmAnalyzer",
    "ControlLoopAnalyzer",
    "TroubleshootingReport",
    "TroubleshootingIssue",
    "TrendData",
    "TrendPoint",
    "AlarmEvent",
    "IssueSeverity",
    "IssueCategory",
    "analyze_trends",
    "analyze_alarms",
    # Confidence
    "ConfidenceScorer",
    "ConfidenceScore",
    "ScoredOutput",
    "ConfidenceLevel",
    "ConfidenceFactor",
    "score_confidence",
    # Validation
    "EngineeringRulesEngine",
    "EngineeringRule",
    "ValidationFinding",
    "ValidationRuleType",
    "validate_engineering_rules",
    # Assumptions
    "AssumptionTracker",
    "AssumptionSet",
    "Assumption",
    "AssumptionStatus",
    "AssumptionCategory",
    "BAS_ASSUMPTION_TEMPLATES",
    "create_bas_assumptions",
]