from __future__ import annotations

import json
from pathlib import Path

from taxonomy.pipeline.s1_extraction_normalization.main import _stream_candidates_enveloped
from taxonomy.pipeline.s1_extraction_normalization.processor import AggregatedCandidate


def test_s1_stream_includes_institutions_and_records(tmp_path: Path) -> None:
    bucket = AggregatedCandidate(
        level=1,
        normalized="computer science",
        parents=("L0:college of engineering",),
        primary_label="Department of Computer Science",
    )
    bucket.aliases.update({"Department of Computer Science", "CS"})
    bucket.institutions.update({"Example University"})
    bucket.record_fingerprints.update({"record:abc123"})
    bucket.total_count = 2

    out = tmp_path / "candidates.jsonl"
    _stream_candidates_enveloped([bucket], out)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert "candidate" in payload
    assert payload["institutions"] == ["Example University"]
    assert payload["record_fingerprints"] == ["record:abc123"]
    candidate = payload["candidate"]
    assert candidate["normalized"] == "computer science"
    assert candidate["support"]["institutions"] == 1
    assert candidate["support"]["records"] == 1

