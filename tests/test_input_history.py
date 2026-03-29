from __future__ import annotations

from yathaavat.app.input_history import InputHistory


def test_input_history_push_dedupes_consecutive() -> None:
    history = InputHistory()
    history.push("x")
    history.push("x")
    history.push("y")
    assert history.items() == ("x", "y")


def test_input_history_prev_next_preserves_scratch() -> None:
    history = InputHistory()
    history.push("one")
    history.push("two")
    history.push("three")

    assert history.prev("draft") == "three"
    assert history.prev("ignored") == "two"
    assert history.next() == "three"
    assert history.next() == "draft"
    assert history.next() is None


def test_input_history_resets_after_push() -> None:
    history = InputHistory()
    history.push("one")
    assert history.prev("draft") == "one"
    history.push("two")
    assert history.next() is None
    assert history.prev("") == "two"


def test_input_history_enforces_max_entries() -> None:
    history = InputHistory(max_entries=2)
    history.push("one")
    history.push("two")
    history.push("three")
    assert history.items() == ("two", "three")
