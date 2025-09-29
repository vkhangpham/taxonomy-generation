# Shared Utilities — Logic Spec

See also: `docs/logic-spec.md`

Purpose
- Describe shared utilities for normalization, similarity, phonetics, acronym handling, logging, and context features.

Core Tech
- String and token utilities with deterministic behavior and fixed seeds where applicable.

Utilities
- Normalization — minimal canonical form, boilerplate removal, alias generation per level.
- Similarity — Jaccard (char/token), Jaro‑Winkler, MinHash, and combined similarity scoring.
- Phonetic — Double Metaphone keys and buckets for name variation clustering.
- Acronyms — detection and expansion matching.
- Context features — windows, co‑occurrence, divergence metrics, and summaries for LLM prompts.
- Logging — structured logging with context and timing helpers.

Rules & Invariants
- ASCII canonical preference, whitespace normalization, punctuation handling as per label policy.
- All randomized components accept a `seed` and default to global settings for reproducibility.

Examples
- Similarity:
  ```python
  compute_similarity("computer vision", "vision, computer", algo="combined", return_parts=True)
  ```
- Phonetic bucket keys:
  ```python
  phonetic_bucket_keys("robotics")  # -> ("RBTKS", "RPTKS")
  ```

