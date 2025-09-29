# Validation (Rule/Web/LLM) — Logic Spec

Purpose
- Provide complementary validation signals to increase precision and document evidence without leaking into business logic.

Core Tech
- Rule validation: compiled regex/pattern engine and configurable vocabularies.
- Web validation: Firecrawl v2.0 snapshots as the only web evidence source; no ad-hoc fetching.
- LLM validation: DSPy-managed entailment prompts with strict JSON `{pass, reason, confidence?}` responses (legacy `validated` keys are accepted but normalized).

LLM Usage
- LLM checks must go through the LLM package: `llm.run("validation.entailment", {claim, evidence})`.
- Responses must include `{pass: bool, reason: str}`; `validated` remains a backward-compatible alias for `pass`.
- The package resolves the active prompt from disk; inline prompts are prohibited.

Inputs/Outputs (semantic)
- Input: Concepts[] (or high-confidence Candidates)
- Output: ValidationFinding[] and an aggregated pass/fail per concept with rationale

Modes
- Rule: regex/vocabulary/structure checks; hard failures for forbidden patterns; soft warnings for style. Venue detections at L3 remain warnings by default, escalate automatically when the same pattern matches a forbidden rule, and can be forced to hard failures via `rules.venue_detection_hard=true`.
- Web: confirm presence/consistency in authoritative pages (institutional sites, trusted catalogs); capture evidence snippets. Authority lists match both root domains and their subdomains. Snapshot timeouts or an empty index surface `unknown` results that record findings without casting a vote.
- LLM: entailment-style check with strict JSON {pass, reason}; no free-form text.

Aggregation Policy
- Any hard rule failure → FAIL.
- Otherwise weighted vote: Rule > Web > LLM; conservative tie-breaks only flip to PASS when the evidence strength (max of web average snippet score and LLM confidence) meets `aggregation.tie_break_min_strength` (defaulting to the LLM confidence threshold).
- Always record individual findings; expose reasons and evidence in final manifest.
- Web checks marked `unknown` do not contribute weight to the tally.
- Rationale invariants: `passed_gates` always maps non-empty string gate names to booleans. Clearing the final gate (passing `None`) resets the aggregate decision to `None` so consumers can distinguish "not evaluated" from a concrete pass/fail outcome.

Failure Handling
- If web fetch fails repeatedly or the evidence index is empty, mark as unknown (neither pass nor fail) and do not block aggregation.
- If LLM returns invalid JSON, retry with schema reminder; quarantine if repeated.

Observability
- Counters: checked, rule_failed, web_failed, llm_failed, passed_all (legacy `*_passed` counters remain for dashboards).
- Evidence store: sampled snippets and URLs for audit.

Acceptance Tests
- Concepts with forbidden suffixes (e.g., venue names at L3) fail rule checks.
- Concepts supported by authoritative pages pass web validation with captured quotes.

Open Questions
- Which external sources qualify as “authoritative” for web validation beyond institutional domains?

Examples
- Example A: Rule failure (venue at L3)
  - Concept: {level: 3, label: "neurips"}
  - Rule: forbidden_venues → FAIL with detail "venue, not a topic".

- Example B: Web validation pass
  - Concept: {level: 2, label: "computer vision"}
  - Evidence: institutional research page contains exact phrase and description.
  - Finding (web): {passed: true, evidence_url: "https://u4.edu/cs/research", snippet: "Our computer vision group..."}

- Example C: LLM entailment check
  - Input JSON: {claim: "X is a level-2 research area", evidence: "..."}
  - Output JSON: {pass: true, reason: "evidence describes research area within CS"}
