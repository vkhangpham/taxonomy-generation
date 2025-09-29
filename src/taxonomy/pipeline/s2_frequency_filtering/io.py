"""Streaming I/O helpers for S2 frequency filtering."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from taxonomy.entities.core import Candidate
from taxonomy.utils.helpers import ensure_directory, normalize_whitespace
from taxonomy.utils.logging import get_logger

from .aggregator import CandidateEvidence, FrequencyDecision


def load_candidates(
    input_path: str | Path,
    *,
    level_filter: Optional[int] = None,
) -> Iterator[CandidateEvidence]:
    """Yield :class:`CandidateEvidence` parsed from an S1 candidate JSONL file."""

    log = get_logger(module=__name__)
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Candidate file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for offset, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            candidate_payload = _extract_candidate_payload(payload)
            candidate = Candidate.model_validate(candidate_payload)
            if level_filter is not None and candidate.level != level_filter:
                continue

            institutions = _extract_institutions(payload, candidate_payload)
            record_ids = _extract_record_fingerprints(payload, candidate_payload)

            evidence = CandidateEvidence(
                candidate=candidate,
                institutions=institutions,
                record_fingerprints=record_ids,
                raw_payload=payload,
            )
            log.debug(
                "Loaded candidate for S2",
                level=candidate.level,
                normalized=candidate.normalized,
                institutions=len(institutions),
            )
            yield evidence


def write_kept_candidates(
    decisions: Iterable[FrequencyDecision],
    output_path: str | Path,
) -> Path:
    """Write kept candidates with rationale to JSONL."""

    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            if not decision.passed:
                continue
            payload = {
                "candidate": decision.candidate.model_dump(mode="json", exclude_none=True),
                "rationale": decision.rationale.model_dump(mode="json"),
                "institutions": decision.institutions,
                "record_fingerprints": decision.record_fingerprints,
                "weight": decision.weight,
                "passed": True,
            }
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
    return path.resolve()


def write_dropped_candidates(
    decisions: Iterable[FrequencyDecision],
    output_path: str | Path,
) -> Path:
    """Write dropped candidate audit information to JSONL."""

    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            if decision.passed:
                continue
            payload = {
                "candidate": decision.candidate.model_dump(mode="json", exclude_none=True),
                "rationale": decision.rationale.model_dump(mode="json"),
                "institutions": decision.institutions,
                "record_fingerprints": decision.record_fingerprints,
                "weight": decision.weight,
                "passed": False,
            }
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
    return path.resolve()


def generate_s2_metadata(
    processing_stats: dict,
    config_used: dict,
    threshold_decisions: dict,
    *,
    observability: dict[str, object] | None = None,
) -> dict:
    """Generate metadata describing the S2 processing run."""

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": dict(processing_stats),
        "thresholds": dict(threshold_decisions),
        "config": dict(config_used),
    }
    if observability is not None:
        metadata["observability"] = observability
    return metadata


def _extract_candidate_payload(payload: dict) -> dict:
    if "candidate" in payload and isinstance(payload["candidate"], dict):
        return payload["candidate"]
    return payload


def _extract_institutions(*sources: dict) -> set[str]:
    institutions: set[str] = set()
    for source in sources:
        data = source or {}
        raw = data.get("institutions") or data.get("supporting_institutions")
        if isinstance(raw, str):
            institutions.add(normalize_whitespace(raw))
        elif isinstance(raw, list):
            institutions.update(
                normalize_whitespace(str(entry))
                for entry in raw
                if str(entry).strip()
            )
        support_details = data.get("support_details")
        if isinstance(support_details, dict):
            inst_values = support_details.get("institutions")
            if isinstance(inst_values, list):
                institutions.update(
                    normalize_whitespace(str(entry))
                    for entry in inst_values
                    if str(entry).strip()
                )
        provenance = data.get("provenance")
        if isinstance(provenance, dict):
            inst = provenance.get("institution")
            if inst:
                institutions.add(normalize_whitespace(str(inst)))
        elif isinstance(provenance, list):
            for entry in provenance:
                if isinstance(entry, dict):
                    inst = entry.get("institution")
                    if inst:
                        institutions.add(normalize_whitespace(str(inst)))
    return {value for value in institutions if value}


def _extract_record_fingerprints(*sources: dict) -> set[str]:
    fingerprints: set[str] = set()
    for source in sources:
        data = source or {}
        raw = data.get("record_fingerprints") or data.get("records")
        if isinstance(raw, list):
            fingerprints.update(str(entry) for entry in raw if str(entry).strip())
        support_details = data.get("support_details")
        if isinstance(support_details, dict):
            record_values = support_details.get("record_fingerprints")
            if isinstance(record_values, list):
                fingerprints.update(str(entry) for entry in record_values if str(entry).strip())
    return {value for value in fingerprints if value}


__all__ = [
    "load_candidates",
    "write_kept_candidates",
    "write_dropped_candidates",
    "generate_s2_metadata",
    "CandidateEvidence",
]
