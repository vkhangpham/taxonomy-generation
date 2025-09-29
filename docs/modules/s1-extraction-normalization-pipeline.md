# S1 Extraction & Normalization Pipeline

This document specifies how `SourceRecord` inputs are transformed into normalized `Candidate` outputs per taxonomy level.

## Scope

- `src/taxonomy/pipeline/s1_extraction_normalization/processor.py`
- `src/taxonomy/pipeline/s1_extraction_normalization/main.py`
- `src/taxonomy/pipeline/s1_extraction_normalization/extractor.py`

## Components

- `S1Processor`: level-aware coordinator for batching, extraction, normalization, and aggregation.
- `ExtractionProcessor`: LLM-backed pattern extractor with deterministic settings (temp=0, JSON mode).
- `CandidateNormalizer`: canonicalizes casing, ASCII form, and trims stop terms; applies single-token preference.
- `ParentIndex`: resolves parent references where applicable to maintain level consistency.

## Data Flow

`SourceRecord` → LLM extraction → raw candidates → normalization → parent resolution → aggregated `Candidate`

## Checkpointing

- Per-level checkpoints capture progress and allow resuming mid-level without reprocessing completed batches.

## Observability

- Token accounting, extraction yield rates, normalization drop reasons.

## CLI

- `pipeline generate --step S1 --level <0..3>`
- Entry: `extract_candidates()` in `main.py`.

## Example

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

## Contracts

- Normalization yields a unique canonical form per token.
- Parent references must point to known tokens at the parent level or be omitted.

