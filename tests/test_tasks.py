from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from textual.widgets import DataTable, Static

from tests.support import RecordingHost, SingleWidgetApp, make_context
from yathaavat.app.tasks import TasksPanel, _name_cell, _state_cell, _status_message
from yathaavat.core import (
    SESSION_STORE,
    TaskCaptureStatus,
    TaskGraphInfo,
    TaskInfo,
    TaskNode,
    TaskStackFrame,
    TaskState,
    TaskViewMode,
)


def test_tasks_panel_renders_status_toggle_and_local_activation(tmp_path: Path) -> None:
    async def run() -> None:
        host = RecordingHost()
        ctx = make_context(host=host)
        store = ctx.services.get(SESSION_STORE)
        source = tmp_path / "tasks.py"
        source.write_text("async def main(): pass\n", encoding="utf-8")
        task = TaskInfo(
            id="task-1",
            name="main-task",
            state=TaskState.PENDING,
            coroutine="main",
            stack=(TaskStackFrame(name="main", path=str(source), line=1),),
            awaiting=("task-2",),
        )
        graph = TaskGraphInfo(
            tasks=(task,),
            roots=(TaskNode(task_id="task-1"),),
            status=TaskCaptureStatus.OK,
        )

        app = SingleWidgetApp(lambda: TasksPanel(ctx=ctx))
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = cast(TasksPanel, app.widget)
            assert _status_message(None) == "Pause to capture tasks."
            assert _name_cell(task) == "main-task"
            assert "pending" in _state_cell(task).plain

            store.update(task_graph=graph, selected_task_id="task-1")
            await pilot.pause()
            assert "1 task" in str(panel.query_one("#tasks_status", Static).content)
            assert panel.query_one("#tasks_table", DataTable).row_count == 1
            panel.action_toggle_mode()
            await pilot.pause()
            assert store.snapshot().task_view_mode is TaskViewMode.TREE

            await panel._activate_task(task)
            snap = store.snapshot()
            assert (snap.selected_task_id, snap.source_path, snap.source_line) == (
                "task-1",
                str(source),
                1,
            )

    asyncio.run(run())
