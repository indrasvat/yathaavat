from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from yathaavat.core import BreakpointInfo, NullUiHost, SessionState, SessionStore
from yathaavat.core.dap import DapClient
from yathaavat.plugins.debugpy import DebugpySessionManager


class _TestDebugpySessionManager(DebugpySessionManager):
    def __init__(self, store: SessionStore) -> None:
        super().__init__(store=store, host=NullUiHost())
        self._dap = cast(DapClient, object())
        self.set_breakpoints_calls: list[tuple[str, tuple[int, ...]]] = []

    async def _set_breakpoints(self, path: str, lines: list[int]) -> None:
        self.set_breakpoints_calls.append((path, tuple(lines)))
        existing = tuple(bp for bp in self.store.snapshot().breakpoints if bp.path != path)
        updated = tuple(
            BreakpointInfo(path=path, line=line, verified=True, message=None) for line in lines
        )
        self.store.update(
            breakpoints=tuple(sorted((*existing, *updated), key=lambda b: (b.path, b.line)))
        )

    async def resume(self) -> None:
        self.store.update(state=SessionState.RUNNING)


def test_run_to_cursor_adds_temporary_breakpoint_and_clears_on_hit(tmp_path: Path) -> None:
    store = SessionStore()
    manager = _TestDebugpySessionManager(store)

    target = tmp_path / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    path = str(target.resolve())

    asyncio.run(manager.run_to_cursor(path, 10))
    assert manager._run_to_cursor_target == (path, 10)
    assert manager._run_to_cursor_added is True
    assert store.snapshot().state == SessionState.RUNNING
    assert store.snapshot().breakpoints == (
        BreakpointInfo(path=path, line=10, verified=True, message=None),
    )

    # Stop somewhere else first; do not clear.
    store.update(state=SessionState.PAUSED, source_path=path, source_line=12)
    asyncio.run(manager._run_to_cursor_maybe_complete())
    assert store.snapshot().breakpoints == (
        BreakpointInfo(path=path, line=10, verified=True, message=None),
    )

    # Now stop at target; clear temporary breakpoint.
    store.update(state=SessionState.PAUSED, source_path=path, source_line=10)
    asyncio.run(manager._run_to_cursor_maybe_complete())
    assert store.snapshot().breakpoints == ()
    assert manager._run_to_cursor_target is None


def test_run_to_cursor_does_not_remove_existing_breakpoint(tmp_path: Path) -> None:
    store = SessionStore()
    manager = _TestDebugpySessionManager(store)

    target = tmp_path / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    path = str(target.resolve())

    manager._breakpoints[path] = {10}
    store.update(breakpoints=(BreakpointInfo(path=path, line=10, verified=True, message=None),))

    asyncio.run(manager.run_to_cursor(path, 10))
    assert manager._run_to_cursor_target == (path, 10)
    assert manager._run_to_cursor_added is False

    store.update(state=SessionState.PAUSED, source_path=path, source_line=10)
    asyncio.run(manager._run_to_cursor_maybe_complete())
    assert store.snapshot().breakpoints == (
        BreakpointInfo(path=path, line=10, verified=True, message=None),
    )
