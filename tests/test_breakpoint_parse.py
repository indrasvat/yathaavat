from __future__ import annotations

from pathlib import Path

from yathaavat.app.breakpoint import parse_breakpoint_spec


def test_parse_breakpoint_spec_path_line(tmp_path: Path) -> None:
    p = tmp_path / "app.py"
    p.write_text("print('hi')\n", encoding="utf-8")
    spec = parse_breakpoint_spec("app.py:12", cwd=tmp_path)
    assert spec is not None
    assert spec.line == 12
    assert spec.path == str(p.resolve())


def test_parse_breakpoint_spec_hash_l(tmp_path: Path) -> None:
    p = tmp_path / "mod.py"
    p.write_text("x = 1\n", encoding="utf-8")
    spec = parse_breakpoint_spec("mod.py#L7", cwd=tmp_path)
    assert spec is not None
    assert spec.line == 7
    assert spec.path == str(p.resolve())


def test_parse_breakpoint_spec_line_only_requires_default(tmp_path: Path) -> None:
    p = tmp_path / "x.py"
    p.write_text("x = 1\n", encoding="utf-8")
    spec = parse_breakpoint_spec("9", default_path=str(p))
    assert spec is not None
    assert spec.line == 9
    assert spec.path == str(p.resolve())

    assert parse_breakpoint_spec("9", default_path=None) is None
