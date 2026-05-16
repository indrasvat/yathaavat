from __future__ import annotations

import asyncio

from textual.widgets import ListView

from tests.support import RecordingManager, SingleWidgetApp, make_context
from yathaavat.app.threads import ThreadsPanel, _thread_rows
from yathaavat.core import SESSION_STORE, ThreadInfo


def test_thread_rows_fill_missing_names() -> None:
    assert _thread_rows((ThreadInfo(id=99, name=""),))[0].label == "Thread 99"


def test_threads_panel_selects_thread_via_manager() -> None:
    async def run() -> None:
        manager = RecordingManager()
        ctx = make_context(manager=manager)
        store = ctx.services.get(SESSION_STORE)
        threads = ThreadsPanel(ctx=ctx)
        async with SingleWidgetApp(threads).run_test() as pilot:
            await pilot.pause()
            store.update(
                threads=(ThreadInfo(id=5, name="MainThread"), ThreadInfo(id=6, name="worker")),
                selected_thread_id=6,
            )
            await pilot.pause()
            lv = threads.query_one("#threads_list", ListView)
            assert lv.index == 1
            threads._on_selected(ListView.Selected(lv, lv.children[0], 0))  # type: ignore[arg-type]
            await pilot.pause()

        assert ("select_thread", (5,)) in manager.calls

    asyncio.run(run())
