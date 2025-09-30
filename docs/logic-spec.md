# Logic & Algorithms Specification (Implementation‑Agnostic)

This specification defines the functional logic, decision rules, and invariants required to rebuild the glossary pipeline and prompt optimization from scratch. It avoids code structure and focuses on the what and why.

## Domain Entities (Semantic Contracts)
- SourceRecord
  - text (string), provenance {institution, url, section, fetched_at}, meta {language, charset, hints}
  - Purpose: smallest analyzable unit after segmentation; carries evidence.
- Candidate (pre‑merge, pre‑disambiguation)
  - level ∈ {0,1,2,3}, label (level‑aware: L0 stores the extracted research topic/field derived from the unit text; L1–L3 store the original unit text), normalized (canonical), parents (anchors or ids; may be empty above L0 when unresolved), aliases[], support {records[], institutions[], count}
  - Purpose: unit of decision‑making across S1–S3.
- Concept (post‑gates)
  - id (stable), level, canonical_label, parents, aliases[], support, rationale {passed_gates[], reasons, thresholds}
  - Purpose: node eligible for final hierarchy assembly.
- ValidationFinding
  - concept_id, mode ∈ {rule, web, llm}, passed (bool), detail (string), evidence (optional snippet/URL)
  - Purpose: audit trail for gate outcomes.
- MergeOp / SplitOp
  - MergeOp: {winners: [concept_id], losers: [concept_id], rule: string, evidence}
  - SplitOp: {source_id, new_ids: [concept_id], rule: string, evidence}

## Normalization Rules (Level‑Aware)
- Case: lowercase for comparison; preserve display case separately if needed.
- Whitespace: collapse internal spaces; trim; normalize hyphens/underscores.
- Punctuation: strip trailing punctuation; keep internal hyphens only if policy allows.
- Diacritics: fold to ASCII for comparison; store original in aliases.
- Acronyms: detect patterns (e.g., “EECS”, “CS”); map to expanded forms when context confirms or policy allows; ambiguous cases (e.g., “AI”) remain short unless explicitly enabled.
- Stop terms: remove leading institutional boilerplate (e.g., “Department of”, “School of”) during normalization for L1; record original in aliases.

## Step Logic
S0 Raw Extraction
- Input: heterogeneous institutional pages. Output: SourceRecord[].
- Segment by semantic blocks (headers, lists, tables, bullets). Remove navigation/boilerplate; respect language.
- Filter: min/max length; allowed character set; dedupe near‑identical blocks per page.

S1 Extraction & Normalization (LLM‑assisted)
- For each SourceRecord, prompt for level‑appropriate research topics/fields with strict JSON output:
  - Level 0: Extract the research field/domain represented by top‑level academic units (e.g., "Annenberg School for Communication" → "communication"; "Perelman School of Medicine" → "medicine").
  - Levels 1–3: Extract departments, research areas, and fine‑grained topics as before.
  - Fields: {label, normalized, parent_anchor?, aliases[], confidence?, notes?}
  - Determinism: require sorted outputs (by normalized, case‑insensitive) and temperature 0.0.
- Post‑processing:
  - Apply normalization rules again; drop empty/invalid; attach SourceRecord to support.records.
  - Parent anchoring: resolve anchors to concrete parents when possible by normalizing across all shallower levels; when no identifier exists, produce a scoped fallback identifier (`L{level}:{normalized}`) and carry empty anchors forward for later resolution.

S2 Cross‑Institution Frequency Filtering
- Compute metrics per candidate key = (level, normalized, parent_lineage_key):
  - inst_count = |distinct institutions supporting|.
  - src_count = |distinct SourceRecord ids supporting|.
  - weight = w1*inst_count + w2*log(1+src_count) (defaults: w1=1.0, w2=0.3)
- Thresholds per level (suggested defaults; tune with eval set):
  - L0: inst_count ≥ 1
  - L1: inst_count ≥ 1
  - L2: inst_count ≥ 2
  - L3: inst_count ≥ 2 and src_count ≥ 3
- Keep rationale: store contributing institutions, sample snippets, and computed metrics.

S3 Single‑Token Verification (Label Minimality)
- Policy: Guard only single-token terms via LLM; multi-token terms (token_count > 1) bypass LLM and pass automatically after basic rule checks. Allow exceptions on allowlist.
- Gate order:
  - **Multi-token bypass**: If token_count > 1, set passed=True, skip LLM, add rationale "bypass:multi_token".
  - **Single-token verification** (token_count == 1): rules → LLM yes/no verification.
    - Rules: reject if contains forbidden punctuation; check alnum ratio; check venue names at L3.
    - LLM prompt asks: “Is this single token a legitimate research field/term for level‑X?” with JSON {pass: bool, reason}. Rejects generic organizational tokens (“department”, “program”) and branding tokens.
- On failure: propose a minimal alternative (via rules or prompt) and attach to aliases; keep both when justified.

## Deduplication (Similarity + Merge Policy)
- Candidate blocking keys: prefix of normalized (e.g., first 6 chars), acronym bucket, Soundex/Metaphone bucket.
- Similarity score s ∈ [0,1] = max(
  JaroWinkler(normalized_i, normalized_j),
  Jaccard(tokens_i, tokens_j),
  AbbrevScore(i, j)  # acronym ↔ expanded
).
- Merge when s ≥ τ(level): τ(L0,L1)=0.93, τ(L2,L3)=0.90.
- Canonical representative selection (deterministic):
  1) higher inst_count, 2) shorter normalized length, 3) lexicographically earlier.
- MergeOp emits mapping {loser_id→winner_id}; update support, aliases, and rationale.

## Disambiguation (Ambiguity Detection + Split)
- Detect when same normalized label appears under multiple incompatible parents or contexts.
- Evidence features: parent_lineage, co‑occurring terms, venue/source types.
- Split policy:
  - If contexts are separable, create distinct Concepts with explicit parentage and rationale.
  - If not separable, keep a single Concept but record multiple parents only when policy allows (prefer single parent).
- Use LLM disambiguation prompt to confirm splits and produce concise sense glosses.

## Validation Modes & Aggregation
- Rule validation: pattern and vocabulary checks; level‑specific forbidden/required forms. Venue detections at L3 emit soft warnings by default, escalate when they collide with forbidden patterns, and can be force-escalated via `rules.venue_detection_hard`.
- Web validation: confirm keyword/phrase presence in source or authoritative pages; capture evidence snippets. Authority lists match both apex domains and subdomains. An empty index or timeout surfaces an `unknown` tri-state (non-voting) while still recording findings, and snapshot lookup no longer truncates before aggregation.
- LLM validation: entailment prompt “Does evidence support that label X is a legitimate level‑Y concept at institution Z?” → JSON {pass, reason, confidence?}; legacy `validated` keys are normalized to `pass`.
- Aggregation policy: FAIL if any hard rule fails; otherwise weighted vote (rule > web > LLM). Conservative ties only flip to PASS when evidence strength (max of web average snippet score and LLM confidence) meets `aggregation.tie_break_min_strength` (defaults to the LLM confidence threshold), and `unknown` web checks contribute no weight. Always record all findings.

## Hierarchy Assembly & Invariants
- Build a DAG with exactly four levels; each node has exactly one parent except L0 (root level); exceptions documented.
- Invariants:
  - No cycles; no cross‑level shortcuts (e.g., L3 directly under L1).
  - Unique path from L0 to any node (unless explicit multi‑parent policy for cross‑listed cases is approved).
  - Sibling name collisions resolved via dedup/disambiguation.

## Prompt Semantics (No Inline Templates Here)
- Extraction prompt must:
  - Constrain outputs to JSON arrays; forbid explanations.
  - Require deterministic ordering and stable keys.
  - Be level‑aware (definitions and examples per level) without leaking chain‑of‑thought.
- Resolution via LLM package:
  - All prompts are loaded from disk by prompt_key through the LLM package (DSPy-backed) which selects the active optimized variant.
  - Business logic passes only prompt_key + variables; never raw template strings.
- Verification prompts must:
  - Return compact JSON {pass: bool, reason: string}.
  - Include a strict schema stanza and an example of valid/invalid outputs.

## Run Orchestration (Top‑Level Logic)
- Phase 1: Levelwise Generation (0→3)
  - For level in {0,1,2,3}: execute S0→S3 to produce vetted candidates with provenance and gate rationales.
  - Ordering enforces parent‑before‑child availability (e.g., L1 depends on L0 anchors).

- Phase 2: Consolidation
  - Union all per‑level outputs into a raw term universe: nodes (terms) + tentative parent lineage.

- Phase 3: Post‑Processing Order
  - Validate → Enrich (Web Mining) → Disambiguate → Deduplicate.
  - Enrichment augments evidence via web snapshots; due to TTL and cost, it is typically single‑pass per run window.
  - Validation, Disambiguation, Deduplication are multi‑pass capable: repeat until a fixed point (no changes to findings/splits/merges).

- Phase 4: Resume Semantics
  - Persist artifacts and operation logs after each phase; maintain a ledger of per-concept status and last operation.
  - A subsequent run can reload the ledger and continue from any completed phase, or re-enter an iterative phase.
  - Determinism ensures repeated runs with the same inputs/policies yield identical results.
  - The S1 CLI persists per-batch checkpoints (processed record count + aggregated candidates) via `--resume-from`, skipping already processed records on restart.

- Phase 5: Finalization
  - Assemble the four‑level DAG with invariant checks, produce summaries and a signed manifest capturing versions, thresholds, seeds, counters, and sampled evidence.

## Prompt Optimization (Offline, Eval‑Driven)
- Frozen eval set: labeled examples per level with gold labels.
- Objective: maximize F1 (primary), maintain JSON validity rate ≥ 99.5% (guardrail), keep token cost reasonable.
- Search levers: few‑shot K, constraint wording, example ordering, temperature (0.0 or 0.2), brevity instructions.
- Protocol: stratified train/dev split; early stop on no improvement; report per‑level metrics and error categories.

## Observability & Reproducibility
- Counters per step: input, kept, dropped (by reason), merged, split, validated_pass/fail. Validation additionally exposes checked, rule_failed, web_failed, llm_failed, passed_all (with legacy pass counters retained for dashboards).
- Manifest per run: prompt versions, thresholds, seeds, time, evidence samples.
- Determinism: sorted inputs, fixed seeds, stable canonical selection tie‑breakers.

## Failure Handling
- Timeouts, validation failures, and retryable provider errors trigger structured retries with exponential backoff; extraction retries include a `repair` hint to the LLM. Irrecoverable records enter quarantine.
- Web evidence timeouts record an `unknown` outcome (no vote) after exhausting retries; downstream aggregation treats these as informational only.
- Partial results are acceptable; never block the batch; mark completeness and reasons.

## Edge Cases (Test Fixtures Required)
- Cross‑listed departments between colleges; shared research centers.
- Acronyms vs. expansions (EECS vs. Electrical Engineering and Computer Science).
- Hyphenation and multi‑word labels (machine‑learning vs. machine learning).
- International naming variations and diacritics (Informatik vs. Computer Science; Álgebra).
- Topic vs. venue confusion at L3 (e.g., “NeurIPS” is a venue, not a topic).

## Acceptance Tests (Logic Only)
- Given a fixed small corpus, S0→S3 yields identical kept/dropped decisions and identical merge/split operations between runs.
- Validation aggregation reaches the same pass/fail for each concept under identical inputs.
- Hierarchy invariants hold and are machine‑verifiable from artifacts alone.
