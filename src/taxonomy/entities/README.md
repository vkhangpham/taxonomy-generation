# Entities — README (Developer Quick Reference)

## Quick Reference

Purpose
- Core domain entities and operations that flow through S0–S3 and post‑processing: source records, candidates, concepts, provenance, support stats, and validation findings.

Key APIs
- Classes: `SourceRecord` — raw ingested item with minimal normalization and provenance.
- Classes: `Candidate` — normalized label candidate with features and support statistics.
- Classes: `Concept` — merged, validated taxonomy node with identifiers and aliases.
- Classes: `Provenance` — source and transformation lineage for auditability.
- Classes: `SupportStats` — frequency and confidence aggregates.
- Classes: `ValidationFinding` — rule outcomes and LLM verification summaries.
- Classes: `MergeOp` / `SplitOp` — transformation operations recorded during assembly and dedup.

Data Contracts
- Typed dataclasses/models in `core.py` define fields and invariants; validation enforces ASCII canonical form and single‑token preferences per policy.

Quick Start
- Creating and validating
  - `from taxonomy.entities.core import Candidate`
  - `cand = Candidate(label="CompSci", level=2, provenance=prov)`
  - `cand.validate()`

Lifecycle
- S0: create `SourceRecord` → initial `Candidate`.
- S1: normalization and feature enrichment.
- S2: frequency filtering and support stats.
- S3: single‑token verification; `ValidationFinding` attached.
- Post: `MergeOp`/`SplitOp` applied to form final `Concept`s.

See Also
- Detailed spec: this README.
- Related: `src/taxonomy/pipeline/*`, `src/taxonomy/utils/*`, `src/taxonomy/observability/*`.

Maintenance
- Update schemas and invariants in `core.py` with corresponding tests in `tests/test_entities.py` and phase tests.

## Detailed Specification

### Entities (Domain) — Logic Spec

See also: `docs/logic-spec.md`, `src/taxonomy/pipeline/hierarchy_assembly/README.md`, `src/taxonomy/pipeline/validation/README.md`

Purpose
- Specify semantic contracts for core domain entities and their lifecycle across S0–S3.

Core Tech
- Pydantic models with validators for canonicalization and invariants.

Inputs/Outputs (semantic)
- Input: upstream phase outputs (S0–S3) that instantiate or transform entities.
- Output: validated entities persisted in artifacts/manifests: `SourceRecord[]`, `Candidate[]`, `Concept[]`, `MergeOp[]`/`SplitOp[]`.

Rules & Invariants
- URLs normalized (scheme+host lowercased, no fragment); invalid schemes rejected.
- `Concept` carries stable id, normalized label, level in [0..3]; parent constraints enforced by hierarchy assembly.
- Provenance timestamps are UTC; evidence text snippets are length‑bounded per policy.

Core Logic
- Define entity schemas with field validators for normalization and invariant checks.
- Enforce canonical label rules at creation time; reject/repair inputs that violate policy.
- Provide upgrade flows: `Candidate → Concept` after S3 policy verification; support consolidation via `MergeOp`/`SplitOp`.

Algorithms & Parameters
- Intentional omission: thresholds and limits (e.g., evidence length, alias counts) live in policy modules under `src/taxonomy/config/policies/*` and are versioned in `docs/policies.md`.

Failure Handling
- Validation errors yield structured findings and raise explicit exceptions; invalid instances are quarantined, not silently corrected.
- On unknown URL schemes or malformed provenance, reject the instance and attach rationale for audit.

Observability
- Manifests include entity counts, level distributions, and sampled evidence; sampling rate is policy‑controlled.

Acceptance Tests
- Creating a `Concept` with an invalid level outside [0..3] raises a validation error.
- Promoting a `Candidate` that fails single‑token policy does not produce a `Concept` and records a failure rationale.

Open Questions
- Stable id derivation: fully deterministic from label vs. salted hash to minimize collisions.

Examples
- Candidate → Concept promotion:
  ```json
  {"label":"computer vision","aliases":["cv"],"level":2}
  ```
  becomes
  ```json
  {"id":"cv","label":"computer vision","level":2,"parents":["ml"]}
  ```

#### Module Reference

Core Models (`src/taxonomy/entities/core.py`)
- `PageSnapshot` — immutable capture of fetched page content with URL, fetch time (UTC), language, and normalized text blocks.
- `SourceRecord` — raw text with provenance (`Provenance`, `SourceMeta`) linking back to `PageSnapshot` or other sources.
- `Candidate` — intermediate proposal with normalized label, aliases, level, and `SupportStats` derived from evidence.
- `Concept` — validated taxonomy node with stable `id`, normalized label, level, parents, and provenance summary.
- `MergeOp` / `SplitOp` — transformation operations to track consolidation and disambiguation with rationales.

Supporting Classes
- `Provenance` — source identifiers, timestamps, and stable content hash.
- `SourceMeta` — origin metadata (institution, crawler, content type).
- `SupportStats` — counts and aggregates (institutions, sources, occurrences) used in S2.
- `Rationale` — compact human‑readable justification; never chain‑of‑thought.
- `ValidationFinding` — structured rule/LLM/web gate result used in S3.

Lifecycle Across S0–S3
- S0 (Web Mining): `PageSnapshot` → `SourceRecord` with provenance.
- S1 (Extraction): `SourceRecord[]` → `Candidate[]` with initial `SupportStats` and normalization applied.
- S2 (Frequency): update `SupportStats`; drop candidates below thresholds; emit `SplitOp` for disambiguation candidates.
- S3 (Verification): validate candidates; promote passing ones to `Concept` and attach `ValidationFinding` summary.

Validation & Normalization
- Canonical label rules applied at creation; alias lists derived via utils; parent constraints enforced in hierarchy assembly.
- URLs normalized (scheme/host lowercased, fragments removed); timestamps stored as UTC ISO‑8601.

Observability
- Entity counts/distributions exported via `ObservabilityManifest`; representative evidence attached to candidates and concepts per policy sampling.

