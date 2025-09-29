# CLI Interfaces — Logic Spec

See also: `docs/modules/pipeline-orchestration.md`, `docs/logic-spec.md`

Purpose
- Document commands for running the pipeline, management utilities, development helpers, and post‑processing.

Core Tech
- Typer-based CLI split across `src/taxonomy/cli/*` modules; main entry under `cli/main.py`.

Command Groups
- Main — `taxonomy.cli.main:app` is the root app; supports global options and error handling.
- Pipeline — run/validate/resume operations mapped to orchestration entry points.
- Management — data and cache management, artifact inspection.
- Utilities — helper commands for ad‑hoc tasks that remain deterministic.
- Development — local workflows: dry‑runs, fixture generation, verbose logging.
- Postprocess — final cleanup and export tasks.

Inputs/Outputs (semantic)
- Input: environment selection, overrides, and command‑specific args.
- Output: status logs, counters, and paths to artifacts; exit codes reflect success/failure.

Examples
- Validate settings only:
  ```bash
  python main.py validate --environment development
  ```
- Run pipeline from S0:
  ```bash
  python main.py run --environment development
  ```
- Resume from S2:
  ```bash
  python main.py run --environment development --resume-phase S2
  ```

Observability
- Each command logs to `logs/` and updates run manifests when executing phases.

