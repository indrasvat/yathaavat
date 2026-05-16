from __future__ import annotations

import time
from pathlib import Path

from tests.support import make_context
from yathaavat.app.file_discovery import DiscoveredFile
from yathaavat.app.launch import (
    LaunchPicker,
    _expand_tilde,
    _relative_time,
    parse_launch_spec,
)


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
