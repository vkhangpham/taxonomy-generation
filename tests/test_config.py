"""Tests for configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from taxonomy.config.policies import Policies, load_policies
from taxonomy.config.settings import Settings


@pytest.fixture
def minimal_policy_dict() -> dict:
    return {
        "policy_version": "test-version",
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
            "excel_file": "data/Faculty Extraction Report.xlsx",
            "sheets_to_process": [],
            "top_n_institutions": 5,
            "random_seed": 42,
        },
    }


def test_load_policies_from_dict(minimal_policy_dict: dict) -> None:
    policies = load_policies(minimal_policy_dict)
    assert isinstance(policies, Policies)
    assert policies.level_thresholds.level_0.min_src_count == 1


def test_settings_environment_override(tmp_path: Path, minimal_policy_dict: dict) -> None:
    default_yaml = {
        "environment": "development",
        "paths": {
            "data_dir": "data",
            "output_dir": "output",
            "cache_dir": ".cache",
            "logs_dir": "logs",
            "metadata_dir": "metadata",
        },
        "random_seed": 1,
        "policies": minimal_policy_dict,
    }
    testing_yaml = {
        "random_seed": 99,
        "policies": {
            "policy_version": "testing",
        },
    }
    (tmp_path / "default.yaml").write_text(yaml.safe_dump(default_yaml), encoding="utf-8")
    (tmp_path / "testing.yaml").write_text(yaml.safe_dump(testing_yaml), encoding="utf-8")

    settings = Settings(config_dir=tmp_path, environment="testing")
    assert settings.random_seed == 99
    assert settings.policies.policy_version == "testing"


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, minimal_policy_dict: dict) -> None:
    default_yaml = {
        "environment": "development",
        "paths": {
            "data_dir": "data",
            "output_dir": "output",
            "cache_dir": ".cache",
            "logs_dir": "logs",
            "metadata_dir": "metadata",
        },
        "random_seed": 1,
        "policies": minimal_policy_dict,
    }
    (tmp_path / "default.yaml").write_text(yaml.safe_dump(default_yaml), encoding="utf-8")

    monkeypatch.setenv("TAXONOMY_SETTINGS__random_seed", "123")

    settings = Settings(config_dir=tmp_path)
    assert settings.random_seed == 123
