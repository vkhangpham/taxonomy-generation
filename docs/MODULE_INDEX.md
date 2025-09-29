# Module Index

Purpose
- Map `src/taxonomy/` packages to module docs, track coverage and status.

Legend: ✅ Complete • 📝 Needs Update • ❌ Missing

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
- All module docs should conform to `docs/DOCUMENTATION_GUIDE.md` and cross‑reference `docs/logic-spec.md`.
- Status should be updated when behavior changes, policies bump, or interfaces drift.
