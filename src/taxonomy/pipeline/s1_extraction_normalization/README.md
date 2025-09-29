# S1 · Extraction & Normalization

Purpose
- Generate candidate tokens from `SourceRecord` inputs using LLM extraction and apply normalization rules.

Key Classes
- `S1Processor`: Coordinates extraction by level and aggregates outputs.
- `ExtractionProcessor`: Interfaces with `taxonomy.llm` for deterministic JSON extraction.
- `CandidateNormalizer`: Applies canonicalization and policy rules.
- `ParentIndex`: Resolves parents for hierarchical levels.

Data Contract
- `SourceRecord` → `Candidate` (+ stats, provenance).

Workflow Highlights
- Level‑specific processing, normalization, parent resolution, and aggregation with deterministic seeds.

CLI
- Generate S1 candidates: `python main.py pipeline generate --step S1 --level <N>`

Examples
- Run for level 0: `... --level 0`; repeat for deeper levels as needed.

Related Docs
- Detailed pipeline: `docs/modules/s1-extraction-normalization-pipeline.md`

