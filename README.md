# Taxonomy: Academic Hierarchy Generation Pipeline

Build and maintain a four‑level academic taxonomy from institutional sources with deterministic pipelines, auditable artifacts, and prompt‑driven extraction.

## Project Overview
- Purpose: generate a reproducible L0→L3 hierarchy (Colleges → Departments → Research Areas → Conference Topics) with explainable decisions.
- Approach: staged S0–S3 pipeline plus post‑processing (validation, enrichment, disambiguation, deduplication) and final hierarchy assembly.
- Design: deterministic where possible (seeds, stable sorts), policy‑driven thresholds, and centralized prompts via the `taxonomy.llm` wrapper.

## Quick Start
- Environment
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -e .[dev]`
- Validate config
  - `python main.py validate --environment development`
- Run the pipeline (with resume)
  - `python main.py run --environment development [--resume-phase S2]`
- Tests, lint, format
  - `pytest [-k s3_token_verification]`
  - `ruff check src tests`
  - `black src tests`

## Architecture Overview
- Phases: S0 Raw Extraction → S1 Extraction & Normalization → S2 Frequency Filtering → S3 Single‑Token Verification → Post‑Processing → Hierarchy Assembly.
- Orchestration: checkpointed, resumable execution with persisted artifacts under `output/runs/<run_id>/` and logs under `logs/`.
- LLM usage: all prompts live under `prompts/` and are executed only via `taxonomy.llm` with deterministic settings (temperature 0, JSON mode).

## Documentation Map
- Functional blueprint (logic spec): `docs/functional-blueprint.md`.
- Detailed module specs: `docs/modules/` (implementation‑agnostic, invariants, acceptance scenarios).
- Per‑module READMEs: colocated with code in `src/taxonomy/**/README.md` (APIs, data contracts, examples).
- Module index and status: `docs/MODULE_INDEX.md`.
- Documentation standards: `docs/DOCUMENTATION_GUIDE.md`.
- Policies and versions: `docs/policies.md`.

## Module Organization
- `src/taxonomy/`
  - `config/` (settings, policy defaults)
  - `orchestration/` (checkpointed runner)
  - `pipeline/` (S0–S3 and post‑processing)
  - `llm/`, `observability/`, `web_mining/`, `utils/` (cross‑cutting)
- Prompts: `prompts/` (registry, schemas, templates)

## Development Workflow
- Keep tests, lint, and formatting green before committing.
- Maintain determinism: honor seeds, limit retries, and log token usage.
- Policy changes: update `docs/policies.md`, bump versions, and reflect deltas in module docs.

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
