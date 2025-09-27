# Prompt Optimization — Logic Spec

Purpose
- Improve extraction and verification prompts under strict guardrails without changing business rules.

Core Tech
- DSPy for declarative prompt components and optimization loops.
- GEPA for guided prompt evolution/search under constraints (F1 objective, validity guardrails).
- Provider remains pluggable; evaluation harness isolated from business logic.

Inputs/Outputs (semantic)
- Input: frozen eval dataset with {id, level, text, gold_labels}
- Output: experiment manifest (params, seeds), scores (per-level F1, precision/recall), predictions, error analysis

Objectives & Guardrails
- Primary: maximize F1 on extraction.
- Guardrails: JSON validity ≥ 99.5%; schema adherence 100%; invariants preserved (no leakage of chain-of-thought; deterministic ordering).
- Secondary: latency and token cost reductions tracked but not at precision’s expense.

Search Levers (examples)
- Few-shot K ∈ {0,2,4}
- Constraint wording variants
- Example ordering seeds
- Temperature ∈ {0.0, 0.2}
- Brevity/formatting constraints

Protocol
- Stratified split (train/dev); early stop on no improvement over N trials.
- Error taxonomy: duplicates, missed synonyms, over-extractions, JSON failures.
- Report per-level deltas; never promote a variant that breaks invariants.

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
