# Optimization Baseline

Generated: 2026-07-13

## Current Regression Timing

- Command: `./.venv/bin/pytest tests/test_ui_workflow.py tests/test_auth_and_database.py tests/test_runtime_infrastructure.py -q`
- Result: `61 passed`
- Pytest duration: `90.16s`
- Wall-clock duration: `91.02s`

## Focused Verification

- `tests/test_ui_workflow.py -k 'import_workspace_view_returns_recent_uploads_and_task_summary or import_page_renders_recent_ingestion_outcomes_and_parser_support or htmx_import_returns_inline_result_summary or project_documents_page_and_download_render'`
  - Result: `4 passed`
  - Duration: `9.56s`
- `tests/test_runtime_infrastructure.py -k 'timed_page_context_logs_duration or health_endpoint_reports_loaded_projects'`
  - Result: `2 passed`
  - Duration: `3.66s`

## Notes

- Import workspace data now loads through a single `ProjectQueryService.import_workspace_view()` read model.
- Page-context timing logs are emitted for dashboard, project detail, import page, import result partial, document library, and knowledge search pages.
