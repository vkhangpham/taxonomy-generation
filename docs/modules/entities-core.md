# Entities (Domain) — Logic Spec

See also: `docs/logic-spec.md`

Purpose
- Specify semantic contracts for core domain entities and their lifecycle across S0–S3.

Core Tech
- Pydantic models with validators for canonicalization and invariants.

Entities (semantic)
- Provenance — origin of a source snippet `{institution, url?, section?, fetched_at}`.
- SourceMeta — page-level metadata (language, charset, hints).
- SourceRecord — extracted text block with `{text, provenance, meta}`.
- Candidate — normalized label proposal with aliases/evidence.
- Concept — deduplicated, validated unit with level and parent links.
- ValidationFinding — per-signal result `{passed, reason, evidence?}`.
- MergeOp/SplitOp — consolidation edits with rationale and provenance.

Rules & Invariants
- URLs normalized (scheme+host lowercased, no fragment); invalid schemes rejected.
- `Concept` carries stable id, normalized label, level in [0..3], and parent constraints enforced by hierarchy assembly.
- Provenance timestamps are UTC; evidence text snippets are length‑bounded by policy.

Lifecycle Through Pipeline
- S0 produces `SourceRecord[]` with normalized provenance and meta.
- S1 converts records to `Candidate[]` with normalized labels and alias bundles.
- S2 filters/aggregates with frequency/support thresholds, yielding high‑confidence candidates.
- S3 verifies single‑token/label policy compliance and upgrades to `Concept[]` on pass.
- Consolidation applies `MergeOp`/`SplitOp` to reconcile duplicates and disambiguations.

Observability
- Entities stamped into manifests with counts and level distributions; evidence sampling rate controlled by policy.

Examples
- Candidate → Concept promotion:
  ```json
  {"label":"computer vision","aliases":["cv"],"level":2}
  ```
  becomes
  ```json
  {"id":"cv","label":"computer vision","level":2,"parents":["ml"]}
  ```

