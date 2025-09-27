"""Snapshot text segmentation for S0 raw extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from ...config.policies import RawExtractionPolicy
from ...entities.core import PageSnapshot
from ...utils import get_logger, normalize_whitespace


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
    _MULTISPACE_PATTERN = re.compile(r" {2,}")

    def __init__(self, policy: RawExtractionPolicy) -> None:
        self.policy = policy
        self._logger = get_logger(module=__name__)
        self._header_patterns: List[re.Pattern[str]] = [
            re.compile(pattern, re.IGNORECASE) for pattern in policy.section_header_patterns
        ] if policy.detect_sections else []
        self._boilerplate_patterns: List[re.Pattern[str]] = [
            re.compile(pattern, re.IGNORECASE) for pattern in policy.boilerplate_patterns
        ] if policy.remove_boilerplate else []

    def segment(self, snapshot: PageSnapshot) -> SegmentationResult:
        """Split snapshot text into semantic blocks preserving order."""

        lines = snapshot.text.splitlines()
        table_map = self._detect_table_lines(lines)
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
                if self.policy.verbose_text_logging:
                    self._logger.debug("Removed boilerplate block", text=text[:120])
                else:
                    self._logger.debug("Removed boilerplate block", length=len(text))
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

        for idx, raw_line in enumerate(lines):
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

            line_type = self._classify_line(stripped, table_map[idx])
            if line_type != current_type:
                flush_block()
                current_type = line_type

            source_line = raw_line if line_type == "table" else stripped
            prepared_line = self._prepare_line(source_line, line_type)
            current_lines.append(prepared_line)

        flush_block()

        self._logger.debug(
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

    def _classify_line(self, line: str, is_table_line: bool) -> str:
        if self.policy.segment_on_lists and self._LIST_PATTERN.match(line):
            return "list"
        if self.policy.segment_on_tables and is_table_line:
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

    def _detect_table_lines(self, raw_lines: List[str]) -> List[bool]:
        table_flags: List[bool] = [False] * len(raw_lines)
        if not self.policy.segment_on_tables:
            return table_flags

        stripped = [line.strip() for line in raw_lines]
        pipe_flags = [line.count("|") >= 2 for line in stripped]
        tab_flags = ["\t" in line for line in raw_lines]
        multi_space_columns = [self._multi_space_columns(line) for line in raw_lines]

        for idx, content in enumerate(stripped):
            if not content:
                continue
            if pipe_flags[idx]:
                table_flags[idx] = True
                continue
            if tab_flags[idx] and (
                (idx > 0 and tab_flags[idx - 1]) or (idx + 1 < len(raw_lines) and tab_flags[idx + 1])
            ):
                table_flags[idx] = True
                continue
            if (
                self._columns_align(multi_space_columns[idx], multi_space_columns[idx - 1])
                if idx > 0
                else False
            ) or (
                self._columns_align(multi_space_columns[idx], multi_space_columns[idx + 1])
                if idx + 1 < len(raw_lines)
                else False
            ):
                table_flags[idx] = True

        return table_flags

    def _multi_space_columns(self, line: str) -> List[int]:
        return [
            match.start()
            for match in self._MULTISPACE_PATTERN.finditer(line)
            if (match.end() - match.start()) >= 3
        ]

    @staticmethod
    def _columns_align(current: List[int], other: List[int]) -> bool:
        if len(current) < 2 or len(other) < 2:
            return False
        for position in current:
            if any(abs(position - candidate) <= 1 for candidate in other):
                return True
        return False


__all__ = ["ContentSegmenter", "SegmentedBlock", "SegmentationResult"]
