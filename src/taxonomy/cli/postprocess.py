"""Post-processing commands for validation, deduplication, and disambiguation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from taxonomy.pipeline.deduplication.main import deduplicate_concepts
from taxonomy.pipeline.disambiguation.main import disambiguate_concepts
from taxonomy.pipeline.validation.main import validate_concepts

from .common import CLIError, console, get_state, resolve_path, run_subcommand


app = typer.Typer(
    add_completion=False,
    help="Execute post-processing stages that refine taxonomy quality.",
    no_args_is_help=True,
)


def _validate_command(
    ctx: typer.Context,
    *,
    input_path: Path = typer.Option(..., "--input", "-i", help="Concept JSONL emitted by the pipeline."),
    output_path: Path = typer.Option(..., "--output", "-o", help="Destination for validated concepts."),
    snapshot: list[Path] = typer.Option(
        [],
        "--snapshot",
        "-s",
        help="Optional snapshot JSONL inputs used for evidence (repeatable).",
    ),
    mode: str = typer.Option(
        "all",
        "--mode",
        help="Validation mode: rule, web, llm, or all.",
        case_sensitive=False,
    ),
) -> None:
    state = get_state(ctx)
    mode_normalised = mode.lower()
    if mode_normalised not in {"rule", "web", "llm", "all"}:
        raise CLIError("--mode must be one of: rule, web, llm, all")

    validated = validate_concepts(
        resolve_path(input_path),
        [resolve_path(path) for path in snapshot],
        resolve_path(output_path, must_exist=False),
        mode=mode_normalised,
        settings=state.settings,
    )

    passed = sum(1 for outcome in validated if getattr(outcome.decision, "passed", False))
    total = len(validated)
    table = Table(title="Validation Summary", box=None)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total Concepts", str(total))
    table.add_row("Passed", str(passed))
    table.add_row("Failed", str(total - passed))
    table.add_row("Mode", mode_normalised)
    console.print(table)


def _deduplicate_command(
    ctx: typer.Context,
    *,
    input_path: Path = typer.Option(..., "--input", "-i", help="Concept JSONL before deduplication."),
    output_path: Path = typer.Option(..., "--output", "-o", help="Destination for deduplicated concepts."),
    threshold: Optional[float] = typer.Option(
        None,
        "--threshold",
        help="Override the minimum similarity threshold used for merges.",
    ),
    similarity_method: Optional[str] = typer.Option(
        None,
        "--similarity-method",
        help="Prefer a specific similarity component (jaro-winkler, jaccard, abbrev-score).",
        case_sensitive=False,
    ),
    level: Optional[int] = typer.Option(
        None,
        "--level",
        help="Limit processing to a specific hierarchy level.",
    ),
    merge_ops: Optional[Path] = typer.Option(
        None,
        "--merge-ops",
        help="Optional path for emitted merge operations JSONL.",
    ),
    metadata: Optional[Path] = typer.Option(
        None,
        "--metadata",
        help="Optional path for deduplication metadata output.",
    ),
) -> None:
    state = get_state(ctx)
    policies = state.settings.policies.model_copy(deep=True)
    dedup_policy = policies.deduplication.model_copy(deep=True)

    if threshold is not None:
        if not 0.0 <= threshold <= 1.0:
            raise CLIError("--threshold must be between 0.0 and 1.0")
        dedup_policy.min_similarity_threshold = threshold

    if similarity_method is not None:
        method = similarity_method.lower()
        weights = {
            "jaro-winkler": (1.0, 0.0, 0.0),
            "jaccard": (0.0, 1.0, 0.0),
            "abbrev-score": (0.0, 0.0, 1.0),
        }
        if method not in weights:
            raise CLIError("--similarity-method must be jaro-winkler, jaccard, or abbrev-score")
        jw, jc, ab = weights[method]
        dedup_policy.jaro_winkler_weight = jw
        dedup_policy.jaccard_weight = jc
        dedup_policy.abbrev_score_weight = ab

    policies = policies.model_copy(update={"deduplication": dedup_policy})
    custom_settings = state.settings.model_copy(update={"policies": policies})

    deduplicate_concepts(
        resolve_path(input_path),
        resolve_path(output_path, must_exist=False),
        merge_ops_path=merge_ops,
        metadata_path=metadata,
        level_filter=level,
        settings=custom_settings,
    )

    console.print("[green]Deduplication complete.[/green]")


def _disambiguate_command(
    ctx: typer.Context,
    *,
    input_path: Path = typer.Option(..., "--input", "-i", help="Concept JSONL before disambiguation."),
    output_path: Path = typer.Option(..., "--output", "-o", help="Destination for disambiguated concepts."),
    contexts_path: Optional[Path] = typer.Option(
        None,
        "--contexts",
        help="Optional context features JSONL to guide disambiguation.",
    ),
    context_features: Optional[int] = typer.Option(
        None,
        "--context-features",
        help="Override the max contexts retained per parent during analysis.",
    ),
) -> None:
    state = get_state(ctx)
    policies = state.settings.policies.model_copy(deep=True)
    disambiguation_policy = policies.disambiguation.model_copy(deep=True)

    if context_features is not None:
        if context_features <= 0:
            raise CLIError("--context-features must be positive")
        disambiguation_policy.max_contexts_per_parent = context_features

    policies = policies.model_copy(update={"disambiguation": disambiguation_policy})
    custom_settings = state.settings.model_copy(update={"policies": policies})

    disambiguate_concepts(
        resolve_path(input_path),
        resolve_path(output_path, must_exist=False),
        context_data_path=contexts_path,
        settings=custom_settings,
    )

    console.print("[green]Disambiguation complete.[/green]")


app.command("validate")(_validate_command)
app.command("deduplicate")(_deduplicate_command)
app.command("disambiguate")(_disambiguate_command)


def validate() -> None:
    run_subcommand("postprocess", "validate")


def deduplicate() -> None:
    run_subcommand("postprocess", "deduplicate")


def disambiguate() -> None:
    run_subcommand("postprocess", "disambiguate")
