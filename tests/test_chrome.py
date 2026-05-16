from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from tests.support import SingleWidgetApp
from yathaavat.app.chrome import (
    HelpLine,
    StatusLine,
    StatusSnapshot,
    _short_path,
    _state_style,
)


def test_status_line_renders_workspace_state_and_plugin_errors(tmp_path: Path) -> None:
    async def run() -> None:
        status = StatusLine()
        async with SingleWidgetApp(status).run_test() as pilot:
            await pilot.pause()
            status.set(
                StatusSnapshot(
                    workspace=str(tmp_path),
                    state="PAUSED",
                    pid=123,
                    python="3.14",
                    backend="debugpy",
                    zoom="Source",
                    message="ready",
                    plugin_errors=2,
                )
            )
            rendered = str(status.content)
            assert "yathaavat" in rendered
            assert "PAUSED" in rendered
            assert "PID 123" in rendered
            assert "ready" in rendered

        help_line = HelpLine()
        async with SingleWidgetApp(help_line).run_test() as pilot:
            await pilot.pause()
            help_line.set_text("F5 continue")
            assert str(help_line.content) == "F5 continue"

    asyncio.run(run())
    assert _state_style("RUNNING").bold is True
    assert _state_style("other").fg == "#93a4c7"
    assert _short_path(cast(Any, 123)) == "123"
