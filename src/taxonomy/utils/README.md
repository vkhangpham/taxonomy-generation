# Utils — README (Developer Quick Reference)

Purpose
- Shared text processing, similarity, phonetic matching, and helper utilities used across all pipeline phases.

Key APIs
- Normalization: `normalize_by_level(text, level)`, `generate_aliases(label)`.
- Similarity: `compute_similarity(a, b)`, `find_duplicates(items, threshold)`.
- Phonetic: `double_metaphone(text)`, `bucket_by_phonetic(items)`.
- Helpers: `chunked(iterable, size)`, `stable_shuffle(seq, seed)`.
- Context features: `features_for(text, context)` for language and structure heuristics.
- Logging: `setup_logging(config)` configures module loggers.

Data Contracts
- Normalization rules are ASCII‑first with canonical forms; similarity returns typed scores and match annotations; phonetic buckets group near‑homophones.

Quick Start
- Examples
  - `from taxonomy.utils.normalization import normalize_by_level`
  - `normalized = normalize_by_level("Comp. Sci.", level=2)`
  - `from taxonomy.utils.similarity import compute_similarity`
  - `score = compute_similarity("computer science", "computing science")`

Determinism
- All helpers honor provided seeds and avoid nondeterministic ordering; utilities are pure functions where possible.

See Also
- Detailed spec: `docs/modules/utils-shared.md`.
- Related: `src/taxonomy/entities`, `src/taxonomy/pipeline/*`, `src/taxonomy/observability`.

Maintenance
- Add unit tests for new helpers under `tests/` (e.g., `test_normalization.py`, `test_similarity.py`).

