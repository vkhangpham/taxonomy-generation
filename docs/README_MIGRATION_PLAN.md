# README Migration Plan

Purpose
- Transition from a solely centralized documentation approach to a hybrid model: detailed logic specs in `docs/modules/` plus concise `README.md` files in each module directory under `src/taxonomy/`.

Principles
- Complement, don’t duplicate: READMEs are for quick orientation and APIs; detailed specs capture invariants and algorithms.
- Deterministic: examples and guidance must reflect current policies and seeds.
- Traceable: READMEs link to the authoritative module spec and relevant policies.

Phases
- Phase 1 — Pipeline Steps (S0–S3, deduplication, disambiguation, validation, hierarchy_assembly)
  - Owners: pipeline maintainers
  - Deliverables: eight READMEs created from `docs/README_TEMPLATE.md`
- Phase 2 — Cross‑Cutting Services (llm, observability, web_mining, prompt_optimization)
  - Owners: respective service maintainers
- Phase 3 — Orchestration & Abstractions (pipeline/, orchestration/)
  - Owners: orchestration leads
- Phase 4 — Config/Policies, Entities, Utils, CLI
  - Owners: component leads

Process
- Create README from `docs/README_TEMPLATE.md`; tailor sections to the module.
- Link README → corresponding `docs/modules/<name>.md` and update that spec with a back‑link to the README path.
- Update status in `docs/MODULE_README_INVENTORY.md` and `docs/MODULE_INDEX.md`.
- Add or update tests if data contracts or public APIs change.

Quality Bar
- Each README includes: Purpose, Key APIs, Data Contracts, Quick Start, Configuration, Dependencies, Observability, Determinism, See Also.
- Examples are minimal, deterministic, and runnable within the repository.

Maintenance
- Treat READMEs as API docs: update on any breaking change or new surface area.
- Reviewers check README/spec parity during PR review using the checklists in `docs/DOCUMENTATION_GUIDE.md`.

Timeline
- Week 1: Phase 1 modules.
- Week 2: Phases 2–3.
- Week 3: Phase 4 and audit.

Tracking
- Use `docs/MODULE_README_INVENTORY.md` for granular mapping and `docs/MODULE_INDEX.md` for at‑a‑glance status.

