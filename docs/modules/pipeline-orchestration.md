# Pipeline & Orchestration — Logic Spec

See also: `docs/logic-spec.md`, `docs/modules/validation.md`
Cross‑references:
- Core abstractions — `docs/modules/pipeline-core-abstractions.md`
- Phases & orchestrator — `docs/modules/orchestration-phases.md`
- CLI integration — `docs/modules/cli-pipeline-integration.md`
- Stage specs — `docs/modules/s0-raw-extraction-pipeline.md`, `docs/modules/s1-extraction-normalization-pipeline.md`, `docs/modules/s2-frequency-filtering-pipeline.md`, `docs/modules/s3-token-verification-pipeline.md`, `docs/modules/hierarchy-assembly-pipeline.md`

Purpose
- Define the `Pipeline`/`PipelineStep` abstractions and orchestrate S0–S3 plus final assembly.
- Manage checkpoints and resume semantics with deterministic execution and manifest emission.

Core Tech
- `Pipeline` + `PipelineStep` in `src/taxonomy/pipeline/__init__.py`.
- Orchestration in `src/taxonomy/orchestration/` with `TaxonomyOrchestrator`, `PhaseManager`, and `PhaseContext`.
- Checkpoints via `CheckpointManager` with artifacts under `output/runs/<run_id>/` and logs in `logs/`.

Inputs/Outputs (semantic)
- Input: Settings + policies; optional `resume_phase` token.
- Output: Run manifest with per‑phase summaries, counters, artifacts paths, and policy/version stamps.

Rules & Invariants
- Phase ordering: levelwise generation (S1 L0→L3), consolidation (S2), post‑processing (S3), finalization (assembly). S0 is runnable independently for raw extraction.
- Resume semantics: `resume_phase=X` executes X and subsequent phases; earlier phases remain intact unless forced.
- Determinism: respect seeds, fixed ordering, and stable serialization to ensure reproducible manifests.
- Checkpoints: each phase writes artifacts to a phase‑scoped directory and updates the run manifest atomically.

Core Logic
- `TaxonomyOrchestrator.run()` prepares `PhaseContext`, then `PhaseManager.execute_all(resume_from)` runs ordered phases with resume.
- Within phases, `Pipeline` executes concrete `PipelineStep`s (see core abstractions doc) and records step checkpoints.
- Levelwise generation runs S1 for L0→L3 with per‑level summaries; consolidation aggregates frequency; post‑processing verifies tokens; finalization assembles the hierarchy and emits the run manifest.

Algorithms & Parameters
- Parameterization comes from policies in `src/taxonomy/config/policies/*` and `Settings`.
- Defaults and thresholds live with the policy classes; the orchestrator stamps policy versions into the manifest.

Failure Handling
- Step failure quarantines the phase outputs and records error context in the run manifest; subsequent phases are skipped.
- Idempotent re‑runs: resuming after a failure restarts from the failed step; earlier successful phases are not recomputed unless forced.

Observability
- Counters: per‑phase `ok`, `failed`, `duration_sec`; aggregate token usage if LLM is invoked downstream.
- Artifacts: paths to phase outputs, consolidated files, and final manifests in `output/runs/<run_id>/`.
- Logs: structured log file path exposed via `Settings.paths.logs_dir`.

CLI Mapping
- See `docs/modules/cli-pipeline-integration.md` for comprehensive command mapping and examples.

Acceptance Tests
- `python main.py validate --environment development` verifies configuration loads and merges without running steps.
- Resuming from `S2` executes `S2`, `S3`, and finalization only; earlier artifacts are preserved and referenced.
- Run manifests include per‑phase summaries, durations, and policy versions.

Open Questions
- Policy pinning vs. floating: when resuming, should policies be reloaded from disk or pinned from the original run manifest?

Examples
- CLI: `python main.py run --environment development --resume-phase S2`
  - Expected: executes S2→S3→finalization; updates manifest with new timestamps and summaries.

