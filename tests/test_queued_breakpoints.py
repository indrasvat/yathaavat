from __future__ import annotations

import asyncio
from pathlib import Path

from yathaavat.core import BreakpointInfo, NullUiHost, SessionStore
from yathaavat.plugins.debugpy import DebugpySessionManager


def test_breakpoints_can_be_queued_while_disconnected(tmp_path: Path) -> None:
    store = SessionStore()
    manager = DebugpySessionManager(store=store, host=NullUiHost())

    target = tmp_path / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    resolved = str(target.resolve())

    asyncio.run(manager.toggle_breakpoint(resolved, 10))
    snap = store.snapshot()
    assert snap.breakpoints == (
        BreakpointInfo(path=resolved, line=10, verified=None, message="queued"),
    )
    assert snap.transcript and "Breakpoint queued:" in snap.transcript[-1]

    asyncio.run(manager.toggle_breakpoint(resolved, 10))
    snap = store.snapshot()
    assert snap.breakpoints == ()
    assert snap.transcript and "Breakpoint removed:" in snap.transcript[-1]
