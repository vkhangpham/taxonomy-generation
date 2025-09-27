"""Raw content acquisition utilities."""

from .excel_reader import (
    count_colleges_per_institution,
    generate_source_records,
    load_faculty_dataframe,
    select_top_institutions,
)

__all__ = [
    "load_faculty_dataframe",
    "count_colleges_per_institution",
    "select_top_institutions",
    "generate_source_records",
]
