from __future__ import annotations

import asyncio

from yathaavat.core import BreakpointInfo, NullUiHost, SessionState, SessionStore, WatchInfo
from yathaavat.plugins.debugpy import DebugpySessionManager


def test_disconnect_clears_debuggee_state() -> None:
    async def main() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            pid=123,
            source_path="/tmp/vanilla_service.py",
            source_line=42,
            source_col=7,
            watches=(WatchInfo(expression="order.total", value="140.35", changed=True),),
            breakpoints=(BreakpointInfo(path="/tmp/vanilla_service.py", line=42, verified=True),),
        )
        mgr = DebugpySessionManager(store=store, host=NullUiHost())

        await mgr.disconnect()

        snap = store.snapshot()
        assert snap.state == SessionState.DISCONNECTED
        assert snap.pid is None
        assert snap.source_path is None
        assert snap.source_line is None
        assert snap.source_col is None
        assert snap.frames == ()
        assert snap.locals == ()
        assert snap.watches == (WatchInfo(expression="order.total"),)
        assert snap.breakpoints == (
            BreakpointInfo(
                path="/tmp/vanilla_service.py", line=42, verified=None, message="queued"
            ),
        )

    asyncio.run(main())
