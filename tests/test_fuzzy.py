from __future__ import annotations

from yathaavat.app.fuzzy import fuzzy_match


def test_fuzzy_match_exact_is_best() -> None:
    match = fuzzy_match("abc", "abc")
    assert match is not None
    assert match.score == 0


def test_fuzzy_match_subsequence_scores_by_gaps_and_start() -> None:
    a = fuzzy_match("abc", "a_b_c")
    b = fuzzy_match("abc", "xxa_b_c")
    assert a is not None and b is not None
    assert a.score < b.score


def test_fuzzy_match_rejects_missing_chars() -> None:
    assert fuzzy_match("abc", "ab") is None


def test_fuzzy_match_ignores_spaces_in_query() -> None:
    assert fuzzy_match("a b c", "abc") is not None
