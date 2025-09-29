# CLI — README (Developer Quick Reference)

Purpose
- Typer-based command-line interface to run pipeline phases, utilities, and management tasks with shared state and consistent console output.

Key APIs
- `app`: root Typer application assembled from subcommands.
- `CLIState`: holds `Settings`, `ObservabilityContext`, and common objects.
- `console`: Rich console configured for pretty logging.

Command Groups
- Pipeline: `run`, `resume`, per-phase runners.
- Utilities: data inspection, conversions, exports.
- Management: clean artifacts, generate manifests, validate config.
- Development: debugging helpers; `--environment` switch.
- Postprocess: hierarchy assembly and report generation.

Quick Start
- Examples
  - `python main.py validate --environment development`
  - `python main.py run --environment development [--resume-phase S2]`

State Access
- Commands receive `CLIState` via Typer dependency injection; avoid reloading settings inside commands.

See Also
- Detailed spec: `docs/modules/cli-interfaces.md`.
- Related: `src/taxonomy/pipeline`, `src/taxonomy/orchestration`, `src/taxonomy/observability`.

Maintenance
- Keep command help concise; add integration tests in `tests/test_cli.py` for new commands.

