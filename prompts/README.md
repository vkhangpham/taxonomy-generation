# Prompts Registry — README (Developer Quick Reference)

Purpose
- Central source of truth for prompt metadata, templates, and JSON schemas used by `taxonomy.llm`. Supports versioning and optimization history.

Layout
- `registry.yaml` — maps prompt keys to versions, templates, and schemas.
- `templates/` — Jinja2 prompt templates organized by task.
- `schemas/` — JSON Schemas for LLM outputs enforced by `JSONValidator`.

Data Contracts
- Registry entry: `{key: {active_version, versions: {<ver>: {template, schema, notes?}}}}`.
- Template variables: documented per key; LLM client passes a `variables` dict for rendering.
- Schema: strict output shape; compact JSON only (no chain-of-thought).

Usage
- Business code calls `LLMClient.run(<key>, variables)`; the client resolves the active version from `registry.yaml`.
- Optimized variants update `registry.yaml` via the prompt optimization module.

Versioning
- Use semantic or date-based versions; keep `notes` for lineage. Changing defaults requires a policy bump and docs update.

See Also
- LLM details: `docs/modules/llm.md`.
- Optimization: `src/taxonomy/prompt_optimization`.

Maintenance
- When adding/updating prompts: update template and schema together, adjust registry entry, and add tests touching `tests/test_llm.py` and any task-specific validations.

