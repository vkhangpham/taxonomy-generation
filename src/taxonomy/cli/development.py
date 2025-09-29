"""Developer-focused CLI helpers for testing, debugging, and data export."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

import typer
from rich.table import Table

from taxonomy.observability import ObservabilityContext

from .common import CLIError, console, get_state, resolve_path, run_subcommand


app = typer.Typer(
    add_completion=False,
    help="Developer tooling for test execution, debugging artefacts, and exports.",
    no_args_is_help=True,
)


def _run_pytest(args: list[str]) -> int:
    try:
        import pytest  # type: ignore
    except ImportError as exc:  # pragma: no cover - defensive
        console.print(f"[red]pytest is not installed:[/red] {exc}")
        return 1
    return pytest.main(args)


def _test_command(
    ctx: typer.Context,
    level: Optional[int] = typer.Option(
        None,
        "--level",
        help="Filter pytest collection to a specific hierarchy level.",
    ),
    coverage: bool = typer.Option(
        False,
        "--coverage",
        help="Run pytest with coverage reporting when pytest-cov is available.",
    ),
) -> None:
    args: list[str] = []
    if level is not None:
        args.extend(["-k", f"level_{level}"])
    if coverage:
        import importlib.util

        if importlib.util.find_spec("pytest_cov") is None:
            console.print("[yellow]pytest-cov not installed; skipping coverage instrumentation.[/yellow]")
        else:
            args.extend(["--cov=src/taxonomy", "--cov-report=term-missing"])
    args.extend(list(ctx.args))
    exit_code = _run_pytest(args)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)
    console.print("[green]Tests completed successfully.[/green]")


def _debug_command(
    ctx: typer.Context,
    quarantine: bool = typer.Option(False, "--quarantine", help="Show quarantine summary."),
    validation_failures: bool = typer.Option(
        False,
        "--validation-failures",
        help="Display validation failure statistics when available.",
    ),
) -> None:
    state = get_state(ctx)
    context: ObservabilityContext | None = state.observability
    if context is None:
        console.print("[yellow]Observability disabled for this session.[/yellow]")
        return
    snapshot = context.export()
    if quarantine:
        quarantine_data = snapshot.get("quarantine", {})
        table = Table(title="Quarantine Summary", box=None)
        table.add_column("Reason")
        table.add_column("Count", justify="right")
        for reason, count in sorted(quarantine_data.get("by_reason", {}).items()):
            table.add_row(reason, str(count))
        table.add_row("Total", str(quarantine_data.get("total", 0)))
        console.print(table)
    if validation_failures:
        validation_stats = snapshot.get("performance", {}).get("validation", {})
        if not validation_stats:
            console.print("[yellow]No validation failure metrics recorded.[/yellow]")
        else:
            table = Table(title="Validation Performance", box=None)
            table.add_column("Metric")
            table.add_column("Value", justify="right")
            for metric, value in validation_stats.items():
                table.add_row(metric, str(value))
            console.print(table)
    if not quarantine and not validation_failures:
        console.print("[yellow]No debug options selected; use --quarantine or --validation-failures.[/yellow]")


def _export_command(
    ctx: typer.Context,
    *,
    source: Path = typer.Option(..., "--source", "-s", help="Input JSONL file containing concepts."),
    destination: Path = typer.Option(..., "--output", "-o", help="Destination file for exported data."),
    fmt: str = typer.Option(
        "json",
        "--format",
        help="Export format: csv or json.",
        case_sensitive=False,
    ),
    level: Optional[int] = typer.Option(
        None,
        "--level",
        help="Filter records by the given hierarchy level when present.",
    ),
) -> None:
    source_path = resolve_path(source)
    destination_path = resolve_path(destination, must_exist=False)
    fmt_normalised = fmt.lower()
    if fmt_normalised not in {"csv", "json"}:
        raise CLIError("--format must be either 'csv' or 'json'")

    def iter_records() -> Iterable[dict]:
        with source_path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    excerpt = stripped[:80]
                    raise CLIError(
                        f"Failed to parse JSON on line {index} of {source_path}: {exc.msg} (excerpt: {excerpt!r})"
                    ) from exc
                if level is not None and record.get("level") != level:
                    continue
                yield record

    records = list(iter_records())
    if fmt_normalised == "json":
        destination_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    else:
        if not records:
            destination_path.write_text("")
        else:
            fieldnames = sorted({key for record in records for key in record.keys()})
            with destination_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)

    console.print(f"[green]Exported {len(records)} records to {destination_path}.[/green]")


app.command("test")(_test_command)
app.command("debug")(_debug_command)
app.command("export")(_export_command)


def test() -> None:
    run_subcommand("dev", "test")


def debug() -> None:
    run_subcommand("dev", "debug")


def export() -> None:
    run_subcommand("dev", "export")
