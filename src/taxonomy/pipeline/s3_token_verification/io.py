"""I/O helpers for S3 token verification."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from taxonomy.entities.core import Candidate, Rationale
from taxonomy.utils.helpers import ensure_directory
from taxonomy.utils.logging import get_logger

from .processor import (
    TokenVerificationDecision,
    VerificationInput,
)


def load_candidates(
    input_path: str | Path,
    *,
    level_filter: Optional[int] = None,
) -> Iterator[VerificationInput]:
    """Yield :class:`VerificationInput` instances from S2 output JSONL."""

    log = get_logger(module=__name__)
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"S2 output not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for offset, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            candidate_data = payload.get("candidate", payload)
            rationale_data = payload.get("rationale", {})
            candidate = Candidate.model_validate(candidate_data)
            if level_filter is not None and candidate.level != level_filter:
                continue
            rationale = Rationale.model_validate(rationale_data) if rationale_data else Rationale()
            institutions = list(payload.get("institutions", []))
            record_ids = list(payload.get("record_fingerprints", []))
            metadata = {k: v for k, v in payload.items() if k not in {"candidate", "rationale", "institutions", "record_fingerprints"}}
            log.debug(
                "Loaded candidate for S3",
                level=candidate.level,
                normalized=candidate.normalized,
            )
            yield VerificationInput(
                candidate=candidate,
                rationale=rationale,
                institutions=institutions,
                record_fingerprints=record_ids,
                metadata=metadata or None,
            )


def write_verified_candidates(
    decisions: Iterable[TokenVerificationDecision],
    output_path: str | Path,
) -> Path:
    """Write verified candidates to JSONL."""

    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            if not decision.passed:
                continue
            payload = _decision_payload(decision)
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
    return path.resolve()


def write_failed_candidates(
    decisions: Iterable[TokenVerificationDecision],
    output_path: str | Path,
) -> Path:
    """Write failed verifications to JSONL for auditing."""

    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            if decision.passed:
                continue
            payload = _decision_payload(decision)
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
    return path.resolve()


def generate_s3_metadata(
    processing_stats: dict,
    config_used: dict,
    verification_decisions: dict,
) -> dict:
    """Create a metadata document capturing verification statistics."""

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": dict(processing_stats),
        "verification": dict(verification_decisions),
        "config": dict(config_used),
    }


def _decision_payload(decision: TokenVerificationDecision) -> dict:
    payload = {
        "candidate": decision.candidate.model_dump(mode="json", exclude_none=True),
        "rationale": decision.rationale.model_dump(mode="json"),
        "institutions": decision.institutions,
        "record_fingerprints": decision.record_fingerprints,
        "passed": decision.passed,
        "rule_evaluation": asdict(decision.rule_evaluation),
        "llm_result": asdict(decision.llm_result) if decision.llm_result is not None else None,
    }
    return payload


__all__ = [
    "load_candidates",
    "write_verified_candidates",
    "write_failed_candidates",
    "generate_s3_metadata",
    "VerificationInput",
]
