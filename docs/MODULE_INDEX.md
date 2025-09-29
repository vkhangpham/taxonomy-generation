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
- All module docs should conform to `docs/DOCUMENTATION_GUIDE.md` and cross‑reference `docs/logic-spec.md`.
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
- `src/taxonomy/llm/README.md` — ❌ Missing
- `src/taxonomy/observability/README.md` — ❌ Missing
- `src/taxonomy/web_mining/README.md` — ❌ Missing
- `src/taxonomy/prompt_optimization/README.md` — ❌ Missing

Configuration & Policies
- `src/taxonomy/config/README.md` — ❌ Missing

Domain Entities
- `src/taxonomy/entities/README.md` — ❌ Missing

Shared Utilities
- `src/taxonomy/utils/README.md` — ❌ Missing

CLI
- `src/taxonomy/cli/README.md` — ❌ Missing

See Also
- Full mapping with detailed doc links: `docs/MODULE_README_INVENTORY.md`.
