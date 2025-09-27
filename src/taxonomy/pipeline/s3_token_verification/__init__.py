"""Token-level verification scaffolding for S3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger


class TokenVerifier(Protocol):
    """Interface implemented by token verification checks."""

    name: str

    def verify(self) -> None:
        ...


@dataclass
class TokenVerificationSuite:
    """Coordinator for S3 token verification passes."""

    verifiers: list[TokenVerifier]

    def execute(self) -> None:
        for verifier in self.verifiers:
            logger.info("Running token verifier", verifier=verifier.name)
            verifier.verify()


__all__ = ["TokenVerifier", "TokenVerificationSuite"]
