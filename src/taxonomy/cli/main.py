"""Primary Typer application wiring the taxonomy CLI."""

from __future__ import annotations

from typing import Any, Callable, List, Optional

import typer
from rich.table import Table

from . import development, management, pipeline, postprocess, utilities
from .common import CLIError, configure_state, console, parse_override


class TaxonomyTyper(typer.Typer):
    """Typer subclass that supports registering exception handlers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._exception_handlers: list[tuple[type[BaseException], Callable[[BaseException], Any]]] = []

    def exception_handler(
        self, exception_type: type[BaseException]
    ) -> Callable[[Callable[[BaseException], Any]], Callable[[BaseException], Any]]:
        def decorator(handler: Callable[[BaseException], Any]) -> Callable[[BaseException], Any]:
            self._exception_handlers.append((exception_type, handler))
            return handler

        return decorator

    def _resolve_handler(self, exception: BaseException) -> Callable[[BaseException], Any] | None:
        for registered_type, handler in self._exception_handlers:
            if isinstance(exception, registered_type):
                return handler
        return None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return super().__call__(*args, **kwargs)
        except BaseException as exc:  # pragma: no cover - CLI surface behaviour
            handler = self._resolve_handler(exc)
            if handler is None:
                raise
            result = handler(exc)
            if isinstance(result, typer.Exit):
                raise result
            if isinstance(result, BaseException):
                raise result
            return result


app = TaxonomyTyper(
    add_completion=False,
    help="""
    Run taxonomy generation tasks, manage checkpoints, and invoke development
    tooling from a unified command-line interface.
    """.strip(),
    no_args_is_help=True,
)


@app.exception_handler(CLIError)
def handle_cli_error(exception: CLIError) -> typer.Exit:
    """Render ``CLIError`` messages without stack traces."""

    console.print(f"[bold red]Error:[/bold red] {exception}")
    return typer.Exit(code=2)


@app.callback()
def main(
    ctx: typer.Context,
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "-e",
        help="Active configuration environment (development, testing, production).",
        show_default=False,
    ),
    override: List[str] = typer.Option(  # noqa: B008 - Typer callback signature
        [],
        "--override",
        "-o",
        metavar="KEY=VALUE",
        help="Configuration override in dotted.key=value notation (repeatable).",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Explicit run identifier; defaults to a generated value.",
        show_default=False,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Emit verbose diagnostic output for CLI operations.",
    ),
    no_observability: bool = typer.Option(
        False,
        "--no-observability",
        help="Disable observability capture for the current command invocation.",
    ),
) -> None:
    """Configure shared CLI state prior to executing subcommands."""

    overrides = [parse_override(item) for item in override]
    configure_state(
        ctx,
        environment=environment,
        overrides=overrides,
        run_id=run_id,
        verbose=verbose,
        disable_observability=no_observability,
    )

    if verbose:
        state = ctx.obj
        table = Table(title="CLI Context", show_header=False, box=None)
        table.add_row("Environment", getattr(state, "environment", "<unknown>"))
        table.add_row("Run ID", getattr(state, "run_id", "<unset>"))
        table.add_row("Observability", "disabled" if getattr(state, "observability", None) is None else "enabled")
        console.print(table)


app.add_typer(pipeline.app, name="pipeline", help="Pipeline execution commands")
app.add_typer(postprocess.app, name="postprocess", help="Post-processing utilities")
app.add_typer(utilities.app, name="utilities", help="Auxiliary tooling")
app.add_typer(management.app, name="manage", help="Run management commands")
app.add_typer(development.app, name="dev", help="Developer-focused helpers")
