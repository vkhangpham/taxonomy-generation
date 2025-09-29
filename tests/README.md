# Tests — README (Developer Quick Reference)

Purpose
- Organized, deterministic test suite covering pipeline phases, cross-cutting services, and utilities. Mirrors phase boundaries and reuses fixtures for stable coverage.

Structure
- Unit tests by module: utils, entities, config, llm, web_mining.
- Integration: orchestration and per-phase S0–S3 plus post-processing.
- Observability: counters and manifest materialization.

Workflows
- Run all: `pytest` (use `.venv`).
- Filter: `pytest -k s3_token_verification`.
- Lint/format: `ruff check src tests` and `black src tests` before commit.

Fixtures & Data
- Anonymized fixtures under `tests/` provide consistent seeds and small inputs; avoid large artifacts.

Maintenance
- Pair logic changes with parametrized tests; add integration checks in `tests/test_orchestration.py` for orchestration changes.

