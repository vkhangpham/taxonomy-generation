"""Tests for the S0 raw extraction web snapshot pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from taxonomy.config.policies import RawExtractionPolicy
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


def test_extract_from_snapshots_end_to_end(tmp_path: Path, segmented_snapshot: SnapshotRecord) -> None:
    payload = {
        "snapshot": segmented_snapshot.snapshot.model_dump(mode="json"),
        "language_confidence": 0.95,
    }
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    output_path = tmp_path / "records.jsonl"
    result = extract_from_snapshots(input_path, output_path)

    records_file = result["records"]
    assert Path(records_file).exists()
    contents = Path(records_file).read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 3

    metadata_path = Path(result["metadata"])
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["processor"]["pages_emitted"] == 1
    assert metadata["processor"]["blocks_kept"] == 3
