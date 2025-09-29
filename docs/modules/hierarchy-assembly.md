# Hierarchy Assembly — Logic Spec

See also: `docs/logic-spec.md`, `docs/DOCUMENTATION_GUIDE.md`

Purpose
- Construct a four-level DAG (L0→L3) from validated concepts with acyclicity and unique paths.

Core Tech
- Deterministic graph assembly with adjacency lists; acyclicity via topological sort.
- Path uniqueness verification using parent pointers; strict level guards on edge creation.

Inputs/Outputs (semantic)
- Input: Concepts[] (post-gates, post-dedup/disambiguation)
- Output: Hierarchy manifest (nodes, edges, invariants check, summaries)

Invariants
- Exactly four levels; L0 has no parents; L1 parents must be L0; L2 parents must be L1; L3 parents must be L2.
- No cycles; no shortcuts (e.g., L3 under L1).
- Unique path from L0 to any node unless explicit, documented multi-parent exception.

Core Logic
- Validate parent levels conform; fix or drop nodes that violate constraints with rationale.
- Ensure sibling collisions resolved upstream (dedup/disambiguation); reject residual conflicts.
- Emit summaries: counts per level, degree distributions, orphan detection results.

Failure Handling
- Orphans (missing parents) → quarantine or attach to temporary placeholder; require follow-up.
- Cross-level leaks → drop with reason and include in error report.

Observability
- Counters: nodes_in, nodes_kept, orphans, violations, edges_built.
- Graph checks: acyclicity proof (topo ordering), path uniqueness stats.

Acceptance Tests
- Any artificially introduced cycle is detected and blocked.
- Orphan nodes are reported with clear reasons and not included in final DAG.

Open Questions
- How to represent cross-listed departments spanning multiple colleges without breaking uniqueness?

Examples
- Example A: Valid 4-level path
  - Nodes:
    ```json
    {"id": "eng", "level": 0, "label": "college of engineering"}
    {"id": "cs",  "level": 1, "label": "computer science", "parents": ["eng"]}
    {"id": "ml",  "level": 2, "label": "machine learning", "parents": ["cs"]}
    {"id": "cv",  "level": 3, "label": "computer vision",  "parents": ["ml"]}
    ```
  - Result: DAG passes invariants; unique path eng→cs→ml→cv.

- Example B: Orphan handling
  - Node: {id: "datamining", level: 2, parents: ["unknown_dept"]}
  - Decision: quarantine with reason "missing parent"; exclude from DAG; report in manifest.

- Example C: Cycle detection
  - If an edge ml→cs is erroneously introduced, topo sort fails; reject edge and log violation.
