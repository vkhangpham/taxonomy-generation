# Observability & Reproducibility — Logic Spec

Purpose
- Ensure every decision is auditable and runs are reproducible across environments.

Core Tech
- Structured manifest files (JSON/JSONL) with deterministic IDs and checksums.
- Central counter registry to standardize metrics collection across modules.
- Optional run summarizer that samples evidence and compiles per-step reports.

Run Manifest
- Observability manifest exports counters, performance, prompt versions, thresholds, seeds, and evidence snapshots via `ObservabilityManifest.build_payload`.
- Legacy consumers continue to read `evidence_samples`, `operation_logs`, and configuration sections that are hydrated from the observability snapshot for backward compatibility.
- Deterministic checksums are generated for both the overall manifest and the observability payload.

Counters (minimum set)
- S0: pages_seen, pages_failed, blocks_total, blocks_kept, by_language
- S1: records_in, candidates_out, invalid_json, retries
- S2: candidates_in, kept, dropped_insufficient_support
- S3: checked, passed_rule, failed_rule, passed_llm, failed_llm
- Dedup: pairs_compared, edges_kept, components, merges_applied
- Disambig: collisions_detected, splits_made, deferred
- Validation: checked, rule_failed, web_failed, llm_failed, passed_all
- Hierarchy: nodes_in, nodes_kept, orphans, violations, edges_built

Determinism
- Fixed seeds for any stochastic component; stable tie-breakers; sorted processing.
- Canonical representative selection must be deterministic.

Failure Isolation
- Quarantine artifacts with explicit reasons; batch proceeds even with partial failures.

Phase Manager Integration
- Each orchestration phase executes inside an observability phase context; start, completion, and failure events are logged automatically.
- Level generators surface S1 counters; consolidation maps into S2 metrics; post-processing emits S3 checks; finalisation records hierarchy summaries.
- Resume skips create explicit `resume_skip` operation entries to preserve audit trails when resuming a run.

S1 Extraction Integration
- `ExtractionProcessor` now routes all metrics through the shared `ObservabilityContext` while keeping a compatibility snapshot for legacy tests.
- Evidence sampling captures representative successes and failures; provider errors and invalid payloads are quarantined with structured payloads.
- Metadata generation prefers observability snapshots (counters, quarantine totals, provider error counts) ensuring JSON artifacts mirror the canonical registry.
- Performance metrics are reported per batch to enable throughput monitoring without bespoke timers in callers.

## Downstream Observability Adapter (S2 Reference)

Purpose
- Provide a copy-paste-ready integration contract any processor can follow when wiring into the observability stack.
- S2 frequency filtering acts as the reference implementation: counters, evidence, operations, and manifests are all powered by the shared adapter.

Standard Pattern
- Accept `observability: ObservabilityContext | None` in constructors and store it on the processor.
- Wrap processor execution in `with observability.phase("<Phase>") as phase:` and fall back to `contextlib.nullcontext()` when observability is disabled.
- Replace ad-hoc counters with registry updates (`phase.increment("candidates_in")`, `phase.increment("kept")`, etc.).
- Emit evidence through `phase.evidence(...)` for both positive and negative outcomes using JSON-safe payloads (candidate summaries, rationale, thresholds).
- Record performance via `phase.performance({...})` so throughput and histogram data lands in the manifest without custom timers.
- Capture lifecycle log entries with `phase.log_operation(operation="start"|"complete"|"failed", payload=...)` and bubble exceptions after logging failures.
- When thresholds or seeds exist, register them once via `observability.register_threshold("Phase.key", serialized_threshold)` and `observability.register_seed("Phase.key", value)` before processing begins.
- Leave legacy stats in place for compatibility, but reconcile them with the observability snapshot so legacy consumers see aligned values.

Integration Hooks Reference
- **Constructor**: `processor = Processor(..., observability=observability_context)`
- **Phase context**: `with observability.phase("S2") as phase_handle:`
- **Counters**: `phase_handle.increment("candidates_in", total_inputs)` and `phase_handle.increment("kept")` per successful decision.
- **Evidence**: `phase_handle.evidence(category="frequency_filtering", outcome="kept", payload={...})`
- **Quarantine**: `phase_handle.quarantine(reason="processing_error", payload={...})` for deferred items.
- **Performance**: `phase_handle.performance({"elapsed_seconds": elapsed, ...})`
- **Operations**: `phase_handle.log_operation(operation="frequency_aggregation_complete", payload=metrics)`
- **Threshold registration**: `observability.register_threshold("S2.level_2", {...})`
- **Snapshot reuse**: call `observability.snapshot()` after processing to hydrate metadata (`stats`, `observability_checksum`, evidence samples, quarantine summaries).

Rollout Checklist (Remaining Processors)
1. **Validation Processor (S3)**
   - Counters: `checked`, `rule_failed`, `web_failed`, `llm_failed`, `passed_all`
   - Evidence: emit success/failure payloads for each gate; quarantine undecidable cases
   - Performance: record validator latency and throughput per batch
2. **Deduplication Processor**
   - Counters: `pairs_compared`, `edges_kept`, `components`, `merges_applied`
   - Evidence: sample merged pairs with similarity scores; log discarded edges
   - Performance: track union-find iterations and merge latency
3. **Disambiguation Processor**
   - Counters: `collisions_detected`, `splits_made`, `deferred`
   - Evidence: capture representative collision resolutions and deferred items
   - Quarantine: park unresolved collisions with structured payloads
4. **Hierarchy Assembly Processor**
   - Counters: `nodes_in`, `nodes_kept`, `orphans`, `violations`, `edges_built`
   - Evidence: record sampled promotions and constraint violations
   - Performance: log DAG construction timings, including validation retries
5. **Web Mining Processor (S0)**
   - Counters: `pages_seen`, `pages_failed`, `blocks_total`, `blocks_kept`, `by_language`
   - Evidence: sample successful scrapes and blocked responses categorized by language
   - Quarantine: store blocked URLs with HTTP diagnostics for replay

Testing Requirements
- Unit coverage must assert counter deltas, evidence capture, and phase stack hygiene (`registry.current_phase() is None`).
- Integration suites should drive end-to-end flows (Phase Manager → processor → manifest) and confirm metadata includes counters, evidence, operations, thresholds, and checksums.
- Determinism tests must compare observability snapshots (excluding timestamps) for identical inputs and seeds.
- Error-path tests should verify failure operations and quarantines are emitted without breaking primary processing.
- Reference tests: `tests/test_s2_frequency_filtering.py` (unit contract) and `tests/test_s2_observability_integration.py` (pipeline/manifest contract) illustrate the expected structure.

Examples
- S2 reference payload (`tests/test_s2_observability_integration.py`) demonstrates how metadata now embeds `observability.counters.kept` and evidence samples.
- Adapter snippet:
  ```python
  with observability.phase("S2") as phase:
      result = aggregator.aggregate(items)
      for decision in result.kept:
          phase.increment("kept")
          phase.evidence(
              category="frequency_filtering",
              outcome="kept",
              payload=_decision_evidence_payload(decision),
          )
      phase.performance({"candidates_processed": len(items), "elapsed_seconds": elapsed})
  ```


Testing & Tooling
- Unit tests cover counter registry invariants, ObservabilityContext behaviour, PhaseManager orchestration, and S1 pipeline integrations with success and failure scenarios.
- New test suites validate deterministic snapshots, evidence sampling, quarantine reporting, and manifest export structure.
- Use pytest fixtures with temporary checkpoints to verify resume state without polluting working directories.

Acceptance Tests
- Two runs with identical inputs and seeds yield identical outputs and manifests.
- Manifests contain enough information to reconstruct all gate decisions.

Examples
- Example A: Run manifest excerpt
  ```json
  {
    "run_id": "2025-09-27T10:15:00Z_u4_lv2",
    "prompts": {"taxonomy.extract": "v3", "verify.single_token": "v1"},
    "thresholds": {"L2_min_inst": 2, "L3_min_inst": 2, "L3_min_src": 3},
    "seed": 42,
    "counters": {
      "S1": {"records_in": 120, "candidates_out": 210, "invalid_json": 0},
      "S2": {"candidates_in": 210, "kept": 160, "dropped_insufficient_support": 50},
      "Dedup": {"pairs_compared": 540, "merges_applied": 18}
    },
    "samples": {
      "kept_examples": ["computer vision", "robotics"],
      "dropped_examples": [{"label": "graph transformers", "reason": "inst_count=1"}]
    }
  }
  ```

- Example B: Determinism check
  - Re-run with same seed and inputs → identical `run_id` hash, counters, and artifacts checksums.

## Module Reference

Core Classes
- ObservabilityContext (`src/taxonomy/observability/context.py`)
  - Process‑wide facade for counters, evidence, quarantine, operations, and performance.
  - Provides `phase(name)` context manager that ensures balanced start/complete/failed events.
- CounterRegistry (`src/taxonomy/observability/registry.py`)
  - Standardizes counter names and storage; exposes increment/add/set operations.
- EvidenceSampler (`src/taxonomy/observability/evidence.py`)
  - Captures representative outcomes; configurable sampling rates and categories.
- QuarantineManager (`src/taxonomy/observability/quarantine.py`)
  - Records failures with reason and JSON‑safe payloads for replay.
- ObservabilityManifest (`src/taxonomy/observability/manifest.py`)
  - Builds export payload with counters, performance, operations, prompts, thresholds, seeds, and checksums.
- Determinism Utilities (`src/taxonomy/observability/determinism.py`)
  - `stable_hash`, `canonical_json`, `freeze` for checksum and comparison ignoring incidental ordering.

Phase Context Management
- Always wrap work in `with observability.phase("S<idx>") as phase:`.
- Use `phase.increment`, `phase.evidence`, `phase.quarantine`, `phase.performance`, and `phase.log_operation`.
- On exceptions, `phase.failed` is logged automatically before the exception bubbles.

Performance Tracking
- Record per‑batch elapsed seconds and sizes; registry aggregates histograms for manifest.

Thresholds & Seeds
- Register once per run: `observability.register_threshold("S2.level_2", {...})`, `observability.register_seed("global", 42)`.
- Values are copied into manifest for audit and replay.

Config Integration
- Observability policy controls sampling rates, verbosity, and counter namespaces.
- Settings expose paths for logs, manifests, and run outputs consumed by the manifest exporter.

Quarantine Scenarios (examples)
- `processing_error`: unexpected exception inside a phase.
- `invalid_payload`: schema mismatch or unparseable external input.
- `provider_error`: LLM/Web errors exceeding retry budget.

Snapshot Generation
- `observability.snapshot()` returns an immutable view used by metadata builders and tests.
