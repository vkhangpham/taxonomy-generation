"""Tests for the S0 raw extraction web snapshot pipeline."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from taxonomy.config.policies import RawExtractionPolicy
from taxonomy.config.settings import Settings
from taxonomy.entities.core import PageSnapshot, PageSnapshotMeta
from taxonomy.pipeline.s0_raw_extraction import (
    ContentSegmenter,
    RawExtractionProcessor,
    SnapshotLoader,
    SnapshotRecord,
    extract_from_snapshots,
)


@pytest.fixture()
def sample_policy() -> RawExtractionPolicy:
    return RawExtractionPolicy()


def _build_snapshot(text: str, *, lang: str = "en") -> PageSnapshot:
    checksum = PageSnapshot.compute_checksum(text)
    return PageSnapshot(
        institution="test-university",
        url="https://example.edu/admissions",
        canonical_url="https://example.edu/admissions",
        fetched_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        http_status=200,
        content_type="text/html",
        html=None,
        text=text,
        lang=lang,
        checksum=checksum,
        meta=PageSnapshotMeta(),
    )


@pytest.fixture()
def segmented_snapshot() -> SnapshotRecord:
    text = (
        "ADMISSIONS\n"
        "Overview:\n"
        "- Apply online\n"
        "- Submit transcripts\n"
        "\n"
        "Requirements:\n"
        "Applicants must provide transcripts and test scores.\n"
        "\n"
        "© 2024 Example University\n"
        "Contact us\n"
    )
    snapshot = _build_snapshot(text)
    return SnapshotRecord(snapshot=snapshot, metadata={"language_confidence": 0.95})


def test_segmenter_detects_headers_lists_and_removes_boilerplate(
    sample_policy: RawExtractionPolicy, segmented_snapshot: SnapshotRecord
) -> None:
    segmenter = ContentSegmenter(sample_policy)
    result = segmenter.segment(segmented_snapshot.snapshot)
    assert result.boilerplate_removed == 2
    assert [block.block_type for block in result.blocks] == ["header", "header", "list", "header", "paragraph"]
    list_block = result.blocks[2]
    assert "\n" in list_block.text
    assert list_block.section == "Overview:"


def test_segmenter_does_not_flag_double_space_paragraphs_as_table(
    sample_policy: RawExtractionPolicy
) -> None:
    segmenter = ContentSegmenter(sample_policy)
    text = (
        "Our mission  is to  serve the community.\n"
        "We provide  guidance  daily to students and faculty alike."
    )
    snapshot = _build_snapshot(text)
    result = segmenter.segment(snapshot)
    assert all(block.block_type != "table" for block in result.blocks)


def test_segmenter_detects_pipe_delimited_tables(
    sample_policy: RawExtractionPolicy
) -> None:
    segmenter = ContentSegmenter(sample_policy)
    text = "Name | Department | Phone\nAlice | Engineering | 1234"
    snapshot = _build_snapshot(text)
    result = segmenter.segment(snapshot)
    assert any(block.block_type == "table" for block in result.blocks)


def test_processor_filters_language_confidence(
    sample_policy: RawExtractionPolicy, segmented_snapshot: SnapshotRecord
) -> None:
    processor = RawExtractionProcessor(sample_policy)
    low_confidence = SnapshotRecord(
        snapshot=segmented_snapshot.snapshot,
        metadata={"language_confidence": 0.2},
    )
    records = processor.process(low_confidence)
    assert records == []
    assert processor.metrics.pages_language_skipped == 1


def test_processor_requires_confidence_when_configured(
    sample_policy: RawExtractionPolicy, segmented_snapshot: SnapshotRecord
) -> None:
    processor = RawExtractionProcessor(sample_policy)
    missing_confidence = SnapshotRecord(
        snapshot=segmented_snapshot.snapshot,
        metadata={},
    )
    records = processor.process(missing_confidence)
    assert records == []
    assert processor.metrics.pages_language_skipped == 1


def test_processor_allows_missing_confidence_in_permissive_mode(
    segmented_snapshot: SnapshotRecord
) -> None:
    policy = RawExtractionPolicy(require_language_confidence=False)
    processor = RawExtractionProcessor(policy)
    missing_confidence = SnapshotRecord(
        snapshot=segmented_snapshot.snapshot,
        metadata={},
    )
    records = processor.process(missing_confidence)
    assert len(records) == 3
    assert processor.metrics.pages_language_skipped == 0


def test_processor_deduplicates_near_identical_blocks(sample_policy: RawExtractionPolicy) -> None:
    text = (
        "ACADEMICS\n"
        "Programs:\n"
        "Our programs emphasise research excellence and collaboration.\n"
        "\n"
        "Our programs emphasise research excellence and collaboration.\n"
    )
    snapshot = _build_snapshot(text)
    record = SnapshotRecord(snapshot=snapshot, metadata={"language_confidence": 0.99})
    processor = RawExtractionProcessor(sample_policy)
    records = processor.process(record)
    # Header blocks fall below min char length, expect a single content record.
    assert len(records) == 1
    assert "research excellence" in records[0].text
    assert processor.metrics.blocks_deduped == 1


def test_processor_generates_source_records_with_provenance(
    sample_policy: RawExtractionPolicy, segmented_snapshot: SnapshotRecord
) -> None:
    processor = RawExtractionProcessor(sample_policy)
    records = processor.process(segmented_snapshot)
    assert len(records) == 3
    sections = {record.provenance.section for record in records}
    assert sections.issuperset({"Overview:", "Requirements:"})
    for record in records:
        assert record.meta.hints.get("level") == "S0"
        assert record.meta.hints.get("block_type") in {"list", "paragraph", "header"}
        assert record.provenance.institution == "test-university"


def test_loader_reads_jsonl_snapshot(tmp_path: Path, segmented_snapshot: SnapshotRecord) -> None:
    payload = {
        "snapshot": segmented_snapshot.snapshot.model_dump(mode="json"),
        "language_confidence": 0.93,
    }
    jsonl = tmp_path / "snapshots.jsonl"
    jsonl.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    loader = SnapshotLoader()
    records = list(loader.load_from_jsonl(jsonl))
    assert len(records) == 1
    assert loader.metrics.snapshots_loaded == 1
    assert records[0].language_confidence == pytest.approx(0.93)


def test_loader_writes_quarantine_on_invalid_snapshot(tmp_path: Path) -> None:
    settings = Settings(
        create_dirs=True,
        paths={"metadata_dir": str(tmp_path / "metadata")},
        observability={
            "quarantine_enabled": True,
            "quarantine_dir": str(tmp_path / "quarantine"),
        },
    )
    loader = SnapshotLoader(settings=settings)
    payload = {"snapshot": {"url": "https://example.edu/bad"}}  # missing required fields
    jsonl = tmp_path / "invalid.jsonl"
    jsonl.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    records = list(loader.load_from_jsonl(jsonl))
    assert records == []
    assert loader.metrics.validation_errors == 1

    quarantine_file = loader.quarantine_file
    assert quarantine_file is not None
    contents = [json.loads(line) for line in quarantine_file.read_text(encoding="utf-8").splitlines() if line]
    assert len(contents) == 1
    entry = contents[0]
    assert entry["file"] == str(jsonl)
    assert entry["url"] == "https://example.edu/bad"
    assert "raw" in entry


def test_extract_from_snapshots_end_to_end(tmp_path: Path, segmented_snapshot: SnapshotRecord) -> None:
    payload = {
        "snapshot": segmented_snapshot.snapshot.model_dump(mode="json"),
        "language_confidence": 0.95,
    }
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    output_path = tmp_path / "records.jsonl"
    result = extract_from_snapshots(input_path, output_path)

    records_files = result["records"]
    assert isinstance(records_files, list)
    assert len(records_files) == 1
    records_file = Path(records_files[0])
    assert records_file.exists()
    contents = records_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 3

    metadata_path = Path(result["metadata"])
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["processor"]["pages_emitted"] == 1
    assert metadata["processor"]["blocks_kept"] == 3


def test_processor_drops_blocks_exceeding_max_chars(sample_policy: RawExtractionPolicy) -> None:
    text = "A" * 2050
    snapshot = _build_snapshot(text)
    record = SnapshotRecord(snapshot=snapshot, metadata={"language_confidence": 0.99})
    processor = RawExtractionProcessor(sample_policy)

    records = processor.process(record)

    assert records == []
    assert processor.metrics.blocks_filtered_length == 1


def test_extract_from_snapshots_writes_gzip_when_compressed(
    tmp_path: Path, segmented_snapshot: SnapshotRecord
) -> None:
    payload = {
        "snapshot": segmented_snapshot.snapshot.model_dump(mode="json"),
        "language_confidence": 0.95,
    }
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    output_path = tmp_path / "records.jsonl"
    result = extract_from_snapshots(input_path, output_path, compress=True)

    records_files = result["records"]
    assert isinstance(records_files, list)
    assert len(records_files) == 1
    gzip_path = Path(records_files[0])
    assert gzip_path.suffixes[-2:] == [".jsonl", ".gz"]

    with gzip.open(gzip_path, "rt", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle.read().splitlines() if line]

    assert len(lines) == 3
    assert all(isinstance(entry, dict) for entry in lines)

    metadata_path = Path(result["metadata"])
    assert metadata_path.name.endswith(".jsonl.gz.stats.json")


def test_processor_writes_quarantine_on_failure(
    sample_policy: RawExtractionPolicy, segmented_snapshot: SnapshotRecord, tmp_path: Path
) -> None:
    class ExplodingSegmenter(ContentSegmenter):
        def __init__(self) -> None:
            pass

        def segment(self, snapshot: PageSnapshot):  # type: ignore[override]
            raise RuntimeError("boom")

    quarantine_file = tmp_path / "processor.quarantine.jsonl"
    processor = RawExtractionProcessor(
        sample_policy,
        segmenter=ExplodingSegmenter(),
        quarantine_path=quarantine_file,
    )
    failing_record = SnapshotRecord(
        snapshot=segmented_snapshot.snapshot,
        metadata={
            "source_file": "input.jsonl",
            "source_line": 12,
            "language_confidence": 0.99,
        },
    )

    records = processor.process(failing_record)
    assert records == []
    assert processor.metrics.pages_failed == 1

    contents = [json.loads(line) for line in quarantine_file.read_text(encoding="utf-8").splitlines() if line]
    assert len(contents) == 1
    entry = contents[0]
    assert entry["file"] == "input.jsonl"
    assert entry["line"] == 12
    assert entry["url"] == segmented_snapshot.snapshot.url
    assert entry["institution"] == segmented_snapshot.snapshot.institution
    assert entry["raw"]["metadata"]["source_file"] == "input.jsonl"
