# Taxonomy Project Purpose
- Build a deterministic, auditable four-level academic taxonomy (Colleges → Departments → Research Areas → Conference Topics) from institutional data sources.
- Pipeline phases: S0 raw extraction, S1 LLM extraction/normalization, S2 cross-institution frequency filtering, S3 single-token verification, followed by consolidation, validation, web enrichment, disambiguation, deduplication, and final hierarchy assembly.
- Core principles: single source of truth for prompts/policies, deterministic runs with fixed seeds, explainable keeps/drops, and resumable phases with persistent artifacts.
- Prompt optimization is handled offline via DSPy to improve extraction fidelity without violating policy guardrails.