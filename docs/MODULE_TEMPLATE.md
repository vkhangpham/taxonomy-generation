# <Module Name> — Logic Spec

See also: `docs/logic-spec.md`, related: <other-module-docs.md>

Purpose
- <1–3 bullets: what this module is responsible for>

Core Tech
- <libraries, frameworks, or patterns>
- <keep provider-agnostic when possible>

Inputs/Outputs (semantic)
- Input: <shape/contract; key fields>
- Output: <shape/contract; key fields>

Rules & Invariants
- <hard constraints that must always hold>
- <naming/normalization rules, level guards, etc.>

Core Logic
- <high-level flow or algorithm; avoid code details>
- <ordering/determinism requirements>

Algorithms & Parameters
- <named algorithms>
- Defaults: <k=v>; Ranges: <min..max>; Policy keys: <path in config>

Failure Handling
- <what to do on invalid inputs/timeouts/provider errors>
- <quarantine/continue semantics>

Observability
- Counters: <names>
- Timers/histograms: <names>
- Manifest fields: <names and brief meaning>

Acceptance Tests
- <scenario 1: input → expected behavior>
- <scenario 2: input → expected behavior>

Open Questions
- <decision needed or ambiguity>

Examples
- Example A
  - Input:
    ```json
    <minimal JSON input>
    ```
  - Output:
    ```json
    <minimal JSON output>
    ```

