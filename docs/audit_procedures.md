# Level 0 Audit Procedures

This guide documents the end-to-end process for executing a level 0 taxonomy audit in production mode with audit sampling enabled. Follow the steps in order to ensure deterministic runs, comprehensive quality review, and actionable remediation output.

## Prerequisites
- Python 3.11 virtual environment initialised via `python -m venv .venv && source .venv/bin/activate`.
- Project dependencies installed with `pip install -e .[dev]`.
- Production credentials exported in the shell, including `OPENAI_API_KEY` and `FIRECRAWL_API_KEY`.
- `data/Faculty Extraction Report.xlsx` available for the S0 Excel bootstrap, or snapshot JSONL content if opting for web-sourced S0.
- Working directory set to the repository root.

## Execution Steps
1. Validate configuration merges before running the audit:
   ```bash
   source .venv/bin/activate
   python main.py manage config --validate --environment production
   ```
2. Launch the audit-mode pipeline orchestration. The default configuration in `audit_config.yaml` outputs to `output/audit_runs/<run_id>/` and caps each stage at 10 items.
   ```bash
   python -m scripts.audit_level0_run \
     --s0-mode excel \
     --limit 10
   ```
   - Use `--s0-mode snapshots --snapshots-path <path>` to ingest JSONL snapshots instead of Excel.
   - Use `--s0-mode reuse --existing-s0-path <path>` to skip S0 generation when a prior `source_records.jsonl` should be reused.
3. Confirm the run completed successfully by inspecting `output/audit_runs/<run_id>/audit_run_summary.json` and `observability_snapshot.json`.

## Quality Assessment
1. Generate sampling and validation outputs for manual review:
   ```bash
   python -m scripts.audit_quality_checker \
     output/audit_runs/<run_id> \
     --sample-size 10 \
     --seed 20250929
   ```
   This creates `quality_report.json` and `quality_report.md` alongside the run artefacts.
2. Review the Markdown checklist in `quality_report.md`. For each stage:
   - Work through the `- [ ]` checklist items.
   - Inspect the JSON samples provided for anomalies.
   - Record reviewer notes directly beneath the relevant sample or in your run log.
3. Flag any critical issues by opening tracking tickets referencing the run ID and affected stage.

## Timing Analysis
1. Analyse throughput and potential bottlenecks:
   ```bash
   python -m scripts.audit_timing_analyzer \
     output/audit_runs/<run_id> \
     --target-items 1000
   ```
   The script emits `timing_report.json` and `timing_report.md`, detailing stage durations, throughput, and extrapolated performance estimates.
2. Prioritise remediation on stages with low throughput or the highest percentage of total runtime.

## Gap Identification & Remediation Planning
1. Generate the consolidated audit report combining run metadata, quality results, and timing insights:
   ```bash
   python -m scripts.audit_report_generator output/audit_runs/<run_id>
   ```
   Review `audit_report.md` for executive-facing summaries and the ranked recommendation list.
2. Log remediation tasks using the recommendation identifiers (e.g., `REC-01`) to maintain traceability.
3. Update `docs/policies.md` and associated manifests if new issues require policy adjustments.
4. Capture rerun manifests and link them in PR descriptions to demonstrate issue closure.

## Troubleshooting
- **Missing credentials**: The orchestrator checks for required environment variables and exits with a descriptive error. Export the credentials and rerun.
- **Polars import errors during S0 Excel bootstrap**: Install `polars` (`pip install polars`) and rerun the audit. The dependency is required for Excel ingestion.
- **LLM provider timeouts in S3**: Verify production API quotas, then rerun S3 in isolation via `python -m scripts.audit_level0_run --s0-mode reuse --existing-s0-path ...` to avoid repeating earlier stages.
- **Large audit outputs**: Ensure the audit limit remains at 10. If outputs exceed the cap, confirm `audit_mode.enabled` is true in `audit_config.yaml` and rerun the pipeline.

Following this procedure ensures each level 0 audit run is reproducible, thoroughly documented, and ready for downstream remediation work.
