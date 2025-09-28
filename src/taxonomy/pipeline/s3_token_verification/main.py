"""Entry points for S3 token verification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from taxonomy.config.settings import Settings, get_settings
from taxonomy.utils.logging import get_logger, logging_context

from .io import (
    VerificationInput,
    generate_s3_metadata,
    load_candidates,
    write_failed_candidates,
    write_verified_candidates,
)
from .processor import S3Processor, TokenVerificationResult
from .rules import TokenRuleEngine
from .verifier import LLMTokenVerifier


def verify_tokens(
    candidates_path: str | Path,
    *,
    level: int,
    output_path: str | Path,
    failed_output_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
    settings: Settings | None = None,
) -> TokenVerificationResult:
    """Run S3 token verification and persist outputs."""

    cfg = settings or get_settings()
    log = get_logger(module=__name__)

    rule_engine = TokenRuleEngine(
        policy=cfg.policies.single_token,
        minimal_form=cfg.policies.label_policy.minimal_canonical_form,
    )
    verifier = LLMTokenVerifier()
    processor = S3Processor(
        rule_engine=rule_engine,
        llm_verifier=verifier,
        policy=cfg.policies.single_token,
    )

    inputs: Iterable[VerificationInput] = load_candidates(
        candidates_path,
        level_filter=level,
    )

    with logging_context(stage="s3", level=level):
        result = processor.process(inputs)

    verified_path = write_verified_candidates(result.verified, output_path)
    failed_path = failed_output_path or Path(output_path).with_suffix(".failed.jsonl")
    failed_path = write_failed_candidates(result.failed, failed_path)

    metadata_destination = metadata_path or Path(output_path).with_suffix(".metadata.json")
    metadata_payload = generate_s3_metadata(
        result.stats,
        {
            "policy_version": cfg.policies.policy_version,
            "level": level,
            "prefer_rule_over_llm": cfg.policies.single_token.prefer_rule_over_llm,
        },
        {
            "max_tokens_per_level": cfg.policies.single_token.max_tokens_per_level,
            "forbidden_punctuation": cfg.policies.single_token.forbidden_punctuation,
        },
    )
    Path(metadata_destination).parent.mkdir(parents=True, exist_ok=True)
    Path(metadata_destination).write_text(
        json.dumps(metadata_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    log.info(
        "S3 verification complete",
        verified=result.stats.get("verified", 0),
        failed=result.stats.get("failed", 0),
        verified_path=str(verified_path),
        failed_path=str(failed_path),
    )
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run S3 token verification")
    parser.add_argument("candidates", help="Path to S2 output JSONL")
    parser.add_argument("output", help="Destination JSONL for verified candidates")
    parser.add_argument("--level", type=int, required=True, help="Hierarchy level (0-3)")
    parser.add_argument(
        "--failed-output",
        dest="failed_output",
        help="Optional JSONL file for failed candidates",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        help="Optional metadata destination",
    )
    return parser


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI adaptor
    parser = _build_parser()
    args = parser.parse_args(argv)
    verify_tokens(
        args.candidates,
        level=args.level,
        output_path=args.output,
        failed_output_path=args.failed_output,
        metadata_path=args.metadata,
    )


__all__ = ["verify_tokens", "main"]
