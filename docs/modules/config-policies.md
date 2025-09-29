# Configuration & Policies — Logic Spec

See also: `docs/logic-spec.md`

Purpose
- Document the centralized settings system and policy modules controlling pipeline behavior and thresholds.

Core Tech
- Pydantic settings layered from env → YAML → defaults (`src/taxonomy/config/settings.py`).
- Policy modules under `src/taxonomy/config/policies/*` provide typed, versioned knobs.

Configuration Hierarchy
- Environment selection via `--environment` and `TAXONOMY_` env vars.
- YAML overlays in `config/` merged with defaults; paths resolved and created on boot.
- Policy version surfaced in run manifests; updates must bump `docs/policies.md`.

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

Rules & Invariants
- Determinism first: temperatures 0.0 by default; seeds fixed.
- All thresholds and regex vocabularies live in policies; business logic reads but does not hardcode.
- Level-specific settings expressed as maps `{level:int -> value}` with normalization for string keys.

Observability
- Run manifest contains effective policy versions and key thresholds.
- Token accounting and evidence sampling settings are exposed for audit.

Acceptance Tests
- `main.py validate` loads settings, resolves paths, and emits no errors under `development`.
- Changing a threshold in YAML is reflected in the active `Settings` and stamped into the manifest.

