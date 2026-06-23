from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from tests.support import make_context
from yathaavat.app.file_discovery import DiscoveredFile
from yathaavat.app.launch import (
    LaunchPicker,
    _expand_tilde,
    _relative_time,
    parse_launch_spec,
)


def _venv_script_dir(root: Path) -> Path:
    return root / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")


def test_launch_parse_expand_and_rows(tmp_path: Path) -> None:
    spec = parse_launch_spec("script.py --flag 'two words'")
    assert spec is not None
    assert spec.argv == [
        "script.py",
        "--flag",
        "two words",
    ]
    assert parse_launch_spec("") is None
    assert parse_launch_spec("'unterminated") is None

    home_script = Path.home() / "demo.py"
    expanded = _expand_tilde("~/demo.py --x")
    assert expanded.startswith(str(home_script))
    assert _expand_tilde("plain.py") == "plain.py"
    assert _relative_time(time.time() - 3700) == "1h ago"

    picker = LaunchPicker(ctx=make_context())
    picker._entries = []
    picker._files = []
    file_path = tmp_path / "demo.py"
    file_path.write_text("print('ok')\n", encoding="utf-8")

    picker._files = [DiscoveredFile(path=str(file_path), boost=True)]
    rows = picker._build_rows("")
    assert rows[0].kind == "file"
    assert rows[0].command == str(file_path)


def test_launch_parse_uv_run_console_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    bin_dir = _venv_script_dir(tmp_path)
    bin_dir.mkdir(parents=True)
    script = bin_dir / "traffic-ledger"
    script.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    spec = parse_launch_spec("uv run traffic-ledger --port 8077")

    assert spec is not None
    assert spec.argv == [str(script.resolve()), "--port", "8077"]
    assert spec.debugpy_prefix == ["uv", "run", "--with", "debugpy", "python"]
    assert spec.cwd == str(tmp_path)


def test_launch_parse_uv_directory_run_console_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "svc"
    bin_dir = _venv_script_dir(project)
    bin_dir.mkdir(parents=True)
    script = bin_dir / "traffic-ledger"
    script.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    spec = parse_launch_spec("uv --directory svc run traffic-ledger --host 127.0.0.1")

    assert spec is not None
    assert spec.argv == [str(script.resolve()), "--host", "127.0.0.1"]
    assert spec.debugpy_prefix == [
        "uv",
        "--directory",
        str(project),
        "run",
        "--with",
        "debugpy",
        "python",
    ]
    assert spec.cwd == str(project)


def test_launch_parse_uv_project_preserves_caller_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "svc"
    bin_dir = _venv_script_dir(project)
    bin_dir.mkdir(parents=True)
    script = bin_dir / "traffic-ledger"
    script.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    spec = parse_launch_spec("uv --project svc run traffic-ledger --host 127.0.0.1")

    assert spec is not None
    assert spec.argv == [str(script.resolve()), "--host", "127.0.0.1"]
    assert spec.debugpy_prefix == [
        "uv",
        "--project",
        str(project),
        "run",
        "--with",
        "debugpy",
        "python",
    ]
    assert spec.cwd == str(tmp_path)


def test_launch_parse_uv_run_preserves_run_options_before_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    bin_dir = _venv_script_dir(tmp_path)
    bin_dir.mkdir(parents=True)
    script = bin_dir / "traffic-ledger"
    script.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    spec = parse_launch_spec("uv run --with rich --python 3.14 traffic-ledger --port 8077")

    assert spec is not None
    assert spec.argv == [str(script.resolve()), "--port", "8077"]
    assert spec.debugpy_prefix == [
        "uv",
        "run",
        "--with",
        "rich",
        "--python",
        "3.14",
        "--with",
        "debugpy",
        "python",
    ]
    assert spec.cwd == str(tmp_path)


def test_launch_parse_uv_run_requires_synced_console_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert parse_launch_spec("uv run missing-command") is None
