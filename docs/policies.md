# Global Policies — Thresholds, Rules, and Tech Defaults

Policy version: 0.1 (draft). This file centralizes level-wise thresholds, label policies, identity mapping, web domain rules, and deterministic LLM/optimization settings. It is implementation-agnostic and binding for re-implementation.

## Levels and Thresholds
- Level 0 (Colleges/Schools)
  - min_institutions: 1
  - min_src_count: 1
  - notes: names vary widely; lenient thresholds.
- Level 1 (Departments)
  - min_institutions: 1
  - min_src_count: 1
  - notes: accept institutional wording differences; rely on normalization/aliases.
- Level 2 (Research Areas)
  - min_institutions: 2
  - min_src_count: 1
  - notes: cross-institution presence required; frequency filtering applies.
- Level 3 (Conference Topics)
  - min_institutions: 2
  - min_src_count: 3
  - notes: stricter to prevent overfitting to single programs or labs.

Weight (for ranking only): weight = 1.0*inst_count + 0.3*log(1+src_count).

Change control: any threshold change increments this policy version and must be recorded in the run manifest.

## Label Policy (Minimal Canonical Form)
- Token minimality: prefer a single alphanumeric token. Multi-word allowed only when abbreviation reduces clarity (e.g., "computer vision").
- Punctuation: forbid internal punctuation for canonical label; hyphens converted to spaces; underscores removed.
- Case: lowercased for comparison; display case may be stored separately.
- Diacritics: fold to ASCII for comparison; preserve originals as aliases.
- Boilerplate removal (L1): strip leading "department of", "school of", etc.; keep originals as aliases.
- Length bounds: 2 ≤ len(normalized) ≤ 64; otherwise reject or shorten with rationale.
- Venue/brand blocklist at L3: disallow conference/journal names as topics (e.g., neurips, icml, cvpr, nature).

Examples
- "Machine-Learning" → canonical: "machine learning"; alias includes "ml".
- "Department of Computer Science" (L1) → canonical: "computer science"; alias includes original.

## Institution Identity Policy
- Distinct institutions: separate campuses with unique governance count as distinct (e.g., ucb vs ucd).
- Systems vs campuses: map system-level pages to constituent campuses when unambiguous; otherwise treat as separate sources but not distinct institutions for threshold purposes.
- Joint centers/consortia: count once per member institution if each hosts its own page; otherwise count as one institution.
- Cross-listed departments: allowed to have multiple L1 parents only if policy exception is explicitly recorded; prefer single parent.

Examples
- "UC System" overview page does not increase inst_count; "UC Berkeley" and "UC Davis" departmental pages do.

## Web Domains and Crawl Rules
- Allowed domains: institutional base domain + explicitly whitelisted subdomains (e.g., cs.example.edu, eecs.example.edu, labs.example.edu when approved).
- Disallowed paths: /login, /search, session-id URLs, query-only pages producing identical content.
- Robots: always respect robots.txt; do not fetch disallowed paths.
- Dynamic content: enable rendering only when initial HTML is insufficient (empty main content).
- PDFs: allow text extraction for PDFs ≤ max_pdf_mb (default 10 MB) from allowed domains.
- TTL (cache): default 14 days; re-fetch after TTL or on explicit refresh.

Firecrawl v2.0 defaults (policy targets)
- concurrency: 4–8 (respect provider quotas)
- max_depth: 3 (override per institution as needed)
- max_pages: 300 per institution (soft limit)
- render_timeout_ms: 8000–12000 depending on site
- snapshot_format: html + extracted text

## LLM Determinism (DSPy)
- Orchestration: DSPy-managed prompts; all prompt text comes from a central registry with version tags.
- Deterministic settings: temperature=0.0, nucleus_top_p=1.0, no sampling-dependent randomness when supported.
- Grammar/JSON mode: require strict JSON outputs; reject any non-JSON tokens.
- Retries: at most 1 constrained re-ask on invalid JSON; then quarantine.
- Seeds: set a global seed for reproducibility when provider supports it; record in manifests.
- Token budgets: cap max_tokens per task; record tokens_in/out and latency.
- No chain-of-thought: never request long rationales; verification returns only {pass, reason}.

LLM Package Policy
- All LLM calls MUST go through the project LLM package (DSPy-backed wrapper). Business modules cannot call providers directly.
- The LLM package loads prompts from disk (registry + templates) and selects the active optimized variant.
- Inline prompt strings are prohibited. Any new or edited prompt must be saved to disk with a version and referenced by prompt_key.
- Default provider/model profiles are configured once in the LLM package; downstream modules require no reconfiguration.

## Prompt Optimization (DSPy + GEPA)
- Objective: maximize F1 on extraction (primary), subject to guardrails: JSON validity ≥ 99.5%, schema adherence 100%.
- Secondary criteria: latency and token cost; use as tie-breakers within ±0.5% F1.
- Search levers: few-shot K, constraint wording, example ordering seed, temperature ∈ {0.0, 0.2}.
- Protocol: stratified train/dev split; early stopping on no improvement; max_trials default 48 per prompt key.
- Promotion rule: only promote variants that pass guardrails and do not violate label/hierarchy policies.

## Dedup/Disambiguation Policies
- Dedup thresholds: τ(L0,L1)=0.93; τ(L2,L3)=0.90 for similarity score s = max(Jaro–Winkler, token Jaccard, AbbrevScore).
- Edge addition techniques: abbreviation matches, phonetic buckets, prefix/suffix heuristics as documented in the dedup module.
- Parent-context guard: do not merge across incompatible parent contexts; route to disambiguation.
- Disambiguation: prefer split into senses when context features are separable; otherwise keep single concept and document ambiguity.

## Observability & Change Management
- Every run emits a manifest including: policy_version, prompt versions, thresholds, seeds, counters, and sampled evidence.
- Any change to thresholds, label policy, identity mapping, or guardrails increments policy_version and must be noted in CHANGELOG or manifest.

## Version Pinning Policy (Tech)
- Firecrawl: pin to v2.x exact minor in lockfile; record in run manifest (provider, version).
- DSPy: pin exact release; record in run manifest (or git SHA if unreleased).
- GEPA: pin release or commit; record alongside DSPy settings.
- General rule: avoid "latest"; prefer explicit versions for reproducibility.
