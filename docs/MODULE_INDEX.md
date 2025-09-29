# Module Index

Purpose
- Map `src/taxonomy/` packages to module docs, track coverage and status.

Legend: ✅ Complete • 📝 Needs Update • ❌ Missing
README Legend: ✅ README present • ❌ Missing README

Pipeline Steps
- `pipeline/s0_raw_extraction` → `docs/modules/raw-extraction.md` — ✅
- `pipeline/s1_extraction_normalization` → `docs/modules/extraction-normalization.md` — ✅
- `pipeline/s2_frequency_filtering` → `docs/modules/frequency-filtering.md` — ✅
- `pipeline/s3_token_verification` → `docs/modules/single-token-verification.md` — ✅
- `pipeline/deduplication` → `docs/modules/dedup.md` — ✅
- `pipeline/disambiguation` → `docs/modules/disambiguation.md` — ✅
- `pipeline/validation` → `docs/modules/validation.md` — ✅
- `pipeline/hierarchy_assembly` → `docs/modules/hierarchy-assembly.md` — ✅

Orchestration & Pipeline Abstractions
- `pipeline/__init__.py` + `orchestration/` → `docs/modules/pipeline-orchestration.md` — ✅

Cross‑Cutting Services
- `llm/` → `docs/modules/llm.md` — ✅
- `observability/` → `docs/modules/observability-reproducibility.md` — ✅
- `web_mining/` → `docs/modules/web-mining.md` — ✅
- `prompt_optimization/` → `docs/modules/prompt-optimization.md` — ✅

Configuration & Policies
- `config/settings.py` + `config/policies/*` → `docs/modules/config-policies.md` — ✅

Domain Entities
- `entities/` → `docs/modules/entities-core.md` — ✅

Shared Utilities
- `utils/` → `docs/modules/utils-shared.md` — ✅

CLI
- `cli/` → `docs/modules/cli-interfaces.md` — ✅

Notes
- All module docs should conform to `docs/DOCUMENTATION_GUIDE.md` and cross‑reference `docs/functional-blueprint.md`.
- Status should be updated when behavior changes, policies bump, or interfaces drift.
- Per‑module READMEs provide quick reference and practical usage; detailed specs live in `docs/modules/`.

## Per‑Module READMEs (Quick Reference)

Purpose
- Track in‑tree `README.md` coverage for developer quick reference alongside detailed docs above.

Pipeline Steps (README path → status)
- `src/taxonomy/pipeline/s0_raw_extraction/README.md` — ✅ Complete
- `src/taxonomy/pipeline/s1_extraction_normalization/README.md` — ✅ Complete
- `src/taxonomy/pipeline/s2_frequency_filtering/README.md` — ✅ Complete
- `src/taxonomy/pipeline/s3_token_verification/README.md` — ✅ Complete
- `src/taxonomy/pipeline/deduplication/README.md` — ✅ Complete
- `src/taxonomy/pipeline/disambiguation/README.md` — ✅ Complete
- `src/taxonomy/pipeline/validation/README.md` — ✅ Complete
- `src/taxonomy/pipeline/hierarchy_assembly/README.md` — ✅ Complete

Orchestration & Abstractions
- `src/taxonomy/orchestration/README.md` — ✅ Complete
- `src/taxonomy/pipeline/README.md` — ✅ Complete

Cross‑Cutting Services
- `src/taxonomy/llm/README.md` — ✅ Complete
- `src/taxonomy/observability/README.md` — ✅ Complete
- `src/taxonomy/web_mining/README.md` — ✅ Complete
- `src/taxonomy/prompt_optimization/README.md` — ✅ Complete

Configuration & Policies
- `src/taxonomy/config/README.md` — ✅ Complete

Domain Entities
- `src/taxonomy/entities/README.md` — ✅ Complete

Shared Utilities
- `src/taxonomy/utils/README.md` — ✅ Complete

CLI
- `src/taxonomy/cli/README.md` — ✅ Complete

See Also
- Functional blueprint (logic specification): `docs/functional-blueprint.md`.
- Changelog for documentation system updates: `CHANGELOG.md`.

## Documentation Maturity & Maintenance

- The documentation system uses a dual‑track model: quick‑reference READMEs adjacent to code, and comprehensive specs under `docs/modules/`.
- Keep these in sync:
  - Update module specs when behavior, thresholds, or contracts change.
  - Update package READMEs when APIs or usage change.
  - Reflect policy/version changes in `docs/policies.md` and reference them in affected specs.
- Record notable documentation‑level changes in `CHANGELOG.md`.

## README Rollout Summary

Status
- All cross‑cutting services and operational modules now include quick‑reference `README.md` files alongside the detailed module docs in `docs/modules/`.
- Newly completed READMEs: `src/taxonomy/llm/README.md`, `src/taxonomy/observability/README.md`, `src/taxonomy/config/README.md`, `src/taxonomy/entities/README.md`, `src/taxonomy/utils/README.md`, `src/taxonomy/cli/README.md`, `src/taxonomy/prompt_optimization/README.md`, `src/taxonomy/web_mining/README.md`, `prompts/README.md`, and `tests/README.md`.

Cross‑References
- READMEs link to their authoritative specs under `docs/modules/` and reflect current policy defaults captured in `docs/policies.md`.
