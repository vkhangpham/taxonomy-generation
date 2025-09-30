# S3 · Token Verification

## Quick Reference

Purpose
- Verify candidate tokens using rule‑based checks and LLM verification to ensure quality.

Key Classes
- `S3Processor`: Coordinates multi‑stage verification.
- `TokenRuleEngine`: Applies deterministic rules and policy checks.
- `LLMTokenVerifier`: Performs structured LLM validation in JSON mode.
- `TokenVerificationSuite`: Aggregates results, scores confidence, and flags issues.

Data Contract
- `Candidate` → verified `Candidate` (+ confidence, evidence, decisions).

Workflow Highlights
- Rule evaluation, LLM verification, confidence scoring, and decision recording.

CLI
- Run verification: `python main.py pipeline generate --step S3 --level <N>`

Related Docs
- Detailed pipeline: this README

## Detailed Specification

### Single‑Token Verification (S3) — Logic Spec

Purpose
- Guard single-token labels to ensure they denote legitimate research fields/terms; multi-token labels (token_count > 1) bypass LLM verification and pass automatically after basic rule checks.

Core Tech
- Rule engine for token/character policy checks.
- DSPy-managed verification prompt returning compact JSON {pass, reason} (invoked only for single-token terms when deterministic rules fail).

LLM Usage
- Use the LLM package only: `llm.run("taxonomy.verify_single_token", {label, level})`.
- The active optimized prompt is resolved from disk; do not embed prompt text.

Inputs/Outputs (semantic)
- Input: Candidate[] after frequency filtering
- Output: Candidate[] with pass/fail gate results, possibly with suggested minimal alternatives in aliases

Policy
- Guard only single-token terms (token_count == 1) via LLM verification.
- Multi-token terms (token_count > 1) bypass LLM and pass automatically after basic rule checks; rationale records "bypass:multi_token".
- For single-token terms: prefer alphanumeric labels without punctuation; reject generic organizational tokens ("department", "program") and branding tokens.
- Maintain an allowlist for known exceptions (e.g., "computer vision", "machine learning"); record justification in rationale.
- Maintain a configurable set of venue names/aliases that must be rejected at L3.

Gate Order
1) Token count check: if token_count > 1, bypass LLM and pass automatically (rationale: "bypass:multi_token").
2) Rule checks (single-token only): forbidden punctuation, low alnum ratio, venue names (keywords + alias set).
3) LLM verification (single-token only): yes/no JSON {pass: bool, reason: string} with level-aware criteria, only invoked when rules fail and allowlist does not apply.

Failure Handling
- If rules fail, propose deterministic minimal alternative (strip punctuation, collapse tokens, standard shortenings).
- If LLM disagrees with rules, log discrepancy; prefer strictest outcome (AND of rules/LLM) unless allowlist applies.
- When final decision passes, append accepted suggestions to candidate aliases (deduped + normalized) for downstream auditing.

Observability
- Counters: checked, passed_rule, failed_rule, passed_llm, failed_llm, allowlist_hits, llm_called (note: multi-token bypasses increment passed_rule but not llm_called).
- Drift: distribution of token counts by level.

Acceptance Tests
- Labels with internal punctuation are rejected unless in allowlist.
- Known exceptions at L2/L3 pass with rationale recorded.

Open Questions
- Exact tokenization method (unicode words vs. whitespace).
- Should hyphenated compounds be treated as single tokens?

Examples
- Example A0: Multi-token bypass
  - Input label: "computer vision"
  - Token count: 2
  - Rule outcome: bypass (token_count > 1). Rationale: "bypass:multi_token".
  - LLM outcome: not called (bypassed).
  - Final decision: pass.

- Example A: Single-token with suggestion
  - Input label: "machine-learning" (normalized to "machine learning" → 2 tokens, but if hyphen policy treats as single: 1 token)
  - Token count: 1 (if hyphenated compounds not allowed)
  - Rule outcome: fail (forbidden hyphen). Suggested: "machinelearning" or abbreviation "ml".
  - LLM outcome: pass for "ml" at L2 when abbreviation is acceptable; record rationale and add "machine learning" as alias.

- Example B: Multi-token allowlisted term
  - Input label: "computer vision"
  - Token count: 2
  - Rule outcome: bypass (token_count > 1). Rationale: "bypass:multi_token".
  - LLM outcome: not called (bypassed).
  - Note: Even though it's on the allowlist, the multi-token bypass takes precedence.

- Example C: Reject venue names at L3
  - Input label: "neurips"
  - Rule outcome: fail (forbidden venue at L3). No LLM call needed.

### S3 Token Verification Pipeline

This document specifies the multi-stage verification of candidate tokens for validity, appropriateness, and semantic correctness.

#### Scope

- `src/taxonomy/pipeline/s3_token_verification/processor.py`
- `src/taxonomy/pipeline/s3_token_verification/main.py`
- `src/taxonomy/pipeline/s3_token_verification/verifier.py`

#### Components

- Rule validator: applies policy rules (ASCII canonical form, single-token preference, blacklist checks).
- LLM verifier: deterministic LLM call to assess semantic validity and assign confidence.
- Verification processor: coordinates stages and emits verified concepts with reasons.

#### Data Flow

`Candidate` → rule checks → LLM verification → `Concept` (verified)

#### Observability

- Confidence distributions, rule hit rates, and token usage metrics.

#### CLI

- `pipeline generate --step S3 --level <0..3>`
- Entry: `verify_tokens()` in `main.py`.

#### Example

```json
{
  "token": "python",
  "level": 1,
  "confidence": 0.94,
  "reasons": ["passes-rules", "llm-positive"]
}
```

#### Contracts

- Deterministic prompts and seeds; retries limited and logged.
- Rule failures must provide explicit, machine-readable reasons.
