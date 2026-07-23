# UI Audit Checklist

Last updated: 2026-07-23

Purpose:
Provide one pass/fail checklist for cleaning the BAS Assistant UI and reducing layout regressions.

## Shared Rules

- No text should overflow its card, chip, table cell, or modal.
- Long IDs, filenames, point names, URLs, and monospace values must wrap or truncate intentionally.
- Tables must remain usable on smaller screens with horizontal scrolling where needed.
- Dense stat grids must collapse cleanly from desktop to tablet to mobile.
- Buttons and links should not overlap adjacent content.
- Hero/header sections should keep actions readable without collisions.

## Page Sweep

### Global Layout

- `ui/templates/base.html`
- Check sidebar, top bar, flash messages, main content spacing, and footer behavior.

### Project / Navigation Surfaces

- `ui/templates/index.html`
- `ui/templates/project_detail.html`
- `ui/templates/project_status.html`
- `ui/templates/project_activity.html`
- `ui/templates/project_documents.html`
- `ui/templates/project_knowledge.html`
- `ui/templates/project_memberships.html`

### Data Review Surfaces

- `ui/templates/object_list.html`
- `ui/templates/object_detail.html`
- `ui/templates/validate.html`
- `ui/templates/gaps.html`
- `ui/templates/mappings.html`
- `ui/templates/assumptions.html`

### Import / Workflow Surfaces

- `ui/templates/import.html`
- `ui/templates/sequence.html`
- `ui/templates/sequence_result.html`
- `ui/templates/review_release.html`
- `ui/templates/station_sync.html`

### Graphics / Output Surfaces

- `ui/templates/graphics.html`
- `ui/templates/graphics_detail.html`
- `ui/templates/graphics_fullscreen.html`
- `ui/templates/graphics_library.html`
- `ui/templates/reports.html`
- `ui/templates/logic.html`
- `ui/templates/export.html`
- `ui/templates/export_result.html`
- `ui/templates/checkout.html`

### Auth / Admin / Error

- `ui/templates/login.html`
- `ui/templates/admin_users.html`
- `ui/templates/error.html`

## High-Risk Content Types

- Long project names
- Long point names
- Long controller addresses
- Monospace filenames and IDs
- Dense filter forms
- Multi-column stat cards
- Large tables with many narrow columns
- Modal dialogs on smaller widths
- Dynamic badges and chips

## Acceptance Gate

1. Core pages render without visible text overlap at common desktop and mobile widths.
2. Tables scroll horizontally instead of smashing content.
3. Chips, badges, and stat values remain readable with long data.
4. The project dashboard, validation, import, object lists, and graphics pages all pass a manual visual sweep.
5. Focused UI regression tests still pass after cleanup.
