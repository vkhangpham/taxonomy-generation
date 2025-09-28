"""JSON validation and repair routines for LLM responses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from jsonschema import Draft7Validator, ValidationError as JSONSchemaValidationError, validators

from .models import ValidationResult


def _extend_with_defaults(validator_cls: Draft7Validator.__class__):
    validate_properties = validator_cls.VALIDATORS["properties"]

    def _set_defaults(validator, properties, instance, schema):
        if isinstance(instance, dict):
            for property_name, subschema in properties.items():
                if "default" in subschema and property_name not in instance:
                    instance[property_name] = subschema["default"]
        yield from validate_properties(validator, properties, instance, schema)

    return validators.extend(validator_cls, {"properties": _set_defaults})


DefaultDraft7Validator = _extend_with_defaults(Draft7Validator)


class JSONValidator:
    """Validate and repair JSON outputs against registered schemas."""

    def __init__(self, *, schema_base_path: Path) -> None:
        self._schema_base_path = schema_base_path

    def validate(self, payload: str, schema_path: str, *, enforce_order_by: Optional[str] = None) -> ValidationResult:
        schema = self._load_schema(schema_path)
        attempts = [payload]
        repaired = False
        parsed: Any = None
        for candidate in attempts:
            try:
                parsed = json.loads(candidate)
                self._validate_schema(parsed, schema)
                if enforce_order_by:
                    parsed = self._enforce_order(parsed, enforce_order_by)
                return ValidationResult(ok=True, parsed=parsed, repaired=repaired)
            except (json.JSONDecodeError, JSONSchemaValidationError) as exc:
                last_error = str(exc)
        repaired_payload = self._repair_payload(payload)
        if repaired_payload is not None and repaired_payload != payload:
            repaired = True
            try:
                parsed = json.loads(repaired_payload)
                self._validate_schema(parsed, schema)
                if enforce_order_by:
                    parsed = self._enforce_order(parsed, enforce_order_by)
                return ValidationResult(ok=True, parsed=parsed, repaired=repaired)
            except (json.JSONDecodeError, JSONSchemaValidationError) as exc:
                last_error = str(exc)
        return ValidationResult(ok=False, parsed=None, repaired=repaired, error=last_error)

    def _load_schema(self, schema_path: str) -> Dict[str, Any]:
        path = self._resolve_schema_path(schema_path)
        if not path.exists():
            raise FileNotFoundError(f"Schema not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data

    def describe_schema(self, schema_path: str, *, max_keys: int = 5) -> str:
        """Return a compact human-readable summary for constrained retries."""

        schema = self._load_schema(schema_path)
        title = schema.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        if isinstance(schema.get("properties"), dict) and schema["properties"]:
            keys = list(schema["properties"].keys())
            preview = keys[:max_keys]
            if len(keys) > max_keys:
                preview.append("...")
            return f"object with keys: {', '.join(preview)}"
        schema_type = schema.get("type")
        if isinstance(schema_type, str) and schema_type:
            return schema_type
        return Path(schema_path).name

    @staticmethod
    def _validate_schema(payload: Any, schema: Dict[str, Any]) -> None:
        DefaultDraft7Validator(schema).validate(payload)

    @staticmethod
    def _enforce_order(payload: Any, field: str) -> Any:
        if isinstance(payload, list) and all(isinstance(item, dict) and field in item for item in payload):
            return sorted(payload, key=lambda item: str(item[field]).lower())
        return payload

    @staticmethod
    def _repair_payload(payload: str) -> Optional[str]:
        candidate = payload.strip()
        if not candidate:
            return None
        match = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
        if match:
            return match.group(1)
        return None

    def _resolve_schema_path(self, schema_path: str) -> Path:
        base = self._schema_base_path.resolve()
        path = (base / schema_path).resolve()
        if path != base and base not in path.parents:
            raise ValueError("Schema path escapes base directory")
        return path


__all__ = ["JSONValidator"]
