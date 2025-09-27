"""Centralised logging configuration built on loguru."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from loguru import logger

from ..config.settings import Settings, get_settings

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[run_id]}</cyan> | "
    "<magenta>{extra[step]}</magenta> | "
    "{message}"
)


def configure_logging(settings: Settings | None = None, level: str = "INFO") -> None:
    """Initialise loguru sinks according to the active settings."""

    cfg = settings or get_settings()
    log_path = cfg.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=_LOG_FORMAT,
    )
    logger.add(
        log_path,
        rotation="10 MB",
        retention="14 days",
        enqueue=True,
        format=_LOG_FORMAT,
        level=level,
    )
    logger.configure(extra={"run_id": "-", "step": "-"})


_VERBOSE_TEXT_LOGGING = False


def set_verbose_text_logging(enabled: bool) -> None:
    """Control whether text payloads are included in debug logs."""

    global _VERBOSE_TEXT_LOGGING
    _VERBOSE_TEXT_LOGGING = bool(enabled)


def verbose_text_logging_enabled() -> bool:
    """Return True when verbose text debug logging is enabled."""

    return _VERBOSE_TEXT_LOGGING


def get_logger(**context: Any):
    """Return a contextualised logger instance."""

    return logger.bind(**context)


@contextmanager
def logging_context(**context: Any):
    """Context manager that temporarily binds structured context fields."""

    with logger.contextualize(**context):
        yield logger


@contextmanager
def log_timing(step: str, *, logger_=logger):
    """Helper to log elapsed time for a block."""

    start = datetime.utcnow()
    try:
        yield
    finally:
        elapsed = (datetime.utcnow() - start).total_seconds()
        logger_.info("Step timing", step=step, seconds=elapsed)


__all__ = [
    "configure_logging",
    "get_logger",
    "logging_context",
    "log_timing",
    "set_verbose_text_logging",
    "verbose_text_logging_enabled",
]
