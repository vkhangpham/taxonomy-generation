# Orchestration

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
  - `python main.py run --environment development`
  - Resume from a phase: `python main.py run --environment development --resume-phase S2`

Related Docs
- Orchestration phases: `docs/modules/orchestration-phases.md`
- CLI integration: `src/taxonomy/cli/pipeline.py`

