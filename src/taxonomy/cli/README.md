# CLI — README (Developer Quick Reference)

## Quick Reference

### Purpose
- Typer-based entry point to run pipeline phases, supporting utilities, and management tooling with a shared configuration state and observability hooks.

### Global Options
- `--environment` / `-e`: Select configuration profile (development, testing, production). Defaults to project settings if omitted.
- `--override` / `-o` `KEY=VALUE`: Apply dotted-path configuration overrides before command execution; repeatable.
- `--run-id`: Force a run identifier for pipeline and post-processing jobs to group artefacts.
- `--verbose` / `-v`: Print resolved CLI context (environment, run-id, observability state) before running the subcommand.
- `--no-observability`: Disable metrics, manifests, and quarantine capture for the invocation (use sparingly).

### Command Reference
| Group | Command | Description |
| --- | --- | --- |
| pipeline | `pipeline run [--resume-phase S2]` | Execute full S0→S3 orchestration with optional checkpoint resume. |
| pipeline | `pipeline generate --step Sx` | Run a single stage (S0–S3) against explicit input/output paths. |
| manage | `manage status` | List checkpoints recorded for a run. |
| manage | `manage resume` | Resume orchestration for an existing run id. |
| manage | `manage manifest --format {json|yaml}` | Render the stored run manifest. |
| manage | `manage config [--validate]` | Show resolved settings and optionally validate paths. |
| postprocess | `postprocess validate` | Apply rule/web/LLM validation to pipeline concepts. |
| postprocess | `postprocess deduplicate` | Merge near-duplicate concepts with optional threshold overrides. |
| postprocess | `postprocess disambiguate` | Split ambiguous concepts using LLM-assisted analysis. |
| utilities | `utilities mine-resources` | Crawl institutional sites with cache-aware web mining. |
| utilities | `utilities optimize-prompt` | Run one-time DSPy-based prompt optimization workflow. |
| dev | `dev test` | Invoke pytest with optional level and coverage filters. |
| dev | `dev debug` | Inspect observability snapshots (quarantine, validation metrics). |
| dev | `dev export` | Convert concept JSONL into JSON or CSV exports. |

### Pipeline Commands
- `pipeline run [--resume-phase Sx]`: Dispatches to `taxonomy.orchestration.run_taxonomy_pipeline`. Use resume when checkpoints already exist.
- `pipeline generate --step {S0|S1|S2|S3}`:
  - `--input/-i`: Path to upstream artefact (snapshots, candidates, frequency data, or tokens).
  - `--output/-o`: Destination directory or file; created if missing.
  - `--level/-l`: Required for S1–S3 to choose hierarchy level.
  - `--resume-from`: Resume checkpoint for S1 candidate aggregation.
  - `--batch-size`: Tune streaming batch size (auto-capped at 32 in `--test-mode`).
  - `--test-mode`: Apply lighter settings for smoke tests.

### Postprocess Commands
- `postprocess validate --mode {rule|web|llm|all}` with optional `--snapshot` evidence inputs. Emits decision summary table.
- `postprocess deduplicate` parameters:
  - `--threshold`: Override minimum similarity (0.0–1.0).
  - `--similarity-method`: Focus on `jaro-winkler`, `jaccard`, or `abbrev-score` weighting.
  - `--level`: Restrict merges to a hierarchy level.
  - `--merge-ops` / `--metadata`: Persist detailed merge logs.
- `postprocess disambiguate` parameters:
  - `--contexts`: Supplemental context features JSONL.
  - `--context-features`: Cap retained contexts per parent (positive integer).

### Management Commands
- `manage status --run-id RUN`: Lists checkpoints saved to `output/runs/<run>/`.
- `manage resume --run-id RUN [--from-phase Sx]`: Replays orchestration using stored checkpoints.
- `manage manifest --run-id RUN [--format yaml]`: Pretty-print the manifest (JSON or YAML).
- `manage config [--validate]`: Show resolved settings JSON and optionally verify directories.

### Utility Commands
- `utilities mine-resources`: Requires `--institution`, one or more `--seed-url`, and `--allowed-domain`; accepts crawl tuning (`--max-pages`, `--ttl-days`).
- `utilities optimize-prompt`: Provide `--prompt-key` and dataset path; optional `--objective`, `--max-trials`, and `--no-deploy` to inspect results without activating them.

### Development Commands
- `dev test [--level N] [--coverage]`: Passes remaining args directly to pytest.
- `dev debug [--quarantine] [--validation-failures]`: Dumps observability aggregates when available.
- `dev export --source data.jsonl --output data.csv --format csv [--level N]`: Filter and reformat concept dumps.

### Common Workflows
1. **Dry-run configuration**: `python main.py manage config --validate --environment development`.
2. **Full pipeline execution**: `python main.py pipeline run --environment development --run-id run_2025_09_29`.
3. **Resume from checkpoint**: `python main.py pipeline run --environment development --run-id run_2025_09_29 --resume-phase S2`.
4. **Post-process an existing run**: `python main.py postprocess validate --input output/runs/.../concepts.jsonl --mode all` followed by `deduplicate` and `disambiguate`.
5. **Optimize a prompt**: `python main.py utilities optimize-prompt --prompt-key taxonomy.extract --dataset data/train.json --objective f1 --max-trials 30`.

### Error Handling & Troubleshooting
- CLI raises `CLIError` for validation issues (missing files, invalid flags); messages print without stack traces.
- Typer usage errors exit with code `2`; rerun with `--verbose` for additional context table.
- Missing configuration paths can be fixed via `manage config --validate` or by passing overrides (e.g. `-o paths.output_dir=/tmp/output`).
- Pipeline-specific failures emit run manifests and logs under `logs/`; inspect `output/runs/<run_id>/` for checkpoint context.

### Integration Examples
- Combine `pipeline generate --step S0` followed by `pipeline generate --step S1 --level 2` to debug individual stages before a full run.
- Use `utilities mine-resources` to refresh web snapshots, then rerun `pipeline generate --step S0` with the refreshed artefacts.
- Chain `postprocess deduplicate` → `postprocess disambiguate` → `manage manifest --run-id ... --format yaml` to inspect final hierarchy health.
- Run `dev debug --quarantine` immediately after pipeline completion to verify no records require manual review.

## Detailed Specification

### CLI Interfaces — Logic Spec

See also: `src/taxonomy/orchestration/README.md`, `docs/logic-spec.md`

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
  python main.py manage config --validate --environment development
  ```
- Run pipeline from S0:
  ```bash
  python main.py pipeline run --environment development
  ```
- Resume from S2:
  ```bash
  python main.py pipeline run --environment development --resume-phase S2
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

