"""Compatibility entry point delegating to the Typer-powered CLI."""

from __future__ import annotations

from typing import Iterable

import typer

from taxonomy.cli.main import app


def main(argv: Iterable[str] | None = None) -> int:
    """Execute the unified taxonomy CLI via the Typer application."""

    args = list(argv) if argv is not None else None
    try:
        return app(prog_name="taxonomy", args=args, standalone_mode=False) or 0
    except typer.Exit as exc:  # pragma: no cover - delegated exit code
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
