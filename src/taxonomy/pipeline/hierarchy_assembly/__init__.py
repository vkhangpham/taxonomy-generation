"""Hierarchy assembly public API."""

from __future__ import annotations

from .assembler import HierarchyAssembler, HierarchyAssemblyResult
from .graph import HierarchyGraph
from .main import assemble_hierarchy
from .validator import GraphValidator, InvariantChecker, ValidationReport

__all__ = [
    "assemble_hierarchy",
    "HierarchyAssembler",
    "HierarchyAssemblyResult",
    "HierarchyGraph",
    "GraphValidator",
    "InvariantChecker",
    "ValidationReport",
]

__version__ = "0.1.0"
