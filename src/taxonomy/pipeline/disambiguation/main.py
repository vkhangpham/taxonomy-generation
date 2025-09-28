"""Entry point helpers for taxonomy disambiguation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from ...config.settings import Settings
from ...entities.core import Concept
from ...utils.helpers import ensure_directory
from .io import (
    generate_disambiguation_metadata,
    load_concepts,
    load_context_data,
    write_disambiguated_concepts,
    write_split_operations,
)
from .processor import DisambiguationOutcome, DisambiguationProcessor


def disambiguate_concepts(
    concepts_path: str | Path,
    output_path: str | Path,
    *,
    context_data_path: str | Path | None = None,
    settings: Settings | None = None,
) -> DisambiguationOutcome:
    settings = settings or Settings()
    policy = settings.policies.disambiguation

    concepts = list(load_concepts(concepts_path))
    context_data = load_context_data(context_data_path)

    processor = DisambiguationProcessor(policy)
    outcome = processor.process(concepts, context_data)

    write_disambiguated_concepts(outcome.concepts, output_path)
    split_path = Path(output_path).with_suffix(".splits.jsonl")
    write_split_operations(outcome.split_ops, split_path)

    metadata = generate_disambiguation_metadata(
        outcome.stats,
        policy.model_dump(mode="json"),
        {op.source_id: op.new_ids for op in outcome.split_ops},
    )
    metadata_path = Path(output_path).with_suffix(".metadata.json")
    ensure_directory(metadata_path.parent)
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    return outcome


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Disambiguate taxonomy concepts.")
    parser.add_argument("concepts", help="Path to concepts JSONL input.")
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for disambiguated concepts JSONL.",
    )
    parser.add_argument(
        "--contexts",
        default=None,
        help="Optional path to context JSONL data used for feature extraction.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    disambiguate_concepts(
        args.concepts,
        args.output,
        context_data_path=args.contexts,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
