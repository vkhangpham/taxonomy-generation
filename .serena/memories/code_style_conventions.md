# Code Style & Conventions
- Modules use `from __future__ import annotations`, full type hints, and Pydantic BaseModel subclasses with validators for data contracts.
- Functional, deterministic mindset: avoid hidden globals, pass settings/policies explicitly or via `get_settings()` singleton.
- Logging via `loguru.logger`; keep messages structured with key-value context.
- Prompts, thresholds, and mutable policies live in configuration files; business code must reference them indirectly (no inline prompt strings).
- Tests rely on `pytest` fixtures/monkeypatching; follow expressive assertion patterns and raise-based validation checks.
- Utilities emphasize pure helpers (`normalize_label`, deterministic shuffles); prefer immutable artifacts and reproducible seeds.