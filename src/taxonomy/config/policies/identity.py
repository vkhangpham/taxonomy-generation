"""Identity and institution policy models."""

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field


class InstitutionPolicy(BaseModel):
    """Rules for mapping and reconciling institutional identities."""

    campus_vs_system: str = Field(default="prefer-campus")
    joint_center_handling: str = Field(default="duplicate-under-both")
    cross_listing_strategy: str = Field(default="merge-with-stronger-parent")
    canonical_mappings: Dict[str, str] = Field(default_factory=dict)
