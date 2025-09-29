# S2 · Frequency Filtering

Purpose
- Filter candidate tokens by frequency patterns and institution support to reduce noise.

Key Classes
- `S2Processor`: Orchestrates aggregation and filtering per level.
- `CandidateAggregator`: Computes counts, co‑occurrence, and support metrics.
- `InstitutionResolver`: Weighs support by institution signals.
- `FrequencyFilteringPipeline`: Applies thresholds and emits filtered candidates.

Data Contract
- `Candidate` → filtered `Candidate` (+ metrics, decision rationale).

Workflow Highlights
- Frequency analysis, institution weighting, threshold application, and decision logging.

CLI
- Run filtering: `python main.py pipeline generate --step S2 --level <N>`

Related Docs
- Detailed pipeline: `docs/modules/s2-frequency-filtering-pipeline.md`

