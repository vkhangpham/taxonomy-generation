# Orchestration Phases

This document describes the higher-level orchestration used to drive the S0–S3 pipelines and final hierarchy assembly.

## Scope

- `src/taxonomy/orchestration/phases.py`
- `src/taxonomy/orchestration/main.py`
- `src/taxonomy/orchestration/checkpoints.py`

## Key Classes

- `TaxonomyOrchestrator`: user-facing entry for full runs; prepares context, delegates to `PhaseManager`, and emits run manifests.
- `PhaseManager`: executes ordered phases with resume support and shared `PhaseContext`.
- `PhaseContext`: shared state including configuration, paths, observability, and checkpoint manager.

## Phase Model

0. Raw Extraction (S0)
   - Trigger: `pipeline generate --step S0` (can be run independently before orchestration).
   - Produces: `SourceRecord` JSONL shards under the run’s S0 artifact directory with per-batch metrics.
   - Checkpoint: phase completion marker plus counts; inputs for S1 are the S0 record indexes.
   - Handoff: S1 reads the S0 record index and per-shard paths; contract defined in `docs/modules/s0-raw-extraction-pipeline.md`.

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

## Execution Flow

- `TaxonomyOrchestrator.run()` → `PhaseManager.execute_all(resume_from)`
- Each phase updates `PhaseContext` with produced artifacts and metrics.
- `CheckpointManager` persists phase completion; resume skips completed phases.

## Observability

- Per-phase timing, counters, and token accounting.
- Quarantine and anomaly logs for outliers and policy violations.

## Failure Handling

- Phases must fail-fast with clear diagnostics; partial outputs are quarantined and not advanced.
- Resume continues from the last clean checkpoint.

## Examples

```python
from taxonomy.orchestration.main import TaxonomyOrchestrator

orch = TaxonomyOrchestrator(env="development")
result = orch.run(resume_from=None)
print(result.manifest_path)
```

## Related

- Core abstractions: `docs/modules/pipeline-core-abstractions.md`
- CLI integration: `docs/modules/cli-pipeline-integration.md`
- S0–S3 and assembly:
  - `docs/modules/s0-raw-extraction-pipeline.md`
  - `docs/modules/s1-extraction-normalization-pipeline.md`
  - `docs/modules/s2-frequency-filtering-pipeline.md`
  - `docs/modules/s3-token-verification-pipeline.md`
  - `docs/modules/hierarchy-assembly-pipeline.md`
