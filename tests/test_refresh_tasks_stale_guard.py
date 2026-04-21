from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import cast

from yathaavat.core import NullUiHost, SessionState, SessionStore
from yathaavat.core.dap.client import DapClient
from yathaavat.plugins.debugpy import DebugpySessionManager

JsonObject = dict[str, object]
SideEffect = Callable[[str, JsonObject], Awaitable[JsonObject]]


class _FakeDap:
    def __init__(self, *, side_effect: SideEffect) -> None:
        self._side_effect = side_effect
        self.calls: list[tuple[str, JsonObject]] = []

    async def request(
        self,
        command: str,
        arguments: JsonObject | None = None,
        *,
        timeout_s: float = 15.0,
    ) -> JsonObject:
        self.calls.append((command, dict(arguments or {})))
        return await self._side_effect(command, dict(arguments or {}))


def _paused_snapshot(store: SessionStore) -> None:
    store.update(state=SessionState.PAUSED, selected_thread_id=1, selected_frame_id=7)


def test_refresh_tasks_discards_result_if_session_continued() -> None:
    store = SessionStore()
    manager = DebugpySessionManager(store=store, host=NullUiHost())
    _paused_snapshot(store)

    async def side_effect(command: str, args: JsonObject) -> JsonObject:
        # Simulate the target continuing/disconnecting while the evaluate is in
        # flight: by the time the second (CALL) request resolves, the session
        # is no longer PAUSED.
        expr = str(args.get("expression", ""))
        if "__yathaavat_collect_async_tasks__()" in expr:
            store.update(state=SessionState.RUNNING)
        return {"body": {"result": json.dumps({"status": "ok", "tasks": []})}}

    fake = _FakeDap(side_effect=side_effect)
    manager._dap = cast(DapClient, fake)

    asyncio.run(manager.refresh_tasks())

    snap = store.snapshot()
    # The stale result must not have repopulated task_graph on a running session.
    assert snap.task_graph is None


def test_refresh_tasks_discards_result_if_dap_replaced() -> None:
    store = SessionStore()
    manager = DebugpySessionManager(store=store, host=NullUiHost())
    _paused_snapshot(store)

    async def side_effect(command: str, args: JsonObject) -> JsonObject:
        # Simulate a disconnect + reconnect: the previous DAP instance is
        # swapped out while we're awaiting it.
        manager._dap = cast(DapClient, object())
        return {"body": {"result": json.dumps({"status": "ok", "tasks": []})}}

    fake = _FakeDap(side_effect=side_effect)
    manager._dap = cast(DapClient, fake)

    asyncio.run(manager.refresh_tasks())

    snap = store.snapshot()
    assert snap.task_graph is None


def test_refresh_tasks_updates_when_identity_unchanged() -> None:
    store = SessionStore()
    manager = DebugpySessionManager(store=store, host=NullUiHost())
    _paused_snapshot(store)

    async def side_effect(command: str, args: JsonObject) -> JsonObject:
        return {"body": {"result": json.dumps({"status": "ok", "tasks": []})}}

    fake = _FakeDap(side_effect=side_effect)
    manager._dap = cast(DapClient, fake)

    asyncio.run(manager.refresh_tasks())

    snap = store.snapshot()
    assert snap.task_graph is not None
    assert snap.task_graph.tasks == ()
