"""Excel ingestion helpers for S0 raw extraction."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Iterable, List

import polars as pl
from loguru import logger

from ...config.settings import Settings, get_settings
from ...entities import Provenance, SourceMeta, SourceRecord


def load_faculty_dataframe(settings: Settings | None = None) -> pl.DataFrame:
    """Load the faculty extraction Excel workbook as a Polars DataFrame."""

    settings = settings or get_settings()
    excel_policy = settings.policies.level0_excel
    workbook_path = settings.level0_excel_file
    if not workbook_path.exists():
        raise FileNotFoundError(f"Excel workbook not found: {workbook_path}")

    sheet_names = excel_policy.sheets_to_process or [None]
    frames: List[pl.DataFrame] = []
    for sheet in sheet_names:
        label = sheet if sheet is not None else "<default>"
        try:
            frame = pl.read_excel(workbook_path, sheet_name=sheet)
        except pl.exceptions.PolarsError as exc:  # pragma: no cover - surfaced as ValueError
            raise ValueError(f"Failed to parse sheet '{label}': {exc}") from exc
        frame = frame.with_columns(pl.lit(label).alias("sheet_name"))
        frames.append(frame)
        logger.debug("Loaded Excel sheet", sheet=label, row_count=frame.height, columns=frame.columns)

    if not frames:
        raise ValueError("No sheets were loaded from the Excel workbook")

    combined = pl.concat(frames, how="diagonal_relaxed")
    logger.info(
        "Combined Excel sheets",
        sheet_count=len(frames),
        total_rows=combined.height,
        columns=combined.columns,
    )
    return combined


def count_colleges_per_institution(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate the number of unique colleges for each institution."""

    required_columns = {"institution", "department_path"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    default_sheet_label = "<unspecified>"
    if "sheet_name" in df.columns:
        working = df.with_columns(
            pl.col("sheet_name")
            .cast(pl.Utf8, strict=False)
            .fill_null(default_sheet_label)
            .alias("sheet_name")
        )
    else:
        working = df.with_columns(pl.lit(default_sheet_label).alias("sheet_name"))

    prepared = working.with_columns(
        pl.col("department_path")
        .cast(pl.Utf8, strict=False)
        .str.split("->")
        .list.get(0)
        .str.strip_chars()
        .alias("college"),
        pl.col("institution").cast(pl.Utf8, strict=False).str.strip_chars().alias("institution"),
    ).filter(pl.col("college").is_not_null() & (pl.col("college") != ""))

    per_college = prepared.group_by(["institution", "college"]).agg(
        pl.len().alias("occurrences"),
        pl.col("sheet_name").first().alias("primary_sheet"),
    )

    summary = (
        per_college.group_by("institution")
        .agg(
            pl.col("college").unique().alias("colleges"),
            pl.col("occurrences").sum().alias("total_occurrences"),
            pl.len().alias("college_count"),
            pl.col("primary_sheet").unique().alias("sheets"),
        )
        .with_columns(
            pl.col("colleges").list.sort(),
            pl.col("sheets").list.sort().alias("sheets"),
        )
        .with_columns(pl.col("sheets").list.first().alias("primary_sheet"))
        .sort(
            by=["college_count", "total_occurrences", "institution"],
            descending=[True, True, False],
        )
    )

    logger.info("Computed college frequency table", institutions=summary.height)
    return summary


def select_top_institutions(summary: pl.DataFrame, top_n: int, seed: int) -> pl.DataFrame:
    """Pick the top N institutions by distinct college coverage."""

    if top_n <= 0:
        raise ValueError("top_n must be a positive integer")
    trimmed = summary.head(top_n)
    rows = list(trimmed.iter_rows(named=True))
    random.Random(seed).shuffle(rows)
    shuffled = pl.DataFrame(rows) if rows else trimmed
    logger.debug("Selected top institutions", top_n=top_n)
    return shuffled


def _iter_colleges(row: dict, seed: int) -> Iterable[str]:
    colleges: List[str] = list(row.get("colleges", []))
    rng = random.Random(seed)
    rng.shuffle(colleges)
    for college in colleges:
        yield college


def generate_source_records(settings: Settings | None = None) -> List[SourceRecord]:
    """Convert Excel-derived colleges into SourceRecord instances."""

    settings = settings or get_settings()
    excel_policy = settings.policies.level0_excel
    df = load_faculty_dataframe(settings)
    summary = count_colleges_per_institution(df)
    selected = select_top_institutions(
        summary, excel_policy.top_n_institutions, excel_policy.random_seed
    )

    source_records: List[SourceRecord] = []
    file_uri = settings.level0_excel_file.resolve().as_uri()
    timestamp = datetime.now(timezone.utc)

    for idx, row in enumerate(selected.iter_rows(named=True)):
        institution = row["institution"]
        sheet_name = row.get("primary_sheet")
        for college in _iter_colleges(row, excel_policy.random_seed + idx):
            text = f"{institution} - {college}"
            record = SourceRecord(
                text=text,
                provenance=Provenance(
                    institution=institution,
                    url=file_uri,
                    section=str(sheet_name) if sheet_name else None,
                    fetched_at=timestamp,
                ),
                meta=SourceMeta(hints={"source": "excel", "level": "S0"}),
            )
            source_records.append(record)

    logger.info(
        "Generated source records",
        count=len(source_records),
        institutions=selected.height,
        workbook=file_uri,
    )
    return source_records


__all__ = [
    "load_faculty_dataframe",
    "count_colleges_per_institution",
    "select_top_institutions",
    "generate_source_records",
]
