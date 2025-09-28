"""Tests for web evidence validation."""

from __future__ import annotations

from datetime import datetime, timezone

from taxonomy.config.policies import ValidationPolicy
from taxonomy.entities.core import Concept, PageSnapshot
from taxonomy.pipeline.validation.evidence import EvidenceIndexer
from taxonomy.pipeline.validation.web import WebValidator


def _snapshot(text: str, url: str = "https://example.edu/programs") -> PageSnapshot:
    checksum = PageSnapshot.compute_checksum(text)
    return PageSnapshot(
        institution="Example University",
        url=url,
        canonical_url=url,
        fetched_at=datetime.now(timezone.utc),
        http_status=200,
        content_type="text/html",
        html=None,
        text=text,
        lang="en",
        checksum=checksum,
    )


def _concept(label: str) -> Concept:
    return Concept(
        id="c-web",
        level=2,
        canonical_label=label,
        parents=["parent"],
    )


def test_web_validator_collects_evidence() -> None:
    policy = ValidationPolicy()
    indexer = EvidenceIndexer(policy)
    content = "Our Applied Data Science program focuses on modern data science methods."
    indexer.build_index([_snapshot(content)])

    validator = WebValidator(policy, indexer)
    result = validator.validate_concept(_concept("Applied Data Science"))

    assert result.passed
    assert result.evidence
    assert "Evidence snippets" in result.summary


def test_evidence_authority_respects_policy() -> None:
    policy = ValidationPolicy()
    policy = policy.model_copy(update={
        "web": policy.web.model_copy(update={"authoritative_domains": ["example.edu"]})
    })
    indexer = EvidenceIndexer(policy)
    snap = _snapshot("text about robotics", url="https://example.edu/robotics")
    indexer.build_index([snap])

    authority = indexer.assess_authority(snap)
    assert authority == 1.0


def test_snippet_respects_length_limit() -> None:
    policy = ValidationPolicy()
    indexer = EvidenceIndexer(policy)
    long_text = "AI " * 200 + "applied robotics" + " AI" * 200
    snap = _snapshot(long_text)
    indexer.build_index([snap])

    snippets = indexer.extract_snippets(snap, "applied robotics", max_length=100)
    assert snippets
    assert all(len(snippet.text) <= 120 for snippet in snippets)
