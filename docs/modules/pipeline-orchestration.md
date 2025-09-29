# Pipeline & Orchestration — Logic Spec

See also: `docs/logic-spec.md`, `docs/modules/validation.md`, `docs/modules/hierarchy-assembly.md`

Purpose
- Define the `Pipeline` and `PipelineStep` abstractions and orchestrate S0–S3 phases plus consolidation/post‑processing.
- Manage checkpoints and resume semantics across steps with deterministic execution and manifest emission.

Core Tech
- Pure-Python orchestration with a lightweight `Pipeline` container and `Protocol` for steps (`src/taxonomy/pipeline/__init__.py`).
- Orchestration entry points and phase runners in `src/taxonomy/orchestration/`.
- Checkpointed artifacts under `output/runs/<run_id>/`; logs under `logs/`.

Inputs/Outputs (semantic)
- Input: Settings + policies; optional `resume_phase` token.
- Output: Run manifest with per‑phase summaries, counters, artifacts paths, and policy/version stamps.

Rules & Invariants
- Phase ordering: S0 → S1 → S2 → S3 → consolidation → post‑processing → finalization.
- Resume semantics: when `resume_phase=X`, execute X and all subsequent phases; do not repeat earlier phases unless explicitly requested.
- Determinism: respect seeds, fixed ordering, and stable serialization to ensure reproducible manifests.
- Checkpoints: each phase writes artifacts to a phase‑scoped directory and updates the run manifest atomically.

Core Logic
- Build `Pipeline` and register step instances in order with unique `name`s matching phase identifiers (e.g., `S0_raw_extraction`).
- Execute steps via `Pipeline.execute(resume_from?)`, which selects the starting index by `name` and runs to completion.
- Phase runners (`orchestration/phases.py`) encapsulate multi‑level operations:
  - Levelwise generation (e.g., L0→L3) with per‑level summaries.
  - Consolidation across levels (dedup/disambiguation merge results).
  - Post‑processing and final manifest assembly.

Algorithms & Parameters
- Not algorithm-heavy; parameterization comes from policies in `src/taxonomy/config/policies/*` and `Settings`.
- Defaults and thresholds live with the policy classes; the orchestrator reads and stamps their versions.

Failure Handling
- Step failure quarantines the phase outputs and records error context in the run manifest; subsequent phases are skipped.
- Idempotent re‑runs: resuming after a failure restarts from the failed step; earlier successful phases are not recomputed unless forced.

Observability
- Counters: per‑phase `ok`, `failed`, `duration_sec`; aggregate token usage if LLM is invoked downstream.
- Artifacts: paths to phase outputs, consolidated files, and final manifests in `output/runs/<run_id>/`.
- Logs: structured log file path exposed via `Settings.paths.logs_dir`.

Acceptance Tests
- `python main.py validate --environment development` verifies configuration loads and merges without running steps.
- Resuming from `S2` executes `S2`, `S3`, and finalization only; earlier artifacts are preserved and referenced.
- Run manifests include per‑phase summaries, durations, and policy versions.

Open Questions
- Policy pinning vs. floating: when resuming, should policies be reloaded from disk or pinned from the original run manifest?

Examples
- CLI: `python main.py run --environment development --resume-phase S2`
  - Expected: executes S2→S3→finalization; updates manifest with new timestamps and summaries.

