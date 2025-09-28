"""LLM-backed single-token verification utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

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

    def __init__(
        self,
        *,
        runner: Callable[[str, Dict[str, object]], object] | None = None,
    ) -> None:
        self._runner = runner or self._default_runner
        self._log = get_logger(module=__name__)

    @staticmethod
    def _default_runner(prompt_key: str, variables: Dict[str, object]) -> object:
        response = llm_run(prompt_key, variables)
        if getattr(response, "ok", False):
            return response.content
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

        raw_pass = response.get("pass")
        if isinstance(raw_pass, bool):
            passed = raw_pass
        elif isinstance(raw_pass, str):
            passed = raw_pass.strip().lower() in {"true", "1", "yes"}
        elif isinstance(raw_pass, (int, float)):
            passed = bool(raw_pass)
        else:
            passed = False

        reason = str(response.get("reason", "")) or ("pass" if passed else "fail")
        return LLMVerificationResult(passed=passed, reason=reason, raw=response)


__all__ = ["LLMTokenVerifier", "LLMVerificationResult"]
