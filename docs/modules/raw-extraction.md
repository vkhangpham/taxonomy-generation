# Raw Extraction (S0) — Logic Spec

Purpose
- Convert heterogeneous institutional pages into analyzable SourceRecords with clean text and provenance.

Core Tech
- Firecrawl v2.0 snapshots as the only source of page content; S0 never fetches directly.
- Readability-style content extraction and lightweight boilerplate removal on snapshots.

Inputs/Outputs (semantic)
- Input: institutional pages (URLs or HTML/text) with institution id.
- Output: SourceRecord[] with fields: text, provenance{institution,url,section?,fetched_at}, meta{language, charset, hints}.

Rules & Invariants
- Remove navigation/boilerplate; keep content sections likely to contain entities.
- Respect language filter; drop non-target language blocks.
- Length bounds: drop blocks shorter than min_chars or longer than max_chars unless whitelisted.
- De-dup within page: near-identical blocks collapsed; keep first occurrence.
- Preserve ordering within a page for contextual hints (section headers before items).

Core Logic
- Segment by DOM cues (headers, lists, tables, bullet lines) or simple textual heuristics.
- Normalize whitespace; strip markup; retain basic list structure markers for later cues.
- Attach provenance: institution id, url, optional section anchor or Hn path, fetched_at.

Algorithms & Parameters (suggested defaults)
- Language: fast detector; keep if P(lang)==target ≥ 0.8.
- Similarity for intra-page dedup: Jaccard-shingle or MinHash; collapse if ≥ 0.95.
- Bounds: min_chars=12, max_chars=2000 (tune by corpus).

Failure Handling
- If page parse fails, emit SourceRecord with meta.error and empty text=false; quarantine page.
- Log extraction errors but continue; never block batch.

Observability
- Counters: pages_seen, pages_failed, blocks_total, blocks_kept, blocks_deduped, by-language.
- Samples: keep N example blocks per institution for manual spot checks.

Acceptance Tests
- Given fixture pages with menus/footers, output contains only content blocks.
- Language filter keeps only target language; others dropped.
- Duplicate bullet lists within a page are collapsed to one set.

Open Questions
- Should we preserve table structure for department lists or always linearize?
- Do we keep headings as separate records or attach to following block as context?

Examples
- Example A: Department list page
  - Input (HTML snippet):
    ```html
    <h2>Departments</h2>
    <ul>
      <li>Computer Science</li>
      <li>Electrical & Computer Engineering</li>
      <li>Admissions</li>
    </ul>
    <footer>© 2025 University</footer>
    ```
  - Output (SourceRecords):
    ```json
    {"text": "Computer Science", "provenance": {"institution": "u1", "url": "https://u1.edu/eng/depts", "section": "Departments"}}
    {"text": "Electrical & Computer Engineering", "provenance": {"institution": "u1", "url": "https://u1.edu/eng/depts", "section": "Departments"}}
    ```
  - Notes: "Admissions" dropped by section heuristics; footer removed as boilerplate.

- Example B: Non‑target language block
  - Input text: "Facultad de Ingeniería – Admisiones" (lang=es, target=en)
  - Decision: drop (language probability < 0.8 for target=en)

- Example C: Intra‑page duplicate collapse
  - Input: two identical bullet lists appearing in both main content and sidebar
  - Decision: keep first occurrence only (similarity ≥ 0.95), retain earliest section anchor in provenance.
