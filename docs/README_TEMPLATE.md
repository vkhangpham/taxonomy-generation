# <Module Name> — README (Developer Quick Reference)

Purpose
- 1–2 sentences: what this package/subpackage does and where it sits in the pipeline.

Key APIs
- Classes: `<ClassName>` — brief role.
- Functions: `<fn_name(args) -> out>` — brief role.

Data Contracts
- Input: shape/schema; key fields with types.
- Output: shape/schema; key fields with types.
- Error/Warning surfaces: exceptions, return enums, or sentinel values.

Quick Start
- Import/instantiate example with minimal code snippet.
- One end‑to‑end call demonstrating typical usage and expected output.

Configuration
- Relevant settings/policy keys and where they are read from.
- Defaults and tunable ranges; link to `docs/policies.md` when applicable.

Dependencies
- Internal: sibling modules used.
- External: third‑party libraries; runtime/system dependencies.

Observability
- Counters/metrics emitted; manifest fields produced; log tags.

Determinism & Retry
- Notes on seeds, idempotency, and resume semantics.

See Also
- Detailed logic spec: `docs/modules/<module-doc>.md`.
- Related modules: <bulleted list with brief relation>.

Maintenance
- Owner(s) or team, update checklist, and test pointers.

