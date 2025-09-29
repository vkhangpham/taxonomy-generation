# Documentation Guide

Purpose
- Establish a consistent, implementation-agnostic documentation standard for all module READMEs under `src/taxonomy/`.
- Ensure every README is actionable for implementers and reviewers, with clear ties to policy and observability requirements.

Scope
- Applies to every `README.md` colocated with code in `src/taxonomy/**/` (pipeline stages, orchestration, LLM, observability, utilities, etc.).
- Builds on patterns in `src/taxonomy/pipeline/s0_raw_extraction/README.md`, `src/taxonomy/llm/README.md`, and the cross-cutting `docs/functional-blueprint.md`.

Canonical Structure (per module README)
- Title — “<Module Name> — README (Developer Guide)” or module-specific equivalent.
- Quick Reference — Purpose, key APIs, data contracts, configuration keys, observability hooks, determinism notes.
- Detailed Specification — Embedded logic spec covering:
  - Purpose and scope of the module.
  - Core tech and dependencies.
  - Inputs/outputs (semantic contracts).
  - Rules & invariants.
  - Core logic / algorithms & tunables.
  - Failure handling & repair paths.
  - Observability (metrics, manifests, evidence).
  - Acceptance tests or scenario outlines.
  - Examples (JSON/text snippets) and open questions.
- Related links — other module READMEs, policies, functional blueprint.

Writing Style
- Be implementation-agnostic where possible: use “must/should” language tied to semantic behaviors.
- Prefer concise bullets over long paragraphs; keep each bullet to a single descriptive line when feasible.
- Include concrete JSON or tabular examples aligned with fixtures; avoid prose-only descriptions for data contracts.
- Surface numeric thresholds with defaults and ranges; reference the owning policy key.
- Use terminology consistent with `docs/functional-blueprint.md` and policy class/property names in `src/taxonomy/config/policies`.

Placement & Naming
- READMEs live beside their code (e.g., `src/taxonomy/pipeline/s2_frequency_filtering/README.md`).
- Keep filenames as `README.md`; the directory structure conveys module identity.

Cross-Referencing
- At the top of the Detailed Specification, include a “See also” or related links pointing to:
  - `docs/functional-blueprint.md` for global concepts.
  - Other module READMEs that this module interacts with directly.
  - Relevant policy modules (e.g., `src/taxonomy/config/policies/validation.py`).
- When referencing prompts, point to entries in `prompts/registry.yaml` and corresponding schema/template files.

Status Indicators
- Use these markers in `docs/MODULE_INDEX.md` or planning docs:
  - ✅ Complete — README reflects current behavior and policies.
  - 📝 Needs Update — implementation changed; README requires edits.
  - ❌ Missing — README not yet authored.

Review Checklist (per module README)
- Quick Reference captures entry points, data contracts, determinism, and observability hooks.
- Detailed Specification contains all canonical sections listed above.
- Inputs/Outputs specify semantic shapes with key fields and expected ranges.
- Rules & Invariants map to existing or planned automated tests.
- Observability counters/fields are named and discoverable in manifests/logs.
- Examples are deterministic and match current fixtures or regression manifests.
- Cross-references to related READMEs, policies, and the functional blueprint are present.

Versioning & Policy Changes
- When thresholds, label rules, or identity decisions change:
  - update `docs/policies.md` with a new policy version,
  - refresh the relevant module README(s), and
  - ensure manifests surface the new values via observability utilities.

How to Add or Update a Module README
- Start from a representative README (e.g., `src/taxonomy/pipeline/s3_token_verification/README.md`) as a template.
- Copy the canonical sections, replace content with module-specific details, and embed updated specification bullets.
- Run through the review checklist and update `docs/MODULE_INDEX.md` status accordingly.
- Provide links to manifests, regression diffs, or test runs in the PR description for reviewer context.

Anti-Patterns
- Embedding raw prompts or provider-specific implementation details (keep those under `taxonomy.llm` and `prompts/`).
- Providing prose-only descriptions for data-producing/consuming modules.
- Leaving unresolved “TBD” items without owners or timelines; use “Open Questions” with accountable follow-up.

Maintenance
- Keep module READMEs synchronized with code and policies; treat them as the canonical spec now that standalone `docs/modules/` files have been removed.
- For sweeping documentation changes (new sections, format tweaks), update this guide and `docs/MODULE_INDEX.md` in the same change.
- Record major structural updates in `CHANGELOG.md`.
- Continue using `docs/functional-blueprint.md` as the end-to-end logic reference; avoid duplicating its narrative sections inside module READMEs.

