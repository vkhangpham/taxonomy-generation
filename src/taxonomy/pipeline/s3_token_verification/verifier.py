"""LLM-backed single-token verification utilities."""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Callable, Dict, Mapping

from taxonomy.llm import (
    ProviderError,
    QuarantineError,
    ValidationError,
    run as llm_run,
)
from taxonomy.utils.logging import get_logger


@dataclass
class LLMVerificationResult:
    """Structured result emitted by :class:`LLMTokenVerifier`."""

    passed: bool
    reason: str
    raw: dict | None = None
    error: str | None = None


class LLMTokenVerifier:
    """Run the single-token verification prompt and parse responses."""

    _PASS_KEY_CANDIDATES = ("pass", "passed", "ok", "success")
    _TRUTHY_STRINGS = {
        "true",
        "1",
        "yes",
        "y",
        "on",
        "pass",
        "passed",
        "ok",
        "success",
    }
    _FALSY_STRINGS = {
        "false",
        "0",
        "no",
        "n",
        "off",
        "fail",
        "failed",
        "failure",
    }

    def __init__(
        self,
        *,
        runner: Callable[[str, Dict[str, object]], object] | None = None,
    ) -> None:
        self._runner = runner or self._default_runner
        self._log = get_logger(module=__name__)

    def _default_runner(self, prompt_key: str, variables: Dict[str, object]) -> object:
        response = llm_run(prompt_key, variables)
        if getattr(response, "ok", False):
            content = response.content
            if isinstance(content, dict):
                # Validate the pass flag early to surface schema issues sooner.
                self._parse_pass_value(content)
            return content
        raise ProviderError(response.error or "LLM verification failed", retryable=False)

    def verify(self, label: str, level: int) -> LLMVerificationResult:
        payload = {"label": label, "level": level}
        try:
            response = self._runner("taxonomy.verify_single_token", payload)
        except ValidationError as exc:
            self._log.error("LLM validation error during token verification", error=str(exc))
            return LLMVerificationResult(passed=False, reason="invalid-json", error=str(exc))
        except QuarantineError as exc:
            self._log.error("LLM response quarantined during token verification", error=str(exc))
            return LLMVerificationResult(passed=False, reason="quarantined", error=str(exc))
        except ProviderError as exc:
            self._log.error("LLM provider error during token verification", error=str(exc))
            return LLMVerificationResult(passed=False, reason="provider-error", error=str(exc))

        if not isinstance(response, dict):
            self._log.error(
                "LLM returned unexpected payload for token verification",
                payload_type=type(response).__name__,
            )
            return LLMVerificationResult(
                passed=False,
                reason="unexpected-payload",
                raw={"payload": response},
                error="LLM returned non-dict payload",
            )

        passed = self._parse_pass_value(response)
        reason = str(response.get("reason", "")) or ("pass" if passed else "fail")
        return LLMVerificationResult(passed=passed, reason=reason, raw=response)

    def _parse_pass_value(self, response: Mapping[str, object]) -> bool:
        raw_pass: object | None = None
        selected_key: str | None = None
        for key in self._PASS_KEY_CANDIDATES:
            if key in response:
                raw_pass = response[key]
                selected_key = key
                break

        if isinstance(raw_pass, bool):
            return raw_pass

        if raw_pass is None:
            return False

        if not isinstance(raw_pass, (bool, str, int, float)):
            self._log.warning(
                "LLM token verification returned non-primitive pass value",
                pass_key=selected_key,
                value_type=type(raw_pass).__name__,
                value_summary=self._summarize_value(raw_pass),
            )

        if isinstance(raw_pass, str):
            normalized = raw_pass.strip()
            if not normalized:
                return False
            folded = normalized.casefold()
            if folded in self._TRUTHY_STRINGS:
                return True
            if folded in self._FALSY_STRINGS:
                return False
            try:
                numeric_value = float(normalized)
            except ValueError:
                return False
            if math.isnan(numeric_value):
                return False
            return numeric_value != 0.0

        if isinstance(raw_pass, numbers.Number) and not isinstance(raw_pass, bool):
            try:
                numeric_value = float(raw_pass)
            except (TypeError, ValueError):
                return bool(raw_pass)
            if math.isnan(numeric_value):
                return False
            return numeric_value != 0.0

        return False

    @staticmethod
    def _summarize_value(value: object) -> str:
        if value is None:
            return "None"
        if isinstance(value, dict):
            return f"dict(len={len(value)})"
        if isinstance(value, (list, tuple, set)):
            return f"{type(value).__name__}(len={len(value)})"
        summary = repr(value)
        summary = summary.replace("\n", " ")
        if len(summary) > 48:
            summary = f"{summary[:45]}..."
        return summary


__all__ = ["LLMTokenVerifier", "LLMVerificationResult"]
