from taxonomy.utils.acronym import abbrev_score, detect_acronym, is_acronym_expansion


def test_detect_acronym_basic():
    assert detect_acronym("CS") == "CS"
    assert detect_acronym("computer science") is None


def test_is_acronym_expansion_matches_known_pairs():
    assert is_acronym_expansion("CS", "Computer Science")
    assert is_acronym_expansion("AI", "Artificial Intelligence")
    assert not is_acronym_expansion("CV", "Machine Learning")


def test_abbrev_score_bidirectional():
    assert abbrev_score("Artificial Intelligence", "AI") == 1.0
    assert abbrev_score("machine learning", "ML") == 1.0
    assert abbrev_score("computer science", "data science") == 0.0
