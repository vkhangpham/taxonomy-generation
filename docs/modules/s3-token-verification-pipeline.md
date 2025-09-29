# S3 Token Verification Pipeline

This document specifies the multi-stage verification of candidate tokens for validity, appropriateness, and semantic correctness.

## Scope

- `src/taxonomy/pipeline/s3_token_verification/processor.py`
- `src/taxonomy/pipeline/s3_token_verification/main.py`
- `src/taxonomy/pipeline/s3_token_verification/verifier.py`

## Components

- Rule validator: applies policy rules (ASCII canonical form, single-token preference, blacklist checks).
- LLM verifier: deterministic LLM call to assess semantic validity and assign confidence.
- Verification processor: coordinates stages and emits verified concepts with reasons.

## Data Flow

`Candidate` → rule checks → LLM verification → `Concept` (verified)

## Observability

- Confidence distributions, rule hit rates, and token usage metrics.

## CLI

- `pipeline generate --step S3 --level <0..3>`
- Entry: `verify_tokens()` in `main.py`.

## Example

```json
{
  "token": "python",
  "level": 1,
  "confidence": 0.94,
  "reasons": ["passes-rules", "llm-positive"]
}
```

## Contracts

- Deterministic prompts and seeds; retries limited and logged.
- Rule failures must provide explicit, machine-readable reasons.

