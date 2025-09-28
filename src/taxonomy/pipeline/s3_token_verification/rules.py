"""Deterministic rule checks for single-token verification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from taxonomy.config.policies import MinimalCanonicalForm, SingleTokenVerificationPolicy
from taxonomy.utils.helpers import normalize_whitespace
from taxonomy.utils.logging import get_logger


@dataclass
class RuleEvaluation:
    """Result emitted by :class:`TokenRuleEngine.apply_all_rules`."""

    passed: bool
    allowlist_hit: bool
    token_count: int
    checks: Dict[str, bool]
    reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class TokenRuleEngine:
    """Apply deterministic validation rules prior to LLM verification."""

    VENUE_KEYWORDS = (
        "conference",
        "symposium",
        "symposia",
        "journal",
        "transactions",
        "workshop",
        "proceedings",
    )

    def __init__(
        self,
        *,
        policy: SingleTokenVerificationPolicy,
        minimal_form: MinimalCanonicalForm,
        min_alnum_ratio: float = 0.7,
    ) -> None:
        self._policy = policy
        self._minimal_form = minimal_form
        self._min_alnum_ratio = min_alnum_ratio
        self._log = get_logger(module=__name__)
        self._allowlist = {entry.lower(): entry for entry in policy.allowlist}

    def count_tokens(self, label: str) -> int:
        prepared = label.strip()
        if not self._policy.hyphenated_compounds_allowed:
            prepared = prepared.replace("-", " ")
        tokens = [token for token in re.split(r"\s+", prepared) if token]
        return len(tokens)

    def check_forbidden_punctuation(self, label: str) -> Tuple[bool, List[str]]:
        violations = sorted(
            {mark for mark in self._policy.forbidden_punctuation if mark and mark in label}
        )
        return (not violations, violations)

    def check_length_bounds(self, label: str) -> Tuple[bool, Tuple[int, int]]:
        minimal = self._minimal_form
        length = len(label.strip())
        return (minimal.min_length <= length <= minimal.max_length, (minimal.min_length, minimal.max_length))

    def check_alnum_ratio(self, label: str) -> Tuple[bool, float]:
        material = label.replace(" ", "")
        if not material:
            return False, 0.0
        alnum = sum(1 for char in material if char.isalnum())
        ratio = alnum / len(material)
        return ratio >= self._min_alnum_ratio, ratio

    def check_venue_names(self, label: str, level: int) -> Tuple[bool, str | None]:
        if not self._policy.venue_names_forbidden or level != 3:
            return True, None
        lowered = label.lower()
        for keyword in self.VENUE_KEYWORDS:
            if keyword in lowered:
                return False, keyword
        return True, None

    def check_allowlist(self, label: str) -> bool:
        return label.lower() in self._allowlist

    def suggest_minimal_alternative(self, label: str) -> List[str]:
        collapsed = normalize_whitespace(label)
        suggestions = []
        stripped = collapsed.strip()
        if not stripped:
            return suggestions
        punctuation_free = stripped
        for mark in self._policy.forbidden_punctuation:
            punctuation_free = punctuation_free.replace(mark, " ")
        punctuation_free = normalize_whitespace(punctuation_free)
        if punctuation_free and punctuation_free != stripped:
            suggestions.append(punctuation_free)
        if not self._policy.hyphenated_compounds_allowed and "-" in stripped:
            suggestions.append(stripped.replace("-", " "))
        condensed = re.sub(r"[^A-Za-z0-9 ]+", "", stripped)
        condensed = normalize_whitespace(condensed)
        if condensed and condensed not in suggestions and condensed != stripped:
            suggestions.append(condensed)
        return suggestions[:3]

    def apply_all_rules(self, label: str, level: int) -> RuleEvaluation:
        cleaned = normalize_whitespace(label)
        allowlist_hit = self.check_allowlist(cleaned)
        token_count = self.count_tokens(cleaned)
        max_tokens = self._policy.max_tokens_per_level.get(level, max(self._policy.max_tokens_per_level.values()))

        checks: Dict[str, bool] = {}
        reasons: List[str] = []

        if allowlist_hit:
            checks["allowlist"] = True
            evaluation = RuleEvaluation(
                passed=True,
                allowlist_hit=True,
                token_count=token_count,
                checks=checks,
                reasons=["label matched allowlist"],
            )
            self._log.debug("Rule evaluation allowlist bypass", label=cleaned)
            return evaluation

        token_ok = token_count <= max_tokens
        checks["token_limit"] = token_ok
        if not token_ok:
            reasons.append(f"token_count {token_count} exceeds max {max_tokens}")

        punctuation_ok, punctuation = self.check_forbidden_punctuation(cleaned)
        checks["punctuation"] = punctuation_ok
        if not punctuation_ok:
            reasons.append(f"forbidden punctuation: {', '.join(punctuation)}")

        length_ok, bounds = self.check_length_bounds(cleaned)
        checks["length_bounds"] = length_ok
        if not length_ok:
            reasons.append(f"length outside range {bounds[0]}-{bounds[1]}")

        ratio_ok, ratio = self.check_alnum_ratio(cleaned)
        checks["alnum_ratio"] = ratio_ok
        if not ratio_ok:
            reasons.append(f"alphanumeric ratio {ratio:.2f} below {self._min_alnum_ratio:.2f}")

        venue_ok, keyword = self.check_venue_names(cleaned, level)
        checks["venue"] = venue_ok
        if not venue_ok and keyword is not None:
            reasons.append(f"contains venue keyword '{keyword}'")

        passed = all(checks.values())
        suggestions: List[str] = []
        if not passed:
            suggestions = self.suggest_minimal_alternative(cleaned)

        evaluation = RuleEvaluation(
            passed=passed,
            allowlist_hit=False,
            token_count=token_count,
            checks=checks,
            reasons=reasons,
            suggestions=suggestions,
        )
        self._log.debug(
            "Rule evaluation complete",
            label=cleaned,
            passed=passed,
            reasons=reasons,
            suggestions=suggestions,
        )
        return evaluation


__all__ = ["TokenRuleEngine", "RuleEvaluation"]
