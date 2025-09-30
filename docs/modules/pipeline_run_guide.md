# Taxonomy Run Guide

## Purpose
- Provide an operator-facing walkthrough for executing the taxonomy pipeline end-to-end.
- Document required inputs, CLI invocations, expected artifacts, and validation touch points.

## Audience
- Engineers and analysts running scheduled taxonomy refreshes.
- Developers onboarding to the pipeline and post-processing subsystems.

## Prerequisites
- Python 3.11 virtual environment (`python -m venv .venv && source .venv/bin/activate`).
- Project dependencies installed (`pip install -e .[dev]`).
- Secrets exported via environment variables or `.env` (e.g., `OPENAI_API_KEY`, `FIRECRAWL_API_KEY`).
- Access to source snapshots for S0 extraction (JSONL files or web mining credentials).

## Directory Layout
- Run artifacts: `output/runs/<run_id>/` (phase outputs, manifests, checkpoints).
- Logs: `logs/<run_id>/` with structured run logs.
- Quarantine/observability data: nested under the run directory when enabled.
- Prompts: `prompts/` (registry and templates) – reference only; do not edit in runbooks.

## Step-by-Step Pipeline Execution

### 1. Validate Configuration
- Ensure config merges before long executions:
  ```bash
  python main.py manage config --validate --environment development
  ```
- Use overrides for ad-hoc changes: `--override policies.deduplication.min_similarity_threshold=0.82`.

### 2. Prepare Input Snapshots (S0)
- If web mining is required, refresh materialized snapshots:
  ```bash
  python main.py utilities mine-resources --output data/snapshots --provider firecrawl
  ```
- Alternatively, confirm an existing JSONL snapshot file is available for S0.

### 3. Full Pipeline Run (S0 → Assembly)
- Execute the orchestrated pipeline; a run ID is generated if not provided:
  ```bash
  python main.py pipeline run --environment development [--run-id 20240901-dev]
  ```
- The orchestrator checkpoints after each phase, emits artifacts under `output/runs/<run_id>/`, and writes `run_manifest.json` summarizing outputs.
- Audit runs: enable `audit_mode.enabled` in `config/default.yaml` (or the active environment file) to cap every stage at the configured audit `limit` (10 by default) for quick inspection.
- To resume after a partial failure, pass `--resume-phase <phase_token>` using the tokens listed in **Resume Phase Tokens**.
- **S3 Token Verification**: As of policy version 0.5, S3 guards only single-token terms via LLM. Multi-token terms (token_count > 1) bypass LLM verification and pass automatically after basic rule checks. This ensures that only potentially ambiguous single-token labels (e.g., "ai", "ml", "biology") undergo semantic validation, while descriptive multi-token labels (e.g., "computer vision", "machine learning") pass through efficiently.

### 4. Inspect Manifests and Artifacts
- View the manifest table to locate emitted files:
  ```bash
  python main.py manage manifest --run-id <run_id> --format table
  ```
- The manifest includes pointers to S0–S3 artifacts, post-processing results, and the assembled hierarchy report.

### Resume Phase Tokens
- `phase1_level0` — Level 0 candidate generation (S1 L0).
- `phase1_level1` — Level 1 candidate generation (S1 L1).
- `phase1_level2` — Level 2 candidate generation (S1 L2).
- `phase1_level3` — Level 3 candidate generation (S1 L3).
- `phase2_consolidation` — Frequency aggregation and filtering (S2).
- `phase3_post_processing` — Token verification loop (S3).
- `phase4_resume` — Resume bookkeeping; rarely rerun directly.
- `phase5_finalization` — Hierarchy assembly and manifest emission.

### 5. Execute Individual Generation Stages (Optional)
- Run a single pipeline step when iterating on logic:
  ```bash
  # S0 raw extraction
  python main.py pipeline generate --step S0 --input data/snapshots.jsonl --output output/s0/

  # S1 candidate extraction (requires level and prior output)
  python main.py pipeline generate --step S1 --level 1 --input output/s0/raw.jsonl --output output/s1/
  ```
- Apply `--audit-mode` (optionally with `--audit-limit <n>`) to limit the invoked stage to the configured number of records when triaging issues.
- Use `--resume-from <checkpoint_dir>` for long-running S1 aggregations.
- Batch sizing: `--batch-size N` (clamped to 32 in `--test-mode`).

Output schema notes
- S1 JSONL wraps each candidate with support details required by S2:
  - `{"candidate": <Candidate>, "institutions": [..], "record_fingerprints": [..]}`
  - Bare candidate fields are unchanged; additional arrays carry exact institution identities and deduplicated record fingerprints used during S2 aggregation.
  - This removes prior `placeholder::unknown` artifacts when evidence lacked institutions in serialized form.

### 6. Post-Processing Workflow
- **Validation** – policy, LLM, and web evidence gates:
  ```bash
  python main.py postprocess validate --input output/s3/concepts.jsonl \
      --output output/validated.jsonl --mode all --snapshot data/snapshots.jsonl
  ```
- **Deduplication** – merge near-duplicate concepts:
  ```bash
  python main.py postprocess deduplicate --input output/validated.jsonl \
      --output output/deduped.jsonl --merge-ops output/dedup_merge_ops.jsonl
  ```
- Override thresholds or similarity weights via CLI flags (`--threshold`, `--similarity-method`).
- **Disambiguation** – resolve multi-parent collisions and ambiguous labels:
  ```bash
  python main.py postprocess disambiguate --input output/deduped.jsonl \
      --output output/disambiguated.jsonl --contexts data/context_features.jsonl
  ```

### 7. Hierarchy Assembly & Delivery
- The orchestrated run invokes hierarchy assembly automatically after post-processing.
- To rebuild the hierarchy without rerunning generation, reuse the same run ID and resume finalization:
  ```bash
  python main.py pipeline run --run-id <existing_run> --resume-phase phase5_finalization
  ```
- Final deliverables:
  - `run_manifest.json` – canonical manifest of artifacts and metrics.
  - `hierarchy/graph.json` (and related reports) under `output/runs/<run_id>/final/`.

## Operational Tips
- Always run `pytest`, `ruff check`, and `black` before committing changes that alter behavior.
- Maintain determinism: avoid changing seeds unless intentionally regenerating baselines.
- Observe token usage via logs when LLM prompts are involved; keep `--no-observability` disabled for production runs.
- Clean large temporary artifacts before publishing results; keep manifests and audit trails.

## Troubleshooting & Resume
- Use `python main.py manage status --run-id <run_id>` to inspect checkpoint progress.
- If a phase fails, fix the root cause and rerun with `pipeline run --resume-phase <phase_token>` (see **Resume Phase Tokens**).
- When adjusting policies mid-run, update `docs/policies.md` and bump the policy version before re-executing.

## Reference
- CLI details: `src/taxonomy/cli/README.md`
- Pipeline step specs: `src/taxonomy/pipeline/**/README.md`
- Orchestration design: `src/taxonomy/orchestration/README.md`
- Observability contract: `src/taxonomy/observability/README.md`
