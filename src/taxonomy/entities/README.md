# Entities — README (Developer Quick Reference)

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
- Detailed spec: `docs/modules/entities-core.md`.
- Related: `src/taxonomy/pipeline/*`, `src/taxonomy/utils/*`, `src/taxonomy/observability/*`.

Maintenance
- Update schemas and invariants in `core.py` with corresponding tests in `tests/test_entities.py` and phase tests.

