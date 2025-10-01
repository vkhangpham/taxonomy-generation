from __future__ import annotations

from taxonomy.config.policies import LabelPolicy, MinimalCanonicalForm
from taxonomy.entities.core import Provenance, SourceMeta, SourceRecord
from taxonomy.pipeline.s1_extraction_normalization.extractor import RawExtractionCandidate
from taxonomy.pipeline.s1_extraction_normalization.normalizer import CandidateNormalizer


def test_l0_normalization_strips_institution_prefix() -> None:
    policy = LabelPolicy(minimal_canonical_form=MinimalCanonicalForm())
    normalizer = CandidateNormalizer(label_policy=policy)

    prov = Provenance(institution="University of Pennsylvania", url="https://example.edu")
    meta = SourceMeta(hints={"level": "0"})
    source = SourceRecord(text="UNIVERSITY OF PENNSYLVANIA - Annenberg School of Communication", provenance=prov, meta=meta)

    raw = RawExtractionCandidate(
        label="UNIVERSITY OF PENNSYLVANIA - Annenberg School of Communication",
        normalized="UNIVERSITY OF PENNSYLVANIA - Annenberg School of Communication",
        aliases=["Annenberg School of Communication"],
        parents=[],
        source=source,
    )

    results = normalizer.normalize([raw], level=0)
    assert results, "Expected a normalized candidate"
    candidate = results[0]
    # Owning institution should be stripped from the head of the canonical form.
    assert not candidate.normalized.startswith("university of pennsylvania ")
    # Token cap for S3 (<=5) should be satisfied by removing the prefix.
    assert len(candidate.normalized.split()) <= 5

