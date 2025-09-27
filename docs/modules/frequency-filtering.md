# Cross‑Institution Frequency Filtering (S2) — Logic Spec

Purpose
- Retain candidates with sufficient support across distinct institutions/sources; drop idiosyncratic or localized terms.

Core Tech
- Deterministic aggregator over normalized keys (level, normalized, parent_lineage).
- Stable institution identity resolver (policy-configured campus/system mapping).

Inputs/Outputs (semantic)
- Input: Candidate[] with provenance
- Output: Candidate[] (kept) with support metrics and rationale; dropped list with reasons

Metrics
- inst_count: number of distinct institutions supporting the (level, normalized, parent_lineage) key
- src_count: number of distinct SourceRecords
- weight: w1*inst_count + w2*log(1+src_count) (defaults w1=1.0, w2=0.3)

Thresholds (defaults; tune with eval set)
- L0 ≥ 1 inst
- L1 ≥ 1 inst
- L2 ≥ 2 inst
- L3 ≥ 2 inst and src_count ≥ 3

Rules & Invariants
- Distinct institution definition must be stable (campus vs. system); document policy.
- De‑duplicate near-identical pages within the same institution before counting.
- Keep rationale: store counts, institution list (sampled if large), and representative snippets.

Core Logic
- Aggregate by key; compute metrics; compare with per‑level thresholds.
- Produce explainable rationale entries: kept/dropped with threshold references.

Failure Handling
- On missing provenance, treat as single‑institution fallback; flag low confidence.

Observability
- Counters: candidates_in, kept, dropped_insufficient_support, policy_exceptions.
- Distributions: inst_count histogram by level.

Acceptance Tests
- Candidates with identical normalized forms across ≥2 institutions pass at L2/L3.
- Near-duplicate sources at a single institution do not inflate counts.

Open Questions
- Should research consortia/shared centers count as independent institutions?

Examples
- Example A: L2 concept passes
  - Aggregated supports:
    ```json
    {
      "key": [2, "computer vision", "college of engineering>computer science"],
      "inst_count": 3,
      "src_count": 7,
      "institutions": ["u1","u4","u7"]
    }
    ```
  - Decision: keep (inst_count ≥ 2 satisfied for L2).

- Example B: L3 concept fails due to insufficient breadth
  - Aggregated supports:
    ```json
    {
      "key": [3, "graph transformers", "...>machine learning"],
      "inst_count": 1,
      "src_count": 5
    }
    ```
  - Decision: drop (requires ≥ 2 institutions at L3).

- Example C: Near‑duplicate sources de‑inflated
  - Two pages from the same institution with 0.98 similarity count as one source; src_count reflects de‑duped pages.
