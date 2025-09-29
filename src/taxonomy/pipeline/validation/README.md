# Validation

Purpose
- Validate candidates for correctness and appropriateness via rules, LLM, and web evidence.

Key Classes
- `ValidationProcessor`: Runs the multi‑stage validation workflow.
- `RuleEngine`: Deterministic policy checks with clear failure codes.
- `LLMValidator`: Structured LLM validation with JSON outputs.
- `WebValidator`: Performs targeted lookups to collect evidence.

Data Contract
- `Candidate` → validated `Candidate` (+ findings, evidence bundle).

Workflow Highlights
- Rule checks → LLM validation → web evidence triage; results logged and reproducible.

Related Docs
- Detailed pipeline: `docs/modules/validation.md`

