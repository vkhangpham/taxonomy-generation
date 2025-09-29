# Taxonomy: Academic Hierarchy Generation Pipeline

Build and maintain a four-level academic taxonomy from institutional sources with deterministic pipelines, auditable artifacts, and prompt-driven extraction.

## Project Overview
- Purpose: generate a reproducible L0→L3 hierarchy (Colleges → Departments → Research Areas → Conference Topics) with explainable decisions.
- Approach: staged S0–S3 pipeline plus post-processing (validation, enrichment, disambiguation, deduplication) and final hierarchy assembly.
- Design: deterministic where possible (seeds, stable sorts), policy-driven thresholds, and centralized prompts via the `taxonomy.llm` wrapper.

## Quick Start
- Set up the environment
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -e .[dev]`
- Provide secrets
  - Create a `.env` file in the repository root with provider credentials (for example `OPENAI_API_KEY=...`, `FIRECRAWL_API_KEY=...`).
  - The CLI loads this file automatically, so values become available via `os.environ` and the `TAXONOMY_*` overrides when runs start.
- Validate configuration and paths
  - `python main.py manage config --validate --environment development`
- Run the full pipeline (resume-aware)
  - `python main.py pipeline run --environment development [--resume-phase S2]`
- Execute an individual stage
  - `python main.py pipeline generate --step S1 --level 2 --input <snapshots.jsonl> --output <candidates_dir>`
- Post-process existing concepts
  - `python main.py postprocess validate --mode all --input <concepts.jsonl> --output <validated.jsonl>`
  - `python main.py postprocess deduplicate --input <validated.jsonl> --output <deduped.jsonl>`
  - `python main.py postprocess disambiguate --input <deduped.jsonl> --output <disambiguated.jsonl>`
- Quality gates and tooling
  - `pytest [-k s3_token_verification]`
  - `ruff check src tests`
  - `black src tests`

## CLI Usage
- Global options (apply to all commands)
  - `--environment / -e`: select configuration profile (development/testing/production)
  - `--override / -o KEY=VALUE`: dotted-path overrides applied before execution (repeatable)
  - `--run-id`: reuse or pin an artefact directory under `output/runs/<run_id>/`
  - `--verbose / -v`: print the resolved CLI context table before running
  - `--no-observability`: disable metrics, manifests, and quarantine capture temporarily
- Command groups (full reference lives in `src/taxonomy/cli/README.md`)
  - `pipeline`: `run`, `generate --step {S0|S1|S2|S3}`, optional `--resume-phase`
  - `postprocess`: `validate`, `deduplicate`, `disambiguate`
  - `manage`: `status`, `resume`, `manifest`, `config --validate`
  - `utilities`: `mine-resources`, `optimize-prompt`
  - `dev`: `test`, `debug`, `export`
- Common workflows
  1. Dry-run settings: `python main.py manage config --validate --environment development`
  2. Resume from a checkpoint: `python main.py pipeline run --run-id <id> --resume-phase S2`
  3. Refresh web snapshots then regenerate S0: `python main.py utilities mine-resources ...` → `python main.py pipeline generate --step S0`
  4. Inspect manifests: `python main.py manage manifest --run-id <id> --format yaml`
  5. Optimize prompts: `python main.py utilities optimize-prompt --prompt-key taxonomy.extract --dataset data/train.json --objective f1`

## Documentation Map
- Functional blueprint (system logic): `docs/functional-blueprint.md`
- Run operations guide: `docs/modules/pipeline_run_guide.md`
- Module READMEs (single source of truth for specs and quick reference):
  - `src/taxonomy/cli/README.md`
  - `src/taxonomy/llm/README.md`
  - `src/taxonomy/orchestration/README.md`
  - `src/taxonomy/pipeline/**/README.md` (S0–S3, deduplication, disambiguation, validation, hierarchy assembly)
  - `src/taxonomy/observability/README.md`, `src/taxonomy/web_mining/README.md`, `src/taxonomy/prompt_optimization/README.md`, `src/taxonomy/config/README.md`, `src/taxonomy/entities/README.md`, `src/taxonomy/utils/README.md`
- Module index and maintenance tracker: `docs/MODULE_INDEX.md`
- Documentation standards and style: `docs/DOCUMENTATION_GUIDE.md`
- Policies and thresholds: `docs/policies.md`

## Documentation Maintenance
- Update the relevant module README whenever behavior, thresholds, or contracts change; treat these as canonical specs.
- Record policy/version shifts in `docs/policies.md` and link to affected READMEs.
- Capture notable documentation changes in `CHANGELOG.md` and refresh `docs/MODULE_INDEX.md` status entries.
- Keep examples deterministic and aligned with fixtures; prefer JSON snippets that mirror integration tests.

## Architecture Overview
- Phases: S0 Raw Extraction → S1 Extraction & Normalization → S2 Frequency Filtering → S3 Single-Token Verification → Post-Processing → Hierarchy Assembly.
- Orchestration: checkpointed, resumable execution with persisted artifacts under `output/runs/<run_id>/` and logs under `logs/`.
- LLM usage: all prompts live under `prompts/` and are executed only via `taxonomy.llm` with deterministic settings (temperature 0, JSON mode).

## Module Organization
- `src/taxonomy/`
  - `config/` (settings, policy defaults)
  - `orchestration/` (checkpointed runner)
  - `pipeline/` (S0–S3 and post-processing)
  - `llm/`, `observability/`, `web_mining/`, `utils/` (cross-cutting)
- Prompts: `prompts/` (registry, schemas, templates)

## Development Workflow
- Keep tests, lint, and formatting green before committing.
- Maintain determinism: honor seeds, limit retries, and log token usage.
- Policy changes: update `docs/policies.md`, bump versions, and reflect deltas in module READMEs.

## Key Resources
- Logic blueprint: `docs/functional-blueprint.md`
- Module index: `docs/MODULE_INDEX.md`
- Documentation guide: `docs/DOCUMENTATION_GUIDE.md`
- Policies: `docs/policies.md`
- Changelog: `CHANGELOG.md`

## Contributing
- Use Conventional Commit subjects (e.g., `feat:`, `chore:`) and add context in bodies as needed.
- Link runs/manifests in PRs; attach diffs for prompt or policy updates.
- Request review only after `pytest`, `ruff`, and `black` succeed; note any skipped checks.
