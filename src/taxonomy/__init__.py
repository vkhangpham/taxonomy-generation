"""Top-level package for the taxonomy generation system."""

from __future__ import annotations

from importlib.metadata import version

try:
    __version__ = version("taxonomy")
except Exception:  # pragma: no cover - fallback during local development
    __version__ = "0.1.0"

from .config.settings import Settings, get_settings
from .entities import (
    Candidate,
    Concept,
    MergeOp,
    SourceRecord,
    SplitOp,
    ValidationFinding,
)

__all__ = [
    "__version__",
    "Settings",
    "get_settings",
    "SourceRecord",
    "Candidate",
    "Concept",
    "ValidationFinding",
    "MergeOp",
    "SplitOp",
]
