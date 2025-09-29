# Functional Blueprint: Taxonomy Generation & Prompt Optimization

Note
- This blueprint defines the system’s functional requirements and logic specification. It complements the module READMEs under `src/taxonomy/**/README.md` and provides end-to-end context when you need deeper reasoning about behaviors, invariants, and flows.

This document defines what the system must do — the behaviors, rules, and guarantees — without prescribing any file layout, frameworks, or implementation details. It preserves logic so you can rebuild from scratch with freedom of structure.

## Purpose
- Construct a four‑level academic taxonomy from institutional sources with explainable decisions and reproducible outputs.
- Improve extraction fidelity via prompt optimization while keeping business rules and invariants intact.

## Scope
- Levels: 0 Colleges/Schools → 1 Departments → 2 Research Areas → 3 Conference Topics.
- Steps: S0 Raw Extraction → S1 Extraction & Normalization (LLM) → S2 Cross‑Institution Frequency Filtering → S3 Single‑Token Verification (LLM + rules).
- Cross‑cutting: Deduplication, Disambiguation, Validation (rule/web/LLM), Hierarchy Assembly, Observability.

## Core Tenets
- Single source of truth for prompts and thresholds (no inline ad‑hoc instructions).
- Progressive refinement: each step tightens quality using explicit gates.
- Determinism where possible: fixed seeds, stable sort keys, idempotent operations.
- Error containment: every step produces auditable artifacts and reasons for keeps/drops.
- Functional mindset: pure transformations over hidden global state.
- Centralized LLM package: all LLM calls use the project LLM package (DSPy-backed), which loads optimized prompts from disk by key; business logic never embeds prompt text.

## Top‑Level Run Logic (Orchestration)
- Phase 1 — Generate by Level (0 → 3)
  - For each level in order: run S0 (raw extraction) → S1 (LLM extraction/normalization) → S2 (cross‑institution filtering) → S3 (single‑token verification).
  - Output of this phase is a staged, per‑level set of candidates with provenance and gate rationales.

- Phase 2 — Consolidate Raw Term Universe
  - Combine staged outputs from all four levels into a single raw term universe (terms + parent anchors/lineage) for post‑processing.

- Phase 3 — Post‑Processing Pipeline
  - Validate → Enrich (Web Mining) → Disambiguate → Deduplicate, in that order.
  - Enrichment augments evidence (web snapshots, snippets); it is typically run once per TTL window.
  - Validation, Disambiguation, and Deduplication may be iterated multiple times until stable (no changes).

- Phase 4 — Resume and Maintainability
  - Every phase emits persistent, auditable artifacts and operation logs (e.g., validations, SplitOps, MergeOps).
  - Runs are re‑entrant: you can resume from any completed phase, or re‑run iterative phases until convergence.
  - Enrichment honors TTL; other phases are idempotent given identical inputs and policies.

- Phase 5 — Finalization
  - Assemble the four‑level hierarchy (acyclic, unique paths), generate summaries, and freeze a manifest with versions, thresholds, counters, and evidence samples.

## Pipeline Logic (Implementation‑Agnostic)
- S0 Raw Extraction
  - Fetch institutional content (catalogs, department lists, research groups, conference topics).
  - Segment into records with provenance (URL, institution, timestamp, section anchors).
  - Apply structural filters: language check, length bounds, allowed characters, boilerplate removal.

- S1 Extraction & Normalization
  - Use a prompt to extract level‑appropriate candidate concepts from each record.
  - Normalize to canonical surface forms (case, punctuation, spacing, diacritics, acronym policy).
  - Emit parent anchors (e.g., map a department to its college) and keep aliases/synonyms.

- S2 Cross‑Institution Frequency Filtering
  - Aggregate candidate supports across distinct institutions and independent sources.
  - Apply per‑level thresholds (Areas/Topics stricter than Colleges/Departments).
  - Retain support evidence: counts, institution list, representative snippets.

- S3 Single‑Token Verification
  - Ensure labels conform to minimal canonical token rules for downstream use.
  - Combine deterministic rule checks with an LLM confirmation prompt; exceptions require justification.

## Quality Gates (What “Pass” Means)
- Structural: valid text, expected language, within length, allowed characters.
- Semantic: normalized equivalence groups; alias tracking; consistent parentage.
- Frequency: minimum distinct‑institution support; robust to near‑duplicate pages.
- Domain: level‑appropriate vocabulary; aligns with academic norms.

## Deduplication
- Build similarity evidence from normalized strings, token overlap, abbreviation expansion, and domain heuristics.
- Merge highly similar items into a single canonical node; accumulate provenance and support.
- Canonical selection policy: shortest normalized label → highest cross‑institution support → stable tie‑break.

## Disambiguation
- Detect identical surface forms with conflicting contexts/parents.
- Split into distinct senses leveraging parent lineage, context windows, and an LLM disambiguation prompt.
- Preserve rationale for each split and maintain traceability to originals.

## Validation (Three Modes)
- Rule: regex/vocabulary checks for form and level appropriateness.
- Web: presence/consistency in authoritative pages; store evidence snippets.
- LLM: entailment‑style yes/no with strict JSON outputs; no free‑form prose.

## Hierarchy Assembly
- Assemble a DAG constrained to four levels with acyclicity and unique L0→L3 paths.
- Enforce parent‑child constraints and prevent shortcuts or cross‑level leaks.
- Produce a final manifest with counts per level, merge/split logs, and validation summaries.

## Non‑Functional Requirements
- Reproducibility: seed control, deterministic ordering, versioned prompts/thresholds.
- Observability: counters per step (kept/dropped/merged/split), token usage (if applicable), error rates.
- Failure isolation: quarantine non‑conforming records with explicit reasons; never fail the batch.

## Acceptance Criteria
- Small, known fixtures reproduce prior taxonomy decisions (within agreed tolerances).
- Every kept node includes provenance, support evidence, and gate pass reasons.
- No cycles; dedup merges and disambiguation splits are explainable and reversible via logs.

## Guardrails for a Fresh Implementation
- Keep external fetching and model calls behind thin, swappable boundaries.
- Centralize prompts and thresholds; version anything that can change outputs.
- Prefer explicit, immutable artifacts between steps over in‑memory handoffs.

## Cutover (Logic‑First)
1) Recreate prompts and normalization rules; freeze thresholds per level.
2) Rebuild S0→S3 behaviors with fixtures covering edge cases (acronyms, hyphenation, cross‑listed units).
3) Add dedup/disambiguation and the three validation modes; verify global invariants.
4) Assemble the hierarchy and compare against historical fixtures; document deltas.
5) Optimize prompts on a frozen eval set; improvements must preserve invariants and gates.

## Open Questions to Decide Early
- Multi‑word policy at Levels 2/3 (allowlist vs. general exceptions).
- Thresholds for “distinct institution” when campuses share governance.
- Canonical label tie‑break priority order beyond length/support.
- Treatment of cross‑listed departments across multiple colleges.

