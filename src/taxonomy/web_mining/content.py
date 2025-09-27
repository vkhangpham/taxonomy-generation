"""Content extraction, normalization, and metadata handling."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Tuple

try:  # pragma: no cover - optional dependency
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - fallback path
    BeautifulSoup = None

try:  # pragma: no cover - optional dependency
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    DetectorFactory.seed = 0
except Exception:  # pragma: no cover - fallback path
    detect_langs = None
    LangDetectException = Exception  # type: ignore

try:  # pragma: no cover - optional dependency
    import pdfplumber
except Exception:  # pragma: no cover - fallback path
    pdfplumber = None  # type: ignore

from taxonomy.entities.core import PageSnapshot, PageSnapshotMeta
from taxonomy.utils.logging import get_logger

from .models import ContentMetadata, QualityMetrics
from .utils import canonicalize_url, clean_text, generate_checksum, normalize_url


class ContentPolicyError(Exception):
    """Raised when extracted content violates configured processing policies."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"ContentPolicyError(reason={self.reason!r}, message={self.args[0]!r})"


_CANONICAL_PATTERNS = (
    ("link", "rel", "canonical", "href"),
    ("meta", "property", "og:url", "content"),
)


@dataclass
class LanguageDetectionResult:
    language: str
    confidence: float


class ContentProcessor:
    """Processes raw HTTP responses into structured page snapshots."""

    def __init__(
        self,
        *,
        language_allowlist: Iterable[str] | None = None,
        language_confidence_threshold: float = 0.0,
        min_text_length: int = 120,
        pdf_extraction_enabled: bool = True,
        pdf_size_limit_mb: int = 5,
    ) -> None:
        self.language_allowlist = {code.lower() for code in language_allowlist or []}
        self.language_confidence_threshold = max(0.0, min(1.0, float(language_confidence_threshold)))
        self.min_text_length = min_text_length
        self.pdf_extraction_enabled = pdf_extraction_enabled
        self.pdf_size_limit_mb = pdf_size_limit_mb
        self._logger = get_logger(component="content")

    def _detect_language(self, text: str) -> LanguageDetectionResult:
        if not text.strip():
            return LanguageDetectionResult(language="und", confidence=0.0)
        if detect_langs is None:
            return LanguageDetectionResult(language="und", confidence=0.0)
        try:
            langs = detect_langs(text)
        except LangDetectException:  # pragma: no cover - rare path
            return LanguageDetectionResult(language="und", confidence=0.0)
        if not langs:
            return LanguageDetectionResult(language="und", confidence=0.0)
        best = max(langs, key=lambda item: item.prob)
        return LanguageDetectionResult(language=best.lang.lower(), confidence=float(best.prob))

    def _extract_text_from_html(self, html: str, base_url: str | None = None) -> Tuple[str, str | None]:
        if BeautifulSoup is None:
            cleaned = clean_text(re.sub(r"<[^>]+>", " ", html))
            return cleaned, None
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.extract()
        text = clean_text(soup.get_text(" \n"))
        canonical = None
        for tag, attr, expected, value_attr in _CANONICAL_PATTERNS:
            candidate = soup.find(tag, attrs={attr: expected})
            if candidate and candidate.has_attr(value_attr):
                try:
                    canonical = canonicalize_url(candidate[value_attr], base=base_url)
                    break
                except Exception:  # pragma: no cover - normalised failure
                    continue
        if canonical is None and soup.title and soup.title.string:
            canonical = None
        return text, canonical

    def _extract_text_from_pdf(self, payload: bytes) -> str:
        if not self.pdf_extraction_enabled or pdfplumber is None:
            return ""
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return clean_text("\n".join(pages))

    def _enforce_language_policy(self, detection: LanguageDetectionResult) -> str:
        if not self.language_allowlist:
            return detection.language
        return detection.language if detection.language in self.language_allowlist else "und"

    def process(
        self,
        *,
        institution: str,
        url: str,
        http_status: int,
        content_type: str,
        body: bytes | str,
        fetched_at: datetime | None = None,
        rendered: bool = False,
        robots_blocked: bool = False,
        redirects: List[str] | None = None,
        source: str = "crawl",
    ) -> tuple[PageSnapshot, ContentMetadata]:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        redirects = redirects or []
        meta = PageSnapshotMeta(rendered=rendered, robots_blocked=robots_blocked, redirects=redirects, source=source)

        html: str | None = None
        text: str = ""
        canonical_url: str | None = None
        payload = body
        if isinstance(payload, bytes):
            if "text" in content_type or "html" in content_type:
                try:
                    html = payload.decode("utf-8", errors="ignore")
                except Exception:  # pragma: no cover - defensive
                    html = payload.decode("latin-1", errors="ignore")
            else:
                html = None
        else:
            html = payload if "html" in content_type else None
            if isinstance(payload, str):
                payload = payload.encode("utf-8")

        if "pdf" in content_type:
            payload_bytes = payload if isinstance(payload, bytes) else payload.encode("utf-8")
            if self.pdf_size_limit_mb and len(payload_bytes) > self.pdf_size_limit_mb * 1024 * 1024:
                raise ContentPolicyError(
                    "pdf_size_limit",
                    f"PDF payload {len(payload_bytes)} bytes exceeds limit of {self.pdf_size_limit_mb} MB",
                )
            text = self._extract_text_from_pdf(payload if isinstance(payload, bytes) else payload.encode("utf-8"))
        elif html is not None:
            text, canonical_url = self._extract_text_from_html(html, base_url=url)
        else:
            text = clean_text(payload.decode("utf-8", errors="ignore")) if isinstance(payload, bytes) else clean_text(payload)

        detection = self._detect_language(text)
        language = self._enforce_language_policy(detection)

        if self.min_text_length and len(text) < self.min_text_length:
            raise ContentPolicyError(
                "min_text_length",
                f"Extracted text length {len(text)} below minimum {self.min_text_length}",
            )

        if (
            self.language_allowlist
            and detection.language
            and detection.language not in self.language_allowlist
            and detection.confidence >= self.language_confidence_threshold
        ):
            raise ContentPolicyError(
                "language_allowlist",
                f"Detected language {detection.language} not in allowlist {sorted(self.language_allowlist)}",
            )

        checksum = generate_checksum(text)
        quality = QualityMetrics(
            text_length=len(text),
            language_confidence=detection.confidence,
            contains_lists="\n- " in text or "\n* " in text,
        )
        content_meta = ContentMetadata(
            title=None,
            description=None,
            language=language,
            language_confidence=detection.confidence,
            checksum=checksum,
            quality=quality,
        )

        if len(text) < self.min_text_length:
            self._logger.debug(
                "Discarding snapshot due to insufficient text",
                institution=institution,
                url=url,
                text_length=len(text),
            )

        snapshot = PageSnapshot(
            institution=institution,
            url=normalize_url(url),
            canonical_url=canonical_url,
            fetched_at=fetched_at,
            http_status=http_status,
            content_type=content_type,
            html=html,
            text=text,
            lang=language,
            checksum=checksum,
            meta=meta,
        )
        return snapshot, content_meta


__all__ = ["ContentProcessor", "LanguageDetectionResult", "ContentPolicyError"]
