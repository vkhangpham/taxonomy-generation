# Pipeline Core Abstractions

This document specifies the core pipeline abstractions used across the taxonomy system. It focuses on the lightweight orchestrator pattern, the step protocol, and how checkpointing and resume semantics integrate with sequential execution.

## Scope

- Runtime: `src/taxonomy/pipeline/__init__.py`
- Checkpoint integration: `src/taxonomy/orchestration/checkpoints.py`

## Concepts

- `PipelineStep` (protocol): a unit of deterministic work with `name`, `run(ctx) -> StepResult`, and optional `resume(ctx) -> StepResult`.
- `Pipeline`: executes a list of `PipelineStep` instances in order, persisting step boundaries through the checkpoint manager.
- `StepResult`: dataclass-like structure capturing outputs, metrics, warnings, and next-step hints.
- `CheckpointManager`: provides idempotent boundaries for step completion and supports resuming from the last successful step.

## Execution Semantics

- Steps run sequentially; a step starts only after the prior step has committed its checkpoint.
- On failure, the pipeline stops and records the failure with context in step metrics.
- On resume, the pipeline consults the `CheckpointManager` to skip any previously completed steps and continues from the first incomplete step.

## Error Handling

- Steps must raise typed exceptions for irrecoverable conditions; transient issues are surfaced via `StepResult.warnings` and retried by the enclosing orchestrator when configured.
- All exceptions are annotated with step name and minimal repro metadata for later analysis.

## Observability

- Each step logs: start/stop timestamps, input/output counts, token usage (when applicable), and derived metrics.
- The pipeline aggregates step metrics and emits a run manifest at completion.

## Example: Defining and Running a Pipeline

```python
from taxonomy.pipeline import Pipeline, PipelineStep

class FetchStep(PipelineStep):
    name = "fetch"
    def run(self, ctx):
        items = ctx.source.read()
        ctx.checkpoints.save_step(self.name, count=len(items))
        return {"items": items}

class ProcessStep(PipelineStep):
    name = "process"
    def run(self, ctx):
        items = ctx.prev["items"]
        outputs = [x for x in items if x]
        ctx.checkpoints.save_step(self.name, produced=len(outputs))
        return {"outputs": outputs}

pipe = Pipeline([FetchStep(), ProcessStep()])
result = pipe.run(ctx)
```

## Checkpoint Integration

- Steps call `CheckpointManager.save_step(step_name, **metadata)` after producing durable artifacts.
- `Pipeline.run()` reads `CheckpointManager.completed_steps()` and skips those steps when `ctx.resume=True`.
- Step outputs are written to phase-scoped artifact directories for reproducibility.

## Contracts

- Inputs and outputs must be serializable (JSON or parquet where applicable).
- Steps are deterministic under fixed seed and configuration; concurrency must not reorder output semantics.

## Related

- Orchestration phases: `docs/modules/orchestration-phases.md`
- CLI integration: `docs/modules/cli-pipeline-integration.md`

