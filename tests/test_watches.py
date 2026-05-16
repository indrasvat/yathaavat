from __future__ import annotations

import asyncio
from typing import cast

from tests.support import RecordingHost, RecordingManager, SingleWidgetApp, make_context
from yathaavat.app.watches import WatchesPanel, WatchesTable
from yathaavat.core import SESSION_STORE, FrameInfo, SessionState, WatchInfo


def test_watches_panel_evaluates_changed_values_and_preserves_errors() -> None:
    async def run() -> None:
        manager = RecordingManager(silent_results={"total": "11"})
        ctx = make_context(manager=manager)
        store = ctx.services.get(SESSION_STORE)
        app = SingleWidgetApp(lambda: WatchesPanel(ctx=ctx))
        async with app.run_test() as pilot:
            await pilot.pause()
            store.update(
                state=SessionState.PAUSED,
                frames=(FrameInfo(id=1, name="main", path="/repo/app.py", line=3),),
                selected_frame_id=1,
                watches=(WatchInfo(expression="total", value="10"),),
            )
            await pilot.pause()
            await pilot.pause()
            watch = store.snapshot().watches[0]
            assert watch.value == "11"
            assert watch.changed is True
            assert ("evaluate_silent", ("total",)) in manager.calls

    asyncio.run(run())


def test_watches_table_delete_and_copy_value() -> None:
    async def run() -> None:
        host = RecordingHost()
        ctx = make_context(host=host)
        store = ctx.services.get(SESSION_STORE)
        app = SingleWidgetApp(lambda: WatchesTable(ctx=ctx, store=store))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(WatchesTable, app.widget)
            store.update(watches=(WatchInfo(expression="x", value="1"),))
            table.set_watches(store.snapshot().watches)
            table.move_cursor(row=0)
            table.action_copy_value()
            await table.action_delete_watch()
            assert host.notifications[-1][0] == "Deleted watch."
            assert store.snapshot().watches == ()

    asyncio.run(run())
