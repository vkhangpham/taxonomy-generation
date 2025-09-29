"""Utility commands covering web mining and prompt optimization."""

from __future__ import annotations

from typing import Optional
from pathlib import Path

import typer
from rich.table import Table

from taxonomy.prompt_optimization.one_time_optimizer import OneTimeGEPAOptimizer
from taxonomy.web_mining import CrawlConfig, build_web_miner

from .common import CLIError, console, get_state, resolve_path, run_subcommand


app = typer.Typer(
    add_completion=False,
    help="Supporting utilities for web mining and prompt optimization workflows.",
    no_args_is_help=True,
)


def _build_objective_optimizer(objective: Optional[str]) -> type[OneTimeGEPAOptimizer]:
    if objective is None:
        return OneTimeGEPAOptimizer
    metric_key = objective.lower()
    if metric_key not in {"f1", "precision", "recall"}:
        raise CLIError("--objective must be one of: F1, precision, recall")

    def _select_best_run(runs):  # type: ignore[override]
        from taxonomy.prompt_optimization.one_time_optimizer import LeverRun

        best_run: LeverRun | None = None
        best_score = float("-inf")
        for run in runs:
            summary = run.metric_summary or {}
            raw_value = summary.get(metric_key)
            try:
                score = float(raw_value)
            except (TypeError, ValueError):
                score = float("-inf")
            if best_run is None or score > best_score:
                best_run = run
                best_score = score
        return best_run

    return type(
        f"ObjectiveOptimizer_{metric_key}",
        (OneTimeGEPAOptimizer,),
        {"_select_best_run": staticmethod(_select_best_run)},
    )


def _mine_resources_command(
    ctx: typer.Context,
    *,
    institution: str = typer.Option(..., "--institution", "-i", help="Institution identifier."),
    seed_url: list[str] = typer.Option(
        ..., "--seed-url", help="Seed URL for the crawl (repeatable)."
    ),
    allowed_domain: list[str] = typer.Option(
        ..., "--allowed-domain", help="Allowed domain for crawling (repeatable)."
    ),
    max_pages: int = typer.Option(100, "--max-pages", help="Maximum pages to crawl."),
    ttl_days: int = typer.Option(14, "--ttl-days", help="Cache TTL in days."),
) -> None:
    state = get_state(ctx)
    state.settings.paths.ensure_exists()
    seeds = [url.strip() for url in seed_url if url.strip()]
    domains = [domain.strip() for domain in allowed_domain if domain.strip()]
    if not seeds:
        raise CLIError("At least one --seed-url must be provided")
    if not domains:
        raise CLIError("At least one --allowed-domain must be provided")

    policies = state.settings.policies
    cache_root = Path(state.settings.paths.cache_dir)
    paths_root = cache_root.parent if cache_root.parent else cache_root
    miner = build_web_miner(policies, paths_root)

    config = CrawlConfig(
        institution_id=institution,
        seed_urls=seeds,
        allowed_domains=domains,
        max_pages=max_pages,
        ttl_days=ttl_days,
    )

    with console.status(f"Mining resources for {institution}..."):
        result = miner.crawl_institution(config)

    table = Table(title=f"Crawl Result: {institution}", box=None)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Snapshots", str(result.metrics.get("snapshots", 0)))
    table.add_row("Errors", str(result.metrics.get("errors", 0)))
    table.add_row("Last Finished", str(result.finished_at))
    console.print(table)


def _optimize_prompt_command(
    ctx: typer.Context,
    *,
    prompt_key: str = typer.Option(..., "--prompt-key", "-p", help="Prompt registry key."),
    dataset: Path = typer.Option(..., "--dataset", "-d", help="Training dataset JSON path."),
    objective: Optional[str] = typer.Option(
        None,
        "--objective",
        help="Optimization objective (F1, precision, recall).",
    ),
    max_trials: Optional[int] = typer.Option(
        None,
        "--max-trials",
        help="Size of the optimization search budget.",
    ),
    deploy: bool = typer.Option(True, "--deploy/--no-deploy", help="Deploy the winning variant."),
) -> None:
    state = get_state(ctx)
    dataset_path = resolve_path(dataset)
    policies = state.settings.policies.model_copy(deep=True)
    optimization_policy = policies.prompt_optimization.model_copy(deep=True)

    if max_trials is not None:
        if max_trials <= 10:
            optimization_policy.optimization_budget = "light"
        elif max_trials <= 30:
            optimization_policy.optimization_budget = "medium"
        else:
            optimization_policy.optimization_budget = "heavy"
        optimization_policy.min_trials_for_confidence = max(max_trials, 1)
        optimization_policy.convergence_patience = max(max_trials // 2, 5)

    policies = policies.model_copy(update={"prompt_optimization": optimization_policy})
    custom_settings = state.settings.model_copy(update={"policies": policies})

    optimizer_cls = _build_objective_optimizer(objective)
    optimizer = optimizer_cls(
        policy=custom_settings.policies.prompt_optimization,
        llm_settings=custom_settings.policies.llm,
        reflection_model=custom_settings.policies.prompt_optimization.reflection_model,
    )

    with console.status("Running prompt optimization..."):
        result = optimizer.optimize(
            prompt_key=prompt_key,
            dataset_path=dataset_path,
            deploy=deploy,
        )

    table = Table(title="Optimization Summary", box=None)
    selected = result.optimization_report.get("selected_config", {})
    table.add_column("Field")
    table.add_column("Value", justify="left")
    table.add_row("Deployed Variant", result.deployed_variant or "(not deployed)")
    table.add_row("Few-shot k", str(selected.get("few_shot_k", "?")))
    table.add_row("Temperature", str(selected.get("temperature", "?")))
    table.add_row("Constraint", selected.get("constraint_variant", "?"))
    best_score = result.optimization_report.get("best_validation_score")
    if best_score is not None:
        table.add_row("Validation Score", f"{best_score:.3f}")
    console.print(table)


app.command("mine-resources")(_mine_resources_command)
app.command("optimize-prompt")(_optimize_prompt_command)


def mine_resources() -> None:
    run_subcommand("utilities", "mine-resources")


def optimize_prompt() -> None:
    run_subcommand("utilities", "optimize-prompt")
