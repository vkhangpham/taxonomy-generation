# Single‑Token Verification (S3) — Logic Spec

Purpose
- Enforce minimal canonical labels for downstream use, while allowing justified exceptions.

Core Tech
- Rule engine for token/character policy checks.
- DSPy-managed verification prompt returning compact JSON {pass, reason}.

LLM Usage
- Use the LLM package only: `llm.run("taxonomy.verify_single_token", {label, level})`.
- The active optimized prompt is resolved from disk; do not embed prompt text.

Inputs/Outputs (semantic)
- Input: Candidate[] after frequency filtering
- Output: Candidate[] with pass/fail gate results, possibly with suggested minimal alternatives in aliases

Policy
- Prefer single-token, alphanumeric labels without punctuation.
- Allow multi-word when abbreviation would materially reduce clarity (e.g., "computer vision").
- Maintain an allowlist for known exceptions; record justification in rationale.

Gate Order
1) Rule checks: forbidden punctuation, token count > N, low alnum ratio.
2) LLM verification: yes/no JSON {pass: bool, reason: string} with level-aware criteria.

Failure Handling
- If rules fail, propose deterministic minimal alternative (strip punctuation, collapse tokens, standard shortenings).
- If LLM disagrees with rules, log discrepancy; prefer stricter outcome unless allowlist applies.

Observability
- Counters: checked, passed_rule, failed_rule, passed_llm, failed_llm, allowlist_hits.
- Drift: distribution of token counts by level.

Acceptance Tests
- Labels with internal punctuation are rejected unless in allowlist.
- Known exceptions at L2/L3 pass with rationale recorded.

Open Questions
- Exact tokenization method (unicode words vs. whitespace).
- Should hyphenated compounds be treated as single tokens?

Examples
- Example A: Suggest minimal alternative
  - Input label: "Machine-Learning"
  - Rule outcome: fail (forbidden hyphen). Suggested: "machine learning" or abbreviation "ml".
  - LLM outcome: pass for "machine learning" at L2 when abbreviation harms clarity; record rationale and add "ml" as alias.

- Example B: Allowlisted multi‑word
  - Input label: "computer vision"
  - Rule outcome: flagged (two tokens) → check allowlist.
  - LLM outcome: pass with reason "standard field name; abbreviation reduces clarity".

- Example C: Reject venue names at L3
  - Input label: "neurips"
  - Rule outcome: fail (forbidden venue at L3). No LLM call needed.
