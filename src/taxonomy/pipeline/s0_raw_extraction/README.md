# S0 · Raw Extraction

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
- Detailed pipeline: `docs/modules/s0-raw-extraction-pipeline.md`

