# S1 · Extraction & Normalization

## Quick Reference

Purpose
- Generate candidate **research topics/fields** from `SourceRecord` inputs using LLM extraction and apply normalization rules. For Level 0, this means extracting the research domain represented by top-level academic units (e.g., "School of Medicine" → "medicine"), not the unit names themselves.

Key Classes
- `S1Processor`: Coordinates extraction by level and aggregates outputs.
- `ExtractionProcessor`: Interfaces with `taxonomy.llm` for deterministic JSON extraction.
- `CandidateNormalizer`: Applies canonicalization and policy rules.
- `ParentIndex`: Resolves parents for hierarchical levels.

Data Contract
- `SourceRecord` → `Candidate` (+ stats, provenance).

Workflow Highlights
- Level‑specific processing, normalization, parent resolution, and aggregation with deterministic seeds.

CLI
- Generate S1 candidates: `python main.py pipeline generate --step S1 --level <N>`

Examples
- Run for level 0: `... --level 0`; repeat for deeper levels as needed.

Related Docs
- Detailed pipeline: this README

## Detailed Specification

### Extraction & Normalization (S1) — Logic Spec

Purpose
- Extract level-appropriate candidate concepts from SourceRecords using a deterministic prompt, then normalize to canonical surface forms and attach parent anchors.

Core Tech
- DSPy-managed extraction prompts (level-aware) with strict JSON outputs and deterministic settings.
- Shared normalization utilities (case, punctuation, diacritics, acronym mapping) applied post-LLM.

LLM Usage
- All calls go through the LLM package: `llm.run("taxonomy.extract", variables)`.
- The package loads the active, optimized prompt from disk via the registry; no inline prompt strings.

Inputs/Outputs (semantic)
- Input: SourceRecord[]
- Output: Candidate[] with fields: level, label, normalized, parents(anchors or ids), aliases[], support{records, institutions}, notes?

Rules & Invariants
- Determinism: enforce temperature=0.0 (or equivalent) and sorted outputs by normalized label.
- Strict JSON: prompt must forbid free-form prose; only schema-compliant arrays.
- Normalization: apply case/punctuation/whitespace/diacritics/acronym policies consistently across levels; ambiguous acronym expansions (e.g., “AI”) are opt-in via policy and only surface when context supports them.
- Parent anchoring: include best-effort parent references or textual anchors; never hallucinate parents absent evidence. Anchor resolution normalizes against all shallower levels and, when no stable identifier exists, emits a scoped fallback (`L{level}:{normalized}`) to avoid collisions.

Core Logic
- Prompt level definition (what belongs at L0/L1/L2/L3) with 1–2 minimal examples per level. **L0 extracts research fields/domains** (e.g., "communication", "medicine", "business", "law") from top-level academic unit names, aligning with L1-L3 behavior of extracting research topics.
- Extract labels; generate normalized forms; collect plausible aliases when present.
- Attach SourceRecord provenance to support and compute an initial institution set.

Normalization Rules (summary)
- Lowercase for comparison; preserve display case separately if needed.
- Collapse spaces; normalize hyphens/underscores; strip trailing punctuation.
- Fold diacritics for comparison; keep original in aliases.
- Remove boilerplate prefixes at L1 (e.g., “Department of …”), keeping alias.
- Acronyms: retain both short and expanded forms when context confirms the expansion or the level policy allows it; ambiguous short forms are skipped unless explicitly enabled.

Failure Handling
- If JSON invalid, retry with constrained re-ask (same input, schema reminder) and pass a `repair` hint on subsequent attempts; retryable provider errors are re-attempted with exponential backoff until the budget is exhausted. On repeated failure, quarantine record.
- Drop empty/invalid labels with reason; keep record-level logs for audit.

Observability
- Counters: records_in, records_processed_total, candidates_out, invalid_json, provider_errors, retries, quarantined.
- Drift: track normalized length distribution and alias rates by level.

Acceptance Tests
- Given fixture records, extracted candidates match expected sets and are stably ordered.
- Normalization removes boilerplate and folds diacritics as specified.
- Parent anchors included when textual evidence exists; absent otherwise.

Open Questions
- How aggressive should acronym expansion be at L2/L3?
- Should we allow multi-word preservation at L3 when abbreviation harms clarity?

Examples
- Example A0: Level 0 research field extraction
  - Input SourceRecord:
    ```json
    {"text": "Annenberg School for Communication", "provenance": {"institution": "upenn", "url": "https://upenn.edu/academics"}}
    ```
  - Expected Candidates:
    ```json
    {"level": 0, "label": "communication", "normalized": "communication", "parents": [], "aliases": ["communications"], "support": {"institutions": ["upenn"], "records": ["r0"]}}
    ```
  - Note: The unit name "Annenberg School for Communication" is transformed into the research field "communication".

- Example A1: Level 1 department normalization
  - Input SourceRecord:
    ```json
    {"text": "Department of Computer Science", "provenance": {"institution": "u2", "url": "https://u2.edu/eng/departments"}}
    ```
  - Expected Candidates (sorted by normalized):
    ```json
    {"level": 1, "label": "Department of Computer Science", "normalized": "computer science", "parents": ["L0:college of engineering"], "aliases": ["dept. of computer science", "cs"], "support": {"institutions": ["u2"], "records": ["r1"]}}
    ```

- Example B: Level 2 research areas with diacritics
  - Input SourceRecord:
    ```json
    {"text": "Álgebra Lineal; Aprendizaje Automático", "provenance": {"institution": "u3", "url": "https://u3.edu/math/research"}}
    ```
  - Expected Candidates:
    ```json
    {"level": 2, "label": "Álgebra Lineal", "normalized": "algebra lineal", "aliases": ["álgebra lineal"], "support": {"institutions": ["u3"], "records": ["r2"]}}
    {"level": 2, "label": "Aprendizaje Automático", "normalized": "aprendizaje automatico", "aliases": ["aprendizaje automático"], "support": {"institutions": ["u3"], "records": ["r2"]}}
    ```

- Example C: Parent anchoring from context
  - Given page header "College of Engineering" and section "Departments", extracted L1 candidates include parent anchor "college of engineering" and resolve to `L0:college of engineering`; absent such context, parents remain empty and are carried forward for later resolution.

CLI Usage
- `--batch-size` controls how many SourceRecords are processed per extraction chunk.
- `--resume-from` points to a checkpoint JSON file storing processed record counts and aggregated candidates; when present, the CLI skips completed records and resumes aggregation without reprocessing.

### S1 Extraction & Normalization Pipeline

This document specifies how `SourceRecord` inputs are transformed into normalized `Candidate` outputs per taxonomy level.

#### Scope

- `src/taxonomy/pipeline/s1_extraction_normalization/processor.py`
- `src/taxonomy/pipeline/s1_extraction_normalization/main.py`
- `src/taxonomy/pipeline/s1_extraction_normalization/extractor.py`

#### Components

- `S1Processor`: level-aware coordinator for batching, extraction, normalization, and aggregation.
- `ExtractionProcessor`: LLM-backed pattern extractor with deterministic settings (temp=0, JSON mode).
- `CandidateNormalizer`: canonicalizes casing, ASCII form, and trims stop terms; enforces the 1–5 token span.
- `ParentIndex`: resolves parent references where applicable to maintain level consistency.

#### Data Flow

`SourceRecord` → LLM extraction → raw candidates → normalization → parent resolution → aggregated `Candidate`

#### Checkpointing

- Per-level checkpoints capture progress and allow resuming mid-level without reprocessing completed batches.

#### Observability

- Token accounting, extraction yield rates, normalization drop reasons.

#### CLI

- `pipeline generate --step S1 --level <0..3>`
- Entry: `extract_candidates()` in `main.py`.

#### Example

```json
{
  "record_id": "abc123-0",
  "text": "...Python and Java are popular..."
}
```
→
```json
{
  "token": "python",
  "level": 1,
  "count": 3,
  "parents": ["programming-language"]
}
```

#### Contracts

- Normalization yields a unique canonical form per token.
- Parent references must point to known tokens at the parent level or be omitted.
