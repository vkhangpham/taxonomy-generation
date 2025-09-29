"""Hierarchy threshold policy models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LevelThreshold(BaseModel):
    """Threshold configuration for a specific hierarchy level."""

    min_institutions: int = Field(..., ge=0)
    min_src_count: int = Field(..., ge=0)
    weight_formula: str = Field(
        default="1.0*inst_count + 0.3*log(1+src_count)",
        description="Human-readable representation of the weighting rule.",
    )


class LevelThresholds(BaseModel):
    """Collection of threshold policies for every hierarchy level."""

    level_0: LevelThreshold
    level_1: LevelThreshold
    level_2: LevelThreshold
    level_3: LevelThreshold
