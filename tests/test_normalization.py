import pytest

from taxonomy.config.policies import LabelPolicy, MinimalCanonicalForm
from taxonomy.utils.normalization import (
    detect_acronyms,
    expand_acronym,
    remove_boilerplate,
    to_canonical_form,
)


@pytest.fixture()
def label_policy() -> LabelPolicy:
    return LabelPolicy(minimal_canonical_form=MinimalCanonicalForm())


def test_remove_boilerplate_department(label_policy: LabelPolicy) -> None:
    bundle = remove_boilerplate("Department of Computer Science", 1, policy=label_policy)
    assert bundle.cleaned == "Computer Science"
    assert "Department of Computer Science" in bundle.aliases


def test_detect_acronyms_identifies_uppercase() -> None:
    text = "Department of Computer Science (CS) and EECS Labs"
    assert detect_acronyms(text) == ("CS", "EECS")


def test_expand_acronym_known_value(label_policy: LabelPolicy) -> None:
    assert (
        expand_acronym("EECS", level=1, policy=label_policy)
        == "electrical engineering and computer science"
    )
    assert expand_acronym("XYZ", level=1, policy=label_policy) is None


def test_expand_acronym_blocks_ambiguous_without_context(label_policy: LabelPolicy) -> None:
    assert expand_acronym("AI", level=1, policy=label_policy) is None
    assert (
        expand_acronym(
            "AI",
            level=2,
            context="Cutting-edge Artificial Intelligence (AI) research",
            policy=label_policy,
        )
        == "artificial intelligence"
    )


def test_expand_acronym_policy_toggle_allows_ambiguous() -> None:
    policy = LabelPolicy(
        minimal_canonical_form=MinimalCanonicalForm(),
        include_ambiguous_acronyms=True,
    )
    assert expand_acronym("AI", level=1, policy=policy) == "artificial intelligence"


def test_expand_acronym_level_gate(label_policy: LabelPolicy) -> None:
    assert expand_acronym("EECS", level=2, policy=label_policy) is None


def test_generate_aliases_includes_boilerplate_and_acronyms(label_policy: LabelPolicy) -> None:
    normalized, aliases = to_canonical_form("Department of Computer Science (CS)", 1, label_policy)
    assert normalized == "computer science"
    assert "CS" in aliases
    assert "Department of Computer Science (CS)" in aliases


def test_to_canonical_form_bounds(label_policy: LabelPolicy) -> None:
    normalized, aliases = to_canonical_form("Álgebra Lineal", 2, label_policy)
    assert normalized == "algebra lineal"
    assert "Álgebra Lineal" in aliases
