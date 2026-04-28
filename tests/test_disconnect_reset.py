from __future__ import annotations

import asyncio

from yathaavat.core import NullUiHost, SessionStore
from yathaavat.core.session import (
    TaskCaptureStatus,
    TaskGraphInfo,
    TaskInfo,
    TaskNode,
    TaskState,
)
from yathaavat.plugins.debugpy import DebugpySessionManager


def _graph_with_one_task() -> TaskGraphInfo:
    task = TaskInfo(
        id="0x1",
        name="worker",
        state=TaskState.PENDING,
        coroutine="run",
        path="/app/main.py",
        line=10,
    )
    return TaskGraphInfo(
        status=TaskCaptureStatus.OK,
        tasks=(task,),
        roots=(TaskNode(task_id="0x1"),),
    )


def test_hard_disconnect_clears_task_graph_and_selection() -> None:
    store = SessionStore()
    manager = DebugpySessionManager(store=store, host=NullUiHost())

    store.update(task_graph=_graph_with_one_task(), selected_task_id="0x1")
    pre = store.snapshot()
    assert pre.task_graph is not None
    assert pre.selected_task_id == "0x1"

    asyncio.run(manager.disconnect())

    post = store.snapshot()
    assert post.task_graph is None
    assert post.selected_task_id is None
