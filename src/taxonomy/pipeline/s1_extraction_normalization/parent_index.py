"""Parent anchor resolution utilities for S1 normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
import difflib
from typing import Dict, Iterable, List, Sequence, Tuple

from taxonomy.config.policies import LabelPolicy
from taxonomy.entities.core import Candidate, Concept
from taxonomy.utils.helpers import normalize_whitespace
from taxonomy.utils.normalization import normalize_by_level


@dataclass(frozen=True)
class ParentEntry:
    """Lightweight projection of a parent concept for indexing."""

    identifier: str
    level: int
    canonical: str
    aliases: Tuple[str, ...] = field(default_factory=tuple)


class ParentIndex:
    """Resolve textual parent anchors to known concept identifiers."""

    def __init__(
        self,
        *,
        label_policy: LabelPolicy,
        similarity_cutoff: float = 0.86,
    ) -> None:
        self._policy = label_policy
        self._similarity_cutoff = similarity_cutoff
        self._entries: Dict[str, List[ParentEntry]] = {}
        self._cache: Dict[Tuple[str, int], List[str]] = {}
        self._unresolved: Dict[int, List[str]] = {}

    @property
    def unresolved(self) -> Dict[int, List[str]]:
        """Return unresolved anchors grouped by target level."""

        return {level: list(values) for level, values in self._unresolved.items()}

    def build_index(self, parents: Sequence[Candidate | Concept]) -> None:
        """Populate the index from previously emitted candidates or concepts."""

        self._entries.clear()
        for parent in parents:
            identifier = getattr(parent, "id", None)
            level = getattr(parent, "level", 0)
            aliases_source: Sequence[str]
            if isinstance(parent, Concept):
                identifier = identifier or parent.canonical_label
                base_label = parent.canonical_label
                aliases_source = parent.aliases
            else:
                identifier = identifier or parent.normalized
                base_label = parent.normalized or parent.label
                aliases_source = parent.aliases

            canonical = normalize_by_level(base_label, level, self._policy)
            aliases = tuple(
                normalize_by_level(alias, level, self._policy)
                for alias in aliases_source
            )
            entry = ParentEntry(
                identifier=identifier,
                level=level,
                canonical=canonical,
                aliases=aliases,
            )
            self._store_entry(entry)

    def _store_entry(self, entry: ParentEntry) -> None:
        for key in (entry.canonical, *entry.aliases):
            if not key:
                continue
            self._entries.setdefault(key, []).append(entry)

    def resolve_anchor(self, anchor: str, target_level: int) -> List[str]:
        """Resolve *anchor* text to known parent identifiers.

        Args:
            anchor: Textual anchor emitted by the LLM.
            target_level: Level of the candidate referencing this parent.

        Returns:
            A list of parent identifiers.  When resolution fails the anchor is
            tracked for diagnostics and an empty list is returned.
        """

        normalized_anchor = normalize_by_level(anchor, max(target_level - 1, 0), self._policy)
        cache_key = (normalized_anchor, target_level)
        if cache_key in self._cache:
            return list(self._cache[cache_key])

        matches = self._match_exact(normalized_anchor, target_level)
        if not matches:
            matches = self._match_fuzzy(normalized_anchor, target_level)

        if matches:
            resolved = sorted({entry.identifier for entry in matches})
            self._cache[cache_key] = resolved
            return list(resolved)

        self._unresolved.setdefault(target_level, []).append(normalize_whitespace(anchor))
        self._cache[cache_key] = []
        return []

    def _match_exact(self, normalized_anchor: str, target_level: int) -> List[ParentEntry]:
        return [
            entry
            for entry in self._entries.get(normalized_anchor, [])
            if entry.level < target_level
        ]

    def _match_fuzzy(self, normalized_anchor: str, target_level: int) -> List[ParentEntry]:
        keys = [
            key
            for key, entries in self._entries.items()
            if any(entry.level < target_level for entry in entries)
        ]
        if not keys:
            return []
        candidates = difflib.get_close_matches(
            normalized_anchor,
            keys,
            n=3,
            cutoff=self._similarity_cutoff,
        )
        results: List[ParentEntry] = []
        for key in candidates:
            results.extend(
                entry
                for entry in self._entries.get(key, [])
                if entry.level < target_level
            )
        return results


__all__ = ["ParentIndex", "ParentEntry"]
