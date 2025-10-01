# Utils — README (Developer Quick Reference)

## Quick Reference

Purpose
- Shared text processing, similarity, phonetic matching, and helper utilities used across all pipeline phases.

Key APIs
- Normalization: `normalize_by_level(text, level, *, owning_institution=None)`, `generate_aliases(label)`.
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
- Detailed spec: this README.
- Related: `src/taxonomy/entities`, `src/taxonomy/pipeline/*`, `src/taxonomy/observability`.

Maintenance
- Add unit tests for new helpers under `tests/` (e.g., `test_normalization.py`, `test_similarity.py`).

## Detailed Specification

### Shared Utilities — Logic Spec

See also: `docs/logic-spec.md`

Purpose
- Describe shared utilities for normalization, similarity, phonetics, acronym handling, logging, and context features.

Core Tech
- String and token utilities with deterministic behavior and fixed seeds where applicable.

Inputs/Outputs (semantic)
- Input: strings, token sequences, and small typed records used across phases.
- Output: normalized forms, similarity scores/components, phonetic keys, derived context features, and structured log records.

Rules & Invariants
- ASCII canonical preference, whitespace normalization, punctuation handling as per label policy.
- All randomized components accept a `seed` and default to global settings for reproducibility.

Core Logic
- Provide pure functions with stable behavior for text normalization and similarity.
- Expose composite helpers that bundle common operations (e.g., normalize → compute similarity parts → aggregate).
- Keep side effects limited to structured logging helpers.

Algorithms & Parameters
- Similarity: Jaccard (char/token), Jaro‑Winkler, MinHash, and combined scoring; tunables passed as arguments.
- Phonetic: Double Metaphone; optional key count and tie‑breakers.
- Intentional omission: numeric defaults and thresholds are controlled by policies or caller‑provided args.

Utilities
- Normalization — minimal canonical form, boilerplate removal, alias generation per level.
- Similarity — Jaccard (char/token), Jaro‑Winkler, MinHash, and combined similarity scoring.
- Phonetic — Double Metaphone keys and buckets for name variation clustering.
- Acronyms — detection and expansion matching.
- Context features — windows, co‑occurrence, divergence metrics, and summaries for LLM prompts.
- Logging — structured logging with context and timing helpers.

Failure Handling
- Empty/whitespace inputs return neutral outputs (e.g., zero scores, empty keys) rather than raising.
- Unicode normalization errors are handled via replacement mode and logged with context.

Observability
- Logging helpers capture timing and call metadata; counters/histograms names are defined in `observability` policy.

Examples
- Similarity:
  ```python
  compute_similarity("computer vision", "vision, computer", algo="combined", return_parts=True)
  ```
- Phonetic bucket keys:
  ```python
  phonetic_bucket_keys("robotics")  # -> ("RBTKS", "RPTKS")
  ```

Acceptance Tests
- Normalization preserves alphanumeric content and collapses whitespace deterministically.
- Similarity with identical inputs returns max score and aligned parts.

Open Questions
- Unify tokenization across utilities and policies vs. allow per‑call overrides.

#### API Reference

Normalization (`src/taxonomy/utils/normalization.py`)
- `AliasBundle` — container for primary label and derived aliases.
- `to_canonical_form(text, level, policy, *, owning_institution=None)` — ASCII‑preferred canonicalization with optional L0 institution‑prefix stripping.
- `remove_boilerplate(text, level, *, policy=None, owning_institution=None)` — strips policy‑defined boilerplate and, for L0 when provided, the owning institution prefix.
- `normalize_by_level(text, level, policy, *, owning_institution=None)` — applies level‑specific canonical rules.
- `generate_aliases(text, *, level)` — heuristic expansions with deterministic ordering.

Acronyms (`src/taxonomy/utils/acronym.py`)
- `detect_acronyms(text)` — returns detected acronym candidates with spans.
- `expand_acronym(acronym, context)` — best effort expansion given local context.

Similarity (`src/taxonomy/utils/similarity.py`)
- `preprocess_for_similarity(text)` — standard tokenization and normalization pipeline.
- `jaccard_similarity(a, b)` / `token_jaccard_similarity(a, b)` — set‑based char/token measures.
- `jaro_winkler_similarity(a, b)` — fuzzy distance with prefix boost.
- `minhash_similarity(a, b, *, seed=...)` — locality‑sensitive hashing; accepts fixed seed.
- `compute_similarity(a, b, *, algo="combined", return_parts=False)` — composite scorer; parts include per‑metric components.
- `find_duplicates(items, *, threshold)` — groups near‑duplicates; deterministic tie‑breaking.

Phonetic (`src/taxonomy/utils/phonetic.py`)
- `normalize_for_phonetic(text)` — pre‑normalization for robust keys.
- `double_metaphone(text)` — (p1, p2) keys.
- `generate_phonetic_key(text)` — single stable key for indexing.
- `phonetic_bucket_keys(text)` — canonical bucket pair.
- `bucket_by_phonetic(items)` — groups by phonetic keys; stable ordering.

Context Features (`src/taxonomy/utils/context_features.py`)
- Context windows, co‑occurrence statistics, divergence metrics used by disambiguation and validation prompts.

Logging (`src/taxonomy/utils/logging.py`)
- Structured logger with timing helpers; integrates with observability counters where configured.

Determinism & Performance
- All randomized utilities accept a `seed`; default source comes from settings/policy.
- Caching: pure functions may use in‑memory memoization keyed on canonical inputs.

Examples
- Normalization & aliasing:
  ```python
  from taxonomy.utils.normalization import to_canonical_form, generate_aliases
  to_canonical_form("Machine‑Learning ")  # -> "machine learning"
  generate_aliases("nlp", level=2)       # -> ["nlp", "natural language processing"]
  ```
- Similarity parts:
  ```python
  compute_similarity("computer vision", "vision, computer", return_parts=True)
  ```
- Phonetic buckets:
  ```python
  bucket_by_phonetic(["robitics", "robotics"])  # stable grouping
  ```
