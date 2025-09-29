import json
from pathlib import Path
from typing import List

import pytest

from taxonomy.config.settings import Settings
from taxonomy.entities.core import Provenance, SourceMeta, SourceRecord
from taxonomy.llm import ProviderError, ValidationError
from taxonomy.observability import ObservabilityContext
from taxonomy.pipeline.s1_extraction_normalization import extractor as extractor_module
from taxonomy.pipeline.s1_extraction_normalization import main as s1_main
from taxonomy.pipeline.s1_extraction_normalization.main import extract_candidates


def _write_source_records(tmp_path: Path) -> Path:
    prov = Provenance(institution="Example University", url="https://example.edu")
    meta = SourceMeta(hints={"level": "1", "record_id": "r-1"})
    records: List[SourceRecord] = [
        SourceRecord(text="Department of Computer Science", provenance=prov, meta=meta),
        SourceRecord(text="Department of Mathematics", provenance=prov, meta=meta),
    ]
    path = tmp_path / "records.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")
    return path


def test_s1_pipeline_observability_success(monkeypatch, tmp_path) -> None:
    calls = {"total": 0}

    def fake_runner(prompt_key, variables):
        calls["total"] += 1
        if calls["total"] == 2 and "repair" not in variables:
            raise ValidationError("payload failed validation")
        label = variables["source_text"]
        return [
            {
                "label": label,
                "normalized": label.lower(),
                "aliases": [label.split()[0]],
                "parents": ["College"],
            }
        ]

    monkeypatch.setattr(
        extractor_module.ExtractionProcessor,
        "_default_runner",
        staticmethod(fake_runner),
    )

    settings = Settings()
    policy = settings.policies.observability.model_copy(update={"evidence_sampling_rate": 1.0})
    observability = ObservabilityContext(
        run_id="run",
        policy=policy,
    )
    records_path = _write_source_records(Path(tmp_path))
    output_path = Path(tmp_path) / "candidates.jsonl"
    metadata_path = Path(tmp_path) / "candidates.metadata.json"

    monkeypatch.setattr(s1_main, "_stream_candidates", lambda candidates, path: Path(path))

    candidates = extract_candidates(
        records_path,
        level=1,
        output_path=output_path,
        metadata_path=metadata_path,
        settings=settings,
        observability=observability,
    )

    assert len(candidates) == 2

    snapshot = observability.snapshot()
    assert snapshot.counters["S1"]["records_in"] == 2
    assert snapshot.counters["S1"]["candidates_out"] == 2
    assert snapshot.counters["S1"]["retries"] == 1
    assert snapshot.counters["S1"]["invalid_json"] == 0

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    stats = metadata["stats"]
    assert stats["records_in"] == 2
    assert stats["candidates_out"] == 2
    assert stats["retries"] == 1
    assert stats["provider_errors"] == 0
    assert stats["quarantined"] == 0

    evidence = snapshot.evidence["samples"].get("S1", [])
    assert evidence, "Expected sampled evidence for successful extractions"


def test_s1_pipeline_observability_records_failures(monkeypatch, tmp_path) -> None:
    def failing_runner(prompt_key, variables):
        raise ProviderError("llm outage", retryable=False)

    monkeypatch.setattr(
        extractor_module.ExtractionProcessor,
        "_default_runner",
        staticmethod(failing_runner),
    )

    settings = Settings()
    policy = settings.policies.observability.model_copy(update={"evidence_sampling_rate": 1.0})
    observability = ObservabilityContext(
        run_id="run-fail",
        policy=policy,
    )
    records_path = _write_source_records(Path(tmp_path))
    output_path = Path(tmp_path) / "fail.jsonl"
    metadata_path = Path(tmp_path) / "fail.metadata.json"

    monkeypatch.setattr(s1_main, "_stream_candidates", lambda candidates, path: Path(path))

    candidates = extract_candidates(
        records_path,
        level=1,
        output_path=output_path,
        metadata_path=metadata_path,
        settings=settings,
        observability=observability,
    )

    assert candidates == []

    snapshot = observability.snapshot()
    assert snapshot.counters["S1"]["records_in"] == 2
    assert snapshot.counters["S1"]["candidates_out"] == 0
    assert snapshot.quarantine["total"] == 2

    operations = [
        entry for entry in snapshot.operations if entry.get("operation") == "provider_error"
    ]
    assert len(operations) == 2

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    stats = metadata["stats"]
    assert stats["provider_errors"] == 2
    assert stats["quarantined"] == 2
    assert stats["candidates_out"] == 0
    assert stats["invalid_json"] == 0
