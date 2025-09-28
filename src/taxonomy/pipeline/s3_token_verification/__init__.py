"""Public API for S3 token verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from .io import (
    VerificationInput,
    generate_s3_metadata,
    load_candidates,
    write_failed_candidates,
    write_verified_candidates,
)
from .main import verify_tokens
from .processor import (
    S3Processor,
    TokenVerificationDecision,
    TokenVerificationResult,
)
from .rules import RuleEvaluation, TokenRuleEngine
from .verifier import LLMTokenVerifier, LLMVerificationResult


class TokenVerifier(Protocol):
    """Legacy interface preserved for compatibility."""

    name: str

    def verify(self) -> None:
        ...


@dataclass
class TokenVerificationSuite:
    """Coordinator for user-defined verifier plugs."""

    verifiers: list[TokenVerifier]

    def execute(self) -> None:
        for verifier in self.verifiers:
            logger.info("Running token verifier", verifier=verifier.name)
            verifier.verify()


__all__ = [
    "TokenRuleEngine",
    "RuleEvaluation",
    "LLMTokenVerifier",
    "LLMVerificationResult",
    "S3Processor",
    "TokenVerificationDecision",
    "TokenVerificationResult",
    "VerificationInput",
    "load_candidates",
    "write_verified_candidates",
    "write_failed_candidates",
    "generate_s3_metadata",
    "verify_tokens",
    "TokenVerifier",
    "TokenVerificationSuite",
]
