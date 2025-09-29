"""Pipeline execution commands for the taxonomy CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.progress import Progress

from taxonomy.orchestration import run_taxonomy_pipeline
from taxonomy.pipeline.s0_raw_extraction.main import extract_from_snapshots
from taxonomy.pipeline.s1_extraction_normalization.main import extract_candidates
from taxonomy.pipeline.s2_frequency_filtering.main import filter_by_frequency
from taxonomy.pipeline.s3_token_verification.main import verify_tokens

from .common import CLIError, console, get_state, resolve_path, run_subcommand


app = typer.Typer(
    add_completion=False,
    help="Invoke individual pipeline stages or run the full taxonomy pipeline.",
    no_args_is_help=True,
)

_VALID_STEPS = {"S0", "S1", "S2", "S3"}


def _normalise_step(step: str) -> str:
    upper = step.strip().upper()
    if upper not in _VALID_STEPS:
        raise CLIError(f"Unknown pipeline step '{step}'. Expected one of: {', '.join(sorted(_VALID_STEPS))}")
    return upper


def _adjust_batch_size(batch_size: int, test_mode: bool) -> int:
    if batch_size <= 0:
        raise CLIError("Batch size must be positive")
    if test_mode and batch_size > 32:
        return 32
    return batch_size


def _generate_command(
    ctx: typer.Context,
    *,
    step: str = typer.Option(..., "--step", "-s", help="Pipeline step to execute (S0-S3)."),
    level: Optional[int] = typer.Option(None, "--level", "-l", help="Hierarchy level for S1-S3 stages."),
    input_path: Path = typer.Option(..., "--input", "-i", help="Input artefact for the selected step."),
    output_path: Path = typer.Option(..., "--output", "-o", help="Destination for generated artefacts."),
    resume_from: Optional[Path] = typer.Option(
        None,
        "--resume-from",
        help="Resume checkpoint for S1 candidate aggregation.",
        show_default=False,
    ),
    batch_size: int = typer.Option(64, "--batch-size", help="Batch size for streaming stages."),
    test_mode: bool = typer.Option(
        False,
        "--test-mode",
        help="Enable lightweight settings suited for smoke testing.",
    ),
    audit_mode: bool = typer.Option(
        False,
        "--audit-mode",
        help="Limit the selected stage to 10 items for audit verification.",
    ),
) -> None:
    state = get_state(ctx)
    resolved_step = _normalise_step(step)
    adjusted_batch_size = _adjust_batch_size(batch_size, test_mode)
    observability = state.observability

    input_resolved = resolve_path(input_path)
    output_resolved = resolve_path(output_path, must_exist=False)

    resume_checkpoint = resolve_path(resume_from, must_exist=True) if resume_from else None
    effective_audit_mode = audit_mode or state.settings.audit_mode.enabled
    if audit_mode and not state.settings.audit_mode.enabled:
        state.settings.audit_mode.enabled = True

    with Progress(transient=True) as progress:
        task = progress.add_task(f"Running {resolved_step}", start=False)
        progress.start_task(task)
        if resolved_step == "S0":
            extract_from_snapshots(
                input_resolved,
                output_resolved,
                settings=state.settings,
                batch_size=adjusted_batch_size,
                audit_mode=effective_audit_mode,
            )
        elif resolved_step == "S1":
            if level is None:
                raise CLIError("--level must be provided for S1")
            extract_candidates(
                input_resolved,
                level=level,
                output_path=output_resolved,
                resume_from=resume_checkpoint,
                batch_size=adjusted_batch_size,
                settings=state.settings,
                observability=observability,
                audit_mode=effective_audit_mode,
            )
        elif resolved_step == "S2":
            if level is None:
                raise CLIError("--level must be provided for S2")
            filter_by_frequency(
                input_resolved,
                level=level,
                output_path=output_resolved,
                settings=state.settings,
                observability=observability,
                audit_mode=effective_audit_mode,
            )
        else:  # S3
            if level is None:
                raise CLIError("--level must be provided for S3")
            verify_tokens(
                input_resolved,
                level=level,
                output_path=output_resolved,
                settings=state.settings,
                audit_mode=effective_audit_mode,
            )
        progress.update(task, completed=1)

    console.print(f"[green]Completed {resolved_step}[/green] -> {output_resolved}")


def _run_command(
    ctx: typer.Context,
    resume_phase: Optional[str] = typer.Option(
        None,
        "--resume-phase",
        help="Resume orchestration from the specified phase.",
        show_default=False,
    ),
) -> None:
    state = get_state(ctx)
    with console.status("Running taxonomy pipeline..."):
        result = run_taxonomy_pipeline(
            resume_from=resume_phase,
            settings=state.settings,
        )
    console.print(f"[green]Pipeline complete[/green]. Manifest: {result.manifest_path}")


app.command("generate")(_generate_command)
app.command("run")(_run_command)


def generate() -> None:
    """Standalone entry point mirroring ``pipeline generate``."""

    run_subcommand("pipeline", "generate")


def run() -> None:
    """Standalone entry point mirroring ``pipeline run``."""

    run_subcommand("pipeline", "run")
