# LLM Integration — Logic Spec

See also: `docs/logic-spec.md`, `docs/DOCUMENTATION_GUIDE.md`

Purpose
- Provide a provider-agnostic interface for structured, deterministic LLM calls used by extraction, verification, disambiguation, and validation prompts.

Core Tech
- DSPy as the orchestration layer for declarative prompt components and deterministic runs.
- Provider-agnostic transport (pluggable), configured via DSPy; registry-driven prompts.
- Strict JSON or tool/grammar modes when available to enforce structure.

Principles
- Single prompt registry as the source of truth; no inline prompts in business logic.
- Deterministic by default (temperature=0.0 or equivalent); stable ordering in outputs.
- Strict JSON outputs; never request or store chain-of-thought/rationales beyond compact reasons.
- Clear separation between rendering (prompt + variables) and transport (provider call).

Package Contract (LLM Package)
- All LLM usage MUST go through the project LLM package (the wrapper around DSPy). Business logic never calls providers directly.
- The package exposes a small DSPy-aligned API surface so it plugs into prompt optimization seamlessly and runs with zero reconfiguration:
  - run(prompt_key, variables, options?) -> Result
  - load_prompt(prompt_key) -> {version, path, metadata}
  - set_profile(profile_name) -> None  # selects provider/model/limits
  - active_version(prompt_key) -> str   # returns currently selected optimized variant
- Prompts are resolved from disk (registry + templates); the package refuses free-form prompt strings.
- Optimized prompts produced by the optimization module are saved to disk with version tags; the LLM package auto-resolves the active variant based on policy (e.g., profile or registry flag).

Prompt Storage & Resolution
- On-disk registry (YAML) maps prompt_key to template path(s), metadata, and active version.
- The LLM package reads the registry at runtime; hot-reload optional but not required.
- No inline definitions are allowed; any attempt to pass custom prompt text should be rejected or logged as a misuse.

Prohibited Patterns
- Passing raw prompt strings from business logic.
- Hardcoding provider/model settings outside the LLM package.
- Modifying prompts in memory without persisting to disk with a version.

Inputs/Outputs (semantic)
- Input: {prompt_key, variables, options{temperature?, max_tokens?, seed?, stop?, provider_hint?}}
- Output: {ok: bool, content: string|object, tokens_in: int, tokens_out: int, latency_ms: int, meta{provider, model, prompt_version}, error?}

Tasks Covered
- S1 extraction: produces arrays of candidate objects.
- S3 verification: returns {pass: bool, reason} for minimal-label checks.
- Disambiguation: returns sense splits with short glosses.
- Validation (LLM mode): entailment yes/no with brief reason.

Rules & Invariants
- JSON schema enforcement: validate output; if invalid, perform at most R retries with a constrained re-ask that repeats the schema and a minimal example.
- No free-form prose: require the model to output only JSON; reject extra text.
- Token accounting: record tokens_in/out and attach to run manifest.
- Redaction: do not log full sensitive inputs; keep hashes/snippets for debugging.

Core Logic
- Render: load template by prompt_key and fill variables; include explicit schema and ordering instructions.
- Call: send to provider with deterministic options; prefer tools/JSON mode when available.
- Repair: if invalid JSON, try: (1) strip/non-JSON content → parse; (2) constrained re-ask; (3) quarantine.
- Ordering: for list outputs, require sort by normalized label (case-insensitive) to ensure stable diffs.

Failure Handling
- Provider errors (429/5xx): exponential backoff and limited retries; record last status.
- Timeouts: cancel and retry once with increased timeout; if repeated, quarantine item.
- Partial outputs: treat as failure unless JSON is valid and complete by schema.

Observability
- Counters: calls_total, ok, invalid_json, retries, quarantined.
- Performance: avg latency, p95 latency, tokens_in/out totals.
- Versions: prompt_version and model identifier per call for audit.

Acceptance Tests
- Given fixed inputs and seed, list outputs are identically ordered across runs.
- Invalid JSON triggers one constrained re-ask and then quarantines; manifests record the retry path.
- Verification prompts return compact JSON and never include chain-of-thought.

Examples
- Example A: Extraction call
  - Input:
    ```json
    {
      "prompt_key": "taxonomy.extract",
      "variables": {
        "institution": "u2",
        "level": 2,
        "text": "Our research areas include computer vision, robotics, and NLP."
      },
      "options": {"temperature": 0.0, "max_tokens": 300}
    }
    ```
  - Expected output (JSON array, sorted by normalized):
    ```json
    [
      {"label": "computer vision", "normalized": "computer vision", "aliases": ["cv"]},
      {"label": "nlp", "normalized": "nlp", "aliases": ["natural language processing"]},
      {"label": "robotics", "normalized": "robotics"}
    ]
    ```

- Example B: Verification call
  - Input:
    ```json
    {
      "prompt_key": "taxonomy.verify_single_token",
      "variables": {"label": "Machine-Learning", "level": 2},
      "options": {"temperature": 0.0}
    }
    ```
  - Expected output:
    ```json
    {"pass": false, "reason": "contains hyphen; use 'machine learning'"}
    ```

- Example C: Invalid JSON then constrained re-ask
  - First response: "Candidates: computer vision, robotics" (invalid)
  - Repair step: re-ask with schema reminder → valid JSON array as in Example A.

Usage Note
- Business modules call: llm.run("taxonomy.extract", {...}) and let the package resolve the optimized on-disk prompt; they never embed or construct the template inline.

Open Questions
- Preferred provider JSON/grammar mode for maximum determinism?
- Should we support provider failover or keep a single provider for reproducibility?
- Hard cap on retries per batch to bound latency?

## Architecture Overview

Components
- LLMClient (`src/taxonomy/llm/client.py`)
  - Single entry point: deterministic execution, options normalization, token accounting, and error mapping.
  - Public API: `run(prompt_key, variables, options=None)`, `load_prompt(prompt_key)`, `set_profile(profile)`, `active_version(prompt_key)`.
- PromptRegistry (`src/taxonomy/llm/registry.py`)
  - Loads `prompts/registry.yaml`, resolves active version and template path, supports optional hot‑reload.
  - Exposes metadata for manifests: `{key, version, template_path, schema_path}`.
- ProviderManager (`src/taxonomy/llm/providers.py`)
  - Thin DSPy‑backed adapter that configures provider/model, timeouts, and retry/backoff per policy.
  - Supports provider failover when enabled by policy; otherwise pinned for reproducibility.
- JSONValidator (`src/taxonomy/llm/validation.py`)
  - Enforces schema (JSON mode or post‑parse), applies repair heuristics, and returns typed errors.
- MetricsCollector (`src/taxonomy/llm/observability.py`)
  - Emits counters, latency, and token usage to `ObservabilityContext` with per‑prompt attribution.

Deterministic Defaults
- `temperature=0.0`, `top_p=1.0`, fixed `seed` (when supported), sorted list outputs.
- Output must be JSON‑only; extra text is rejected before validation.

## Config & Policy Integration

Sources
- Settings (`src/taxonomy/config/settings.py`) selects the active LLM profile and paths.
- LLM policy (`src/taxonomy/config/policies/llm.py`) declares: provider/model, max tokens, retries, backoff, JSON/tool modes, and failover strategy.

Behavior
- `LLMClient.set_profile(profile)` pins a `(provider, model)` tuple and option caps from policy.
- Prompt versions from the registry and the active profile are stamped into the run manifest via observability.

## Prompt Resolution & Versioning

Flow
1. `LLMClient.run(key, vars)` → `PromptRegistry.resolve(key)`.
2. Registry returns `{template, schema, version}`; template rendered with variables.
3. ProviderManager executes with deterministic options; response validated against schema.
4. MetricsCollector records `{model, prompt_version, tokens_in/out, latency_ms}`.

Hot‑Reload (optional)
- When enabled, registry re‑reads `prompts/registry.yaml` on change; otherwise, it is loaded once at startup for reproducibility.

Example: Registry Entry (abbrev.)
```yaml
schema_version: 1
prompts:
  taxonomy.extract:
    active: v3
    versions:
      v3:
        template: prompts/templates/extraction.jinja2
        schema: prompts/schemas/extraction.json
```

## Provider Configuration Examples

Select Profile (Python)
```python
from taxonomy.llm.client import LLMClient

llm = LLMClient.from_settings(settings)
llm.set_profile("default")  # pins provider/model from policy
result = llm.run("taxonomy.extract", {"institution": "u2", "level": 2, "text": doc})
```

Policy Snippet (conceptual)
```python
LLMPolicy(
  profile="default",
  provider="openai",
  model="gpt-4o-mini",
  retries=2,
  backoff_ms=(200, 800),
  json_mode=True,
  temperature=0.0,
)
```

## Error Handling & Repair Path

Categories
- Transport errors (429/5xx): bounded retries with exponential backoff; final failure quarantined.
- Invalid JSON: try parse‑strip → constrained re‑ask → quarantine with evidence payload.
- Schema mismatch: emit `invalid_schema` with field errors; no free‑form fallbacks.

Evidence Payload (quarantine)
```json
{
  "prompt_key": "taxonomy.extract",
  "version": "v3",
  "provider": "openai:gpt-4o-mini",
  "error": "invalid_json",
  "attempts": 2,
  "sample": "Candidates: computer vision, robotics"
}
```

## Observability Integration

Counters
- `llm.calls_total`, `llm.ok`, `llm.invalid_json`, `llm.retries`, `llm.quarantined`.

Performance
- Per‑call latency and tokens_in/out; aggregated in manifest by prompt key and model.

Manifest Fields
- `prompts[{key}] = version`, `models[{key}] = model_id`, `llm.tokens = {in, out}`.

## Contract Examples

Extraction
```python
result = llm.run("taxonomy.extract", {"institution": "u2", "level": 2, "text": text})
assert result.ok and isinstance(result.content, list)
```

Verification
```python
res = llm.run("taxonomy.verify_single_token", {"label": label, "level": 2})
assert res.content == {"pass": True, "reason": ""}
```
