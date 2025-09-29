# Observability — README (Developer Quick Reference)

Purpose
- End-to-end observability for the pipeline: phase-scoped context, counters, evidence sampling, quarantine, determinism helpers, and manifest generation.

Key APIs
- Classes: `ObservabilityContext` — lifecycle manager; enters phases, records metrics/evidence, writes manifests.
- Classes: `PhaseHandle` — context token for a specific pipeline phase; aggregates counters and evidence.
- Classes: `EvidenceSampler` — configurable sampling of records and LLM IO for inspection.
- Classes: `QuarantineManager` — isolates problematic items with reasons and hints for reprocessing.
- Classes: `CounterRegistry` — typed counters and gauges for phases and subsystems.
- Functions: `ObservabilityContext.from_settings(settings)` — build context using policy and path config.
- Functions: `context.phase(name)` — context manager for scoping operations.

Data Contracts
- Phase context: `{name:str, started_at:datetime, counters:dict, evidence:list, quarantine:list}`.
- Evidence item: `{kind:str, payload:dict, sample:bool, checksum:str}`.
- Quarantine item: `{id:str, reason:str, payload:dict, retryable:bool}`.
- Snapshot/manifest: materialized JSON with deterministic checksums and policy/version stamps.

Quick Start
- Usage sketch
  - `from taxonomy.observability.context import ObservabilityContext`
  - `ctx = ObservabilityContext.from_settings(settings)`
  - `with ctx.phase("s1_extraction_normalization") as ph:`
  - `    ph.counters.inc("records_in", n)`
  - `    ph.evidence.sample({"text": raw_text, "label": label})`
  - `    ph.quarantine.add(item_id, reason="invalid_lang", payload=rec)`

Determinism & Manifest
- Deterministic utilities ensure stable ordering and hashing; manifests capture settings, policies, prompt versions, and token accounting per phase.

Configuration
- Controlled via `settings.observability.*` and relevant policies; see `src/taxonomy/config/settings.py` and `docs/policies.md`.

Dependencies
- Internal: `taxonomy.config`, `taxonomy.llm` (for LLM counters), pipeline phases.
- External: none at runtime beyond stdlib/logging helpers.

See Also
- Detailed spec: `docs/modules/observability-reproducibility.md`.
- Related: `src/taxonomy/pipeline`, `src/taxonomy/orchestration`, `src/taxonomy/llm`.

Maintenance
- Update counters/fields together with tests: `tests/test_observability.py`, `tests/test_observability_manifest.py`.

