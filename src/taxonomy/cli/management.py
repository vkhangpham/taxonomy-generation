"""Run management commands for the taxonomy CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.table import Table

from taxonomy.orchestration import TaxonomyOrchestrator

from .common import CLIError, console, get_state, render_panel, resolve_path, run_subcommand


app = typer.Typer(
    add_completion=False,
    help="Inspect and manage taxonomy runs, checkpoints, and configuration.",
    no_args_is_help=True,
)


def _ensure_run_directory(base: Path, run_id: str) -> Path:
    run_dir = base / run_id
    if not run_dir.exists():
        raise CLIError(f"Run '{run_id}' has no recorded artifacts at {run_dir}")
    return run_dir


def _status_command(
    ctx: typer.Context,
    run_id: str = typer.Option(..., "--run-id", "-r", help="Run identifier to inspect."),
) -> None:
    state = get_state(ctx)
    runs_root = Path(state.settings.paths.output_dir) / "runs"
    run_dir = _ensure_run_directory(runs_root, run_id)
    table = Table(title=f"Run {run_id} Checkpoints", box=None)
    table.add_column("Phase")
    table.add_column("Saved At")
    found = False
    for checkpoint in sorted(run_dir.glob("*.checkpoint.json")):
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        table.add_row(payload.get("phase", checkpoint.stem), payload.get("saved_at", "<unknown>"))
        found = True

    if not found:
        console.print(f"[yellow]No checkpoints recorded for run {run_id}.[/yellow]")
        return

    console.print(table)


def _resume_command(
    ctx: typer.Context,
    *,
    run_id: str = typer.Option(..., "--run-id", "-r", help="Run identifier to resume."),
    from_phase: Optional[str] = typer.Option(
        None,
        "--from-phase",
        help="Resume from a specific phase identifier (optional).",
    ),
) -> None:
    state = get_state(ctx)
    orchestrator = TaxonomyOrchestrator.from_settings(state.settings, run_id=run_id)
    with console.status(f"Resuming run {run_id}..."):
        orchestrator.run(resume_phase=from_phase)
    console.print(f"[green]Run {run_id} resumed successfully.[/green]")


def _manifest_command(
    ctx: typer.Context,
    *,
    run_id: str = typer.Option(..., "--run-id", "-r", help="Run identifier to load."),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Manifest rendering format (json or yaml).",
        case_sensitive=False,
    ),
) -> None:
    state = get_state(ctx)
    runs_root = Path(state.settings.paths.output_dir) / "runs"
    run_dir = _ensure_run_directory(runs_root, run_id)
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise CLIError(f"Manifest not found for run {run_id} at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fmt = output_format.lower()
    if fmt == "json":
        render_panel(f"Run {run_id} Manifest", manifest)
    elif fmt == "yaml":
        console.print(f"# Manifest for run {run_id}")
        console.print(yaml.safe_dump(manifest, sort_keys=False))
    else:
        raise CLIError("--format must be either 'json' or 'yaml'")


def _config_command(
    ctx: typer.Context,
    *,
    show: bool = typer.Option(True, "--show/--no-show", help="Display resolved configuration."),
    validate: bool = typer.Option(
        False,
        "--validate",
        help="Revalidate configuration and report success or failure.",
    ),
) -> None:
    state = get_state(ctx)
    if show:
        render_panel("Resolved Settings", state.settings.model_dump(mode="json"))

    if validate:
        try:
            resolve_path(state.settings.paths.output_dir, must_exist=False)
        except CLIError as error:
            console.print(f"[red]Configuration validation failed:[/red] {error}")
            raise typer.Exit(code=2) from error
        console.print("[green]Configuration validated successfully.[/green]")


app.command("status")(_status_command)
app.command("resume")(_resume_command)
app.command("manifest")(_manifest_command)
app.command("config")(_config_command)


def status() -> None:
    run_subcommand("manage", "status")


def resume() -> None:
    run_subcommand("manage", "resume")


def manifest() -> None:
    run_subcommand("manage", "manifest")


def config() -> None:
    run_subcommand("manage", "config")
