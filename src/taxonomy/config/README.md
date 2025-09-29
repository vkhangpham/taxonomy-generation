# Config & Policies — README (Developer Quick Reference)

## Quick Reference

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
- Detailed spec: this README.
- Related: `src/taxonomy/llm`, `src/taxonomy/observability`, `src/taxonomy/web_mining`.

Maintenance
- Validate with `python main.py manage config --validate --environment development` and add tests in `tests/test_config.py`.

## Detailed Specification

### Configuration & Policies — Logic Spec

See also: `docs/logic-spec.md`

Purpose
- Document the centralized settings system and policy modules controlling pipeline behavior and thresholds.

Core Tech
- Pydantic settings layered from env → YAML → defaults (`src/taxonomy/config/settings.py`).
- Policy modules under `src/taxonomy/config/policies/*` provide typed, versioned knobs.

Inputs/Outputs (semantic)
- Input: environment name, env vars (`TAXONOMY_*`), YAML overlays in `config/`, and defaults.
- Output: a merged `Settings` instance plus policy objects; active policy versions stamped into the run manifest.

Rules & Invariants
- Determinism first: temperatures 0.0 by default; seeds fixed.
- All thresholds and regex vocabularies live in policies; business logic reads but does not hardcode.
- Level-specific settings expressed as maps `{level:int -> value}` with normalization for string keys.

Core Logic
- Resolve environment → load defaults → merge YAML overlays → apply env var overrides → construct typed `Settings`.
- Load policy modules, validate internal constraints, and expose version identifiers.
- Provide read‑only access to effective values during a run; surface paths and policy versions in manifest.

Policy Modules (overview)
- validation.py — label policy, single-token verification, rule/web/LLM settings, aggregation.
- identity.py — institution identity handling (campus/system, joint centers, cross‑listing).
- extraction.py — S0/S1 thresholds, language detection, dedup, bounds.
- hierarchy.py — parent level guards, uniqueness, DAG constraints.
- llm.py — provider/profile selection, retry/backoff, JSON/tooling guards.
- web.py — authoritative domains, timeouts, snippet limits.
- thresholds.py — shared numeric thresholds by level.
- observability.py — counters, sampling, log verbosity.
- prompt_optimization.py — search space, validation ratios, strictness.

Algorithms & Parameters
- Enumerated by the modules above; defaults and valid ranges live with each policy class.
- Intentional omission here: concrete numeric defaults remain source‑of‑truth in policy code and `docs/policies.md`.

Observability
- Run manifest contains effective policy versions and key thresholds.
- Token accounting and evidence sampling settings are exposed for audit.

Acceptance Tests
- `main.py validate` loads settings, resolves paths, and emits no errors under `development`.
- Changing a threshold in YAML is reflected in the active `Settings` and stamped into the manifest.

Failure Handling
- Missing/invalid YAML or env values raise configuration errors; no partial runs permitted.
- Policy constraint violations (e.g., invalid level map keys) fail fast during boot.

Open Questions
- Policy pinning semantics when resuming a run from a manifest vs. re‑loading from disk.

Examples
- Minimal environment overlay:
  ```yaml
  environment: development
  paths:
    runs_dir: output/runs
  ```
  Produces a `Settings` instance whose manifest includes `{ "environment": "development" }` and a policy version block.

#### Settings Structure

Top‑Level
- `Settings` (`src/taxonomy/config/settings.py`) — typed container for all config, layered from defaults → YAML overlays → env.
- `PathsConfig` — normalized filesystem layout (runs, logs, prompts, cache); all paths are absolute at runtime.
- `PipelineObservabilityConfig` — sampling rates, verbosity, manifest toggles, and performance counters enablement.

Layering
- YAML overlays in `config/` are merged by environment; env vars override using `TAXONOMY_*` and nested policy overrides via `TAXONOMY_POLICY__<policy>__<field>`.
- Example: `export TAXONOMY_POLICY__llm__retries=1` forces a single retry in development.

Policy Modules (detailed)
- `validation.py` — label canonicalization, single‑token constraints, regex vocabularies, web/LLM validator toggles.
- `identity.py` — campus/system affiliation, joint centers, cross‑listing normalization.
- `extraction.py` — S0/S1 heuristics: language detection, page/record bounds, dedup caps.
- `hierarchy.py` — parent/child level guards, DAG constraints, orphan handling.
- `llm.py` — provider/model profiles, retries/backoff, json/tool modes, token limits.
- `web.py` — authoritative domains, timeouts, snippet size, user‑agent and robots rules.
- `thresholds.py` — shared numeric thresholds per level; consumed by S2 and validators.
- `observability.py` — counter namespaces, evidence sampling rates, log verbosity.
- `prompt_optimization.py` — search space, validation ratios, strictness gates.

Policy Versions & Manifests
- Every policy carries a semantic version; `Settings` exports the active versions into the run manifest (and observability payload).
- When resuming from a checkpoint, the pipeline can pin to manifest‑recorded versions to guarantee reproducibility.

Examples
- Env override for a nested threshold map:
  ```bash
  export TAXONOMY_POLICY__thresholds__L3_min_src=3
  ```
- YAML overlay enabling stricter JSON validation for LLM:
  ```yaml
  policy:
    llm:
      json_mode: true
      retries: 2
  ```

