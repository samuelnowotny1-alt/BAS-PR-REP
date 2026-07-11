# Commissioning

## Purpose
Define commissioning concepts used by the assistant.

## Scope
Includes point checkout, functional testing, issue tracking, verification evidence, and approval status.

## Inputs
- Commissioning specifications.
- Point lists.
- Equipment schedules.
- Sequences of operation.

## Outputs
- Checkout steps.
- Functional test procedures.
- Issue logs.
- Completion reports.

## Dependencies
- [Checkout Conventions](../conventions/checkout.md)
- [Checkout Model](../models/checkout.md)

## Design Reasoning
Commissioning confirms installed behavior. Generated procedures must be specific enough for field execution and must not claim completion without observed evidence.

## Future Improvements
- Add evidence attachment model.
- Add issue severity definitions.
- Add functional test templates.

## Examples
- A failed fan proof test should record command state, expected proof, observed proof, timestamp, and notes.

