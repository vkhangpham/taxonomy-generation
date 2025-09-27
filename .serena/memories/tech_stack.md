# Tech Stack
- Language: Python 3.11+ (configured via `pyproject.toml`).
- Key libraries: Pydantic v2 (data models), pydantic-settings (config bootstrap), Polars (dataframes + Excel ingestion), loguru (logging), DSPy + OpenAI SDK (LLM orchestration), firecrawl-py (web crawling), requests, yaml, jellyfish & python-Levenshtein (string similarity), tqdm.
- Config format: YAML policies under `config/` with environment overrides via `TAXONOMY_SETTINGS__*` and `TAXONOMY_POLICY__*` environment variables.
- Dev tooling (optional extras): pytest, black, ruff. No framework-specific CLI; rely on standard Python tooling.