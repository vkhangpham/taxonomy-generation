# Taxonomy Audit Procedures (Multi-Level)

This guide documents the end-to-end process for executing a taxonomy audit at any level (0-3) in production mode with audit sampling enabled. Follow the steps in order to ensure deterministic runs, comprehensive quality review, and actionable remediation output.

## Prerequisites
- Python 3.11 virtual environment initialised via `python -m venv .venv && source .venv/bin/activate`.
- Project dependencies installed with `pip install -e .[dev]`.
- Production credentials exported in the shell, including `OPENAI_API_KEY` and `FIRECRAWL_API_KEY`.
- `data/Faculty Extraction Report.xlsx` available for level 0 S0 Excel bootstrap, or snapshot JSONL content for levels 1-3 or web-sourced level 0.
- Working directory set to the repository root.

## Execution Steps
1. Validate configuration merges before running the audit:
   ```bash
   source .venv/bin/activate
   python main.py manage config --validate --environment production
   ```
2. Launch the audit-mode pipeline orchestration. The default configuration in `audit_config.yaml` outputs to `output/audit_runs/<run_id>/` and caps each stage at the configured audit `limit` (10 by default).
  ```bash
  # Level 0 audit (top-level research fields from academic units)
  python -m scripts.audit_level0_run \
     --level 0 \
     --s0-mode excel \
     --limit 10

  # Level 1 audit (departments/divisions)
  python -m scripts.audit_level0_run \
     --level 1 \
     --s0-mode snapshots \
     --snapshots-path data/snapshots/level1_snapshots.jsonl \
     --limit 10

  # Level 2 audit (research areas)
  python -m scripts.audit_level0_run \
     --level 2 \
     --s0-mode reuse \
     --existing-s0-path output/runs/run_20250929/S0/source_records.jsonl \
     --limit 10
  ```
  - **Level selection**: Use `--level 0|1|2|3` to specify the taxonomy level to audit.
  - **S0 source modes**:
    - `--s0-mode excel`: Only available for level 0; bootstraps from `data/Faculty Extraction Report.xlsx`.
    - `--s0-mode snapshots --snapshots-path <path>`: Ingest JSONL snapshots from web mining (available for all levels).
    - `--s0-mode reuse --existing-s0-path <path>`: Skip S0 generation and reuse a prior `source_records.jsonl` (available for all levels).
  - **Important**: Levels 1-3 require `--s0-mode=snapshots` or `--s0-mode=reuse`; Excel bootstrap is only supported for level 0.
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
   - **Level-specific validation**: Verify that extracted concepts match the expected granularity for the audited level (e.g., level 0 should emit research fields like "communication", "medicine"; level 1 should emit departments; level 2 should emit research areas).
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
- **Excel mode not supported for level 1-3**: If you see "--s0-mode=excel is only supported for level 0", use `--s0-mode=snapshots` with `--snapshots-path` or `--s0-mode=reuse` with `--existing-s0-path` instead. Excel bootstrap is only available for level 0.
- **LLM provider timeouts in S3**: Verify production API quotas, then rerun S3 in isolation via `python -m scripts.audit_level0_run --level <matching-level> --s0-mode reuse --existing-s0-path ...` to avoid repeating earlier stages. Ensure `--level` matches the audit run you are recovering so downstream stages stay aligned.
- **Large audit outputs**: Ensure the audit limit matches expectations. If outputs exceed the cap, confirm both `audit_mode.enabled` and `audit_mode.limit` are set correctly in `audit_config.yaml`, or pass `--limit <n>` when invoking the script, then rerun the pipeline.

Following this procedure ensures each audit run (at any level) is reproducible, thoroughly documented, and ready for downstream remediation work.
