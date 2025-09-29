"""Generate consolidated audit reports combining run, quality, and timing data."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from taxonomy.utils.helpers import ensure_directory, serialize_json


@dataclass
class Recommendation:
    identifier: str
    severity: str
    area: str
    description: str
    action: str
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compose a unified audit report from pipeline artefacts.",
    )
    parser.add_argument("run_dir", type=Path, help="Audit run directory")
    parser.add_argument(
        "--summary-path",
        type=Path,
        help="Override for audit_run_summary.json",
    )
    parser.add_argument(
        "--quality-path",
        type=Path,
        help="Override for quality_report.json",
    )
    parser.add_argument(
        "--timing-path",
        type=Path,
        help="Override for timing_report.json",
    )
    parser.add_argument(
        "--observability-path",
        type=Path,
        help="Override for observability_snapshot.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Destination for generated audit_report files (defaults to run directory).",
    )
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required artefact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _select_top_issues(quality: dict[str, Any], limit: int = 10) -> list[tuple[str, int]]:
    gaps = quality.get("gaps", {}) if isinstance(quality, dict) else {}
    issue_counts = gaps.get("issue_counts", []) if isinstance(gaps, dict) else []
    return issue_counts[:limit]


def _stage_valid_ratios(quality: dict[str, Any]) -> dict[str, float]:
    ratios: Dict[str, float] = {}
    for stage in quality.get("stages", []):
        name = stage.get("name")
        ratio = stage.get("valid_ratio")
        if name is not None and isinstance(ratio, (int, float)):
            ratios[name] = float(ratio)
    return ratios


def _stage_issue_counts(quality: dict[str, Any]) -> dict[str, int]:
    counts: Dict[str, int] = {}
    for stage in quality.get("stages", []):
        name = stage.get("name")
        issues = stage.get("issues") or []
        if name is not None:
            counts[name] = len(issues)
    return counts


def _stage_timings(timing: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: Dict[str, dict[str, Any]] = {}
    for stage in timing.get("stages", []):
        name = stage.get("name")
        if name:
            mapping[name] = stage
    return mapping


def _generate_recommendations(
    *,
    quality: dict[str, Any],
    timing: dict[str, Any],
    summary: dict[str, Any],
) -> List[Recommendation]:
    recommendations: List[Recommendation] = []
    ratios = _stage_valid_ratios(quality)
    issue_counts = _stage_issue_counts(quality)
    timings = _stage_timings(timing)

    identifier_counter = 1

    for stage_name, ratio in ratios.items():
        if ratio < 1.0:
            issues = issue_counts.get(stage_name, 0)
            severity = "high" if ratio < 0.9 else "medium"
            description = (
                f"{stage_name} valid ratio at {ratio:.3f}; {issues} records flagged by automatic checks"
            )
            action = (
                f"Review sampled outputs for {stage_name}, resolve schema issues, and update fixtures/policies."
            )
            evidence = [f"Valid ratio {ratio:.3f}", f"Issues detected: {issues}"]
            recommendations.append(
                Recommendation(
                    identifier=f"REC-{identifier_counter:02d}",
                    severity=severity,
                    area=f"Quality/{stage_name}",
                    description=description,
                    action=action,
                    evidence=evidence,
                )
            )
            identifier_counter += 1

    top_issues = _select_top_issues(quality, limit=5)
    for issue, count in top_issues:
        severity = "high" if count >= 3 else "medium"
        recommendations.append(
            Recommendation(
                identifier=f"REC-{identifier_counter:02d}",
                severity=severity,
                area="Quality",
                description=f"{count} occurrences of '{issue}'",
                action="Augment validation logic or data preprocessing to eliminate repeated issue.",
                evidence=[f"'{issue}' seen {count} times"],
            )
        )
        identifier_counter += 1

    bottleneck = timing.get("bottleneck") if isinstance(timing, dict) else None
    if bottleneck and bottleneck.get("duration_percent", 0) > 35:
        stage_name = bottleneck.get("name", "unknown")
        duration = bottleneck.get("duration_seconds", 0.0)
        throughput = bottleneck.get("throughput_items_per_second", 0.0)
        recommendations.append(
            Recommendation(
                identifier=f"REC-{identifier_counter:02d}",
                severity="medium",
                area=f"Performance/{stage_name}",
                description=(
                    f"{stage_name} consumes {bottleneck.get('duration_percent', 0):.2f}% of total runtime "
                    f"(~{duration:.2f}s)"
                ),
                action="Profile stage implementation, cache repeated lookups, and review external call latency.",
                evidence=[
                    f"Duration {duration:.2f}s",
                    f"Throughput {throughput:.3f} items/s",
                ],
            )
        )
        identifier_counter += 1

    if not recommendations:
        recommendations.append(
            Recommendation(
                identifier=f"REC-{identifier_counter:02d}",
                severity="low",
                area="General",
                description="No automated findings detected; perform manual sign-off before promoting artifacts.",
                action="Complete manual checklist, record approvals, and archive audit bundle.",
                evidence=["Automated checks clean"],
            )
        )
    return recommendations


def _build_markdown(
    *,
    summary: dict[str, Any],
    quality: dict[str, Any],
    timing: dict[str, Any],
    observability: dict[str, Any],
    recommendations: List[Recommendation],
    generated_at: str,
) -> str:
    lines: List[str] = []
    lines.append("# Level 0 Audit Report")
    lines.append("")
    lines.append(f"Run ID: {summary.get('run_id', 'unknown')} — Generated at: {generated_at}")
    lines.append("")
    lines.append("## Execution Overview")
    lines.append("")
    lines.append(f"Environment: {summary.get('environment')} | Policy Version: {summary.get('policy_version')}")
    lines.append(f"Output Directory: {summary.get('output_dir')}")
    lines.append(f"Total Duration: {timing.get('total_duration_seconds', 0):.3f}s")
    lines.append("")
    lines.append("## Stage Timing")
    lines.append("")
    lines.append("| Stage | Duration (s) | % Total | Items | Throughput | Mode |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for stage in timing.get("stages", []):
        lines.append(
            "| {name} | {duration:.3f} | {percent:.2f} | {items:.1f} | {throughput:.3f} | {mode} |".format(
                name=stage.get("name"),
                duration=stage.get("duration_seconds", 0.0),
                percent=stage.get("duration_percent", 0.0),
                items=stage.get("items_processed", 0.0),
                throughput=stage.get("throughput_items_per_second", 0.0),
                mode=stage.get("mode", "pipeline"),
            )
        )
    lines.append("")
    lines.append("## Quality Summary")
    lines.append("")
    lines.append("| Stage | Valid Ratio | Issues | Sampled |")
    lines.append("| --- | --- | --- | --- |")
    for stage in quality.get("stages", []):
        lines.append(
            "| {name} | {ratio:.3f} | {issues} | {sampled} |".format(
                name=stage.get("name"),
                ratio=stage.get("valid_ratio", 0.0),
                issues=len(stage.get("issues", [])),
                sampled=stage.get("records_sampled", 0),
            )
        )
    lines.append("")
    top_issues = _select_top_issues(quality, limit=5)
    if top_issues:
        lines.append("Top recurring issues:")
        for issue, count in top_issues:
            lines.append(f"- {issue} ({count})")
        lines.append("")
    snapshot_checksum = observability.get("checksum") if isinstance(observability, dict) else None
    lines.append("## Observability Snapshot")
    lines.append("")
    if snapshot_checksum:
        lines.append(f"Checksum: {snapshot_checksum}")
    counters = observability.get("counters", {}) if isinstance(observability, dict) else {}
    for phase, payload in counters.items():
        formatted = ", ".join(f"{k}={v}" for k, v in sorted(payload.items()))
        lines.append(f"- {phase}: {formatted}")
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    for idx, rec in enumerate(recommendations, start=1):
        lines.append(f"{idx}. [{rec.severity.upper()}] {rec.area} — {rec.description}")
        lines.append(f"   Action: {rec.action}")
        if rec.evidence:
            evidence_str = "; ".join(rec.evidence)
            lines.append(f"   Evidence: {evidence_str}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_dir = args.run_dir.resolve()
    summary_path = args.summary_path or run_dir / "audit_run_summary.json"
    quality_path = args.quality_path or run_dir / "quality_report.json"
    timing_path = args.timing_path or run_dir / "timing_report.json"
    observability_path = args.observability_path or run_dir / "observability_snapshot.json"

    summary = _load_json(summary_path)
    quality = _load_json(quality_path)
    timing = _load_json(timing_path)
    observability = _load_json(observability_path)

    recommendations = _generate_recommendations(
        quality=quality,
        timing=timing,
        summary=summary,
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    output_dir = ensure_directory(args.output_dir or run_dir)

    report_payload = {
        "run_id": summary.get("run_id"),
        "generated_at": generated_at,
        "summary": summary,
        "quality": quality,
        "timing": timing,
        "observability_checksum": observability.get("checksum"),
        "recommendations": [rec.to_dict() for rec in recommendations],
    }
    serialize_json(report_payload, Path(output_dir) / "audit_report.json")

    markdown = _build_markdown(
        summary=summary,
        quality=quality,
        timing=timing,
        observability=observability,
        recommendations=recommendations,
        generated_at=generated_at,
    )
    (Path(output_dir) / "audit_report.md").write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
