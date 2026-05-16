from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from tests.support import RecordingHost, make_context
from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    BreakpointInfo,
    FrameInfo,
    SessionState,
    SessionStore,
    TaskCaptureStatus,
    TaskGraphInfo,
    ThreadInfo,
    VariableInfo,
    WatchInfo,
)
from yathaavat.plugins.debugpy import (
    DebugpyPlugin,
    DebugpySessionManager,
    _as_list,
    _body,
    _is_pyruntime_lookup_failure,
    _is_user_path,
    _parse_variables,
)


class _TestDap:
    def __init__(self, responses: dict[str, list[dict[str, object]]] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[tuple[str, dict[str, object], float | None]] = []
        self.closed = False

    async def request(
        self, command: str, arguments: dict[str, object], timeout_s: float | None = None
    ) -> dict[str, object]:
        self.requests.append((command, arguments, timeout_s))
        items = self.responses.get(command, [])
        if items:
            return items.pop(0)
        return {"body": {}}

    async def close(self) -> None:
        self.closed = True


def _manager(store: SessionStore | None = None) -> DebugpySessionManager:
    return DebugpySessionManager(store=store or SessionStore(), host=RecordingHost())


def _set_dap(manager: DebugpySessionManager, dap: _TestDap | None) -> None:
    cast(Any, manager)._dap = dap


def test_response_helpers_ignore_malformed_payloads() -> None:
    assert _body({"body": {"ok": True}}) == {"ok": True}
    assert _body({"body": "bad"}) == {}
    assert _as_list([1, 2]) == [1, 2]
    assert _as_list("bad") == []
    assert _parse_variables(
        [
            {"name": "x", "value": "1", "type": "int", "variablesReference": 7},
            {"name": "missing-value"},
            "bad",
        ]
    ) == [VariableInfo(name="x", value="1", type="int", variables_reference=7)]


def test_pyruntime_lookup_detection_walks_exception_causes() -> None:
    root = RuntimeError("Failed to find the PyRuntime section")
    wrapped = RuntimeError("outer")
    wrapped.__cause__ = root

    assert _is_pyruntime_lookup_failure(wrapped) is True
    assert _is_pyruntime_lookup_failure(RuntimeError("other")) is False


def test_is_user_path_rejects_synthetic_and_external_paths(tmp_path: Path) -> None:
    assert _is_user_path("<string>") is False
    assert _is_user_path(str(tmp_path / "outside.py")) is False
    assert _is_user_path(str(Path.cwd() / "src" / "yathaavat" / "cli.py")) is True


def test_resume_and_stepping_commands_use_selected_thread() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            threads=(ThreadInfo(id=9, name="main"),),
            selected_thread_id=9,
            frames=(FrameInfo(id=1, name="main", path="/repo/app.py", line=1),),
            locals=(VariableInfo(name="x", value="1"),),
        )
        manager = _manager(store)
        dap = _TestDap()
        _set_dap(manager, dap)

        await manager.resume()
        await manager.pause()
        await manager.step_over()
        await manager.step_in()
        await manager.step_out()

        assert [req[0] for req in dap.requests] == [
            "continue",
            "pause",
            "next",
            "stepIn",
            "stepOut",
        ]
        snap = store.snapshot()
        assert snap.state is SessionState.RUNNING
        assert snap.frames == ()
        assert snap.locals == ()

    asyncio.run(run())


def test_select_thread_requires_paused_state_and_known_thread() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(state=SessionState.RUNNING, threads=(ThreadInfo(id=1, name="main"),))
        manager = _manager(store)

        with pytest.raises(RuntimeError, match="PAUSED"):
            await manager.select_thread(1)

        store.update(state=SessionState.PAUSED)
        with pytest.raises(ValueError, match="Unknown thread"):
            await manager.select_thread(2)

    asyncio.run(run())


def test_refresh_threads_frames_and_locals_choose_user_frame() -> None:
    async def run() -> None:
        source = str(Path.cwd() / "src" / "yathaavat" / "cli.py")
        store = SessionStore()
        manager = _manager(store)
        dap = _TestDap(
            {
                "threads": [
                    {
                        "body": {
                            "threads": [
                                {"id": 3, "name": "worker"},
                                {"id": 1, "name": "main"},
                            ]
                        }
                    }
                ],
                "stackTrace": [
                    {
                        "body": {
                            "stackFrames": [
                                {
                                    "id": 10,
                                    "name": "stdlib",
                                    "line": 1,
                                    "source": {"path": "/opt/python/lib.py"},
                                },
                                {
                                    "id": 11,
                                    "name": "main",
                                    "line": 5,
                                    "source": {"path": source},
                                },
                            ]
                        }
                    }
                ],
                "scopes": [{"body": {"scopes": [{"name": "Locals", "variablesReference": 99}]}}],
                "variables": [
                    {
                        "body": {
                            "variables": [
                                {
                                    "name": "answer",
                                    "value": "42",
                                    "type": "int",
                                    "variablesReference": 0,
                                }
                            ]
                        }
                    }
                ],
            }
        )
        _set_dap(manager, dap)

        await manager._refresh_threads()
        await manager._refresh_frames(1)

        snap = store.snapshot()
        assert snap.threads == (ThreadInfo(id=1, name="main"), ThreadInfo(id=3, name="worker"))
        assert snap.selected_thread_id == 1
        assert snap.selected_frame_id == 11
        assert snap.source_path == source
        assert snap.locals == (VariableInfo(name="answer", value="42", type="int"),)

    asyncio.run(run())


def test_evaluate_variants_include_frame_and_transcript() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(selected_frame_id=4, state=SessionState.PAUSED)
        manager = _manager(store)
        dap = _TestDap(
            {
                "evaluate": [
                    {"body": {"result": "3"}},
                    {"body": {"result": "quiet"}},
                ]
            }
        )
        _set_dap(manager, dap)

        assert await manager.evaluate("1 + 2") == "3"
        assert await manager.evaluate_silent("secret") == "quiet"

        assert dap.requests[0][1] == {"expression": "1 + 2", "context": "repl", "frameId": 4}
        assert dap.requests[1][1] == {"expression": "secret", "context": "watch", "frameId": 4}
        assert ">>> 1 + 2\n3" in store.snapshot().transcript

    asyncio.run(run())


def test_completion_falls_back_to_variables_for_attribute_chain() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            selected_frame_id=4,
            locals=(
                VariableInfo(name="order", value="{...}", type="Order", variables_reference=8),
            ),
        )
        manager = _manager(store)
        dap = _TestDap(
            {
                "completions": [{"body": {"targets": []}}],
                "variables": [
                    {
                        "body": {
                            "variables": [
                                {"name": "subtotal", "value": "10", "type": "Decimal"},
                                {"name": "__class__", "value": "Order", "type": "type"},
                                {"name": "not valid", "value": "x"},
                            ]
                        }
                    }
                ],
            }
        )
        _set_dap(manager, dap)

        items = await manager.complete("order.s", cursor=len("order.s"))

        assert [item.label for item in items] == ["subtotal"]
        assert items[0].replace_start == len("order.")
        assert items[0].replace_length == 1

    asyncio.run(run())


def test_refresh_tasks_reports_unavailable_without_pause_or_dap() -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _manager(store)

        await manager.refresh_tasks()
        assert store.snapshot().task_graph == TaskGraphInfo(
            status=TaskCaptureStatus.UNAVAILABLE,
            message="Pause the target to capture tasks.",
        )

        store.update(state=SessionState.PAUSED)
        await manager.refresh_tasks()
        assert store.snapshot().task_graph == TaskGraphInfo(
            status=TaskCaptureStatus.UNAVAILABLE,
            message="No active DAP connection.",
        )

    asyncio.run(run())


def test_select_task_updates_selection_and_source_from_task_stack(tmp_path: Path) -> None:
    async def run() -> None:
        from yathaavat.core import TaskInfo, TaskStackFrame, TaskState

        source = tmp_path / "tasks.py"
        source.write_text("async def main(): pass\n", encoding="utf-8")
        store = SessionStore()
        manager = _manager(store)
        store.update(
            source_path="/previous.py",
            source_line=99,
            task_graph=TaskGraphInfo(
                tasks=(
                    TaskInfo(
                        id="t1",
                        name="main",
                        state=TaskState.PENDING,
                        coroutine="main",
                        stack=(TaskStackFrame(name="main", path=str(source), line=1),),
                    ),
                ),
                status=TaskCaptureStatus.OK,
            ),
        )

        await manager.select_task("t1")
        assert (store.snapshot().selected_task_id, store.snapshot().source_path) == (
            "t1",
            str(source),
        )
        await manager.select_task("missing")
        assert store.snapshot().selected_task_id == "missing"

    asyncio.run(run())


def test_offline_breakpoint_config_and_toggle_keep_store_sorted(tmp_path: Path) -> None:
    async def run() -> None:
        first = tmp_path / "b.py"
        second = tmp_path / "a.py"
        first.write_text("print('b')\n", encoding="utf-8")
        second.write_text("print('a')\n", encoding="utf-8")
        store = SessionStore()
        manager = _manager(store)

        await manager.set_breakpoint_config(
            str(first),
            2,
            condition="x > 1",
            hit_condition="3",
            log_message="x={x}",
        )
        await manager.toggle_breakpoint(str(second), 1)
        await manager.toggle_breakpoint(str(first), 2)

        snap = store.snapshot()
        assert snap.breakpoints == (
            BreakpointInfo(
                path=str(second.resolve()),
                line=1,
                verified=None,
                message="queued",
            ),
        )
        assert "Breakpoint removed: b.py:2" in snap.transcript[-1]

    asyncio.run(run())


def test_set_breakpoints_normalises_adapter_lines_and_source_cursor(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "main.py"
        source.write_text("\nprint('x')\n", encoding="utf-8")
        store = SessionStore()
        store.update(source_path=str(source.resolve()), source_line=1, source_col=1)
        manager = _manager(store)
        dap = _TestDap(
            {
                "setBreakpoints": [
                    {"body": {"breakpoints": [{"line": 2, "verified": True, "message": "moved"}]}}
                ]
            }
        )
        _set_dap(manager, dap)

        await manager.toggle_breakpoint(str(source), 1)

        snap = store.snapshot()
        assert snap.source_line == 2
        assert snap.breakpoints == (
            BreakpointInfo(path=str(source.resolve()), line=2, verified=True, message="moved"),
        )
        assert manager._breakpoints == {
            str(source.resolve()): {2: manager._breakpoints[str(source.resolve())][2]}
        }

    asyncio.run(run())


def test_run_to_cursor_uses_temporary_breakpoint_and_clears_on_hit(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "main.py"
        source.write_text("print('x')\n", encoding="utf-8")
        path = str(source.resolve())
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            selected_thread_id=1,
            threads=(ThreadInfo(id=1, name="main"),),
        )
        manager = _manager(store)
        dap = _TestDap({"setBreakpoints": [{"body": {"breakpoints": [{"line": 1}]}}]})
        _set_dap(manager, dap)

        await manager.run_to_cursor(path, 1)
        store.update(state=SessionState.PAUSED, source_path=path, source_line=1)
        await manager._run_to_cursor_maybe_complete()

        commands = [r[0] for r in dap.requests]
        assert commands == ["setBreakpoints", "continue", "setBreakpoints"]
        assert "Run to cursor reached: main.py:1" in store.snapshot().transcript[-1]

    asyncio.run(run())


def test_hard_disconnect_preserves_watch_expressions_and_queued_breakpoints(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "main.py"
        source.write_text("print('x')\n", encoding="utf-8")
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            pid=123,
            threads=(ThreadInfo(id=1, name="main"),),
            selected_thread_id=1,
            frames=(FrameInfo(id=1, name="main", path=str(source), line=1),),
            selected_frame_id=1,
            watches=(WatchInfo(expression="x", value="42", changed=True),),
            breakpoints=(BreakpointInfo(path=str(source), line=1, verified=True),),
            task_graph=TaskGraphInfo(status=TaskCaptureStatus.OK),
            selected_task_id="t1",
        )
        manager = _manager(store)
        dap = _TestDap()
        _set_dap(manager, dap)

        await manager._hard_disconnect()

        snap = store.snapshot()
        assert dap.closed is True
        assert snap.state is SessionState.DISCONNECTED
        assert snap.watches == (WatchInfo(expression="x"),)
        assert snap.breakpoints == (
            BreakpointInfo(path=str(source), line=1, verified=None, message="queued"),
        )
        assert snap.task_graph is None
        assert snap.selected_task_id is None

    asyncio.run(run())


def test_debugpy_plugin_reuses_existing_store_and_registers_commands() -> None:
    ctx = make_context()
    DebugpyPlugin().register(ctx)

    assert ctx.services.get(SESSION_STORE) is not None
    assert ctx.services.get(SESSION_MANAGER) is not None
    assert {cmd.spec.id for cmd in ctx.commands.all()} == {
        "session.connect",
        "session.launch",
        "session.disconnect",
        "session.terminate",
    }
