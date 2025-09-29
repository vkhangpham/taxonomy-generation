# Configuration & Policies — Logic Spec

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
