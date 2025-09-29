# Module README Inventory

Purpose
- Map every package/subpackage in `src/taxonomy/` to its in‑tree `README.md` and the corresponding detailed doc in `docs/modules/`.
- Drive the rollout of concise, developer‑focused READMEs using `docs/README_TEMPLATE.md`.

Legend: ✅ Complete • 📝 Needs Update • ❌ Missing

Pipeline Steps
- `src/taxonomy/pipeline/s0_raw_extraction/README.md` — ❌ Missing • Detailed: `docs/modules/raw-extraction.md`
- `src/taxonomy/pipeline/s1_extraction_normalization/README.md` — ❌ Missing • Detailed: `docs/modules/extraction-normalization.md`
- `src/taxonomy/pipeline/s2_frequency_filtering/README.md` — ❌ Missing • Detailed: `docs/modules/frequency-filtering.md`
- `src/taxonomy/pipeline/s3_token_verification/README.md` — ❌ Missing • Detailed: `docs/modules/single-token-verification.md`
- `src/taxonomy/pipeline/deduplication/README.md` — ❌ Missing • Detailed: `docs/modules/dedup.md`
- `src/taxonomy/pipeline/disambiguation/README.md` — ❌ Missing • Detailed: `docs/modules/disambiguation.md`
- `src/taxonomy/pipeline/validation/README.md` — ❌ Missing • Detailed: `docs/modules/validation.md`
- `src/taxonomy/pipeline/hierarchy_assembly/README.md` — ❌ Missing • Detailed: `docs/modules/hierarchy-assembly.md`

Orchestration & Abstractions
- `src/taxonomy/orchestration/README.md` — ❌ Missing • Detailed: `docs/modules/pipeline-orchestration.md`
- `src/taxonomy/pipeline/README.md` — ❌ Missing • Detailed: `docs/modules/pipeline-core-abstractions.md`

Cross‑Cutting Services
- `src/taxonomy/llm/README.md` — ❌ Missing • Detailed: `docs/modules/llm.md`
- `src/taxonomy/observability/README.md` — ❌ Missing • Detailed: `docs/modules/observability-reproducibility.md`
- `src/taxonomy/web_mining/README.md` — ❌ Missing • Detailed: `docs/modules/web-mining.md`
- `src/taxonomy/prompt_optimization/README.md` — ❌ Missing • Detailed: `docs/modules/prompt-optimization.md`

Configuration & Policies
- `src/taxonomy/config/README.md` — ❌ Missing • Detailed: `docs/modules/config-policies.md`

Domain Entities
- `src/taxonomy/entities/README.md` — ❌ Missing • Detailed: `docs/modules/entities-core.md`

Shared Utilities
- `src/taxonomy/utils/README.md` — ❌ Missing • Detailed: `docs/modules/utils-shared.md`

CLI
- `src/taxonomy/cli/README.md` — ❌ Missing • Detailed: `docs/modules/cli-interfaces.md`

Notes
- Create READMEs by copying `docs/README_TEMPLATE.md` and tailoring sections to the module.
- Keep READMEs succinct and link back to the detailed spec in `docs/modules/`.
- Update status here and in `docs/MODULE_INDEX.md` as READMEs land.

