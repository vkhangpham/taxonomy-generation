# Validation (Rule/Web/LLM) — Logic Spec

Purpose
- Provide complementary validation signals to increase precision and document evidence without leaking into business logic.

Core Tech
- Rule validation: compiled regex/pattern engine and configurable vocabularies.
- Web validation: Firecrawl v2.0 snapshots as the only web evidence source; no ad-hoc fetching.
- LLM validation: DSPy-managed entailment prompts with strict JSON returns.

LLM Usage
- LLM checks must go through the LLM package: `llm.run("validation.entailment", {claim, evidence})`.
- The package resolves the active prompt from disk; inline prompts are prohibited.

Inputs/Outputs (semantic)
- Input: Concepts[] (or high-confidence Candidates)
- Output: ValidationFinding[] and an aggregated pass/fail per concept with rationale

Modes
- Rule: regex/vocabulary/structure checks; hard failures for forbidden patterns; soft warnings for style.
- Web: confirm presence/consistency in authoritative pages (institutional sites, trusted catalogs); capture evidence snippets.
- LLM: entailment-style check with strict JSON {pass, reason}; no free-form text.

Aggregation Policy
- Any hard rule failure → FAIL.
- Otherwise weighted vote: Rule > Web > LLM; ties break toward conservative (fail) unless evidence strong.
- Always record individual findings; expose reasons and evidence in final manifest.

Failure Handling
- If web fetch fails repeatedly, mark as unknown (neither pass nor fail) and do not block aggregation.
- If LLM returns invalid JSON, retry with schema reminder; quarantine if repeated.

Observability
- Counters: checked, rule_failed, web_failed, llm_failed, passed_all.
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
