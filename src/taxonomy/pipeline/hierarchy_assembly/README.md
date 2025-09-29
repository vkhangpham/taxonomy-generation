# Hierarchy Assembly

Purpose
- Assemble validated concepts into a coherent hierarchical taxonomy with invariants enforced.

Key Classes
- `HierarchyAssembler`: Main driver to build the hierarchy graph.
- `HierarchyGraph`: Graph representation with utilities for queries and checks.
- `GraphValidator`: Validates structural invariants and reports issues.
- `OrphanHandler`: Detects and handles orphans with placeholders or reparenting.

Data Contract
- `Concept` → `HierarchyAssemblyResult` (+ report, graph, and fixes).

Workflow Highlights
- Parent resolution, orphan/placeholder handling, graph validation, and finalization outputs.

Examples
- Run during finalization to produce the taxonomy deliverables and reports.

Related Docs
- Detailed pipeline: `docs/modules/hierarchy-assembly-pipeline.md`

