# Extraction & Normalization (S1) — Logic Spec

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
- Normalization: apply case/punctuation/whitespace/diacritics/acronym policies consistently across levels.
- Parent anchoring: include best-effort parent references or textual anchors; never hallucinate parents absent evidence.

Core Logic
- Prompt level definition (what belongs at L0/L1/L2/L3) with 1–2 minimal examples per level.
- Extract labels; generate normalized forms; collect plausible aliases when present.
- Attach SourceRecord provenance to support and compute an initial institution set.

Normalization Rules (summary)
- Lowercase for comparison; preserve display case separately if needed.
- Collapse spaces; normalize hyphens/underscores; strip trailing punctuation.
- Fold diacritics for comparison; keep original in aliases.
- Remove boilerplate prefixes at L1 (e.g., “Department of …”), keeping alias.
- Acronyms: retain both short and expanded forms when unambiguous.

Failure Handling
- If JSON invalid, retry with constrained re-ask (same input, schema reminder); on repeated failure, quarantine record.
- Drop empty/invalid labels with reason; keep record-level logs for audit.

Observability
- Counters: records_in, candidates_out, invalid_json, retries, quarantined.
- Drift: track normalized length distribution and alias rates by level.

Acceptance Tests
- Given fixture records, extracted candidates match expected sets and are stably ordered.
- Normalization removes boilerplate and folds diacritics as specified.
- Parent anchors included when textual evidence exists; absent otherwise.

Open Questions
- How aggressive should acronym expansion be at L2/L3?
- Should we allow multi-word preservation at L3 when abbreviation harms clarity?

Examples
- Example A: Level 1 department normalization
  - Input SourceRecord:
    ```json
    {"text": "Department of Computer Science", "provenance": {"institution": "u2", "url": "https://u2.edu/eng/departments"}}
    ```
  - Expected Candidates (sorted by normalized):
    ```json
    {"level": 1, "label": "Department of Computer Science", "normalized": "computer science", "parents": ["college of engineering"], "aliases": ["dept. of computer science", "cs"], "support": {"institutions": ["u2"], "records": ["r1"]}}
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
  - Given page header "College of Engineering" and section "Departments", extracted L1 candidates include parent anchor "college of engineering"; absent such context, parents remain empty and are resolved later.
