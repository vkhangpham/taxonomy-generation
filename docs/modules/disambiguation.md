# Disambiguation — Logic Spec

Purpose
- Split ambiguous surface forms into distinct senses with explicit parentage and concise glosses.

Inputs/Outputs (semantic)
- Input: Concepts[] or high-confidence Candidates with collision signals
- Output: Concepts[] with SplitOps log and rationale per new sense

Ambiguity Detection
- Signals: identical normalized label under multiple parents; divergent co-occurring terms; differing venues/sections.
- Features: parent_lineage, context windows from SourceRecords, institution distributions.

Split Policy
- If contexts are separable, create distinct senses with unique parents and short glosses.
- If contexts inseparable, prefer a single parent; otherwise document multi-parent exception policy explicitly.

LLM Role
- Use a compact prompt to confirm separability and produce gloss candidates; must return strict JSON.

LLM Usage
- Invoke via the LLM package: `llm.run("taxonomy.disambiguate", {label, contexts,...})`.
- The package loads the on-disk optimized prompt; no inline prompt definitions.

Failure Handling
- If evidence is insufficient, defer split and mark for manual review with collected features.

Observability
- Counters: collisions_detected, splits_made, deferred, multi_parent_exceptions.
- Logs: per-split rationale including exemplar snippets.

Acceptance Tests
- Same label appearing under distinct research areas yields separate senses with correct parents.
- Non-separable uses remain a single concept with justification.

Open Questions
- Do we permit temporary multi-parenting at L2 during transition until more evidence arrives?

Examples
- Example A: Split "security" into distinct senses
  - Evidence:
    - Under parent "computer science": co-occurs with "cryptography", "vulnerability", "network".
    - Under parent "political science": co-occurs with "national", "international", "policy".
  - Output concepts:
    ```json
    {"id": "sec_cs", "level": 2, "canonical_label": "security", "parents": ["computer science"], "gloss": "computer and network security"}
    {"id": "sec_ir", "level": 2, "canonical_label": "security", "parents": ["political science"], "gloss": "international and national security"}
    ```
  - SplitOp records source → {sec_cs, sec_ir} with rationale.

- Example B: Defer split (insufficient evidence)
  - Label: "systems" under multiple contexts with overlapping terms; cannot separate reliably.
  - Decision: keep single concept with note "ambiguous; pending more evidence" and mark for review.
