# Config & Policies — README (Developer Quick Reference)

Purpose
- Layered configuration (YAML + env) with policy modules that govern behavior across the pipeline: LLM, extraction, validation, observability, paths.

Key APIs
- Classes: `Settings` — main entry; merges config files and env overrides; exposes typed sub-configs.
- Classes: `Policies` — container for policy modules (e.g., LLM, extraction, validation).
- Classes: `PathsConfig` — normalized project paths for inputs, outputs, logs, prompts.
- Classes: `PipelineObservabilityConfig` — sampling, manifest, and counter options.
- Functions: `Settings.load(environment:str)` — resolve layered settings for the given environment.

Data Contracts
- Settings hierarchy: project → environment → overrides via `TAXONOMY_SETTINGS__*`.
- Policies: typed structures per domain (provider/model, thresholds, retries, limits) with defaults.

Quick Start
- Instantiate
  - `from taxonomy.config.settings import Settings`
  - `settings = Settings.load(environment="development")`
  - `model = settings.policies.llm.model`
  - `output_dir = settings.paths.runs`

Configuration
- Files: YAML configs merged in order; `Settings` documents precedence.
- Env overrides: `TAXONOMY_SETTINGS__POLICIES__LLM__MODEL=gpt-4o-mini` style.
- Policy changes must update `docs/policies.md` and bump version; manifests include policy version.

Dependencies
- Internal: consumed by all major modules (LLM, pipeline, observability, web mining).
- External: `pydantic`, `pydantic-settings`, `pyyaml`.

Observability
- Emits policy and settings fingerprints to run manifests via `observability`.

Determinism
- Stable path resolution and environment pinning; seeds and retry budgets are policy-bound.

See Also
- Detailed spec: `docs/modules/config-policies.md`.
- Related: `src/taxonomy/llm`, `src/taxonomy/observability`, `src/taxonomy/web_mining`.

Maintenance
- Validate with `python main.py validate --environment development` and add tests in `tests/test_config.py`.

