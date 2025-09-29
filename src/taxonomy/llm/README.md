# LLM Package — README (Developer Quick Reference)

Purpose
- Abstractions over DSPy for deterministic, observable LLM calls across the taxonomy pipeline. Centralizes prompt resolution, provider configuration, JSON validation, retries, and metrics.

Key APIs
- Classes: `LLMClient` — high-level entry point to run prompts; manages profiles, provider selection, validation, retries, and observability.
- Classes: `PromptRegistry` — loads `prompts/registry.yaml`, resolves active version and template/schema paths.
- Classes: `ProviderManager` — configures DSPy/OpenAI drivers per policy (model, timeouts, backoff).
- Classes: `JSONValidator` — enforces JSON schema and safe repair of minor violations.
- Classes: `MetricsCollector` — emits counters and attaches prompt/provider metadata to the run manifest.
- Functions: `LLMClient.from_settings(settings)` — build a client from layered configuration.
- Functions: `LLMClient.run(key: str, variables: dict) -> dict` — render template, call provider, validate JSON, and return structured output.

Data Contracts
- Input: `LLMRequest = { key: str, variables: dict[str, Any] }` where `key` maps to a registry entry and `variables` supply Jinja2 template fields.
- Output: `LLMResponse = { data: dict, tokens: {in:int, out:int}, meta: {provider:str, model:str, prompt_version:str} }` with schema guaranteed by `JSONValidator`.
- Errors: raises typed exceptions for unrecoverable provider errors; invalid JSON triggers bounded repair attempts then quarantine.

Quick Start
- Instantiate and call
  - `from taxonomy.config.settings import Settings`
  - `from taxonomy.llm.client import LLMClient`
  - `settings = Settings.load(environment="development")`
  - `llm = LLMClient.from_settings(settings)`
  - `res = llm.run("taxonomy.extract", {"institution": "u2", "level": 2, "text": doc})`

Configuration
- Policies: provider/model, max tokens, retries/backoff, JSON mode — see `src/taxonomy/config/policies/llm.py` and `docs/policies.md`.
- Settings: active profile, paths to prompts, registry hot‑reload, and observability flags — see `src/taxonomy/config/settings.py`.

Dependencies
- Internal: `taxonomy.config`, `taxonomy.observability`, `prompts/` (templates, schemas, registry).
- External: DSPy, OpenAI SDK, Jinja2, jsonschema.

Observability
- Counters: `llm.calls_total`, `llm.ok`, `llm.invalid_json`, `llm.retries`, `llm.quarantined`.
- Manifest: records `{prompt_key, prompt_version, provider, model, tokens}` per call and aggregates totals per phase.

Determinism & Retry
- Temperature 0 and JSON mode enforced. Limited, policy‑bound retries with exponential backoff; seed and profile pinning ensure reproducibility.

See Also
- Detailed logic spec: `docs/modules/llm.md`.
- Related: `prompts/` (registry, templates, schemas), `src/taxonomy/prompt_optimization` (optimized variants), `src/taxonomy/observability` (metrics/manifest).

Maintenance
- Update checklist: bump policy when changing defaults; update `docs/policies.md`; add/adjust tests under `tests/test_llm.py` and validation tests.

