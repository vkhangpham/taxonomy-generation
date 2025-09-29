# CLI Pipeline Integration

This document explains how the CLI maps user commands to pipeline steps and orchestration runs.

## Scope

- `src/taxonomy/cli/pipeline.py`
- Orchestration bridge: `src/taxonomy/orchestration/main.py`

## Commands

- `pipeline generate --step S0` — runs raw extraction.
- `pipeline generate --step S1 --level <0..3>` — runs extraction/normalization for a level.
- `pipeline generate --step S2 --level <0..3>` — runs frequency filtering for a level or consolidated mode when configured.
- `pipeline generate --step S3 --level <0..3>` — runs token verification for a level.
- `pipeline run [--resume-phase S2]` — executes full orchestration with resume.

## Parameters

- Batch size, environment (`--environment development`), resume flags, and test mode map directly to processor configs.

## Output Handling

- Artifacts are written under `output/runs/<run_id>/phase-*/` with logs in `logs/`.
- The run manifest path is printed on success and contains artifact indices.

## Examples

```bash
python main.py validate --environment development
python main.py run --environment development --resume-phase S2
python main.py pipeline generate --step S1 --level 2
```

## Related

- Core pipeline: `docs/modules/pipeline-core-abstractions.md`
- Orchestration phases: `docs/modules/orchestration-phases.md`

