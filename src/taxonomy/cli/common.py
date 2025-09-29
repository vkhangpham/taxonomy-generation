"""Shared helpers used across the taxonomy CLI modules."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping
from uuid import uuid4

import typer
from rich.console import Console
from rich.panel import Panel

from taxonomy.config.settings import Settings
from taxonomy.observability import ObservabilityContext
from taxonomy.utils.logging import get_logger

console = Console()
_LOGGER = get_logger(module=__name__)


class CLIError(RuntimeError):
    """Exception raised for user-facing CLI errors."""


@dataclass(slots=True)
class CLIState:
    """State object attached to ``typer.Context`` for downstream commands."""

    settings: Settings
    overrides: Dict[str, Any]
    environment: str
    run_id: str
    observability: ObservabilityContext | None
    verbose: bool


def _merge_dict(dest: MutableMapping[str, Any], src: Mapping[str, Any]) -> None:
    for key, value in src.items():
        if isinstance(value, Mapping) and isinstance(dest.get(key), MutableMapping):
            _merge_dict(dest[key], value)  # type: ignore[index]
        elif isinstance(value, Mapping):
            dest[key] = dict(value)
        else:
            dest[key] = value


def parse_override(argument: str) -> Dict[str, Any]:
    """Parse dotted ``key=value`` overrides into nested dictionaries."""

    if "=" not in argument:
        raise typer.BadParameter("Overrides must be expressed as dotted.key=value")
    dotted, value = argument.split("=", 1)
    cursor: MutableMapping[str, Any] = {}
    current = cursor
    segments = [segment.strip() for segment in dotted.split(".") if segment.strip()]
    if not segments:
        raise typer.BadParameter("Override keys must not be empty")
    for segment in segments[:-1]:
        nested: Dict[str, Any] = {}
        current[segment] = nested
        current = nested
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value
    current[segments[-1]] = parsed_value
    return cursor


def merge_overrides(overrides: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge override dictionaries using deep semantics."""

    result: Dict[str, Any] = {}
    for override in overrides:
        _merge_dict(result, override)
    return result


def resolve_settings(environment: str | None, overrides: Dict[str, Any]) -> Settings:
    """Construct :class:`Settings` with environment and overrides applied."""

    payload = dict(overrides)
    if environment:
        payload["environment"] = environment
    return Settings(**payload)


def build_observability(settings: Settings, *, run_id: str, disabled: bool) -> ObservabilityContext | None:
    """Create an :class:`ObservabilityContext` when enabled."""

    if disabled:
        return None
    policy = getattr(settings.policies, "observability", None)
    try:
        return ObservabilityContext(run_id=run_id, policy=policy)
    except Exception:  # pragma: no cover - defensive
        _LOGGER.exception("Failed to initialise observability context", run_id=run_id)
        raise CLIError("Unable to initialise observability context; see logs for details")


def configure_state(
    ctx: typer.Context,
    *,
    environment: str | None,
    overrides: Iterable[Dict[str, Any]],
    run_id: str | None,
    verbose: bool,
    disable_observability: bool,
) -> None:
    """Populate ``ctx.obj`` with :class:`CLIState`."""

    merged = merge_overrides(overrides)
    settings = resolve_settings(environment, merged)
    resolved_run_id = run_id or f"cli-{uuid4().hex[:8]}"
    observability = build_observability(settings, run_id=resolved_run_id, disabled=disable_observability)
    ctx.obj = CLIState(
        settings=settings,
        overrides=merged,
        environment=settings.environment,
        run_id=resolved_run_id,
        observability=observability,
        verbose=verbose,
    )


def get_state(ctx: typer.Context) -> CLIState:
    """Return the previously configured :class:`CLIState`.

    Commands must call this helper to access shared state; when the callback has
    not run an informative error is raised to guide developers.
    """

    if ctx.obj is None:
        raise CLIError("CLI context is not initialised")
    if not isinstance(ctx.obj, CLIState):  # pragma: no cover - defensive guard
        raise CLIError("Unexpected CLI context payload")
    return ctx.obj


def render_panel(title: str, content: Mapping[str, Any]) -> None:
    """Utility for rendering JSON-like mappings using Rich panels."""

    from rich.json import JSON as RichJSON

    console.print(Panel(RichJSON.from_data(content), title=title, border_style="cyan"))


def resolve_path(path: str | Path, *, must_exist: bool = True) -> Path:
    """Resolve a filesystem path relative to the project root when required."""

    target = Path(path).expanduser().resolve()
    if must_exist and not target.exists():
        raise CLIError(f"Path does not exist: {target}")
    return target

_GLOBAL_OPTIONS_WITH_VALUES = {"--environment", "-e", "--override", "-o", "--run-id"}
_GLOBAL_FLAG_OPTIONS = {"--verbose", "-v", "--no-observability"}


def _partition_global_arguments(arguments: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split global CLI options from command-specific arguments.

    Only tokens that appear before the first non-global token (i.e. the first
    subcommand or positional argument) are considered for global parsing. Once a
    non-global token is encountered, the remainder is returned as ``command_args``
    without any further inspection. This avoids accidentally treating subcommand
    options as global ones.
    """

    tokens = list(arguments)
    global_args: list[str] = []
    command_args: list[str] = []

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Respect conventional terminator: everything after "--" is for commands
        if token == "--":
            command_args.extend(tokens[i:])
            break

        # Long options (e.g., --flag or --key=value)
        if token.startswith("--"):
            # Use partition to split option and value; empty separator means no value provided.
            option, sep, value = token.partition("=")  # sep is "=" when value is inline
            if option in _GLOBAL_OPTIONS_WITH_VALUES:
                if sep:  # --opt=value form
                    global_args.append(token)
                    i += 1
                    continue
                # value provided as next token
                global_args.append(option)
                i += 1
                if i < len(tokens):
                    global_args.append(tokens[i])
                    i += 1
                else:  # pragma: no cover - delegated to Typer for validation
                    break
                continue
            if option in _GLOBAL_FLAG_OPTIONS:
                global_args.append(option)
                i += 1
                continue

            # First non-global token: stop parsing globals
            command_args.extend(tokens[i:])
            break

        # Short options and clusters (e.g., -v, -oVAL, -o=VAL, -vo)
        if token.startswith("-") and token != "-":
            base, eq_sep, inline_value = token.partition("=")
            cluster = base[1:]

            # Process a short option cluster from left to right.
            j = 0
            consumed_entire_token = True
            while j < len(cluster):
                short = f"-{cluster[j]}"

                if short in _GLOBAL_FLAG_OPTIONS:
                    global_args.append(short)
                    j += 1
                    continue

                if short in _GLOBAL_OPTIONS_WITH_VALUES:
                    global_args.append(short)

                    # Prefer explicit "=value" when present. For clusters like
                    # "-opoly=3", preserve the full suffix ("poly=3") as the value.
                    if eq_sep:
                        if base != short:  # there were extra chars before '=' in the cluster
                            suffix = base[2:] + "=" + inline_value
                            global_args.append(suffix)
                        else:
                            global_args.append(inline_value)
                        j = len(cluster)  # done with this token
                        break

                    # If there are remaining chars in the cluster, treat them as the value (e.g., -odev)
                    if j + 1 < len(cluster):
                        global_args.append(cluster[j + 1 :])
                        j = len(cluster)
                        break

                    # Otherwise, consume the next token as the value
                    i += 1
                    if i < len(tokens):
                        global_args.append(tokens[i])
                        j = len(cluster)
                        break
                    else:  # pragma: no cover - delegated to Typer for validation
                        consumed_entire_token = True
                        j = len(cluster)
                        break

                # Encountered a non-global short option: stop parsing globals
                consumed_entire_token = False
                break

            if consumed_entire_token and j == len(cluster):
                i += 1
                continue

            # First non-global token within the cluster -> stop and pass the rest through
            command_args.extend(tokens[i:])
            break

        # Any other token indicates the start of the subcommand/positional args
        command_args.extend(tokens[i:])
        break

    return global_args, command_args


def run_subcommand(*segments: str) -> None:
    """Invoke the main Typer app with ``segments`` prefixed to ``sys.argv``."""

    from .main import app as main_app

    global_args, command_args = _partition_global_arguments(sys.argv[1:])
    args = global_args + list(segments) + command_args
    exit_code = main_app(prog_name="taxonomy", args=args, standalone_mode=False) or 0
    raise SystemExit(exit_code)
