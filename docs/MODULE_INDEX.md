# Module Index

Purpose
- Map `src/taxonomy/` packages to their canonical READMEs, track coverage, and surface documentation maintenance status.

Legend: ✅ Complete • 📝 Needs Update • ❌ Missing

## Pipeline Steps
- `pipeline/s0_raw_extraction` → `src/taxonomy/pipeline/s0_raw_extraction/README.md` — ✅
- `pipeline/s1_extraction_normalization` → `src/taxonomy/pipeline/s1_extraction_normalization/README.md` — ✅
- `pipeline/s2_frequency_filtering` → `src/taxonomy/pipeline/s2_frequency_filtering/README.md` — ✅
- `pipeline/s3_token_verification` → `src/taxonomy/pipeline/s3_token_verification/README.md` — ✅
- `pipeline/deduplication` → `src/taxonomy/pipeline/deduplication/README.md` — ✅
- `pipeline/disambiguation` → `src/taxonomy/pipeline/disambiguation/README.md` — ✅
- `pipeline/validation` → `src/taxonomy/pipeline/validation/README.md` — ✅
- `pipeline/hierarchy_assembly` → `src/taxonomy/pipeline/hierarchy_assembly/README.md` — ✅

## Orchestration & Pipeline Abstractions
- `pipeline/__init__.py` + `orchestration/` → `src/taxonomy/orchestration/README.md` — ✅
- Core abstractions summary → `src/taxonomy/pipeline/README.md` — ✅

## Cross-Cutting Services
- `llm/` → `src/taxonomy/llm/README.md` — ✅
- `observability/` → `src/taxonomy/observability/README.md` — ✅
- `web_mining/` → `src/taxonomy/web_mining/README.md` — ✅
- `prompt_optimization/` → `src/taxonomy/prompt_optimization/README.md` — ✅

## Configuration & Policies
- `config/settings.py` + `config/policies/*` → `src/taxonomy/config/README.md` — ✅

## Domain Entities & Utilities
- `entities/` → `src/taxonomy/entities/README.md` — ✅
- `utils/` → `src/taxonomy/utils/README.md` — ✅

## CLI
- `cli/` → `src/taxonomy/cli/README.md` — ✅

## Maintenance Notes
- Module READMEs now embed the full specification content; treat them as the single source of truth for behavior, thresholds, and contracts.
- When implementations change, update the corresponding README, adjust status here if a follow-up edit is required, and log policy/version bumps in `docs/policies.md`.
- Use `docs/functional-blueprint.md` for end-to-end context and `docs/DOCUMENTATION_GUIDE.md` for style conventions.
- Record notable documentation updates in `CHANGELOG.md` and provide pointers to relevant READMEs in PR descriptions.

## Coverage Snapshot
- All operational modules and cross-cutting services have comprehensive READMEs colocated with code.
- Keep the index in sync with new packages or top-level reorganizations.

