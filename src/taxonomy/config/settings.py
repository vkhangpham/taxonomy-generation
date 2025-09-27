"""Configuration management built on top of the policy primitives."""

from __future__ import annotations

import argparse
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Literal, Sequence

import yaml
from pydantic import BaseModel, Field, model_validator

try:  # pragma: no cover - optional dependency fallback for development environments
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover
    class BaseSettings(BaseModel):
        model_config = {"extra": "allow"}

    class SettingsConfigDict(dict):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

from .policies import Policies, load_policies

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "default.yaml"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries."""

    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _apply_env_overrides(base: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides from TAXONOMY_SETTINGS__* environment variables."""

    prefix = "TAXONOMY_SETTINGS__"
    result = dict(base)
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix) :].lower().split("__")
        cursor = result
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
    return result


class PathsConfig(BaseModel):
    """Filesystem layout for persistent artefacts.

    Calling :meth:`ensure_exists` creates the configured directories if they are
    missing, so consumers should opt out when the side effect is undesirable.
    """

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    output_dir: Path = Field(default=PROJECT_ROOT / "output")
    cache_dir: Path = Field(default=PROJECT_ROOT / ".cache")
    logs_dir: Path = Field(default=PROJECT_ROOT / "logs")
    metadata_dir: Path = Field(default=PROJECT_ROOT / "metadata")

    def ensure_exists(self) -> None:
        """Create directories backing every configured path if they are missing."""
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            path = Path(value)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            path.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, field_name, path)


class Settings(BaseSettings):
    """Primary configuration object for the taxonomy application.

    Precedence (highest first): explicit kwargs or CLI arguments, environment
    variables prefixed with ``TAXONOMY_`` (handled by :class:`BaseSettings`),
    nested overrides via ``TAXONOMY_SETTINGS__`` variables, environment-specific
    YAML (e.g. ``production.yaml``), the default YAML file, and finally the
    class defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="TAXONOMY_",
        validate_assignment=True,
        extra="allow",
    )

    environment: Literal["development", "testing", "production"] = Field(
        default="development",
        description="Active runtime environment",
    )
    config_dir: Path = Field(default=DEFAULT_CONFIG_DIR)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    create_dirs: bool = Field(
        default=True,
        description="Create filesystem directories declared in `paths` during initialisation.",
    )
    random_seed: int = Field(default=20230927)
    policies: Policies


    @model_validator(mode="before")
    @classmethod
    def _bootstrap_from_files(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Load YAML files and merge with provided overrides."""

        config_dir = Path(values.get("config_dir") or DEFAULT_CONFIG_DIR)
        environment = values.get("environment") or os.getenv("TAXONOMY_ENV", "development")
        base_config = _load_yaml_file(config_dir / "default.yaml")
        env_config = _load_yaml_file(config_dir / f"{environment}.yaml")
        merged = _deep_merge(base_config, env_config)
        hydrated = _apply_env_overrides(merged)

        combined = _deep_merge(hydrated, {k: v for k, v in values.items() if v is not None})

        policies_data = combined.pop("policies", None)
        if isinstance(policies_data, Policies):
            combined["policies"] = policies_data
            return combined

        if policies_data is None:
            candidate = {
                key: hydrated.get(key)
                for key in Policies.model_fields.keys()
                if key in hydrated
            }
            policies_data = {k: v for k, v in candidate.items() if v is not None}
        combined["policies"] = load_policies(policies_data)
        return combined

    @model_validator(mode="after")
    def _ensure_paths(self) -> "Settings":
        """Ensure filesystem paths exist when directory creation is enabled."""

        if self.create_dirs:
            self.paths.ensure_exists()
        return self

    @property
    def policy_version(self) -> str:
        return self.policies.policy_version

    @property
    def level0_excel_file(self) -> Path:
        reference = Path(self.policies.level0_excel.excel_file)
        if not reference.is_absolute():
            reference = PROJECT_ROOT / reference
        return reference

    @property
    def log_file(self) -> Path:
        return self.paths.logs_dir / "taxonomy.log"

    @classmethod
    def from_args(cls, argv: Sequence[str] | None = None) -> "Settings":
        """Instantiate settings from CLI arguments.

        CLI-supplied values take precedence over environment variables and YAML
        files, mirroring direct initialisation.
        """

        parser = argparse.ArgumentParser(prog="taxonomy-settings", add_help=True)
        parser.add_argument(
            "--environment",
            choices=["development", "testing", "production"],
            help="Override the runtime environment (default: value from config or env).",
        )
        parser.add_argument(
            "--config-dir",
            type=Path,
            help="Directory containing configuration YAML files.",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Enable debug logging via Python's logging module.",
        )
        parser.add_argument(
            "--no-create-dirs",
            action="store_true",
            help="Do not create filesystem directories during settings initialisation.",
        )

        args = parser.parse_args(list(argv) if argv is not None else None)

        if args.debug:
            logging.basicConfig(level=logging.DEBUG, force=True)

        overrides: Dict[str, Any] = {}
        if args.environment:
            overrides["environment"] = args.environment
        if args.config_dir:
            overrides["config_dir"] = args.config_dir
        if args.no_create_dirs:
            overrides["create_dirs"] = False

        return cls(**overrides)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a singleton settings instance."""

    return Settings()


__all__ = ["Settings", "get_settings", "PathsConfig"]
