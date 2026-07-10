# Python Conventions

## Purpose
Define Python coding standards for the project.

## Scope
Applies to application code, scripts, tests, generators, validators, and developer utilities.

## Inputs
- Project architecture.
- Existing Python ecosystem standards.
- Testability requirements.

## Outputs
- Maintainable Python modules.
- Predictable error handling.
- Consistent tests and formatting.

## Dependencies
- [Architecture](../ARCHITECTURE.md)
- [Design Principles](../DESIGN_PRINCIPLES.md)
- [Validation](../reasoning/validation.md)

## Design Reasoning
Python should be used as a clear orchestration and data-processing language. Code should favor explicit inputs, typed models, small functions, and deterministic behavior.

## Standards
- Use type hints for public functions.
- Keep pure transformation logic separate from file I/O.
- Avoid module-level mutable state.
- Raise specific exceptions for invalid data.
- Log operational context without hiding failures.
- Prefer structured models over dictionaries when data has a known schema.
- Write tests for validators and generators before relying on generated outputs.

## Future Improvements
- Select formatter, linter, type checker, and test framework.
- Add package layout conventions.
- Add examples after the first code modules exist.

## Examples
```python
def normalize_equipment_name(raw_name: str) -> str:
    """Return a validated equipment name or raise a validation error."""
    ...
```

