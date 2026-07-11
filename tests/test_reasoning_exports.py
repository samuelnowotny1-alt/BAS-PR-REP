from bas_assistant.reasoning import (
    EngineeringRule,
    EngineeringRulesEngine,
    ValidationFinding,
    validate_engineering_rules,
)
from bas_assistant.reasoning.validation import ValidationRuleType


def test_engineering_validation_exports_are_public() -> None:
    assert EngineeringRulesEngine is not None
    assert EngineeringRule is not None
    assert ValidationFinding is not None
    assert ValidationRuleType is not None
    assert callable(validate_engineering_rules)


def test_engineering_rules_engine_loads_builtin_rules() -> None:
    engine = EngineeringRulesEngine()

    assert len(engine.rules) >= 30
    assert all(rule.rule_id for rule in engine.rules)
    assert all(rule.name for rule in engine.rules)
