"""Snapshot text segmentation for S0 raw extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional

from loguru import logger

from ...config.policies import RawExtractionPolicy
from ...entities.core import PageSnapshot
from ...utils import normalize_whitespace


@dataclass
class SegmentedBlock:
    """Represents a logical text block extracted from a snapshot."""

    text: str
    section: Optional[str]
    block_type: str
    order: int


@dataclass
class SegmentationResult:
    """Container for segmentation output and statistics."""

    blocks: List[SegmentedBlock]
    boilerplate_removed: int = 0


class ContentSegmenter:
    """DOM-aware heuristic segmenter for snapshot text content."""

    _LIST_PATTERN = re.compile(r"^(?:[-+*•‣◦]|\d+[.)]|[a-z][.)])\s+", re.IGNORECASE)
    _TABLE_PATTERN = re.compile(r"\s{2,}|\t|\|")

    def __init__(self, policy: RawExtractionPolicy) -> None:
        self.policy = policy
        self._header_patterns: List[re.Pattern[str]] = [
            re.compile(pattern, re.IGNORECASE) for pattern in policy.section_header_patterns
        ] if policy.detect_sections else []
        self._boilerplate_patterns: List[re.Pattern[str]] = [
            re.compile(pattern, re.IGNORECASE) for pattern in policy.boilerplate_patterns
        ] if policy.remove_boilerplate else []

    def segment(self, snapshot: PageSnapshot) -> SegmentationResult:
        """Split snapshot text into semantic blocks preserving order."""

        lines = snapshot.text.splitlines()
        blocks: List[SegmentedBlock] = []
        boilerplate_removed = 0
        current_lines: List[str] = []
        current_type = "paragraph"
        current_section: Optional[str] = None
        order = 0

        def flush_block() -> None:
            nonlocal blocks, current_lines, current_type, current_section, order, boilerplate_removed
            if not current_lines:
                return
            raw_text = "\n".join(line for line in current_lines if line.strip())
            if not raw_text.strip():
                current_lines.clear()
                return
            if current_type == "list" and self.policy.preserve_list_structure:
                text = raw_text.strip()
            else:
                text = normalize_whitespace(raw_text)
            if not text:
                current_lines.clear()
                return
            if self._is_boilerplate(text):
                boilerplate_removed += 1
                logger.debug("Removed boilerplate block", text=text[:120])
                current_lines.clear()
                return
            block = SegmentedBlock(
                text=text,
                section=current_section,
                block_type=current_type,
                order=order,
            )
            blocks.append(block)
            order += 1
            current_lines.clear()

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                flush_block()
                continue

            if self._is_header(stripped):
                flush_block()
                current_section = stripped
                if self.policy.segment_on_headers:
                    header_block = SegmentedBlock(
                        text=normalize_whitespace(stripped),
                        section=current_section,
                        block_type="header",
                        order=order,
                    )
                    if not self._is_boilerplate(header_block.text):
                        blocks.append(header_block)
                        order += 1
                    else:
                        boilerplate_removed += 1
                continue

            line_type = self._classify_line(stripped)
            if line_type != current_type:
                flush_block()
                current_type = line_type

            prepared_line = self._prepare_line(stripped, line_type)
            current_lines.append(prepared_line)

        flush_block()

        logger.debug(
            "Segmented snapshot",
            url=snapshot.url,
            institution=snapshot.institution,
            blocks=len(blocks),
            boilerplate_removed=boilerplate_removed,
        )
        return SegmentationResult(blocks=blocks, boilerplate_removed=boilerplate_removed)

    def _is_header(self, line: str) -> bool:
        if not self.policy.detect_sections:
            return False
        if any(pattern.search(line) for pattern in self._header_patterns):
            return True
        if line.endswith(":") and len(line.split()) <= 12:
            return True
        if line.isupper() and 2 <= len(line.split()) <= 12:
            return True
        return False

    def _classify_line(self, line: str) -> str:
        if self.policy.segment_on_lists and self._LIST_PATTERN.match(line):
            return "list"
        if self.policy.segment_on_tables and self._TABLE_PATTERN.search(line):
            return "table"
        return "paragraph"

    def _prepare_line(self, line: str, block_type: str) -> str:
        if block_type != "list" or self.policy.preserve_list_structure:
            return line
        cleaned = self._LIST_PATTERN.sub("", line).strip()
        return cleaned or line

    def _is_boilerplate(self, text: str) -> bool:
        if not self._boilerplate_patterns:
            return False
        return any(pattern.search(text) for pattern in self._boilerplate_patterns)


__all__ = ["ContentSegmenter", "SegmentedBlock", "SegmentationResult"]
