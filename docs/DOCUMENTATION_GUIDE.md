# Documentation Guide

Purpose
- Establish a consistent, implementation-agnostic documentation standard for all modules under `src/taxonomy/`.
- Ensure every module doc is actionable for implementers and reviewers and traceable to policy.

Scope
- Applies to all docs in `docs/modules/` and any new module documentation.
- Builds on patterns in `docs/modules/raw-extraction.md`, `docs/modules/llm.md`, and the cross-cutting `docs/logic-spec.md`.

Canonical Structure (per module doc)
- Title — “<Module Name> — Logic Spec”.
- Purpose — What the module is responsible for (1–3 bullets).
- Core Tech — Libraries, frameworks, or patterns required (agnostic to specific providers when possible).
- Inputs/Outputs (semantic) — Shapes and contracts, not concrete classes, unless necessary.
- Rules & Invariants — Hard constraints that must hold true; keep testable.
- Core Logic — High-level algorithm or flow; defer code-specific details.
- Algorithms & Parameters — Named algorithms, defaults, and tunables with typical ranges (optional when trivial).
- Failure Handling — What to do on partial/invalid inputs, timeouts, or provider issues.
- Observability — Counters, histograms, sampling, logging and manifest fields.
- Acceptance Tests — Behavior-focused scenarios that can be encoded in pytest.
- Open Questions — Known ambiguities and decisions to be made.
- Examples — Small, concrete JSON or text snippets that illustrate inputs/outputs.

Writing Style
- Be implementation-agnostic: prefer “must/should” language and semantic contracts.
- Prefer bullets over paragraphs; keep each bullet one line when possible.
- Include concrete JSON examples; avoid prose-only descriptions for data.
- Keep numbers explicit (e.g., thresholds with default and range) and tie to policies when relevant.
- Use stable terminology consistent with `docs/logic-spec.md` and policy names in `src/taxonomy/config/policies`.

File Naming & Placement
- Place new module docs in `docs/modules/`.
- Use lowercase hyphenated names aligned with package names (e.g., `raw-extraction.md`, `hierarchy-assembly.md`).
- For cross-cutting topics that span packages, prefer a single doc named by the concept (e.g., `pipeline-orchestration.md`).

Cross-Referencing
- At the top of each module doc, include a “See also” line referencing:
  - `docs/logic-spec.md` (global concepts/policies), and
  - any sibling module docs it interacts with directly.
- Link to policy modules by name (e.g., “validation policy: `src/taxonomy/config/policies/validation.py`”).

Status Indicators
- Use the following status markers in planning indices or checklists:
  - ✅ Complete — in sync with code and policies.
  - 📝 Needs Update — behavior/thresholds changed; doc requires edit.
  - ❌ Missing — not yet documented.

Review Checklist (per module doc)
- Covers all canonical sections listed above.
- Inputs/Outputs specify semantic shapes with key fields.
- Rules & Invariants are testable and map to existing or planned tests.
- Observability counters/fields are named and discoverable in manifests/logs.
- Examples use deterministic, minimal JSON and reflect current policies.
- Cross-references to `docs/logic-spec.md` and relevant module docs are present.

Versioning & Policy Changes
- Any thresholds, label rules, or identity decisions must:
  - update `docs/policies.md` with a new policy version,
  - be reflected in the relevant module doc(s), and
  - surface in emitted manifests as per observability rules.

How to Add a New Module Doc
- Copy `docs/MODULE_TEMPLATE.md` to `docs/modules/<name>.md`.
- Fill each section, keeping bullets concise and testable.
- Add “See also” references and status to `docs/MODULE_INDEX.md`.
- Submit with links to manifests or regression diffs when applicable.

Anti‑Patterns
- Inline prompts or provider-specific details in module docs (keep those in `taxonomy.llm` and the prompt registry).
- Prose-only descriptions without JSON examples for data-producing/consuming modules.
- Unbounded “TBD” items — prefer “Open Questions” with a decision owner or date.

See also
- `docs/logic-spec.md`
- `docs/modules/raw-extraction.md`
- `docs/modules/llm.md`

