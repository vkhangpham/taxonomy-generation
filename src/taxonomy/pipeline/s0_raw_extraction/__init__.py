"""Raw content acquisition utilities.

This package provides two complementary pathways for S0 extraction:

* Excel-based ingestion used for Level 0 bootstrapping via ``excel_reader``.
* Web snapshot processing that converts crawled content into ``SourceRecord``
  instances using the raw extraction pipeline (loader → processor → writer).
"""

from .excel_reader import (
    count_colleges_per_institution,
    generate_source_records,
    load_faculty_dataframe,
    select_top_institutions,
)
from .loader import SnapshotLoader, SnapshotRecord
from .main import extract_from_snapshots
from .processor import ProcessingMetrics, RawExtractionProcessor
from .segmenter import ContentSegmenter, SegmentedBlock, SegmentationResult
from .writer import RecordWriter

__all__ = [
    "load_faculty_dataframe",
    "count_colleges_per_institution",
    "select_top_institutions",
    "generate_source_records",
    "SnapshotLoader",
    "SnapshotRecord",
    "RawExtractionProcessor",
    "ProcessingMetrics",
    "ContentSegmenter",
    "SegmentedBlock",
    "SegmentationResult",
    "RecordWriter",
    "extract_from_snapshots",
]
