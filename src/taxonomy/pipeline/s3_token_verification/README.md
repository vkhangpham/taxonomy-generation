# S3 · Token Verification

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
- Detailed pipeline: `docs/modules/s3-token-verification-pipeline.md`

