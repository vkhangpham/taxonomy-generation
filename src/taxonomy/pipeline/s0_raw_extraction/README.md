# S0 · Raw Extraction

## Quick Reference

Purpose
- Convert web page snapshots and Excel inputs into normalized `SourceRecord` objects for downstream steps.

Key Classes
- `RawExtractionProcessor`: Batch driver orchestrating snapshot/Excel ingestion and writing records.
- `ContentSegmenter`: Splits pages into segments for efficient processing.
- `SnapshotLoader`: Loads and parses page snapshot artifacts.
- `RecordWriter`: Emits `SourceRecord` files and indexes.
- `ExcelReader`: Reads tabular inputs and maps columns to records.

Data Contract
- `PageSnapshot` → `SourceRecord` (+ metadata, provenance).

Workflow Highlights
- Segmentation, language filtering, deduplication, and batched IO with progress logs.

CLI
- Generate S0 artifacts: `python main.py pipeline generate --step S0`

Examples
- From snapshots: configure snapshot paths in settings, then run the command above.
- From Excel: point configuration to the input file and column mapping.

Related Docs
- Detailed pipeline: this README

## Detailed Specification

### Raw Extraction (S0) — Logic Spec

See also: `docs/logic-spec.md`, `docs/DOCUMENTATION_GUIDE.md`

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

### S0 Raw Extraction Pipeline

This document specifies the S0 pipeline that transforms `PageSnapshot` inputs into normalized `SourceRecord` outputs.

#### Scope

- `src/taxonomy/pipeline/s0_raw_extraction/processor.py`
- `src/taxonomy/pipeline/s0_raw_extraction/main.py`
- `src/taxonomy/pipeline/s0_raw_extraction/segmenter.py`

#### Components

- `RawExtractionProcessor`: orchestrates loading, segmentation, filtering, and record writing.
- `ContentSegmenter`: splits content into segments by layout cues and token limits.
- `SnapshotLoader`: iterates `PageSnapshot` sources with language and size pre-filters.
- `RecordWriter`: writes `SourceRecord` artifacts and metrics.

#### Data Flow

`PageSnapshot` → segment → filter (language, length) → dedupe (intra-page) → `SourceRecord`

#### Metrics & Quarantine

- Records counts per reason: kept, language_filtered, too_short, too_long, duplicate.
- Quarantines malformed snapshots and emits examples for debugging.

#### CLI

- `pipeline generate --step S0`
- Entry: `extract_from_snapshots()` in `main.py`.

#### Example

```json
{
  "snapshot_id": "abc123",
  "url": "https://example.org/a",
  "segments": [
    {"text": "Intro paragraph...", "lang": "en"},
    {"text": "Details...", "lang": "en"}
  ]
}
```
becomes
```json
{
  "record_id": "abc123-0",
  "source": "example.org",
  "text": "Intro paragraph...",
  "metadata": {"lang": "en", "snapshot_id": "abc123"}
}
```

#### Contracts

- ASCII canonicalization for text normalization.
- Deterministic segmentation under fixed config and seed.

