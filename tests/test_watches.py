from __future__ import annotations

import asyncio
from typing import cast

from textual.widgets import Static

from tests.support import (
    RecordingHost,
    RecordingManager,
    SingleScreenApp,
    SingleWidgetApp,
    make_context,
)
from yathaavat.app.expression import ExpressionInput
from yathaavat.app.watches import AddWatchDialog, WatchesPanel, WatchesTable
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


def test_add_watch_dialog_adds_unique_expression_and_reports_duplicates() -> None:
    async def run() -> None:
        ctx = make_context()
        store = ctx.services.get(SESSION_STORE)
        dialog = AddWatchDialog(ctx=ctx)

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            control = dialog.query_one("#watch_input", ExpressionInput)
            dialog._on_submit(ExpressionInput.Submitted(control, "total"))
            assert store.snapshot().watches == (WatchInfo(expression="total"),)
            assert str(dialog.query_one("#watch_status", Static).content) == "added"

            dialog._on_submit(ExpressionInput.Submitted(control, "total"))
            assert store.snapshot().watches == (WatchInfo(expression="total"),)
            assert str(dialog.query_one("#watch_status", Static).content) == "exists"

            dialog._on_submit(ExpressionInput.Submitted(control, ""))
            assert store.snapshot().watches == (WatchInfo(expression="total"),)

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


def test_watches_panel_cancels_when_running_and_preserves_stale_results() -> None:
    async def run() -> None:
        manager = RecordingManager(silent_results={"total": "12"})
        ctx = make_context(manager=manager)
        store = ctx.services.get(SESSION_STORE)
        app = SingleWidgetApp(lambda: WatchesPanel(ctx=ctx))
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = cast(WatchesPanel, app.widget)
            store.update(
                state=SessionState.RUNNING,
                watches=(WatchInfo(expression="total", value="10"),),
            )
            await pilot.pause()
            assert panel._eval_task is None

            store.update(
                state=SessionState.PAUSED,
                watches=(),
                frames=(FrameInfo(id=1, name="main", path="/repo/app.py", line=1),),
                selected_frame_id=1,
            )
            await pilot.pause()
            key = panel._compute_eval_key(store.snapshot())
            assert key is None
            store.update(watches=(WatchInfo(expression="total", value="10"),))
            key = panel._compute_eval_key(store.snapshot())
            assert key is not None
            store.update(state=SessionState.RUNNING)
            await panel._eval_watches(key)
            assert store.snapshot().watches == (WatchInfo(expression="total", value="10"),)

    asyncio.run(run())
