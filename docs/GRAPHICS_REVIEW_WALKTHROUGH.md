# Graphics Review Walkthrough

Last updated: 2026-07-20

Purpose:
Provide one reviewer-facing walkthrough for the graphics workbench slice so project-facing graphics can be evaluated consistently.

## Scope

This walkthrough covers:

- active project graphics workbench
- graphic detail inspection
- fullscreen review mode
- known unit graphics library

It does not treat Raspberry Pi deployment helpers or emulator bootstrap scripts as core product surfaces.

## Preconditions

1. BAS Assistant is running.
2. A demo or real project exists with generated graphics.
3. Preferred demo path:
   - load `Demo HVAC Project` from the home page, or
   - use the seeded `Codex Test Project`

## Review Flow

### 1. Open Active Graphics

Page:

- `/project/{project_id}/graphics`

Reviewer checks:

- The page loads without missing asset errors.
- Readiness messaging is visible when validation findings or cautions exist.
- Active device cards show JSON/SVG/fullscreen entrypoints.
- Generated asset links use `/output/...`.

Questions:

- Does the page clearly separate active project graphics from the library?
- Are the linked devices obvious and reviewable?

### 2. Inspect One Graphic

Page:

- `/project/{project_id}/graphics/{graphic_name}`

Reviewer checks:

- The station-style inspect surface renders.
- Object context, point groupings, and graphic metadata are visible.
- Bindings and labels are readable enough to review relationships.
- Validation findings and sequence context, if present, are understandable.

Questions:

- Can an engineer tell what this graphic is tied to?
- Are the points and roles believable for the equipment shown?

### 3. Open Fullscreen Review

Page:

- `/project/{project_id}/graphics/{graphic_name}/fullscreen`

Reviewer checks:

- Scene opens without broken asset references.
- Physical assets, bindings, and readiness data are all visible.
- Reference export is available when SVG output exists.
- The page reads as a review mode, not as a promise of real-time field operation.

Questions:

- Does the fullscreen mode help review composition and asset placement?
- Does it avoid implying unsupported live control behavior?

### 4. Open Known Unit Library

Page:

- `/project/{project_id}/graphics/library`

Reviewer checks:

- Active graphics and library are clearly separated.
- Isometric asset library is presented as reusable building blocks.
- Legacy flat symbols are hidden by default and labeled as compatibility/reference when revealed.

Questions:

- Which assets are canonical product building blocks?
- Which symbols should remain only for compatibility?

## Acceptance Signals

The graphics slice is review-ready when:

1. Workbench, detail, fullscreen, and library pages all render.
2. Active project graphics are clearly separated from reusable library assets.
3. Review links and output links resolve correctly.
4. The slice narrative stays grounded in engineering review, not vague “graphics polish.”

## Non-Goals

This walkthrough does not certify:

- field deployment correctness
- live station synchronization behavior
- Raspberry Pi lab installation flow
- production graphics design-system completeness
