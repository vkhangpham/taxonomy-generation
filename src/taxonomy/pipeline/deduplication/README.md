# Deduplication

Purpose
- Identify and merge duplicate candidates using similarity and blocking strategies.

Key Classes
- `DeduplicationProcessor`: Orchestrates matching and merge operations.
- `SimilarityMatcher`: Computes candidate similarity with configurable metrics.
- `CandidateMerger`: Produces merged records and audit trails.
- `BlockingStrategy`: Reduces comparisons via candidate partitioning.

Data Contract
- `Candidate` → deduplicated `Candidate` (+ merge graph, rationale).

Workflow Highlights
- Blocking, similarity scoring, graph‑based merging, and deterministic tie‑breaks.

Examples
- Run as part of post‑processing to consolidate S2/S3 outputs.

Related Docs
- Detailed pipeline: `docs/modules/dedup.md`

