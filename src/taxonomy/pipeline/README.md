# Pipeline Core

Purpose
- Provide lightweight primitives to compose sequential S0–S3 steps with deterministic IO, checkpointing, and resume.

Key Classes
- `Pipeline`: Executes a list of `PipelineStep` instances with shared context and error handling.
- `PipelineStep` (protocol): Contract for step modules (S0–S3) to implement `run(context)` and emit artifacts.

Data Flow
- Input/outputs are plain dataclasses and file artifacts; each step reads prior artifacts and writes its own outputs and logs.
- Steps are ordered and checkpointed so runs can resume mid‑sequence without recomputation.

CLI Integration
- The CLI layer dispatches to concrete S0–S3 modules while reusing the `Pipeline` façade for consistent UX (`pipeline generate`, `pipeline run`).

Configuration
- All settings are resolved via `taxonomy.config` and injected into the pipeline context at construction.
- Determinism: LLM calls funnel through `taxonomy.llm` with temperature 0 and JSON mode.

Checkpoints & Resume
- Each step writes a checkpoint manifest with paths to emitted artifacts.
- On resume, `Pipeline` skips completed steps whose outputs are present and valid.

Example: Implement a Step
```python
from typing import Protocol
from taxonomy.pipeline import Pipeline, PipelineStep

class MyStep(PipelineStep):
    name = "Sx_example"
    def run(self, context) -> None:
        # read inputs from context, write artifacts, update context
        context.logger.info("running Sx")

pipeline = Pipeline(steps=[MyStep()])
pipeline.run(context)
```

Related Docs
- Detailed abstractions: `docs/modules/pipeline-core-abstractions.md`
- CLI entry points: `src/taxonomy/cli/pipeline.py`

