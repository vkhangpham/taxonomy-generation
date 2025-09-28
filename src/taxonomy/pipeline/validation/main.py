"""Entry-point helpers for executing the validation pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Sequence

from ...config.settings import Settings
from ...entities.core import Concept, ValidationFinding
from ...utils.helpers import ensure_directory
from .io import (
    export_evidence_samples,
    generate_validation_metadata,
    load_concepts,
    load_snapshots,
    write_validated_concepts,
    write_validation_findings,
)
from .processor import ValidationOutcome, ValidationProcessor


def _normalize_paths(value: str | Sequence[str] | None) -> List[Path]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [Path(item) for item in value]
    return [Path(value)]


def validate_concepts(
    concepts_path: str | Path,
    snapshots_path: str | Sequence[str] | None,
    output_path: str | Path,
    *,
    mode: str = "all",
    settings: Settings | None = None,
) -> List[ValidationOutcome]:
    settings = settings or Settings()
    concepts = list(load_concepts(concepts_path))
    snapshot_paths = _normalize_paths(snapshots_path)
    snapshots = load_snapshots(snapshot_paths) if snapshot_paths else []

    enable_web = mode in {"all", "web"}
    enable_llm = mode in {"all", "llm"}

    processor = ValidationProcessor(
        settings.policies.validation,
        enable_web=enable_web,
        enable_llm=enable_llm,
    )

    if snapshots:
        processor.prepare_evidence(snapshots)

    outcomes = processor.process(concepts)

    write_validated_concepts((outcome.concept for outcome in outcomes), output_path)
    findings = [finding for outcome in outcomes for finding in outcome.findings]
    findings_path = Path(output_path).with_suffix(".findings.jsonl")
    write_validation_findings(findings, findings_path)

    evidence_samples = [
        {
            "concept_id": outcome.concept.id,
            "evidence": [
                {
                    "text": snippet.text,
                    "url": snippet.url,
                    "institution": snippet.institution,
                    "score": snippet.score,
                }
                for snippet in outcome.evidence
            ],
        }
        for outcome in outcomes
        if outcome.evidence
    ]
    if evidence_samples:
        evidence_path = Path(output_path).with_suffix(".evidence.json")
        export_evidence_samples(evidence_samples, evidence_path)

    metadata = generate_validation_metadata(
        processor.stats,
        settings.policies.validation.model_dump(mode="json"),
        {outcome.concept.id: outcome.decision.passed for outcome in outcomes},
    )
    metadata_path = Path(output_path).with_suffix(".metadata.json")
    ensure_directory(metadata_path.parent)
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    return outcomes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate taxonomy concepts.")
    parser.add_argument("concepts", help="Path to concepts JSONL input.")
    parser.add_argument(
        "--snapshots",
        nargs="*",
        help="Paths to snapshot JSONL files used for evidence.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for validated concepts JSONL.",
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=["all", "rule", "web", "llm"],
        help="Which validation modes to execute.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = Settings()
    validate_concepts(
        args.concepts,
        args.snapshots,
        args.output,
        mode=args.mode,
        settings=settings,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
