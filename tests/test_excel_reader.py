"""Tests for the Level 0 Excel reader."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml
from openpyxl import Workbook

from taxonomy.config.settings import Settings
from taxonomy.pipeline.s0_raw_extraction import (
    count_colleges_per_institution,
    generate_source_records,
    load_faculty_dataframe,
    select_top_institutions,
)


def _policy_template(excel_path: Path, *, top_n: int = 2, seed: int = 7) -> dict:
    return {
        "policy_version": "test",
        "level_thresholds": {
            "level_0": {"min_institutions": 1, "min_src_count": 1},
            "level_1": {"min_institutions": 1, "min_src_count": 1},
            "level_2": {"min_institutions": 1, "min_src_count": 1},
            "level_3": {"min_institutions": 1, "min_src_count": 1},
        },
        "label_policy": {
            "minimal_canonical_form": {
                "case": "lower",
                "remove_punctuation": True,
                "fold_diacritics": True,
                "collapse_whitespace": True,
                "min_length": 2,
                "max_length": 64,
                "boilerplate_patterns": [],
            },
            "token_minimality_preference": "prefer_shortest_unique",
            "punctuation_handling": "strip_terminal",
        },
        "institution_policy": {
            "campus_vs_system": "prefer-campus",
            "joint_center_handling": "duplicate-under-both",
            "cross_listing_strategy": "merge-with-stronger-parent",
            "canonical_mappings": {},
        },
        "web": {
            "allowed_domains": [".edu"],
            "disallowed_paths": [],
            "robots_txt_compliance": True,
            "dynamic_content": False,
            "pdf_processing_limit": 100,
            "ttl_cache_days": 14,
            "firecrawl": {
                "concurrency": 4,
                "max_depth": 3,
                "max_pages": 100,
                "render_timeout_ms": 10000,
            },
        },
        "llm": {
            "temperature": 0.0,
            "nucleus_top_p": 1.0,
            "json_mode": True,
            "retry_attempts": 1,
            "retry_backoff_seconds": 1.0,
            "random_seed": 123,
            "token_budget": 2048,
        },
        "deduplication": {
            "thresholds": {"l0_l1": 0.93, "l2_l3": 0.9},
            "merge_policy": "conservative",
        },
        "level0_excel": {
            "excel_file": str(excel_path),
            "sheets_to_process": ["Sheet1"],
            "top_n_institutions": top_n,
            "random_seed": seed,
        },
    }


@pytest.fixture()
def sample_dataframe() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "institution": [
                "University A",
                "University A",
                "University B",
                "University B",
                "University B",
            ],
            "department_path": [
                "College of Science -> Department of Biology",
                "College of Science -> Department of Chemistry",
                "College of Arts -> Department of Design",
                "College of Arts -> Department of Media",
                "College of Business -> Department of Finance",
            ],
            "sheet_name": ["Sheet1", "Sheet1", "Sheet1", "Sheet1", "Sheet1"],
        }
    )


@pytest.fixture()
def settings_with_excel(
    tmp_path: Path, sample_dataframe: pl.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    workbook = tmp_path / "faculty.xlsx"
    workbook.touch()

    config = {
        "environment": "development",
        "paths": {
            "data_dir": "data",
            "output_dir": "output",
            "cache_dir": ".cache",
            "logs_dir": "logs",
            "metadata_dir": "metadata",
        },
        "random_seed": 1,
        "policies": _policy_template(workbook),
    }
    (tmp_path / "default.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    def fake_read_excel(*_args, **_kwargs):
        return sample_dataframe

    monkeypatch.setattr(pl, "read_excel", fake_read_excel)
    return Settings(config_dir=tmp_path)


def test_count_colleges_per_institution(sample_dataframe: pl.DataFrame) -> None:
    summary = count_colleges_per_institution(sample_dataframe)
    counts = {row["institution"]: row["college_count"] for row in summary.iter_rows(named=True)}
    assert counts == {"University B": 2, "University A": 1}


def test_select_top_institutions_is_deterministic(sample_dataframe: pl.DataFrame) -> None:
    summary = count_colleges_per_institution(sample_dataframe)
    first = select_top_institutions(summary, top_n=2, seed=5)
    second = select_top_institutions(summary, top_n=2, seed=5)
    assert first.to_dict(as_series=False) == second.to_dict(as_series=False)


def test_generate_source_records(settings_with_excel: Settings) -> None:
    records = generate_source_records(settings_with_excel)
    assert records
    payloads = {record.text for record in records}
    assert "University A - College of Science" in payloads
    assert all(record.provenance.institution in {"University A", "University B"} for record in records)


def test_load_faculty_dataframe_raises_for_missing_file(tmp_path: Path) -> None:
    config = {
        "environment": "development",
        "paths": {
            "data_dir": "data",
            "output_dir": "output",
            "cache_dir": ".cache",
            "logs_dir": "logs",
            "metadata_dir": "metadata",
        },
        "random_seed": 1,
        "policies": _policy_template(tmp_path / "missing.xlsx"),
    }
    (tmp_path / "default.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    settings = Settings(config_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        load_faculty_dataframe(settings)


def test_load_faculty_dataframe_raises_for_missing_sheet(tmp_path: Path) -> None:
    workbook = tmp_path / "faculty.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "PresentSheet"
    wb.save(workbook)

    policy = _policy_template(workbook)
    policy["level0_excel"]["sheets_to_process"] = ["NoSuchSheet"]

    config = {
        "environment": "development",
        "paths": {
            "data_dir": "data",
            "output_dir": "output",
            "cache_dir": ".cache",
            "logs_dir": "logs",
            "metadata_dir": "metadata",
        },
        "random_seed": 1,
        "policies": policy,
    }
    (tmp_path / "default.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    settings = Settings(config_dir=tmp_path)
    with pytest.raises(ValueError) as excinfo:
        load_faculty_dataframe(settings)
    message = str(excinfo.value)
    assert "NoSuchSheet" in message
    assert str(workbook) in message
