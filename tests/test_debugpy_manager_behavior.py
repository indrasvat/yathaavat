from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest

from tests.support import RecordingHost, make_context
from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    BreakpointInfo,
    DapCapabilities,
    FrameInfo,
    ScopeInfo,
    SessionState,
    SessionStore,
    TaskCaptureStatus,
    TaskGraphInfo,
    ThreadInfo,
    VariableInfo,
    VariablePage,
    WatchInfo,
)
from yathaavat.core.dap import DapRequestError
from yathaavat.plugins.debugpy import (
    DebugpyPlugin,
    DebugpySessionManager,
    _as_list,
    _body,
    _BreakpointConfig,
    _initialize_arguments,
    _is_pyruntime_lookup_failure,
    _is_user_path,
    _launch_user_roots,
    _parse_scopes,
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
            {
                "name": "x",
                "value": "1",
                "type": "int",
                "variablesReference": 7,
                "indexedVariables": 3,
            },
            {"name": "missing-value"},
            "bad",
        ]
    ) == [
        VariableInfo(
            name="x",
            value="1",
            type="int",
            variables_reference=7,
            indexed_variables=3,
        )
    ]
    assert _parse_scopes(
        [
            {
                "name": "Globals",
                "variablesReference": 12,
                "expensive": True,
                "namedVariables": 3,
            },
            {"name": "missing-ref"},
            "bad",
        ]
    ) == (
        ScopeInfo(
            name="Globals",
            variables_reference=12,
            expensive=True,
            named_variables=3,
        ),
    )


def test_initialize_arguments_advertise_variable_paging() -> None:
    args = _initialize_arguments()

    assert args["supportsVariablePaging"] is True


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
    roots = _launch_user_roots(["/tmp/gauntlet/target/.venv/bin/tool"], cwd="/tmp/gauntlet/target")
    assert _is_user_path("/tmp/gauntlet/target/src/app.py", roots) is True
    assert _is_user_path("/tmp/gauntlet/target/.venv/bin/tool", roots) is False
    assert _is_user_path("/tmp/gauntlet/target/.venv/site-packages/click/core.py", roots) is False
    assert _is_user_path("/tmp/gauntlet/other/app.py", roots) is False
    direct_roots = _launch_user_roots([str(tmp_path / "bin" / "tool")], cwd=None)
    assert _is_user_path(str(tmp_path / "bin" / "app.py"), direct_roots) is True


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
        store.update(state=SessionState.PAUSED)
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
                "scopes": [
                    {
                        "body": {
                            "scopes": [
                                {
                                    "name": "Globals",
                                    "variablesReference": 100,
                                    "expensive": True,
                                    "namedVariables": 8,
                                },
                                {
                                    "name": "Locals",
                                    "variablesReference": 99,
                                    "namedVariables": 1,
                                },
                            ]
                        }
                    }
                ],
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
        assert snap.selected_scope_name == "Locals"
        assert snap.variables_generation == 1
        assert snap.scopes == (
            ScopeInfo(
                name="Globals",
                variables_reference=100,
                expensive=True,
                named_variables=8,
            ),
            ScopeInfo(
                name="Locals",
                variables_reference=99,
                named_variables=1,
                variables=(VariableInfo(name="answer", value="42", type="int"),),
                page=VariablePage(
                    variables=(VariableInfo(name="answer", value="42", type="int"),),
                    named_variables=1,
                ),
            ),
        )
        assert snap.locals == (VariableInfo(name="answer", value="42", type="int"),)
        assert snap.locals_reference == 99

    asyncio.run(run())


def test_refresh_frames_prefers_launched_external_target_root(tmp_path: Path) -> None:
    async def run() -> None:
        target_root = tmp_path / "target"
        user_source = target_root / "src" / "app.py"
        user_source.parent.mkdir(parents=True)
        user_source.write_text("print('boom')\n", encoding="utf-8")
        click_source = target_root / ".venv" / "site-packages" / "click" / "core.py"
        click_source.parent.mkdir(parents=True)
        click_source.write_text("raise SystemExit(2)\n", encoding="utf-8")

        store = SessionStore()
        store.update(state=SessionState.PAUSED)
        manager = _manager(store)
        manager._user_roots = _launch_user_roots(
            [str(target_root / ".venv" / "bin" / "async-ledger")],
            cwd=str(target_root),
        )
        dap = _TestDap(
            {
                "stackTrace": [
                    {
                        "body": {
                            "stackFrames": [
                                {
                                    "id": 10,
                                    "name": "main",
                                    "line": 1473,
                                    "source": {"path": str(click_source)},
                                },
                                {
                                    "id": 11,
                                    "name": "repro",
                                    "line": 61,
                                    "source": {"path": str(user_source)},
                                },
                            ]
                        }
                    }
                ],
                "scopes": [{"body": {"scopes": []}}],
            }
        )
        _set_dap(manager, dap)

        await manager._refresh_frames(1)

        snap = store.snapshot()
        assert snap.selected_frame_id == 11
        assert snap.source_path == str(user_source)

    asyncio.run(run())


def test_refresh_locals_ignores_stale_variables_after_resume() -> None:
    class BlockingVariablesDap(_TestDap):
        def __init__(self) -> None:
            super().__init__()
            self.variables_started = asyncio.Event()
            self.release_variables = asyncio.Event()

        async def request(
            self, command: str, arguments: dict[str, object], timeout_s: float | None = None
        ) -> dict[str, object]:
            self.requests.append((command, arguments, timeout_s))
            if command == "scopes":
                return {
                    "body": {
                        "scopes": [
                            {
                                "name": "Locals",
                                "variablesReference": 7,
                                "namedVariables": 1,
                            }
                        ]
                    }
                }
            if command == "variables":
                self.variables_started.set()
                await self.release_variables.wait()
                return {
                    "body": {
                        "variables": [
                            {
                                "name": "late",
                                "value": "99",
                                "type": "int",
                                "variablesReference": 0,
                            }
                        ]
                    }
                }
            return {"body": {}}

    async def run() -> None:
        store = SessionStore()
        store.update(state=SessionState.PAUSED, selected_frame_id=7)
        manager = _manager(store)
        dap = BlockingVariablesDap()
        _set_dap(manager, dap)

        refresh_task = asyncio.create_task(manager._refresh_locals(7))
        await asyncio.wait_for(dap.variables_started.wait(), timeout=1)
        generation = store.snapshot().variables_generation + 1
        store.update(
            state=SessionState.RUNNING,
            selected_frame_id=None,
            scopes=(),
            selected_scope_name=None,
            locals=(),
            locals_reference=None,
            variables_generation=generation,
        )
        dap.release_variables.set()
        await asyncio.wait_for(refresh_task, timeout=1)

        snap = store.snapshot()
        assert snap.state is SessionState.RUNNING
        assert snap.selected_frame_id is None
        assert snap.scopes == ()
        assert snap.selected_scope_name is None
        assert snap.locals == ()
        assert snap.locals_reference is None
        assert snap.variables_generation == generation

    asyncio.run(run())


def test_refresh_locals_ignores_stale_variables_after_scope_switch() -> None:
    class BlockingScopeDap(_TestDap):
        def __init__(self) -> None:
            super().__init__()
            self.variables_started = asyncio.Event()
            self.release_variables = asyncio.Event()

        async def request(
            self, command: str, arguments: dict[str, object], timeout_s: float | None = None
        ) -> dict[str, object]:
            self.requests.append((command, arguments, timeout_s))
            if command == "scopes":
                return {
                    "body": {
                        "scopes": [
                            {
                                "name": "Locals",
                                "variablesReference": 7,
                                "namedVariables": 1,
                            },
                            {
                                "name": "Globals",
                                "variablesReference": 8,
                                "namedVariables": 1,
                            },
                        ]
                    }
                }
            if command == "variables":
                self.variables_started.set()
                await self.release_variables.wait()
                return {
                    "body": {
                        "variables": [
                            {
                                "name": "late_local",
                                "value": "99",
                                "type": "int",
                                "variablesReference": 0,
                            }
                        ]
                    }
                }
            return {"body": {}}

    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            selected_frame_id=7,
            selected_scope_name="Locals",
        )
        manager = _manager(store)
        dap = BlockingScopeDap()
        _set_dap(manager, dap)

        refresh_task = asyncio.create_task(manager._refresh_locals(7))
        await asyncio.wait_for(dap.variables_started.wait(), timeout=1)
        store.update(selected_scope_name="Globals")
        dap.release_variables.set()
        await asyncio.wait_for(refresh_task, timeout=1)

        snap = store.snapshot()
        assert snap.selected_scope_name == "Globals"
        assert snap.scopes == ()
        assert snap.locals == ()
        assert snap.locals_reference is None

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


def test_completion_fallback_resolves_nested_variable_chains() -> None:
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
                                {
                                    "name": "customer",
                                    "value": "{...}",
                                    "type": "Customer",
                                    "variablesReference": 9,
                                }
                            ]
                        }
                    },
                    {
                        "body": {
                            "variables": [
                                {"name": "name", "value": "'Ada'", "type": "str"},
                                {"name": "nickname", "value": "'A'", "type": "str"},
                                {"name": "_private", "value": "1", "type": "int"},
                                {"name": "__class__", "value": "Customer", "type": "type"},
                                {"name": "not valid", "value": "x"},
                            ]
                        }
                    },
                ],
            }
        )
        _set_dap(manager, dap)

        items = await manager.complete("order.customer.n", cursor=len("order.customer.n"))

        assert [item.label for item in items] == ["name", "nickname"]
        assert items[0].replace_start == len("order.customer.")
        assert items[0].replace_length == 1
        assert dap.requests[0] == (
            "completions",
            {"text": "order.customer.n", "column": len("order.customer.n") + 1, "frameId": 4},
            1.5,
        )

    asyncio.run(run())


def test_completion_fallback_ignores_missing_or_non_expandable_roots() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            locals=(VariableInfo(name="order", value="{...}", type="Order"),),
        )
        manager = _manager(store)
        dap = _TestDap({"completions": [{"body": {"targets": []}}, {"body": {"targets": []}}]})
        _set_dap(manager, dap)

        assert await manager.complete("missing.name", cursor=len("missing.name")) == ()
        assert await manager.complete("order.name", cursor=len("order.name")) == ()
        assert [request[0] for request in dap.requests] == ["completions", "completions"]

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


def test_refresh_tasks_records_dap_errors_for_current_stop() -> None:
    class ErrorDap(_TestDap):
        async def request(
            self, command: str, arguments: dict[str, object], timeout_s: float | None = None
        ) -> dict[str, object]:
            self.requests.append((command, arguments, timeout_s))
            raise DapRequestError(
                command=command,
                message="collector failed",
                response={"success": False},
            )

    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            selected_thread_id=7,
            selected_frame_id=11,
        )
        manager = _manager(store)
        dap = ErrorDap()
        _set_dap(manager, dap)

        await manager.refresh_tasks()

        graph = store.snapshot().task_graph
        assert graph is not None
        assert graph.status is TaskCaptureStatus.ERROR
        assert "collector failed" in (graph.message or "")
        assert dap.requests[0] == (
            "evaluate",
            {
                "expression": dap.requests[0][1]["expression"],
                "context": "repl",
                "frameId": 11,
            },
            5.0,
        )

    asyncio.run(run())


def test_refresh_tasks_discards_stale_capture_after_resume() -> None:
    class BlockingTaskDap(_TestDap):
        def __init__(self) -> None:
            super().__init__()
            self.collector_started = asyncio.Event()
            self.release_collector = asyncio.Event()

        async def request(
            self, command: str, arguments: dict[str, object], timeout_s: float | None = None
        ) -> dict[str, object]:
            self.requests.append((command, arguments, timeout_s))
            expression = arguments.get("expression")
            if expression == "__yathaavat_collect_async_tasks__()":
                self.collector_started.set()
                await self.release_collector.wait()
                return {
                    "body": {
                        "result": json.dumps(
                            {"status": "empty", "tasks": [], "message": "late result"}
                        )
                    }
                }
            return {"body": {}}

    async def run() -> None:
        previous = TaskGraphInfo(
            status=TaskCaptureStatus.UNAVAILABLE,
            message="previous graph",
        )
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            selected_thread_id=7,
            selected_frame_id=11,
            task_graph=previous,
        )
        manager = _manager(store)
        dap = BlockingTaskDap()
        _set_dap(manager, dap)

        task = asyncio.create_task(manager.refresh_tasks())
        await asyncio.wait_for(dap.collector_started.wait(), timeout=1)
        store.update(state=SessionState.RUNNING)
        dap.release_collector.set()
        await asyncio.wait_for(task, timeout=1)

        assert store.snapshot().task_graph == previous

    asyncio.run(run())


def test_safe_refresh_tasks_records_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _manager(store)

        async def fail_refresh_tasks() -> None:
            raise RuntimeError("collector wrapper failed")

        monkeypatch.setattr(manager, "refresh_tasks", fail_refresh_tasks)

        await manager._safe_refresh_tasks()

        graph = store.snapshot().task_graph
        assert graph is not None
        assert graph.status is TaskCaptureStatus.ERROR
        assert graph.message == "collector wrapper failed"

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
        assert store.snapshot().transcript[-1] == (
            "Breakpoint queued: b.py:2 (if x > 1 • hit 3 • log x={x})"
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


def test_require_helpers_report_missing_dap_or_threads() -> None:
    manager = _manager()
    with pytest.raises(RuntimeError, match="No active debug session"):
        manager._require_dap()
    with pytest.raises(RuntimeError, match="No threads available"):
        manager._require_thread()

    manager.store.update(threads=(ThreadInfo(id=42, name="worker"),))
    assert manager._require_thread() == 42


def test_get_variables_and_quick_variables_handle_invalid_refs_and_failures() -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _manager(store)
        dap = _TestDap(
            {
                "variables": [
                    {
                        "body": {
                            "variables": [
                                {
                                    "name": "x",
                                    "value": "1",
                                    "type": "int",
                                    "variablesReference": 0,
                                }
                            ]
                        }
                    }
                ]
            }
        )
        _set_dap(manager, dap)

        assert await manager.get_variables(0) == ()
        assert await manager._variables_quick(-1) == ()
        assert await manager.get_variables(7) == (VariableInfo(name="x", value="1", type="int"),)

        class FailingDap(_TestDap):
            async def request(
                self, command: str, arguments: dict[str, object], timeout_s: float | None = None
            ) -> dict[str, object]:
                raise RuntimeError("no variables")

        _set_dap(manager, FailingDap())
        assert await manager._variables_quick(7) == ()

    asyncio.run(run())


def test_adapter_capabilities_are_stored_from_initialize_response() -> None:
    store = SessionStore()
    manager = _manager(store)

    manager._store_capabilities(
        {
            "body": {
                "supportsSetVariable": True,
                "supportsSetExpression": False,
            }
        }
    )

    assert store.snapshot().capabilities == DapCapabilities(
        supports_variable_paging=True,
        supports_set_variable=True,
        supports_set_expression=False,
    )


def test_get_variables_page_uses_start_count_and_filter() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(capabilities=DapCapabilities(supports_variable_paging=True))
        manager = _manager(store)
        dap = _TestDap(
            {
                "variables": [
                    {
                        "body": {
                            "variables": [
                                {
                                    "name": "[50]",
                                    "value": "item-50",
                                    "type": "str",
                                    "variablesReference": 0,
                                }
                            ]
                        }
                    }
                ]
            }
        )
        _set_dap(manager, dap)

        page = await manager.get_variables_page(7, start=50, count=25, filter="indexed")

        assert page == VariablePage(
            variables=(VariableInfo(name="[50]", value="item-50", type="str"),),
            start=50,
            count=25,
            filter="indexed",
        )
        assert dap.requests[-1] == (
            "variables",
            {
                "variablesReference": 7,
                "start": 50,
                "count": 25,
                "filter": "indexed",
            },
            None,
        )

    asyncio.run(run())


def test_get_variables_page_uses_remembered_variable_counts() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(capabilities=DapCapabilities(supports_variable_paging=True))
        manager = _manager(store)
        dap = _TestDap(
            {
                "variables": [
                    {
                        "body": {
                            "variables": [
                                {
                                    "name": "items",
                                    "value": "list[5]",
                                    "variablesReference": 7,
                                    "indexedVariables": 5,
                                }
                            ]
                        }
                    },
                    {
                        "body": {
                            "variables": [
                                {
                                    "name": "[0]",
                                    "value": "zero",
                                    "variablesReference": 0,
                                }
                            ]
                        }
                    },
                ]
            }
        )
        _set_dap(manager, dap)

        await manager.get_variables(99)
        page = await manager.get_variables_page(7, start=0, count=1)

        assert page.indexed_variables == 5
        assert page.next_start == 1

    asyncio.run(run())


def test_get_variables_page_falls_back_to_full_fetch_when_paging_unsupported() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(capabilities=DapCapabilities(supports_variable_paging=False))
        manager = _manager(store)
        dap = _TestDap({"variables": [{"body": {"variables": []}}]})
        _set_dap(manager, dap)

        await manager.get_variables_page(7, start=50, count=25, filter="indexed")

        assert dap.requests[-1] == ("variables", {"variablesReference": 7}, None)

    asyncio.run(run())


def test_refresh_locals_fetches_initial_page_only_when_supported() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            selected_frame_id=22,
            capabilities=DapCapabilities(supports_variable_paging=True),
        )
        manager = _manager(store)
        dap = _TestDap(
            {
                "scopes": [
                    {
                        "body": {
                            "scopes": [
                                {
                                    "name": "Locals",
                                    "variablesReference": 7,
                                    "namedVariables": 5000,
                                }
                            ]
                        }
                    }
                ],
                "variables": [
                    {
                        "body": {
                            "variables": [
                                {
                                    "name": f"item_{idx}",
                                    "value": str(idx),
                                    "type": "int",
                                    "variablesReference": 0,
                                }
                                for idx in range(50)
                            ]
                        }
                    }
                ],
            }
        )
        _set_dap(manager, dap)

        await manager._refresh_locals(22)

        assert dap.requests[-1] == (
            "variables",
            {"variablesReference": 7, "start": 0, "count": 50},
            None,
        )
        snap = store.snapshot()
        assert len(snap.locals) == 50
        assert snap.scopes[0].page == VariablePage(
            variables=snap.locals,
            start=0,
            count=50,
            indexed_variables=None,
            named_variables=5000,
        )
        assert snap.scopes[0].page.next_start == 50

    asyncio.run(run())


def test_refresh_locals_falls_back_to_full_fetch_when_paging_unsupported() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            selected_frame_id=22,
            capabilities=DapCapabilities(supports_variable_paging=False),
        )
        manager = _manager(store)
        dap = _TestDap(
            {
                "scopes": [
                    {
                        "body": {
                            "scopes": [
                                {
                                    "name": "Locals",
                                    "variablesReference": 7,
                                    "namedVariables": 2,
                                }
                            ]
                        }
                    }
                ],
                "variables": [
                    {
                        "body": {
                            "variables": [
                                {
                                    "name": "one",
                                    "value": "1",
                                    "variablesReference": 0,
                                },
                                {
                                    "name": "two",
                                    "value": "2",
                                    "variablesReference": 0,
                                },
                            ]
                        }
                    }
                ],
            }
        )
        _set_dap(manager, dap)

        await manager._refresh_locals(22)

        assert dap.requests[-1] == ("variables", {"variablesReference": 7}, None)
        assert len(store.snapshot().locals) == 2

    asyncio.run(run())


def test_set_variable_uses_dap_and_updates_returned_variable() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(capabilities=DapCapabilities(supports_set_variable=True))
        manager = _manager(store)
        dap = _TestDap(
            {
                "setVariable": [
                    {
                        "body": {
                            "value": "43",
                            "type": "int",
                            "variablesReference": 0,
                        }
                    }
                ]
            }
        )
        _set_dap(manager, dap)

        updated = await manager.set_variable(9, "answer", "43")

        assert updated == VariableInfo(name="answer", value="43", type="int")
        assert dap.requests[-1] == (
            "setVariable",
            {"variablesReference": 9, "name": "answer", "value": "43"},
            None,
        )

    asyncio.run(run())


def test_set_variable_reports_unsupported_capability() -> None:
    async def run() -> None:
        manager = _manager()
        _set_dap(manager, _TestDap())

        with pytest.raises(RuntimeError, match="not supported"):
            await manager.set_variable(9, "answer", "43")

    asyncio.run(run())


def test_completion_uses_dap_results_and_running_state_skips_variable_fallback() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(state=SessionState.RUNNING)
        manager = _manager(store)
        dap = _TestDap(
            {
                "completions": [
                    {
                        "body": {
                            "targets": [
                                {
                                    "label": "alpha",
                                    "text": "alpha",
                                    "start": 0,
                                    "length": 1,
                                    "type": "property",
                                }
                            ]
                        }
                    },
                    {"body": {"targets": []}},
                ]
            }
        )
        _set_dap(manager, dap)

        parsed = await manager.complete("a", cursor=1)
        assert [item.label for item in parsed] == ["alpha"]
        assert await manager.complete("order.", cursor=len("order.")) == ()

    asyncio.run(run())


def test_select_frame_missing_frame_clears_source_and_refreshes_locals() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(frames=(FrameInfo(id=1, name="main", path="/repo/app.py", line=10),))
        manager = _manager(store)
        dap = _TestDap({"scopes": [{"body": {"scopes": []}}]})
        _set_dap(manager, dap)

        await manager.select_frame(99)

        snap = store.snapshot()
        assert snap.selected_frame_id == 99
        assert snap.source_path is None
        assert snap.locals == ()
        assert snap.locals_reference is None

    asyncio.run(run())


def test_exception_info_parses_break_mode_and_handles_bad_payloads() -> None:
    async def run() -> None:
        manager = _manager()
        dap = _TestDap(
            {
                "exceptionInfo": [
                    {
                        "body": {
                            "exceptionId": "ValueError",
                            "description": "bad",
                            "breakMode": "always",
                            "details": {"stackTrace": "Traceback...\nValueError: bad"},
                        }
                    },
                    {"body": {"exceptionId": 123}},
                ]
            }
        )
        _set_dap(manager, dap)

        info = await manager.get_exception_info(1)
        assert info is not None
        assert info.exception_id == "ValueError"
        assert info.stack_trace.startswith("Traceback")
        assert await manager.get_exception_info(1) is None

        class ErrorDap(_TestDap):
            async def request(
                self, command: str, arguments: dict[str, object], timeout_s: float | None = None
            ) -> dict[str, object]:
                raise DapRequestError(
                    command="exceptionInfo",
                    message="not stopped",
                    response={"success": False},
                )

        _set_dap(manager, ErrorDap())
        assert await manager.get_exception_info(1) is None

    asyncio.run(run())


def test_fetch_exception_info_updates_only_current_exception_stop() -> None:
    async def run() -> None:
        store = SessionStore()
        store.update(
            state=SessionState.PAUSED,
            stop_reason="exception",
            selected_thread_id=3,
        )
        manager = _manager(store)
        dap = _TestDap(
            {
                "exceptionInfo": [
                    {
                        "body": {
                            "exceptionId": "RuntimeError",
                            "description": "boom",
                            "breakMode": "unhandled",
                        }
                    },
                    {
                        "body": {
                            "exceptionId": "ValueError",
                            "description": "stale",
                            "breakMode": "unhandled",
                        }
                    },
                ]
            }
        )
        _set_dap(manager, dap)

        await manager._fetch_exception_info(3)
        assert store.snapshot().exception_info is not None

        store.update(stop_reason="breakpoint")
        await manager._fetch_exception_info(3)
        assert store.snapshot().exception_info is not None

    asyncio.run(run())


def test_on_event_updates_session_state_and_filters_output() -> None:
    async def run() -> None:
        store = SessionStore()
        host = RecordingHost()
        manager = DebugpySessionManager(store=store, host=host)
        dap = _TestDap(
            {
                "threads": [{"body": {"threads": [{"id": 1, "name": "main"}]}}],
                "stackTrace": [
                    {
                        "body": {
                            "stackFrames": [
                                {
                                    "id": 5,
                                    "name": "main",
                                    "line": 1,
                                    "source": {"path": str(Path.cwd() / "pyproject.toml")},
                                }
                            ]
                        }
                    }
                ],
                "scopes": [{"body": {"scopes": []}}],
                "evaluate": [{"body": {"result": "[]"}}],
            }
        )
        _set_dap(manager, dap)

        await manager._on_event({"event": "initialized", "body": {}})
        assert manager._initialized.is_set()

        await manager._on_event({"event": "process", "body": {"systemProcessId": 123}})
        assert store.snapshot().pid == 123

        await manager._on_event(
            {"event": "output", "body": {"category": "telemetry", "output": "x"}}
        )
        await manager._on_event(
            {"event": "output", "body": {"category": "stdout", "output": "hi\n"}}
        )
        assert store.snapshot().transcript[-1] == "hi"

        await manager._on_event(
            {
                "event": "stopped",
                "body": {"reason": "breakpoint", "threadId": 1, "description": "hit"},
            }
        )
        snap = store.snapshot()
        assert snap.state is SessionState.PAUSED
        assert snap.selected_thread_id == 1
        assert snap.selected_frame_id == 5
        assert snap.stop_reason == "breakpoint"

        await manager._on_event({"event": "continued", "body": {}})
        assert store.snapshot().state is SessionState.RUNNING

    asyncio.run(run())


def test_set_breakpoints_clears_and_preserves_stronger_config_on_line_collision(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        source = tmp_path / "main.py"
        source.write_text("print('x')\n", encoding="utf-8")
        path = str(source.resolve())
        store = SessionStore()
        manager = _manager(store)
        dap = _TestDap(
            {
                "setBreakpoints": [
                    {
                        "body": {
                            "breakpoints": [
                                {"line": 10, "verified": True},
                                {"line": 10, "verified": True},
                            ]
                        }
                    },
                    {"body": {"breakpoints": []}},
                ]
            }
        )
        _set_dap(manager, dap)

        manager._breakpoints[path] = {
            1: _BreakpointConfig(condition="x > 1"),
            2: _BreakpointConfig(condition="x > 1", log_message="x={x}"),
        }
        await manager._set_breakpoints(path, [1, 2])
        assert sorted(manager._breakpoints[path]) == [10]
        assert manager._breakpoints[path][10].log_message == "x={x}"

        await manager._set_breakpoints(path, [])
        assert store.snapshot().breakpoints == ()
        assert store.snapshot().transcript[-1] == "Breakpoints cleared: main.py"

    asyncio.run(run())
