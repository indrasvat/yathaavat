from __future__ import annotations

from yathaavat.app.source_nav import parse_goto_spec


def test_parse_goto_spec_line_only() -> None:
    spec = parse_goto_spec("12")
    assert spec is not None
    assert spec.line == 12
    assert spec.col == 1


def test_parse_goto_spec_line_col() -> None:
    spec = parse_goto_spec("12:5")
    assert spec is not None
    assert spec.line == 12
    assert spec.col == 5


def test_parse_goto_spec_rejects_invalid() -> None:
    assert parse_goto_spec("") is None
    assert parse_goto_spec("a") is None
    assert parse_goto_spec("0") is None
    assert parse_goto_spec("12:0") is None
    assert parse_goto_spec("12:x") is None
