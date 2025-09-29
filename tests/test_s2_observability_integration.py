"""Integration tests validating S2 observability wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taxonomy.config.settings import Settings
from taxonomy.observability import ObservabilityContext
from taxonomy.pipeline.s2_frequency_filtering.main import filter_by_frequency
from taxonomy.pipeline.s2_frequency_filtering.processor import S2Processor


def _candidate_entry(
    *,
    level: int,
    label: str,
    normalized: str,
    parents: list[str],
    institutions: list[str],
    record_fingerprints: list[str],
    support: dict[str, int] | None = None,
) -> dict[str, object]:
    base_support = support or {"records": 1, "institutions": 1, "count": 1}
    return {
        "candidate": {
            "level": level,
            "label": label,
            "normalized": normalized,
            "parents": parents,
            "aliases": [label],
            "support": base_support,
        },
        "institutions": institutions,
        "record_fingerprints": record_fingerprints,
    }


def _write_candidates(path: Path) -> None:
    entries = [
        _candidate_entry(
            level=2,
            label="Computer Vision",
            normalized="computer vision",
            parents=["ai"],
            institutions=["MIT"],
            record_fingerprints=["rec-1"],
        ),
        _candidate_entry(
            level=2,
            label="Computer Vision",
            normalized="computer vision",
            parents=["AI"],
            institutions=["Stanford"],
            record_fingerprints=["rec-2"],
        ),
        _candidate_entry(
            level=2,
            label="Quantum Vision",
            normalized="quantum vision",
            parents=["ai"],
            institutions=["OnlyOne"],
            record_fingerprints=["rec-3"],
        ),
    ]
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")


def _observability_context(*, sampling_rate: float = 1.0, seed: int = 123) -> ObservabilityContext:
    settings = Settings()
    policy = settings.policies.observability.model_copy(
        update={
            "evidence_sampling_rate": sampling_rate,
            "max_evidence_samples_per_phase": 100,
            "deterministic_sampling_seed": seed,
        }
    )
    return ObservabilityContext(run_id=f"s2-{seed}", policy=policy)


def test_filter_by_frequency_emits_observability_metadata(tmp_path: Path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    metadata_path = tmp_path / "metadata.json"
    _write_candidates(candidates_path)

    settings = Settings()
    observability = _observability_context()

    result = filter_by_frequency(
        candidates_path,
        level=2,
        output_path=output_path,
        dropped_output_path=dropped_path,
        metadata_path=metadata_path,
        settings=settings,
        observability=observability,
    )

    snapshot = observability.snapshot()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert result.stats["kept"] == 1
    assert result.stats["observability_checksum"] == snapshot.checksum

    stats = metadata["stats"]
    assert stats["kept"] == 1
    assert stats["candidates_in"] == 3
    observability_section = metadata["observability"]
    assert observability_section["counters"]["kept"] == 1
    assert observability_section["counters"]["dropped_insufficient_support"] == 1
    assert observability_section["performance"]["candidates_processed"] == 3
    assert observability_section["evidence_samples"], "Expected sampled evidence entries"
    assert observability_section["thresholds"]["S2.level_2"]["min_institutions"] == 2


def test_s2_observability_snapshots_are_deterministic(tmp_path: Path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    output_a = tmp_path / "kept-a.jsonl"
    output_b = tmp_path / "kept-b.jsonl"
    dropped_a = tmp_path / "dropped-a.jsonl"
    dropped_b = tmp_path / "dropped-b.jsonl"
    metadata_a = tmp_path / "metadata-a.json"
    metadata_b = tmp_path / "metadata-b.json"
    _write_candidates(candidates_path)

    settings = Settings()
    observability_a = _observability_context(seed=999)
    observability_b = _observability_context(seed=999)

    filter_by_frequency(
        candidates_path,
        level=2,
        output_path=output_a,
        dropped_output_path=dropped_a,
        metadata_path=metadata_a,
        settings=settings,
        observability=observability_a,
    )

    filter_by_frequency(
        candidates_path,
        level=2,
        output_path=output_b,
        dropped_output_path=dropped_b,
        metadata_path=metadata_b,
        settings=settings,
        observability=observability_b,
    )

    snap_a = observability_a.snapshot()
    snap_b = observability_b.snapshot()

    assert snap_a.counters["S2"] == snap_b.counters["S2"]
    perf_a = dict(snap_a.performance["S2"])
    perf_b = dict(snap_b.performance["S2"])
    perf_a.pop("elapsed_seconds", None)
    perf_b.pop("elapsed_seconds", None)
    assert perf_a == perf_b
    assert snap_a.evidence["samples"].get("S2") == snap_b.evidence["samples"].get("S2")


def test_s2_processor_logs_failure_operations(tmp_path: Path) -> None:
    observability = _observability_context()

    class FailingAggregator:
        def aggregate(self, _items):
            raise RuntimeError("boom")

    processor = S2Processor(aggregator=FailingAggregator(), observability=observability)

    with pytest.raises(RuntimeError):
        processor.process([])

    snapshot = observability.snapshot()
    operations = [entry for entry in snapshot.operations if entry.get("operation") == "frequency_aggregation_failed"]
    assert operations, "Expected failure operation logged for exception"
    assert operations[0]["outcome"] == "error"
    assert observability.registry.current_phase() is None
