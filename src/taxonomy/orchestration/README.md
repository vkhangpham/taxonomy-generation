# Orchestration

## Quick Reference

Purpose
- Coordinate the full taxonomy lifecycle across phases with checkpoints, manifests, and resume.

Key Classes
- `TaxonomyOrchestrator`: Runs all phases, aggregates results, and emits a run manifest.
- `PhaseManager`: Encapsulates phase boundaries and execution order.
- `PhaseContext`: Shared state across phases (paths, config, seeds, counters).
- `CheckpointManager`: Reads/writes phase checkpoints for reliable resume.
- `RunManifest`: Structured record of inputs, outputs, and policy versions.

Execution Model
- Five‑phase workflow executing S0–S3 plus post‑processing/finalization.
- Each phase validates preconditions, runs step pipelines, and records outputs.

Resume & Checkpoints
- Phases are idempotent where possible; resume picks up from the last incomplete phase using manifests.

CLI Integration
- `pipeline run` delegates into the orchestrator for end‑to‑end execution.

Examples
- Run the full pipeline with development settings:
  - `python main.py pipeline run --environment development`
  - Resume from a phase: `python main.py pipeline run --environment development --resume-phase S2`

Related Docs
- Orchestration phases: this README
- CLI integration: `src/taxonomy/cli/pipeline.py`

## Detailed Specification

### Pipeline & Orchestration — Logic Spec

See also: `docs/logic-spec.md`, `src/taxonomy/pipeline/validation/README.md`
Cross‑references:
- Core abstractions — `src/taxonomy/pipeline/README.md`
- Phases & orchestrator — `src/taxonomy/orchestration/README.md`
- CLI integration — `src/taxonomy/cli/README.md`
- Stage specs — `src/taxonomy/pipeline/s0_raw_extraction/README.md`, `src/taxonomy/pipeline/s1_extraction_normalization/README.md`, `src/taxonomy/pipeline/s2_frequency_filtering/README.md`, `src/taxonomy/pipeline/s3_token_verification/README.md`, `src/taxonomy/pipeline/hierarchy_assembly/README.md`

Purpose
- Define the `Pipeline`/`PipelineStep` abstractions and orchestrate S0–S3 plus final assembly.
- Manage checkpoints and resume semantics with deterministic execution and manifest emission.

Core Tech
- `Pipeline` + `PipelineStep` in `src/taxonomy/pipeline/__init__.py`.
- Orchestration in `src/taxonomy/orchestration/` with `TaxonomyOrchestrator`, `PhaseManager`, and `PhaseContext`.
- Checkpoints via `CheckpointManager` with artifacts under `output/runs/<run_id>/` and logs in `logs/`.

Inputs/Outputs (semantic)
- Input: Settings + policies; optional `resume_phase` token.
- Output: Run manifest with per‑phase summaries, counters, artifacts paths, and policy/version stamps.

Rules & Invariants
- Phase ordering: levelwise generation (S1 L0→L3), consolidation (S2), post‑processing (S3), finalization (assembly). S0 is runnable independently for raw extraction.
- Resume semantics: `resume_phase=X` executes X and subsequent phases; earlier phases remain intact unless forced.
- Determinism: respect seeds, fixed ordering, and stable serialization to ensure reproducible manifests.
- Checkpoints: each phase writes artifacts to a phase‑scoped directory and updates the run manifest atomically.

Core Logic
- `TaxonomyOrchestrator.run()` prepares `PhaseContext`, then `PhaseManager.execute_all(resume_from)` runs ordered phases with resume.
- Within phases, `Pipeline` executes concrete `PipelineStep`s (see core abstractions doc) and records step checkpoints.
- Levelwise generation runs S1 for L0→L3 with per‑level summaries; consolidation aggregates frequency; post‑processing verifies tokens; finalization assembles the hierarchy and emits the run manifest.

Algorithms & Parameters
- Parameterization comes from policies in `src/taxonomy/config/policies/*` and `Settings`.
- Defaults and thresholds live with the policy classes; the orchestrator stamps policy versions into the manifest.

Failure Handling
- Step failure quarantines the phase outputs and records error context in the run manifest; subsequent phases are skipped.
- Idempotent re‑runs: resuming after a failure restarts from the failed step; earlier successful phases are not recomputed unless forced.

Observability
- Counters: per‑phase `ok`, `failed`, `duration_sec`; aggregate token usage if LLM is invoked downstream.
- Artifacts: paths to phase outputs, consolidated files, and final manifests in `output/runs/<run_id>/`.
- Logs: structured log file path exposed via `Settings.paths.logs_dir`.

CLI Mapping
- See `src/taxonomy/cli/README.md` for comprehensive command mapping and examples.

Acceptance Tests
- `python main.py manage config --validate --environment development` verifies configuration loads and merges without running steps.
- Resuming from `S2` executes `S2`, `S3`, and finalization only; earlier artifacts are preserved and referenced.
- Run manifests include per‑phase summaries, durations, and policy versions.

Open Questions
- Policy pinning vs. floating: when resuming, should policies be reloaded from disk or pinned from the original run manifest?

Examples
- CLI: `python main.py pipeline run --environment development --resume-phase S2`
  - Expected: executes S2→S3→finalization; updates manifest with new timestamps and summaries.

### Orchestration Phases

This document describes the higher-level orchestration used to drive the S0–S3 pipelines and final hierarchy assembly.

#### Scope

- `src/taxonomy/orchestration/phases.py`
- `src/taxonomy/orchestration/main.py`
- `src/taxonomy/orchestration/checkpoints.py`

#### Key Classes

- `TaxonomyOrchestrator`: user-facing entry for full runs; prepares context, delegates to `PhaseManager`, and emits run manifests.
- `PhaseManager`: executes ordered phases with resume support and shared `PhaseContext`.
- `PhaseContext`: shared state including configuration, paths, observability, and checkpoint manager.

#### Phase Model

0. Raw Extraction (S0)
   - Trigger: `pipeline generate --step S0` (can be run independently before orchestration).
   - Produces: `SourceRecord` JSONL shards under the run’s S0 artifact directory with per-batch metrics.
   - Checkpoint: phase completion marker plus counts; inputs for S1 are the S0 record indexes.
   - Handoff: S1 reads the S0 record index and per-shard paths; contract defined in `src/taxonomy/pipeline/s0_raw_extraction/README.md`.

1. Levelwise Generation (S1 for levels 0–3)
   - Extract and normalize candidates per level.
   - Saves level checkpoints and stats.
2. Consolidation (S2)
   - Frequency aggregation and threshold-based filtering across levels.
3. Post-Processing (S3)
   - Rule- and LLM-backed token verification; emits verified concepts.
4. Resume Management
   - Determines last successful phase and continues execution idempotently.
5. Finalization
   - Hierarchy assembly and validation; emits result manifest and indexes.

#### Execution Flow

- `TaxonomyOrchestrator.run()` → `PhaseManager.execute_all(resume_from)`
- Each phase updates `PhaseContext` with produced artifacts and metrics.
- `CheckpointManager` persists phase completion; resume skips completed phases.

#### Observability

- Per-phase timing, counters, and token accounting.
- Quarantine and anomaly logs for outliers and policy violations.

#### Failure Handling

- Phases must fail-fast with clear diagnostics; partial outputs are quarantined and not advanced.
- Resume continues from the last clean checkpoint.

#### Examples

```python
from taxonomy.orchestration.main import TaxonomyOrchestrator

orch = TaxonomyOrchestrator(env="development")
result = orch.run(resume_from=None)
print(result.manifest_path)
```

#### Related

- Core abstractions: `src/taxonomy/pipeline/README.md`
- CLI integration: `src/taxonomy/cli/README.md`
- S0–S3 and assembly:
  - `src/taxonomy/pipeline/s0_raw_extraction/README.md`
  - `src/taxonomy/pipeline/s1_extraction_normalization/README.md`
  - `src/taxonomy/pipeline/s2_frequency_filtering/README.md`
  - `src/taxonomy/pipeline/s3_token_verification/README.md`
  - `src/taxonomy/pipeline/hierarchy_assembly/README.md`

