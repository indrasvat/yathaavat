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


def test_parse_breakpoint_spec_with_condition(tmp_path: Path) -> None:
    p = tmp_path / "svc.py"
    p.write_text("x = 1\n", encoding="utf-8")

    spec = parse_breakpoint_spec('svc.py:12 if "x > 1"', cwd=tmp_path)
    assert spec is not None
    assert spec.path == str(p.resolve())
    assert spec.line == 12
    assert spec.condition == "x > 1"
    assert spec.hit_condition is None
    assert spec.log_message is None


def test_parse_breakpoint_spec_with_hit_condition(tmp_path: Path) -> None:
    p = tmp_path / "svc.py"
    p.write_text("x = 1\n", encoding="utf-8")

    spec = parse_breakpoint_spec("svc.py:7 hit 3", cwd=tmp_path)
    assert spec is not None
    assert spec.path == str(p.resolve())
    assert spec.line == 7
    assert spec.hit_condition == "3"


def test_parse_breakpoint_spec_with_log_message(tmp_path: Path) -> None:
    p = tmp_path / "svc.py"
    p.write_text("x = 1\n", encoding="utf-8")

    spec = parse_breakpoint_spec('svc.py:9 log "hello world"', cwd=tmp_path)
    assert spec is not None
    assert spec.path == str(p.resolve())
    assert spec.line == 9
    assert spec.log_message == "hello world"


def test_parse_breakpoint_spec_with_key_value_tokens(tmp_path: Path) -> None:
    p = tmp_path / "svc.py"
    p.write_text("x = 1\n", encoding="utf-8")

    spec = parse_breakpoint_spec("svc.py:42 if=x>1 hit=5 log=yo", cwd=tmp_path)
    assert spec is not None
    assert spec.path == str(p.resolve())
    assert spec.line == 42
    assert spec.condition == "x>1"
    assert spec.hit_condition == "5"
    assert spec.log_message == "yo"


def test_parse_breakpoint_spec_rejects_unknown_tokens(tmp_path: Path) -> None:
    p = tmp_path / "svc.py"
    p.write_text("x = 1\n", encoding="utf-8")

    assert parse_breakpoint_spec("svc.py:12 maybe", cwd=tmp_path) is None
