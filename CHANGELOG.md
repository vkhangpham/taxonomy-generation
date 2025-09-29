# Changelog

All notable changes to this project’s documentation system are recorded here. The format follows Conventional Commits where practical. Dates use YYYY‑MM‑DD.

## 2025-09-29 — docs: initial consolidation and rollout complete

- docs: established dual‑track documentation approach
  - Comprehensive, implementation‑agnostic specs under `docs/modules/`.
  - Quick‑reference, developer‑oriented READMEs colocated with code in `src/taxonomy/**/README.md`.
- docs: added architecture/logic reference as a dedicated blueprint
  - Moved the functional blueprint from the root `README.md` to `docs/functional-blueprint.md` to preserve the logic specification and make the root README a true project guide.
- docs: created an explicit navigation layer
  - `docs/MODULE_INDEX.md` tracks coverage for both detailed specs and per‑module READMEs.
  - `docs/DOCUMENTATION_GUIDE.md` defines structure, style, and cross‑referencing rules.
- cleanup: removed temporary rollout artifacts
  - Deleted `docs/README_MIGRATION_PLAN.md`, `docs/MODULE_README_INVENTORY.md`, `docs/README_TEMPLATE.md`, and `docs/MODULE_TEMPLATE.md`.
- readme: rewrote the root `README.md` as a project overview with quick start, architecture overview, documentation map, and contribution workflow.
- policy: reaffirmed that policy changes must update `docs/policies.md` and corresponding module specs; surfaced in manifests.

See also:
- Documentation guide: `docs/DOCUMENTATION_GUIDE.md`
- Module index and status: `docs/MODULE_INDEX.md`
- Functional blueprint: `docs/functional-blueprint.md`

