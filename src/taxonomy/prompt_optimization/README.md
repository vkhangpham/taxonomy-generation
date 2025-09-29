# Prompt Optimization — README (Developer Quick Reference)

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
- Detailed spec: `docs/modules/prompt-optimization.md`.
- Related: `src/taxonomy/llm`, `prompts/` (templates, schemas, registry).

Maintenance
- Add regression datasets and update tests: `tests/test_one_time_optimization.py`.

