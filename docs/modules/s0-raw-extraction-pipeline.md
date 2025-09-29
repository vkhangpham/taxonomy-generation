# S0 Raw Extraction Pipeline

This document specifies the S0 pipeline that transforms `PageSnapshot` inputs into normalized `SourceRecord` outputs.

## Scope

- `src/taxonomy/pipeline/s0_raw_extraction/processor.py`
- `src/taxonomy/pipeline/s0_raw_extraction/main.py`
- `src/taxonomy/pipeline/s0_raw_extraction/segmenter.py`

## Components

- `RawExtractionProcessor`: orchestrates loading, segmentation, filtering, and record writing.
- `ContentSegmenter`: splits content into segments by layout cues and token limits.
- `SnapshotLoader`: iterates `PageSnapshot` sources with language and size pre-filters.
- `RecordWriter`: writes `SourceRecord` artifacts and metrics.

## Data Flow

`PageSnapshot` → segment → filter (language, length) → dedupe (intra-page) → `SourceRecord`

## Metrics & Quarantine

- Records counts per reason: kept, language_filtered, too_short, too_long, duplicate.
- Quarantines malformed snapshots and emits examples for debugging.

## CLI

- `pipeline generate --step S0`
- Entry: `extract_from_snapshots()` in `main.py`.

## Example

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

## Contracts

- ASCII canonicalization for text normalization.
- Deterministic segmentation under fixed config and seed.

