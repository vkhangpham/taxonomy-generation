# Prompt Optimization — README (Developer Quick Reference)

## Quick Reference

Purpose
- DSPy-based optimization of prompts used by taxonomy tasks, producing versioned variants evaluated against task-specific metrics.

Key APIs
- Classes: `OneTimeGEPAOptimizer` — configures and runs a single optimization pass.
- Classes: `TaxonomyEvaluationMetric` — computes scalar quality for extraction/verification tasks.
- Functions: `run_one_time_optimization(dataset, config) -> OptimizedVariant`.
- Functions: `deploy_optimized_variant(variant, registry_path)` — writes new version and updates `prompts/registry.yaml`.
- Helpers: dataset loading utilities in `dataset_loader.py` and DSPy program in `dspy_program.py`.

Data Contracts
- Optimization dataset: examples with inputs and expected outputs for metrics.
- Optimized variant: `{version:str, prompt_path:str, metrics:{...}, created_at:...}` persisted alongside templates.

Quick Start
- Example flow
  - `python -m taxonomy.prompt_optimization.main --dataset path/to.jsonl --task extraction`
  - Review metrics, then `deploy_optimized_variant(...)` to make it active under policy.

Configuration
- Reads settings/policies for provider/model and budgets; integrates with `taxonomy.llm` for execution.

Observability
- Records run metrics and chosen variants; updates manifests with prompt version lineage.

See Also
- Detailed spec: this README.
- Related: `src/taxonomy/llm`, `prompts/` (templates, schemas, registry).

Maintenance
- Add regression datasets and update tests: `tests/test_one_time_optimization.py`.

## Detailed Specification

### Prompt Optimization — Logic Spec

Purpose
- Improve extraction and verification prompts under strict guardrails without changing business rules.

Core Tech
- DSPy for declarative prompt components and optimization loops.
- GEPA for guided prompt evolution/search under constraints via teacher-student reflection loops (F1 objective, validity guardrails).citeturn8open0
- Provider remains pluggable; evaluation harness isolated from business logic.

Inputs/Outputs (semantic)
- Input: frozen eval dataset with {id, level, text, gold_labels}
- Output: experiment manifest (params, seeds), scores (per-level F1, precision/recall), predictions, error analysis

Objectives & Guardrails
- Primary: maximize F1 on extraction.
- Guardrails: JSON validity ≥ 99.5%; schema adherence 100%; invariants preserved (no leakage of chain-of-thought; deterministic ordering).
- Secondary: latency and token cost reductions tracked but not at precision’s expense.

DSPy + GEPA Primer
- GEPA (Generalized Experience-based Prompt Actor) pairs the student program with a reflection LM that rewrites prompts and few-shot demos using curated feedback, while composing with other DSPy optimizers where helpful.citeturn8open0turn8open2
- Requires balanced train/dev splits so GEPA can snapshot module traces before search; the optimizer mutates prompts, reruns evaluation, and keeps Pareto-respecting improvements.citeturn8open2
- Auto budgets (`auto="small" | "medium" | "large"`) tune iteration limits, reflection minibatch sizes, and mutation breadth for quick smoke tests versus exhaustive runs.citeturn8open2
- Configure a capable reflection LM (default `gpt-4.1-mini`) plus optional teacher optimizer kwargs; the production student model remains unchanged during trials.citeturn8open3

Search Levers (examples)
- Few-shot K values defined in `policies.prompt_optimization.few_shot_k_options` (default {0,2,4})
- Constraint wording variants from `policies.prompt_optimization.constraint_variants`
- Example ordering seeds (still randomized via `ordering_seed`)
- Temperature values from `policies.prompt_optimization.temperature_variants` (default {0.0, 0.2})
- Brevity/formatting constraints

Metric & Feedback Design
- Metrics must return `dspy.ScoreWithFeedback(score, feedback)` so GEPA can blend numeric improvements with actionable critiques; score-only metrics stall the reflection loop.citeturn8open2turn9open2
- Keep guardrail checks (JSON validity, schema adherence, invariants) inside the metric and surface violations in the feedback text so GEPA prioritizes structural fixes.citeturn9open2
- Compose module-aware feedback (missing labels, casing issues, over-extractions) to give GEPA enough context for targeted prompt rewrites instead of global resets.citeturn9find0

Protocol
- Stratified split (train/dev); early stop on no improvement over N trials.
- Error taxonomy: duplicates, missed synonyms, over-extractions, JSON failures.
- Report per-level deltas; never promote a variant that breaks invariants.
- Persist lever sweeps: the optimization report now records `lever_trials` with the score and guardrail summary for every searched configuration, plus `selected_config` for the deployed choice.

DSPy Integration Notes
- Wrap extraction logic in typed DSPy `Signature` classes and compose them into a program so GEPA can serialize module traces and mutate prompts safely.citeturn9find0
- Prepare train/dev splits as `dspy.Dataset` objects carrying ids and metadata, then call `dspy.compile(program, trainset=train, evalset=dev, optimizer=gepa)` to kick off optimization.citeturn9open0turn9open2
- Persist `gepa.best_program`, `gepa.stats`, and evaluation artifacts alongside existing manifests to feed regression checks and guardrail audits.citeturn8open2turn9open2

Acceptance Tests
- On the same eval set, the chosen prompt variant improves F1 and maintains guardrails.
- All outputs remain strictly parseable JSON across the entire run.

Open Questions
- Should we include negative examples (non-entity lines) to reduce over-extraction on noisy sources?

Examples
- Example A: Eval dataset line
  - Input:
    ```json
    {"id": "ex17", "level": 2, "text": "Our research includes computer vision, robotics, and NLP.", "gold_labels": ["computer vision", "robotics", "nlp"]}
    ```
  - Baseline prediction: ["computer vision", "nlp"] → P=1.0, R=0.67, F1=0.8
  - Variant (few-shot=2, strict schema wording): ["computer vision", "robotics", "nlp"] → P=1.0, R=1.0, F1=1.0

- Example B: JSON validity guardrail
  - A variant with higher recall but 2% invalid JSON is rejected despite F1 gain; guardrail requires ≥ 99.5% validity.

- Example C: Cost/latency tracking
  - Two variants with equal F1; choose lower token cost if within ±0.5% F1.

