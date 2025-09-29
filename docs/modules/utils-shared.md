# Shared Utilities — Logic Spec

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
