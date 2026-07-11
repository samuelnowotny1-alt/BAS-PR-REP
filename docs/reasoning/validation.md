# Validation

## Purpose
Define how project data and generated artifacts are validated.

## Scope
Includes completeness, consistency, naming, type correctness, protocol mapping, sequence coverage, and output readiness.

## Inputs
- Structured models.
- Conventions.
- Engineering rules.
- Source documents.

## Outputs
- Errors.
- Warnings.
- Assumptions.
- Approval blockers.

## Dependencies
- [Engineering Rules](engineering_rules.md)
- [Naming Conventions](../conventions/naming.md)
- [Points Model](../models/points.md)

## Design Reasoning
Validation is the barrier between source data and generated deliverables. It should fail clearly and early when data is missing or contradictory.

## Severity Levels
- Error: Blocks generation or approval.
- Warning: Allows generation but requires review.
- Info: Provides useful context.
- Assumption: Marks a provisional interpretation requiring approval.

## Future Improvements
- Add validation rule catalog.
- Add machine-readable validation report schema.
- Add automated tests for each rule.

## Examples
- Error: A required analog point has no units.
- Warning: Equipment location is missing.
- Assumption: Controller assignment inferred from source sheet grouping.

