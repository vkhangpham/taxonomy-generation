"""Quality assessment utilities for level 0 audit runs.

The checker samples stage outputs (S0–S3), performs lightweight schema
validation, and emits structured reports to support manual review. A companion
Markdown file provides checklists and prompts for auditors to capture face-check
findings.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple

from taxonomy.utils.helpers import ensure_directory, serialize_json


@dataclass(frozen=True)
class StageDefinition:
    name: str
    relative_path: Path
    stage_type: str
    description: str


STAGE_DEFINITIONS: tuple[StageDefinition, ...] = (
    StageDefinition(
        name="S0",
        relative_path=Path("S0/source_records.jsonl"),
        stage_type="s0",
        description="Raw source records emitted from level 0 bootstrap",
    ),
    StageDefinition(
        name="S1",
        relative_path=Path("S1/level0_candidates.jsonl"),
        stage_type="s1",
        description="Extracted level 0 candidates",
    ),
    StageDefinition(
        name="S2_kept",
        relative_path=Path("S2/level0_kept.jsonl"),
        stage_type="s2_kept",
        description="Candidates retained after frequency filtering",
    ),
    StageDefinition(
        name="S2_dropped",
        relative_path=Path("S2/level0_dropped.jsonl"),
        stage_type="s2_dropped",
        description="Candidates dropped during frequency filtering",
    ),
    StageDefinition(
        name="S3_verified",
        relative_path=Path("S3/level0_verified.jsonl"),
        stage_type="s3_verified",
        description="Token-verified candidates passed downstream",
    ),
    StageDefinition(
        name="S3_failed",
        relative_path=Path("S3/level0_failed.jsonl"),
        stage_type="s3_failed",
        description="Candidates failing token verification",
    ),
)


@dataclass
class StageReport:
    name: str
    path: str
    stage_type: str
    records_total: int
    records_sampled: int
    valid_ratio: float
    issues: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


ValidationFn = Callable[[dict[str, Any]], List[str]]
SummaryFn = Callable[[dict[str, Any]], dict[str, Any]]


def _validate_s0(record: dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(record, dict):
        return ["record is not a JSON object"]
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        errors.append("missing or empty text field")
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("missing provenance object")
    else:
        institution = provenance.get("institution")
        url = provenance.get("url")
        fetched_at = provenance.get("fetched_at")
        if not isinstance(institution, str) or not institution.strip():
            errors.append("provenance.institution missing or blank")
        if not isinstance(url, str) or not url.strip():
            errors.append("provenance.url missing or blank")
        if not isinstance(fetched_at, str) or "T" not in fetched_at:
            errors.append("provenance.fetched_at missing or not ISO timestamp")
    meta = record.get("meta")
    if not isinstance(meta, dict):
        errors.append("missing meta object")
    else:
        hints = meta.get("hints")
        if not isinstance(hints, dict):
            errors.append("meta.hints missing or not mapping")
        else:
            if not isinstance(hints.get("source"), str):
                errors.append("meta.hints.source missing")
            if hints.get("level") not in {"S0", 0, "0"}:
                errors.append("meta.hints.level not set to S0")
    return errors


def _summarize_s0(record: dict[str, Any]) -> dict[str, Any]:
    provenance = record.get("provenance", {}) if isinstance(record, dict) else {}
    text = record.get("text", "") if isinstance(record, dict) else ""
    clipped = (text[:120] + "…") if len(text) > 120 else text
    return {
        "text": clipped,
        "institution": provenance.get("institution"),
        "url": provenance.get("url"),
    }


def _validate_s1(record: dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(record, dict):
        return ["candidate is not a JSON object"]
    level = record.get("level")
    if level != 0:
        errors.append("expected level 0 candidate")
    for field in ("label", "normalized"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing or empty {field}")
    support = record.get("support")
    if not isinstance(support, dict):
        errors.append("support metadata missing")
    else:
        for key in ("institutions", "records", "count"):
            if not isinstance(support.get(key), int) or support.get(key) < 0:
                errors.append(f"support.{key} missing or negative")
    aliases = record.get("aliases")
    if aliases is not None and not isinstance(aliases, list):
        errors.append("aliases should be a list")
    return errors


def _summarize_s1(record: dict[str, Any]) -> dict[str, Any]:
    support = record.get("support", {}) if isinstance(record, dict) else {}
    return {
        "label": record.get("label"),
        "normalized": record.get("normalized"),
        "support_institutions": support.get("institutions"),
        "support_records": support.get("records"),
    }


def _validate_s2(record: dict[str, Any], *, expect_passed: bool) -> List[str]:
    errors: List[str] = []
    if not isinstance(record, dict):
        return ["S2 decision is not a JSON object"]
    candidate = record.get("candidate")
    if not isinstance(candidate, dict):
        errors.append("candidate payload missing")
    else:
        if candidate.get("level") != 0:
            errors.append("candidate.level is not 0")
        if not isinstance(candidate.get("normalized"), str) or not candidate.get("normalized").strip():
            errors.append("candidate.normalized missing or blank")
    if bool(record.get("passed")) != expect_passed:
        expected = "passed" if expect_passed else "dropped"
        errors.append(f"decision should be marked as {expected}")
    institutions = record.get("institutions")
    if not isinstance(institutions, list):
        errors.append("institutions list missing")
    rationale = record.get("rationale")
    if not isinstance(rationale, dict):
        errors.append("rationale missing")
    return errors


def _summarize_s2(record: dict[str, Any]) -> dict[str, Any]:
    candidate = record.get("candidate", {}) if isinstance(record, dict) else {}
    return {
        "normalized": candidate.get("normalized"),
        "weight": record.get("weight"),
        "institutions": len(record.get("institutions", []) if isinstance(record, dict) else []),
        "passed": record.get("passed"),
    }


def _validate_s3(record: dict[str, Any], *, expect_passed: bool) -> List[str]:
    errors: List[str] = []
    if not isinstance(record, dict):
        return ["S3 decision is not a JSON object"]
    candidate = record.get("candidate")
    if not isinstance(candidate, dict):
        errors.append("candidate payload missing")
    else:
        if candidate.get("level") != 0:
            errors.append("candidate.level is not 0")
        normalized = candidate.get("normalized")
        if not isinstance(normalized, str) or not normalized.strip():
            errors.append("candidate.normalized missing or blank")
    if bool(record.get("passed")) != expect_passed:
        state = "passed" if expect_passed else "failed"
        errors.append(f"candidate should be marked as {state}")
    rule_eval = record.get("rule_evaluation")
    if not isinstance(rule_eval, dict):
        errors.append("rule_evaluation missing")
    rationale = record.get("rationale")
    if not isinstance(rationale, dict):
        errors.append("rationale missing")
    return errors


def _summarize_s3(record: dict[str, Any]) -> dict[str, Any]:
    candidate = record.get("candidate", {}) if isinstance(record, dict) else {}
    rule_eval = record.get("rule_evaluation", {}) if isinstance(record, dict) else {}
    return {
        "normalized": candidate.get("normalized"),
        "passed": record.get("passed"),
        "rule_passed": rule_eval.get("passed"),
        "allowlist_hit": rule_eval.get("allowlist_hit"),
    }


VALIDATION_MAP: dict[str, tuple[ValidationFn, SummaryFn]] = {
    "s0": (_validate_s0, _summarize_s0),
    "s1": (_validate_s1, _summarize_s1),
    "s2_kept": (lambda payload: _validate_s2(payload, expect_passed=True), _summarize_s2),
    "s2_dropped": (lambda payload: _validate_s2(payload, expect_passed=False), _summarize_s2),
    "s3_verified": (lambda payload: _validate_s3(payload, expect_passed=True), _summarize_s3),
    "s3_failed": (lambda payload: _validate_s3(payload, expect_passed=False), _summarize_s3),
}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample and validate audit outputs for manual review.",
    )
    parser.add_argument("run_dir", type=Path, help="Path to the audit run directory generated by audit_level0_run.py")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated quality reports (defaults to the run directory).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Maximum number of records to sample per stage.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20250929,
        help="Random seed for deterministic sampling.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Optional previous quality_report.json for comparison.",
    )
    return parser.parse_args(argv)


def _load_lines(path: Path) -> Iterable[Tuple[int, str]]:
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            yield index, stripped


def _evaluate_stage(
    definition: StageDefinition,
    run_dir: Path,
    sample_size: int,
    rng: random.Random,
) -> StageReport:
    path = run_dir / definition.relative_path
    if not path.exists():
        issue = {"line": None, "errors": ["output file missing"], "path": str(path)}
        return StageReport(
            name=definition.name,
            path=str(path),
            stage_type=definition.stage_type,
            records_total=0,
            records_sampled=0,
            valid_ratio=0.0,
            issues=[issue],
            samples=[],
            summary={"missing": True},
        )

    validator, summarizer = VALIDATION_MAP[definition.stage_type]
    issues: List[dict[str, Any]] = []
    records: List[Tuple[int, dict[str, Any]]] = []
    invalid_lines: set[int] = set()

    for line_no, raw in _load_lines(path):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append({
                "line": line_no,
                "errors": [f"invalid JSON ({exc.msg})"],
                "raw": raw[:160],
            })
            invalid_lines.add(line_no)
            continue
        errors = validator(payload)
        if errors:
            issues.append({"line": line_no, "errors": errors})
            invalid_lines.add(line_no)
        records.append((line_no, payload))

    total_records = len(records) + len({line for line in invalid_lines if line not in {idx for idx, _ in records}})
    if total_records == 0:
        return StageReport(
            name=definition.name,
            path=str(path),
            stage_type=definition.stage_type,
            records_total=0,
            records_sampled=0,
            valid_ratio=0.0,
            issues=issues,
            samples=[],
            summary={"missing": False, "empty": True},
        )

    valid_records = total_records - len(invalid_lines)
    valid_ratio = valid_records / total_records if total_records else 0.0

    record_sample = records
    if len(records) > sample_size:
        indices = rng.sample(range(len(records)), sample_size)
        record_sample = [records[idx] for idx in sorted(indices)]

    samples: List[dict[str, Any]] = []
    for line_no, payload in record_sample:
        summary = summarizer(payload)
        flattened = json.dumps(payload, indent=2, sort_keys=True)
        samples.append(
            {
                "line": line_no,
                "summary": summary,
                "record": flattened,
                "has_issues": any(issue.get("line") == line_no for issue in issues),
            }
        )

    summary_payload = {
        "description": definition.description,
        "path": str(path),
        "records": total_records,
        "valid": valid_records,
    }
    return StageReport(
        name=definition.name,
        path=str(path),
        stage_type=definition.stage_type,
        records_total=total_records,
        records_sampled=len(record_sample),
        valid_ratio=round(valid_ratio, 3),
        issues=issues,
        samples=samples,
        summary=summary_payload,
    )


def _aggregate_gaps(stage_reports: Iterable[StageReport]) -> dict[str, Any]:
    counts: Dict[str, int] = {}
    for report in stage_reports:
        for issue in report.issues:
            for error in issue.get("errors", []):
                counts[error] = counts.get(error, 0) + 1
    top = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return {
        "issue_counts": top,
        "total_issues": sum(counts.values()),
        "distinct_issues": len(counts),
    }


def _load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _compare_with_baseline(current: List[StageReport], baseline: dict[str, Any] | None) -> dict[str, Any] | None:
    if baseline is None:
        return None
    baseline_stages = {stage["name"]: stage for stage in baseline.get("stages", [])}
    comparison: Dict[str, Any] = {}
    for report in current:
        previous = baseline_stages.get(report.name)
        if not previous:
            continue
        valid_delta = report.valid_ratio - previous.get("valid_ratio", 0.0)
        issue_delta = len(report.issues) - len(previous.get("issues", []))
        comparison[report.name] = {
            "valid_ratio_delta": round(valid_delta, 3),
            "issue_count_delta": issue_delta,
        }
    return comparison or None


def _build_markdown(
    *,
    stage_reports: List[StageReport],
    gaps: dict[str, Any],
    comparison: dict[str, Any] | None,
    generated_at: str,
) -> str:
    lines: List[str] = []
    lines.append("# Level 0 Audit Quality Review")
    lines.append("")
    lines.append(f"Generated at: {generated_at}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Stage | Records | Valid Ratio | Issues |")
    lines.append("| --- | --- | --- | --- |")
    for report in stage_reports:
        lines.append(
            f"| {report.name} | {report.records_total} | {report.valid_ratio:.3f} | {len(report.issues)} |"
        )
    lines.append("")
    if gaps.get("issue_counts"):
        lines.append("## Frequent Issues")
        lines.append("")
        for error, count in gaps["issue_counts"][:10]:
            lines.append(f"- {error} ({count})")
        lines.append("")
    if comparison:
        lines.append("## Baseline Comparison")
        lines.append("")
        for stage, deltas in comparison.items():
            lines.append(
                f"- {stage}: Δvalid {deltas['valid_ratio_delta']:+.3f}, Δissues {deltas['issue_count_delta']:+d}"
            )
        lines.append("")
    for report in stage_reports:
        lines.append(f"## {report.name} — {report.summary.get('description', report.name)}")
        lines.append("")
        lines.append(
            f"Records: {report.records_total} • Valid: {report.summary.get('valid', report.records_total)} • "
            f"Issues: {len(report.issues)}"
        )
        lines.append("")
        lines.append("Manual checklist:")
        checklist = {
            "s0": [
                "Content matches expected institution + college combinations",
                "Provenance metadata present and accurate",
                "Language and encoding fields populated",
            ],
            "s1": [
                "Candidate labels are normalized and free of boilerplate",
                "Support counts reflect underlying source diversity",
                "Aliases capture meaningful variants",
            ],
            "s2_kept": [
                "Frequency thresholds applied as expected",
                "Institutions list contains canonical identities",
                "Rationale explains pass decision",
            ],
            "s2_dropped": [
                "Dropped candidates cite clear failure reasons",
                "Record fingerprints trace back to source records",
                "No high-confidence candidates incorrectly removed",
            ],
            "s3_verified": [
                "Token rules enforce single-token policy",
                "LLM outcomes align with rule fallback",
                "Aliases updated with useful suggestions",
            ],
            "s3_failed": [
                "Failed candidates document rejection reasons",
                "LLM error handling is captured when applicable",
                "No allowable items incorrectly rejected",
            ],
        }
        for item in checklist.get(report.stage_type, []):
            lines.append(f"- [ ] {item}")
        lines.append("")
        if not report.samples:
            lines.append("No samples available.\n")
            continue
        lines.append("Samples:")
        for sample in report.samples:
            status = " (issues flagged)" if sample.get("has_issues") else ""
            lines.append(f"- Line {sample['line']}{status}")
            summary = sample.get("summary", {})
            if summary:
                lines.append(f"  Summary: {json.dumps(summary, ensure_ascii=False)}")
            lines.append("  ```json")
            lines.append(sample.get("record", "{}"))
            lines.append("  ```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_dir = args.run_dir.resolve()
    output_dir = ensure_directory(args.output_dir or run_dir)
    rng = random.Random(args.seed)

    stage_reports: List[StageReport] = []
    for definition in STAGE_DEFINITIONS:
        report = _evaluate_stage(definition, run_dir, args.sample_size, rng)
        stage_reports.append(report)

    gaps = _aggregate_gaps(stage_reports)
    baseline = _load_baseline(args.baseline)
    comparison = _compare_with_baseline(stage_reports, baseline)

    generated_at = datetime.now(timezone.utc).isoformat()
    report_payload = {
        "run_dir": str(run_dir),
        "generated_at": generated_at,
        "sample_size": args.sample_size,
        "seed": args.seed,
        "stages": [report.to_dict() for report in stage_reports],
        "gaps": gaps,
        "baseline_comparison": comparison,
    }

    serialize_json(report_payload, Path(output_dir) / "quality_report.json")
    markdown_content = _build_markdown(
        stage_reports=stage_reports,
        gaps=gaps,
        comparison=comparison,
        generated_at=generated_at,
    )
    (Path(output_dir) / "quality_report.md").write_text(markdown_content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
