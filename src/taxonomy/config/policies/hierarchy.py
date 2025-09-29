"""Hierarchy assembly policy models."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator


class HierarchyAssemblyPolicy(BaseModel):
    """Configuration controlling hierarchy graph assembly invariants."""

    enforce_acyclicity: bool = Field(default=True)
    enforce_unique_paths: bool = Field(default=True)
    allow_multi_parent_exceptions: List[str] = Field(default_factory=list)
    orphan_strategy: Literal["quarantine", "attach_placeholder", "drop"] = Field(
        default="quarantine",
        description="Strategy for handling concepts missing valid parent references.",
    )
    placeholder_parent_prefix: str = Field(
        default="placeholder::",
        min_length=1,
        description="Prefix applied when synthesising placeholder parent concepts.",
    )
    strict_level_enforcement: bool = Field(default=True)
    allow_level_shortcuts: bool = Field(default=False)
    max_graph_size: int = Field(default=100_000, ge=1)
    cycle_detection_method: Literal["topological_sort", "dfs"] = Field(
        default="topological_sort",
        description="Algorithm to use when checking for cycles in the hierarchy graph.",
    )
    include_graph_stats: bool = Field(default=True)
    include_invariant_proofs: bool = Field(default=True)

    @field_validator("allow_multi_parent_exceptions", mode="before")
    def _normalize_exceptions(value: List[str]) -> List[str]:
        return [concept_id.strip() for concept_id in value if concept_id and concept_id.strip()]
