# Observability & Reproducibility — Logic Spec

Purpose
- Ensure every decision is auditable and runs are reproducible across environments.

Core Tech
- Structured manifest files (JSON/JSONL) with deterministic IDs and checksums.
- Central counter registry to standardize metrics collection across modules.
- Optional run summarizer that samples evidence and compiles per-step reports.

Run Manifest
- Include: prompt versions, thresholds, seeds, timestamp, input summary stats, counters per step, sampled evidence.
- Record: retries, quarantined items, rule/validation outcomes, merge/split logs.

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
