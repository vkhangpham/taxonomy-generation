"""Deployment helpers for GEPA optimized prompt variants."""

from __future__ import annotations

import datetime as dt
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

from ..config.policies import LLMDeterminismSettings


class VariantDeployer:
    """Persist optimized prompt variants and activate them in the registry."""

    def __init__(
        self,
        *,
        registry_file: Path,
        templates_root: Path,
        backup_before_deployment: bool = True,
    ) -> None:
        self._registry_file = registry_file
        self._templates_root = templates_root
        self._backup = backup_before_deployment

    def deploy(
        self,
        prompt_key: str,
        program,
        *,
        optimization_report: Dict[str, Any],
        activate: bool = True,
    ) -> Tuple[str, Path]:
        registry = self._load_registry()
        if "prompts" not in registry or prompt_key not in registry["prompts"]:
            raise KeyError(f"Prompt '{prompt_key}' is not registered")
        prompt_entry = registry["prompts"][prompt_key]
        variants: Dict[str, Dict[str, Any]] = prompt_entry.setdefault("variants", {})
        active_variant = str(prompt_entry.get("active_variant", ""))
        base_variant = deepcopy(variants.get(active_variant, {})) if active_variant else {}
        if not base_variant:
            raise ValueError(f"Prompt '{prompt_key}' has no active variant to clone")

        timestamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        new_variant_key = self._next_variant_key(variants)
        template_content = program.render_template()
        template_path = self._write_template(prompt_key, new_variant_key, template_content)

        new_variant = deepcopy(base_variant)
        new_variant.update(
            {
                "template": str(template_path),
                "variant_version": timestamp,
                "description": optimization_report.get(
                    "description",
                    "GEPA optimized variant",
                ),
            }
        )
        metadata = getattr(program, "prompt_metadata", lambda: {})()
        history_entry = {
            "optimized_at": timestamp,
            "variant": new_variant_key,
            "metadata": metadata,
            "report": optimization_report,
        }
        history = list(new_variant.get("optimization_history", []))
        history.append(history_entry)
        new_variant["optimization_history"] = history

        variants[new_variant_key] = new_variant
        if activate:
            prompt_entry["active_variant"] = new_variant_key

        if self._backup:
            self._backup_registry()
        self._write_registry(registry)
        return new_variant_key, template_path

    def _write_template(self, prompt_key: str, variant_key: str, content: str) -> Path:
        slug = self._sanitize_slug(prompt_key)
        filename = f"{slug}_{variant_key}.jinja2"
        base_dir = self._templates_root.resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        path = (base_dir / filename).resolve()
        if base_dir not in path.parents and path.parent != base_dir:
            raise ValueError("Resolved template path escapes templates directory")
        final_content = content if content.endswith("\n") else f"{content}\n"
        with path.open("w", encoding="utf-8") as handle:
            handle.write(final_content)
        resolved_base = base_dir
        resolved_parent = resolved_base.parent
        resolved_path = path
        try:
            relative_path = resolved_path.relative_to(resolved_parent)
        except ValueError:
            try:
                relative_path = resolved_path.relative_to(resolved_base)
            except ValueError:
                relative_path = Path(filename)
        return relative_path

    def _load_registry(self) -> Dict[str, Any]:
        if not self._registry_file.exists():
            raise FileNotFoundError(f"Registry file not found: {self._registry_file}")
        with self._registry_file.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data

    def _write_registry(self, payload: Dict[str, Any]) -> None:
        with self._registry_file.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False, indent=2)

    def _backup_registry(self) -> None:
        backup_path = self._registry_file.with_suffix(
            f".backup-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copy2(self._registry_file, backup_path)

    @staticmethod
    def _next_variant_key(variants: Dict[str, Any]) -> str:
        numeric = [
            int(key[1:])
            for key in variants
            if isinstance(key, str) and key.startswith("v") and key[1:].isdigit()
        ]
        next_index = (max(numeric) + 1) if numeric else 1
        return f"v{next_index}"

    @staticmethod
    def _sanitize_slug(prompt_key: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", prompt_key)
        slug = slug.replace("..", "_")
        slug = slug.strip("._-")
        if not slug:
            slug = "prompt"
        return slug


def deploy_optimized_variant(
    *,
    prompt_key: str,
    program,
    optimization_report: Dict[str, Any],
    llm_settings: LLMDeterminismSettings,
    backup_before_deployment: bool = True,
    activate: bool = True,
) -> Tuple[str, Path]:
    """High level helper to deploy a GEPA optimized variant into production."""

    registry_file = Path(llm_settings.registry.file)
    templates_root = Path(llm_settings.registry.templates_root)
    deployer = VariantDeployer(
        registry_file=registry_file,
        templates_root=templates_root,
        backup_before_deployment=backup_before_deployment,
    )
    return deployer.deploy(
        prompt_key=prompt_key,
        program=program,
        optimization_report=optimization_report,
        activate=activate,
    )


__all__ = ["VariantDeployer", "deploy_optimized_variant"]
