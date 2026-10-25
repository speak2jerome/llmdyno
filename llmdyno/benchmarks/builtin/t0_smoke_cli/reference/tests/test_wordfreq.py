from wordfreq import top_words


def test_counts():
    assert top_words("a b a") == [("a", 2), ("b", 1)]


def test_case():
    assert top_words("A a") == [("a", 2)]


def test_zero():
    assert top_words("a", 0) == []
