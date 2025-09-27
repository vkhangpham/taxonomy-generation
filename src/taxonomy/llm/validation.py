"""JSON validation and repair routines for LLM responses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from jsonschema import Draft7Validator, ValidationError as JSONSchemaValidationError

from .models import ValidationResult


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
        path = (self._schema_base_path / schema_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Schema not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data

    @staticmethod
    def _validate_schema(payload: Any, schema: Dict[str, Any]) -> None:
        Draft7Validator(schema).validate(payload)

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


__all__ = ["JSONValidator"]
