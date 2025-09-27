# Deduplication — Logic Spec

Purpose
- Collapse equivalent or near-equivalent concepts into a single canonical node while preserving provenance and aliases.

Core Tech
- Centralized in-memory graph for candidate nodes and similarity edges (single source of truth during a run).
- Union–Find (disjoint set) or connected components to compute merges deterministically.
- String similarity stack for edge scoring (Jaro–Winkler, token Jaccard) + acronym/expansion scoring (AbbrevScore).
- Optional phonetic blocking (Double Metaphone) to reduce pairwise comparisons.

Inputs/Outputs (semantic)
- Input: Candidate[] (post S3)
- Output: Concepts[] with MergeOps log and alias mappings

Blocking & Similarity
- Blocking keys: first-k chars of normalized, acronym bucket, phonetic bucket (e.g., Double Metaphone).
- Similarity score s ∈ [0,1] = max(JaroWinkler, token Jaccard, AbbrevScore(acronym↔expanded)).
- Thresholds: τ(L0,L1)=0.93, τ(L2,L3)=0.90 (tuneable).

Merge Policy (deterministic)
1) Higher inst_count
2) Shorter normalized length
3) Lexicographic order as final tie-break

Operations
- Produce MergeOps {loser_id→winner_id}; merge support (records, institutions) and union aliases.
- Record rationale (similarity features, threshold crossed) for audit.

Edge Generation Techniques
- String similarity edge: add edge(i,j) if max(JW, Jaccard) ≥ τ(level).
- Abbreviation edge: add i↔j if acronym(normalized_i)==normalized_j or vice versa (e.g., CS ↔ computer science).
- Phonetic bucket edge: within same phonetic bucket, add edges for pairs exceeding a lower probe threshold, then re-score.
- Prefix/suffix heuristic edge: treat common academic suffixes (e.g., "systems", "theory") with partial-overlap boosts.
- Parent-context guard: do not add cross-parent edges when parent contexts are incompatible unless verified by evidence.

Failure Handling
- In conflicting metadata (parents differ), prefer parent with higher support; otherwise flag for disambiguation instead of merge.

Observability
- Counters: pairs_compared, edges_kept, components, merges_applied.
- Samples: top-k merges by similarity for manual review.

Acceptance Tests
- Acronym/expansion pairs (e.g., CS ↔ Computer Science) merge when unambiguous.
- Concepts with different parents do not merge; routed to disambiguation.

Open Questions
- Do we allow merge across slightly different parent contexts at L2 vs L3 if sibling sets match?

Examples
- Example A: Acronym ↔ expansion merge (L1)
  - Inputs:
    ```json
    {"id": "c1", "level": 1, "normalized": "computer science", "inst_count": 5}
    {"id": "c2", "level": 1, "normalized": "cs", "inst_count": 3, "aliases": ["computer science"]}
    ```
  - Similarity features: AbbrevScore=1.0, JaroWinkler=0.76, Jaccard=0.5 → s=1.0 ≥ τ(L1)=0.93
  - Decision: merge c2 → c1 (winner c1 by higher inst_count); union aliases {"cs","computer science"}.

- Example B: Do not merge across conflicting parents
  - Inputs:
    ```json
    {"id": "a", "level": 2, "normalized": "security", "parents": ["computer science"], "inst_count": 4}
    {"id": "b", "level": 2, "normalized": "security", "parents": ["political science"], "inst_count": 3}
    ```
  - Similarity high on label but parent contexts differ.
  - Decision: no merge; route to disambiguation.
