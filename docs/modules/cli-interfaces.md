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

Rules & Invariants
- Commands are deterministic given the same inputs and environment; no hidden global state.
- Exit codes: `0` success, non‑zero for failures; errors are logged and surfaced to the console.

Core Logic
- Parse args via Typer → construct `Settings` → dispatch to orchestration or utility handlers.
- For `run`, optionally resolve `--resume-phase` to start index and execute remaining phases.
- Ensure logs and manifests paths exist before executing side‑effecting actions.

Algorithms & Parameters
- Not algorithm‑heavy; parameters are forwarded to orchestration and policies.
- Intentional omission: concrete timeouts and concurrency settings are governed by policies or environment configuration.

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

Failure Handling
- Invalid arguments produce usage errors with non‑zero exit code.
- Exceptions during execution are caught at the CLI boundary, logged with context, and result in a non‑zero exit code.

Acceptance Tests
- `validate` exits with code `0` on a healthy configuration; non‑existent environment yields non‑zero.
- `run --resume-phase S2` executes only S2→S3→finalization and preserves earlier artifacts.

Open Questions
- Should CLI support manifest‑based replays with pinned policies vs. current environment state?
