"""Shared normalization utilities for the S1 extraction pipeline.

These helpers sit on top of :mod:`taxonomy.utils.helpers` and extend the
behaviour with level-aware boilerplate removal, acronym handling, and alias
management.  They are intentionally lightweight so they can be reused outside
of the S1 processors (e.g. during deduplication and validation).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
from typing import Iterable, List, Sequence, Tuple

from taxonomy.config.policies import LabelPolicy, MinimalCanonicalForm
from .helpers import fold_diacritics, normalize_label, normalize_whitespace


# Common boilerplate prefixes encountered per hierarchy level.  The values are
# stored in lower case to simplify matching regardless of input casing.
_LEVEL_PREFIXES: dict[int, Tuple[str, ...]] = {
    0: tuple(),
    1: (
        "school of ",
        "college of ",
        "department of ",
        "dept of ",
        "dept. of ",
        "division of ",
    ),
    2: (
        "center for ",
        "centre for ",
        "laboratory for ",
        "lab for ",
        "institute for ",
        "research area: ",
    ),
    3: (
        "workshop on ",
        "symposium on ",
        "track: ",
    ),
}

# Mapping of common academic acronyms to canonical expansions.  The values are
# conservative so we avoid accidental over-expansion during normalization.
_COMMON_ACRONYM_MAP: dict[str, str] = {
    "cs": "computer science",
    "cee": "civil and environmental engineering",
    "ce": "civil engineering",
    "ece": "electrical and computer engineering",
    "ee": "electrical engineering",
    "eecs": "electrical engineering and computer science",
    "ise": "industrial and systems engineering",
    "me": "mechanical engineering",
    "mba": "master of business administration",
    "mse": "materials science and engineering",
    "ai": "artificial intelligence",
}

_AMBIGUOUS_ACRONYMS: frozenset[str] = frozenset({"ai"})

# Acronym detection pattern – we accept two or more consecutive capital letters
# and allow ampersands to support entries like "R&D".  Trailing punctuation is
# handled by stripping within :func:`detect_acronyms` to keep the expression
# readable.
_ACRONYM_PATTERN = re.compile(r"\b[A-Z]{2,}(?:&[A-Z]{2,})*\b")
_ACRONYM_MAX_LENGTH = 6
_ACRONYM_STOPWORDS = frozenset(
    {
        "OF",
        "THE",
        "AND",
        "FOR",
        "WITH",
        "FROM",
        "IN",
        "ON",
        "BY",
        "AT",
        "TO",
        "UNIVERSITY",
        "COLLEGE",
        "SCHOOL",
        "DEPARTMENT",
        "DEPT",
        "CENTER",
        "CENTRE",
        "INSTITUTE",
        "LAB",
        "LABORATORY",
        "PROGRAM",
        "PROGRAMME",
        "RESEARCH",
        "SCIENCE",
        "ENGINEERING",
        "STUDIES",
        "PENNSYLVANIA",
    }
)


@dataclass(frozen=True)
class AliasBundle:
    """Container returned by :func:`remove_boilerplate` describing variants."""

    cleaned: str
    aliases: Tuple[str, ...]


def _apply_boilerplate_patterns(
    text: str,
    policy: MinimalCanonicalForm | None,
) -> Tuple[str, Tuple[str, ...]]:
    """Remove regex boilerplate patterns declared in policy.

    Returns the cleaned text alongside aliases that capture removed variants so
    the caller can preserve them for downstream processing.
    """

    if policy is None or not policy.boilerplate_patterns:
        return text, tuple()

    aliases: List[str] = []
    cleaned = text
    for pattern in policy.boilerplate_patterns:
        compiled = re.compile(pattern, flags=re.IGNORECASE)
        if compiled.search(cleaned):
            aliases.append(cleaned)
            cleaned = compiled.sub(" ", cleaned)
            cleaned = normalize_whitespace(cleaned)
    return cleaned, tuple(aliases)


def remove_boilerplate(
    label: str,
    level: int,
    *,
    policy: LabelPolicy | None = None,
    owning_institution: str | None = None,
) -> AliasBundle:
    """Strip level-aware boilerplate prefixes while preserving aliases.

    Args:
        label: Raw label captured from the source text.
        level: Hierarchy level the label belongs to (0..3).
        policy: Optional label policy whose canonical form patterns will be
            honoured in addition to built-in prefixes.

    Returns:
        An :class:`AliasBundle` containing the cleaned label and any alias
        variants created when boilerplate was removed.
    """

    minimal_form = policy.minimal_canonical_form if policy else None
    working = label.strip()
    aliases: List[str] = []

    # L0: strip owning institution prefix when present (e.g.,
    # "University of X - School of Y" -> "School of Y"). Keep the original
    # variant as an alias to preserve traceability.
    if owning_institution and level == 0:
        inst_raw = owning_institution.strip()
        if inst_raw:
            # Case-insensitive, punctuation-tolerant prefix match supporting
            # common separators: dash, colon, pipe, or whitespace.
            escaped = re.escape(inst_raw)
            prefix_pattern = rf"^\s*(?:{escaped})\s*(?:[-–—:\|])?\s+"
            if re.compile(prefix_pattern, flags=re.IGNORECASE).match(working):
                aliases.append(working)
                working = re.sub(prefix_pattern, "", working, flags=re.IGNORECASE).lstrip()

    prefixes = _LEVEL_PREFIXES.get(level, tuple())
    lowered = working.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            aliases.append(working)
            working = working[len(prefix) :].lstrip(" -:,\t")
            lowered = working.lower()
            break

    working, policy_aliases = _apply_boilerplate_patterns(working, minimal_form)
    if policy_aliases:
        aliases.extend(policy_aliases)

    paren_match = re.search(r"\(([^)]+)\)\s*$", working)
    if paren_match:
        suffix = paren_match.group(1).strip()
        if 1 <= len(suffix) <= 8:
            aliases.append(working)
            working = working[: paren_match.start()].rstrip()

    return AliasBundle(cleaned=working, aliases=tuple(OrderedDict.fromkeys(aliases)))


def detect_acronyms(text: str) -> Tuple[str, ...]:
    """Return unique acronyms found in *text* preserving original order."""

    if not text:
        return tuple()

    seen = OrderedDict()
    for match in _ACRONYM_PATTERN.finditer(text):
        acronym = match.group(0).strip(".()[]{}:;,")
        if len(acronym) < 2:
            continue
        if len(acronym) > _ACRONYM_MAX_LENGTH:
            continue
        if acronym in _ACRONYM_STOPWORDS:
            continue
        seen[acronym] = None
    return tuple(seen.keys())


def expand_acronym(
    acronym: str,
    *,
    level: int,
    context: str | None = None,
    policy: LabelPolicy | None = None,
) -> str | None:
    """Return a conservative expansion for *acronym* when known.

    The *context* parameter allows future heuristics (e.g. matching tokens
    within the surrounding label).  Expansions are limited to shallower levels
    unless the surrounding context already contains the expanded phrase.  When
    the acronym is marked ambiguous (e.g. ``AI``), the policy must opt in unless
    the context explicitly includes the expansion.
    """

    key = acronym.lower()
    expansion = _COMMON_ACRONYM_MAP.get(key)
    if not expansion:
        return None

    normalized_context = (context or "").lower()
    if expansion.lower() in normalized_context:
        return expansion

    if key in _AMBIGUOUS_ACRONYMS:
        allow_ambiguous = bool(getattr(policy, "include_ambiguous_acronyms", False))
        if not allow_ambiguous:
            return None

    if level > 1:
        return None

    return expansion


def generate_aliases(
    original: str,
    normalized: str,
    *,
    level: int,
    policy: LabelPolicy | None = None,
    boilerplate_aliases: Sequence[str] = (),
) -> Tuple[str, ...]:
    """Generate a deterministic alias set for a candidate label.

    The output always includes the original label and the normalized form while
    appending boilerplate variants and acronym expansions when available.
    """

    aliases = OrderedDict({normalize_whitespace(original): None})
    aliases[normalize_whitespace(normalized)] = None

    for variant in boilerplate_aliases:
        aliases[normalize_whitespace(variant)] = None

    for acronym in detect_acronyms(original):
        aliases[acronym] = None
        expansion = expand_acronym(
            acronym,
            level=level,
            context=original,
            policy=policy,
        )
        if expansion:
            aliases[normalize_whitespace(expansion)] = None

    if policy:
        minimal = policy.minimal_canonical_form
        if minimal.fold_diacritics:
            for key in list(aliases.keys()):
                folded = fold_diacritics(key)
                aliases[normalize_whitespace(folded)] = None

    return tuple(aliases.keys())


def _apply_minimal_form(text: str, minimal: MinimalCanonicalForm) -> str:
    """Apply the minimal canonical form configuration."""

    working = text
    if minimal.case == "lower":
        working = working.lower()
    if minimal.remove_punctuation:
        working = re.sub(r"[^0-9A-Za-z\s]+", " ", working)
    if minimal.fold_diacritics:
        working = fold_diacritics(working)
    if minimal.collapse_whitespace:
        working = normalize_whitespace(working)
    else:
        working = working.strip()
    return working


def normalize_by_level(
    label: str,
    level: int,
    policy: LabelPolicy,
    *,
    owning_institution: str | None = None,
) -> str:
    """Apply level-aware normalization rules for canonical comparisons."""

    bundle = remove_boilerplate(
        label,
        level,
        policy=policy,
        owning_institution=owning_institution,
    )
    minimal = policy.minimal_canonical_form
    normalized = normalize_label(bundle.cleaned)
    normalized = _apply_minimal_form(normalized, minimal)
    return normalized


def to_canonical_form(
    label: str,
    level: int,
    policy: LabelPolicy,
    *,
    owning_institution: str | None = None,
) -> Tuple[str, Tuple[str, ...]]:
    """Return the canonical form along with aliases generated for *label*.

    The aliases incorporate boilerplate variants, acronym forms, and
    diacritic-folded variants to give downstream stages a rich equivalence
    class.  The canonical label respects the label policy's minimal form while
    leveraging :func:`normalize_label` for core transformations.
    """

    bundle = remove_boilerplate(
        label,
        level,
        policy=policy,
        owning_institution=owning_institution,
    )
    minimal = policy.minimal_canonical_form
    normalized = normalize_label(bundle.cleaned)
    normalized = _apply_minimal_form(normalized, minimal)

    aliases = generate_aliases(
        original=label,
        normalized=normalized,
        level=level,
        policy=policy,
        boilerplate_aliases=bundle.aliases,
    )
    return normalized, aliases


__all__ = [
    "AliasBundle",
    "remove_boilerplate",
    "detect_acronyms",
    "expand_acronym",
    "generate_aliases",
    "normalize_by_level",
    "to_canonical_form",
]
