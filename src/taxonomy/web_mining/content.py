"""Content extraction, normalization, and metadata handling."""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Tuple, TYPE_CHECKING

try:  # pragma: no cover - optional dependency
    from bs4 import BeautifulSoup
    from bs4.element import NavigableString, Tag
except Exception:  # pragma: no cover - fallback path
    BeautifulSoup = None
    NavigableString = None  # type: ignore
    Tag = None  # type: ignore

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

try:  # pragma: no cover - optional dependency
    from charset_normalizer import from_bytes as detect_charset
except Exception:  # pragma: no cover - fallback path
    detect_charset = None

from taxonomy.entities.core import PageSnapshot, PageSnapshotMeta
from taxonomy.utils.logging import get_logger

from .models import ContentMetadata, QualityMetrics
from .utils import canonicalize_url, clean_text, generate_checksum, normalize_url

_CHARSET_RE = re.compile(r"charset=([\"']?)(?P<charset>[^\s;\"']+)\1", re.IGNORECASE)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .observability import MetricsCollector


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

    def _decode_payload(self, payload: bytes, content_type: str) -> str:
        charset = None
        if content_type:
            match = _CHARSET_RE.search(content_type)
            if match:
                charset = match.group("charset").strip().strip('"').strip("'")

        attempted: set[str] = set()
        if charset:
            try:
                return payload.decode(charset, errors="strict")
            except (LookupError, UnicodeDecodeError):
                attempted.add(charset.lower())

        if detect_charset is not None:
            try:  # pragma: no branch - keep detection optional
                result = detect_charset(payload).best()
            except Exception:  # pragma: no cover - defensive
                result = None
            if result and result.encoding:
                encoding = result.encoding
                try:
                    return payload.decode(encoding, errors="strict")
                except (LookupError, UnicodeDecodeError):
                    attempted.add(encoding.lower())

        for fallback in ("utf-8", "latin-1"):
            if fallback in attempted:
                continue
            try:
                return payload.decode(fallback, errors="strict")
            except UnicodeDecodeError:
                continue

        return payload.decode("utf-8", errors="ignore")

    def _extract_text_from_html(
        self,
        html: str,
        base_url: str | None = None,
    ) -> Tuple[str, str | None, str | None, str | None]:
        if BeautifulSoup is None:
            class _SimpleHTMLExtractor(HTMLParser):
                BLOCK_TAGS = {
                    "p",
                    "div",
                    "section",
                    "article",
                    "header",
                    "footer",
                    "aside",
                    "main",
                    "nav",
                    "summary",
                    "details",
                    "figure",
                    "figcaption",
                    "blockquote",
                    "pre",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                }

                def __init__(self, base: str | None) -> None:
                    super().__init__()
                    self.base = base
                    self.lines: List[str] = []
                    self.current_prefix: str = ""
                    self.current_parts: List[str] = []
                    self.list_stack: List[dict[str, object]] = []
                    self.in_title = False
                    self.title: str | None = None
                    self.description: str | None = None
                    self.canonical: str | None = None

                def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
                    attrs_dict = {name.lower(): (value or "") for name, value in attrs}
                    tag_lower = tag.lower()
                    if tag_lower == "title":
                        self.in_title = True
                        return
                    if tag_lower == "meta":
                        content = attrs_dict.get("content", "")
                        name = attrs_dict.get("name", "").lower()
                        prop = attrs_dict.get("property", "").lower()
                        if content and self.description is None and name == "description":
                            self.description = clean_text(content).replace("\n", " ")
                        elif content and self.description is None and prop == "og:description":
                            self.description = clean_text(content).replace("\n", " ")
                        if content and self.canonical is None and prop == "og:url":
                            self._set_canonical(content)
                        return
                    if tag_lower == "link":
                        rel = attrs_dict.get("rel", "").lower().split()
                        href = attrs_dict.get("href", "")
                        if href and "canonical" in rel and self.canonical is None:
                            self._set_canonical(href)
                        return
                    if tag_lower == "ul":
                        self.list_stack.append({"ordered": False, "index": 0})
                        self._flush_current_line()
                        return
                    if tag_lower == "ol":
                        self.list_stack.append({"ordered": True, "index": 0})
                        self._flush_current_line()
                        return
                    if tag_lower == "li":
                        self._flush_current_line()
                        self.current_prefix = self._current_list_prefix()
                        self.current_parts = []
                        return
                    if tag_lower == "br":
                        self._flush_current_line()
                        return
                    if tag_lower in self.BLOCK_TAGS:
                        self._flush_current_line()

                def handle_endtag(self, tag: str) -> None:
                    tag_lower = tag.lower()
                    if tag_lower == "title":
                        self.in_title = False
                        return
                    if tag_lower == "li":
                        self._flush_current_line()
                        return
                    if tag_lower in {"ul", "ol"}:
                        self._flush_current_line()
                        if self.list_stack:
                            self.list_stack.pop()
                        return
                    if tag_lower in self.BLOCK_TAGS:
                        self._flush_current_line()

                def handle_data(self, data: str) -> None:
                    if not data:
                        return
                    if self.in_title:
                        candidate = clean_text(data).replace("\n", " ")
                        if candidate:
                            self.title = candidate if self.title is None else self.title
                        return
                    normalized = " ".join(data.split())
                    if not normalized:
                        return
                    self.current_parts.append(normalized)

                def close(self) -> None:
                    super().close()
                    self._flush_current_line()

                def get_lines(self) -> List[str]:
                    return self.lines

                def _current_list_prefix(self) -> str:
                    if not self.list_stack:
                        return "- "
                    frame = self.list_stack[-1]
                    ordered = bool(frame.get("ordered", False))
                    depth = max(0, len(self.list_stack) - 1)
                    if ordered:
                        frame["index"] = int(frame.get("index", 0)) + 1
                        return f"{'  ' * depth}{frame['index']}. "
                    return f"{'  ' * depth}- "

                def _flush_current_line(self) -> None:
                    if not self.current_prefix and not self.current_parts:
                        return
                    content = " ".join(self.current_parts)
                    if self.current_prefix:
                        line = f"{self.current_prefix}{content}".strip()
                    else:
                        line = content
                    cleaned_line = clean_text(line)
                    if cleaned_line:
                        self.lines.append(cleaned_line)
                    self.current_prefix = ""
                    self.current_parts = []

                def _set_canonical(self, href: str) -> None:
                    candidate = href.strip()
                    if not candidate or self.canonical is not None:
                        return
                    try:
                        self.canonical = canonicalize_url(candidate, base=self.base)
                    except Exception:
                        return

            extractor = _SimpleHTMLExtractor(base_url)
            extractor.feed(html)
            extractor.close()
            lines = extractor.get_lines()
            if lines:
                text = clean_text("\n".join(lines))
            else:
                text = clean_text(re.sub(r"<[^>]+>", " ", html))
            return text, extractor.canonical, extractor.title, extractor.description

        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()

        def normalize_inline(text: str) -> str:
            return " ".join(text.split())

        def gather_inline(node: "Tag | NavigableString | str | None") -> str:
            if node is None:
                return ""
            if NavigableString is not None and isinstance(node, NavigableString):
                return normalize_inline(str(node))
            if Tag is not None and isinstance(node, Tag):
                name = (node.name or "").lower()
                if name in {"ul", "ol", "script", "style", "noscript"}:
                    return ""
                parts = [gather_inline(child) for child in node.children]
                joined = " ".join(part for part in parts if part)
                return normalize_inline(joined)
            return normalize_inline(str(node))

        BLOCK_TAGS = {
            "p",
            "blockquote",
            "pre",
            "article",
            "section",
            "aside",
            "header",
            "footer",
            "main",
            "nav",
            "summary",
            "details",
            "figure",
            "figcaption",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }

        def render_list(list_tag: "Tag", indent: int) -> List[str]:
            lines: List[str] = []
            ordered = (list_tag.name or "").lower() == "ol"
            for index, item in enumerate(list_tag.find_all("li", recursive=False), start=1):
                item_text = gather_inline(item)
                prefix = f"{'  ' * indent}{index}. " if ordered else f"{'  ' * indent}- "
                if item_text:
                    lines.append(prefix + item_text)
                for nested in item.find_all(["ul", "ol"], recursive=False):
                    lines.extend(render_list(nested, indent + 1))
            return lines

        def render_node(node: "Tag", indent: int = 0) -> List[str]:
            lines: List[str] = []
            inline_parts: List[str] = []

            def flush_inline() -> None:
                if not inline_parts:
                    return
                collapsed = normalize_inline(" ".join(inline_parts))
                cleaned = clean_text(collapsed)
                if cleaned:
                    lines.append(("  " * indent) + cleaned)
                inline_parts.clear()

            for child in node.children:
                if NavigableString is not None and isinstance(child, NavigableString):
                    text = normalize_inline(str(child))
                    if text:
                        inline_parts.append(text)
                elif Tag is not None and isinstance(child, Tag):
                    name = (child.name or "").lower()
                    if name in {"script", "style", "noscript"}:
                        continue
                    if name == "br":
                        flush_inline()
                        continue
                    if name in {"ul", "ol"}:
                        flush_inline()
                        lines.extend(render_list(child, indent))
                        continue
                    if name in BLOCK_TAGS:
                        flush_inline()
                        lines.extend(render_node(child, indent))
                        continue
                    inline_text = gather_inline(child)
                    if inline_text:
                        inline_parts.append(inline_text)
            flush_inline()
            return lines

        root = soup.body or soup
        lines = render_node(root)
        if lines:
            text = clean_text("\n".join(lines))
        else:
            text = clean_text(root.get_text(" "))

        canonical = None
        for tag, attr, expected, value_attr in _CANONICAL_PATTERNS:
            candidate = soup.find(tag, attrs={attr: expected})
            if candidate and candidate.has_attr(value_attr):
                try:
                    canonical = canonicalize_url(candidate[value_attr], base=base_url)
                    break
                except Exception:  # pragma: no cover - normalised failure
                    continue

        title: str | None = None
        if soup.title and soup.title.string:
            candidate_title = clean_text(soup.title.string)
            if candidate_title:
                title = candidate_title.replace("\n", " ")

        description: str | None = None
        description_queries = (
            {"name": "description"},
            {"property": "og:description"},
            {"name": "og:description"},
        )
        for query in description_queries:
            meta_tag = soup.find("meta", attrs=query)
            if meta_tag and meta_tag.get("content"):
                candidate_description = clean_text(meta_tag["content"])
                if candidate_description:
                    description = candidate_description.replace("\n", " ")
                    break

        return text, canonical, title, description

    def _extract_text_from_pdf(self, payload: bytes) -> str:
        if not self.pdf_extraction_enabled or pdfplumber is None:
            return ""
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return clean_text("\n".join(pages))

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
        metrics: "MetricsCollector" | None = None,
    ) -> tuple[PageSnapshot, ContentMetadata]:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        redirects = redirects or []
        meta = PageSnapshotMeta(rendered=rendered, robots_blocked=robots_blocked, redirects=redirects, source=source)

        html: str | None = None
        text: str = ""
        canonical_url: str | None = None
        page_title: str | None = None
        page_description: str | None = None
        payload = body
        if isinstance(payload, bytes):
            if "text" in content_type or "html" in content_type:
                html = self._decode_payload(payload, content_type)
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
            if metrics is not None and self.pdf_extraction_enabled:
                metrics.record_pdf_extracted()
        elif html is not None:
            text, canonical_url, page_title, page_description = self._extract_text_from_html(html, base_url=url)
        else:
            if isinstance(payload, bytes):
                text = clean_text(self._decode_payload(payload, content_type))
            else:
                text = clean_text(str(payload))

        detection = self._detect_language(text)
        language = detection.language

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
            contains_lists=bool(re.search(r"\n\s*(?:-|\*|\d+\.)\s", text)),
        )
        content_meta = ContentMetadata(
            title=page_title,
            description=page_description,
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
