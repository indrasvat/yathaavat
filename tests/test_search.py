from __future__ import annotations

from yathaavat.app.search import find_next_index, find_prev_index


def test_find_next_index_wraps() -> None:
    text = "abc abc abc"
    assert find_next_index(text, "abc", 0) == 4
    assert find_next_index(text, "abc", 4) == 8
    assert find_next_index(text, "abc", 8) == 0


def test_find_prev_index_wraps() -> None:
    text = "abc abc abc"
    assert find_prev_index(text, "abc", 8) == 4
    assert find_prev_index(text, "abc", 4) == 0
    assert find_prev_index(text, "abc", 0) == 8


def test_find_index_returns_none_when_missing() -> None:
    text = "hello"
    assert find_next_index(text, "nope", 0) is None
    assert find_prev_index(text, "nope", 0) is None
