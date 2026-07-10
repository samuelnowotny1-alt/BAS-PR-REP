# Generate Checkout Workflow

## Purpose
Describe how checkout artifacts are generated.

## Scope
Includes point checkout sheets, equipment functional tests, status tracking, and issue reporting.

## Inputs
- Equipment model.
- Points model.
- Sequence requirements.
- Commissioning standards.

## Outputs
- Checkout sheets.
- Functional test procedures.
- Issue templates.

## Dependencies
- [Checkout Model](../models/checkout.md)
- [Checkout Conventions](../conventions/checkout.md)

## Design Reasoning
Checkout generation should convert validated project data into field-executable steps without implying field completion.

## Future Improvements
- Add mobile workflow.
- Add evidence capture.
- Add automated report generation from completed checkout data.

## Examples
- Generate one checkout item per physical point with expected verification method and blank observed result.

