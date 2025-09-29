"""Timing and throughput analysis for audit-mode level 0 runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from taxonomy.utils.helpers import ensure_directory, serialize_json


@dataclass
class StageTiming:
    name: str
    duration_seconds: float
    duration_percent: float
    items_processed: float
    throughput_items_per_second: float
    audit_limit: float
    mode: str
    stats: dict[str, Any]
    observability_counters: dict[str, Any]
    observability_performance: dict[str, Any]
    started_at: str | None
    completed_at: str | None
    estimated_duration_for_target: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["duration_seconds"] = round(payload["duration_seconds"], 3)
        payload["throughput_items_per_second"] = round(payload["throughput_items_per_second"], 3)
        payload["duration_percent"] = round(payload["duration_percent"], 2)
        payload["estimated_duration_for_target"] = round(payload["estimated_duration_for_target"], 1)
        return payload


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze timing and throughput for audit-mode pipeline runs.",
    )
    parser.add_argument("run_dir", type=Path, help="Audit run directory containing audit_run_summary.json")
    parser.add_argument(
        "--summary-path",
        type=Path,
        help="Optional override for the summary JSON path.",
    )
    parser.add_argument(
        "--observability-path",
        type=Path,
        help="Optional override for the observability snapshot JSON path.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated timing reports (defaults to run directory).",
    )
    parser.add_argument(
        "--target-items",
        type=int,
        default=1000,
        help="Target item count for scaling estimates.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Optional previous timing_report.json for comparison.",
    )
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_stage_items(stage: dict[str, Any], counters: dict[str, Any]) -> float:
    if stage.get("audit_items") is not None:
        return float(stage["audit_items"])
    for key in ("records_in", "candidates_in", "checked", "kept", "verified"):
        value = counters.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _gather_stage_timings(
    stages: Iterable[dict[str, Any]],
    observability: dict[str, Any],
    target_items: int,
) -> List[StageTiming]:
    counters = observability.get("counters", {}) if isinstance(observability, dict) else {}
    performance = observability.get("performance", {}) if isinstance(observability, dict) else {}
    stage_list = list(stages)
    total_duration = sum(float(stage.get("duration_seconds", 0.0)) for stage in stage_list)
    timings: List[StageTiming] = []
    for stage in stage_list:
        name = stage.get("name", "unknown")
        duration = float(stage.get("duration_seconds", 0.0))
        if total_duration > 0:
            duration_percent = (duration / total_duration) * 100.0
        else:
            duration_percent = 0.0
        stage_counters = counters.get(name.replace("_kept", "").replace("_dropped", ""), {})
        stage_perf = performance.get(name.replace("_kept", "").replace("_dropped", ""), {})
        items = _resolve_stage_items(stage, stage_counters)
        throughput = items / duration if duration > 0 else 0.0
        audit_limit = float(stage.get("audit_limit") or 0)
        mode = stage.get("mode", "pipeline")
        stats = stage.get("stats") or {}
        started_at = stage.get("started_at")
        completed_at = stage.get("completed_at")
        if items > 0:
            estimated_duration = (duration / items) * target_items
        else:
            estimated_duration = 0.0
        timings.append(
            StageTiming(
                name=name,
                duration_seconds=duration,
                duration_percent=duration_percent,
                items_processed=items,
                throughput_items_per_second=throughput,
                audit_limit=audit_limit,
                mode=mode,
                stats=stats if isinstance(stats, dict) else {},
                observability_counters=stage_counters if isinstance(stage_counters, dict) else {},
                observability_performance=stage_perf if isinstance(stage_perf, dict) else {},
                started_at=started_at,
                completed_at=completed_at,
                estimated_duration_for_target=estimated_duration,
            )
        )
    return timings


def _identify_bottleneck(timings: Iterable[StageTiming]) -> StageTiming | None:
    timings_list = list(timings)
    if not timings_list:
        return None
    return max(timings_list, key=lambda stage: stage.duration_seconds)


def _load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _load_json(path)


def _compare_with_baseline(
    current: List[StageTiming],
    baseline: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if baseline is None:
        return None
    baseline_stages = {
        stage_dict.get("name"): stage_dict
        for stage_dict in baseline.get("stages", [])
    }
    deltas: Dict[str, Any] = {}
    for stage in current:
        previous = baseline_stages.get(stage.name)
        if not previous:
            continue
        duration_delta = stage.duration_seconds - previous.get("duration_seconds", 0.0)
        throughput_delta = stage.throughput_items_per_second - previous.get("throughput_items_per_second", 0.0)
        deltas[stage.name] = {
            "duration_delta": round(duration_delta, 3),
            "throughput_delta": round(throughput_delta, 3),
        }
    return deltas or None


def _build_markdown(
    *,
    summary: dict[str, Any],
    timings: List[StageTiming],
    bottleneck: StageTiming | None,
    comparison: dict[str, Any] | None,
    target_items: int,
    generated_at: str,
) -> str:
    lines: List[str] = []
    lines.append("# Audit Timing Analysis")
    lines.append("")
    lines.append(f"Run ID: {summary.get('run_id', 'unknown')}")
    lines.append(f"Generated at: {generated_at}")
    lines.append("")
    total_duration = sum(t.duration_seconds for t in timings)
    lines.append(f"Total duration (recorded): {total_duration:.3f}s")
    lines.append("")
    lines.append("| Stage | Duration (s) | % Total | Items | Throughput (items/s) | Mode |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for stage in timings:
        lines.append(
            "| {name} | {dur:.3f} | {pct:.2f} | {items:.1f} | {tp:.3f} | {mode} |".format(
                name=stage.name,
                dur=stage.duration_seconds,
                pct=stage.duration_percent,
                items=stage.items_processed,
                tp=stage.throughput_items_per_second,
                mode=stage.mode,
            )
        )
    lines.append("")
    max_duration = max((stage.duration_seconds for stage in timings), default=0.0)
    if max_duration > 0:
        lines.append("Stage duration profile:")
        for stage in timings:
            bar_length = max(1, int(round((stage.duration_seconds / max_duration) * 20))) if stage.duration_seconds else 1
            bar = "=" * bar_length
            lines.append(f"- {stage.name}: {bar} {stage.duration_seconds:.3f}s")
        lines.append("")
    if bottleneck:
        lines.append(
            f"Primary bottleneck: {bottleneck.name} ({bottleneck.duration_percent:.2f}% of runtime, "
            f"~{bottleneck.duration_seconds:.3f}s)"
        )
        if bottleneck.throughput_items_per_second > 0:
            projected = bottleneck.estimated_duration_for_target
            lines.append(
                f"Estimated {target_items} items for {bottleneck.name}: {projected:.1f}s"
            )
        lines.append("")
    if comparison:
        lines.append("Baseline deltas:")
        for stage_name, deltas in comparison.items():
            lines.append(
                f"- {stage_name}: Δduration {deltas['duration_delta']:+.3f}s, Δthroughput {deltas['throughput_delta']:+.3f} items/s"
            )
        lines.append("")
    lines.append("Observability counters:")
    for stage in timings:
        counters = stage.observability_counters
        if not counters:
            continue
        formatted = ", ".join(f"{key}={value}" for key, value in sorted(counters.items()))
        lines.append(f"- {stage.name}: {formatted}")
    lines.append("")
    lines.append("Observability performance metrics:")
    for stage in timings:
        perf = stage.observability_performance
        if not perf:
            continue
        formatted = ", ".join(f"{key}={value}" for key, value in sorted(perf.items()))
        lines.append(f"- {stage.name}: {formatted}")
    lines.append("")
    lines.append("Scaling estimates:")
    for stage in timings:
        if stage.items_processed > 0 and stage.estimated_duration_for_target > 0:
            lines.append(
                f"- {stage.name}: {stage.items_processed:.1f} items in {stage.duration_seconds:.3f}s → "
                f"{stage.estimated_duration_for_target:.1f}s for {target_items} items"
            )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_dir = args.run_dir.resolve()
    summary_path = args.summary_path or run_dir / "audit_run_summary.json"
    observability_path = args.observability_path or run_dir / "observability_snapshot.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")
    if not observability_path.exists():
        raise FileNotFoundError(f"Observability snapshot not found: {observability_path}")

    summary = _load_json(summary_path)
    observability = _load_json(observability_path)
    timings = _gather_stage_timings(summary.get("stages", []), observability, args.target_items)
    bottleneck = _identify_bottleneck(timings)
    baseline = _load_baseline(args.baseline)
    comparison = _compare_with_baseline(timings, baseline)

    generated_at = datetime.now(timezone.utc).isoformat()
    output_dir = ensure_directory(args.output_dir or run_dir)

    report_payload = {
        "run_id": summary.get("run_id"),
        "generated_at": generated_at,
        "target_items": args.target_items,
        "total_duration_seconds": sum(stage.duration_seconds for stage in timings),
        "stages": [stage.to_dict() for stage in timings],
        "bottleneck": bottleneck.to_dict() if bottleneck else None,
        "baseline_comparison": comparison,
    }
    serialize_json(report_payload, Path(output_dir) / "timing_report.json")

    markdown = _build_markdown(
        summary=summary,
        timings=timings,
        bottleneck=bottleneck,
        comparison=comparison,
        target_items=args.target_items,
        generated_at=generated_at,
    )
    (Path(output_dir) / "timing_report.md").write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
