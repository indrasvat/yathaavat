from __future__ import annotations

import asyncio
from pathlib import Path

from tests.support import RecordingHost, RecordingManager, make_context
from yathaavat.core import (
    SESSION_STORE,
    AppContext,
    BreakpointInfo,
    FrameInfo,
    SessionState,
    Slot,
    TaskViewMode,
    ThreadInfo,
)
from yathaavat.plugins.builtin import plugin


def _registered_context(
    *, manager: object | None = None, host: RecordingHost | None = None
) -> AppContext:
    ctx = make_context(host=host, manager=manager)
    plugin().register(ctx)
    return ctx


def test_builtin_registers_expected_commands_and_widget_slots() -> None:
    ctx = _registered_context()

    command_ids = {cmd.spec.id for cmd in ctx.commands.all()}
    assert {
        "app.quit",
        "debug.continue",
        "debug.run_to_cursor",
        "source.jump_to_exec",
        "tasks.refresh",
        "tasks.toggle_mode",
    } <= command_ids

    widget_ids = {widget.id for slot in Slot for widget in ctx.widgets.contributions_for(slot)}
    assert {"builtin.source", "builtin.tasks", "builtin.exception", "builtin.console"} <= widget_ids


def test_debug_commands_call_session_manager_and_report_failures() -> None:
    manager = RecordingManager(fail={"step_in": RuntimeError("adapter is busy")})
    host = RecordingHost()
    ctx = _registered_context(manager=manager, host=host)

    async def run() -> None:
        await ctx.commands.get("debug.continue").run()
        await ctx.commands.get("debug.pause").run()
        await ctx.commands.get("debug.step_over").run()
        await ctx.commands.get("debug.step_in").run()

    asyncio.run(run())

    assert ("resume", ()) in manager.calls
    assert ("pause", ()) in manager.calls
    assert ("step_over", ()) in manager.calls
    assert host.notifications[-1][0] == "adapter is busy"


def test_debug_commands_without_session_report_prototype_notifications() -> None:
    host = RecordingHost()
    ctx = _registered_context(host=host)

    async def run() -> None:
        for command_id in (
            "debug.continue",
            "debug.pause",
            "debug.step_over",
            "debug.step_in",
            "debug.step_out",
            "debug.run_to_cursor",
            "breakpoint.toggle",
        ):
            await ctx.commands.get(command_id).run()

    asyncio.run(run())

    assert [message for message, _timeout in host.notifications] == [
        "continue (prototype)",
        "pause (prototype)",
        "step over (prototype)",
        "step in (prototype)",
        "step out (prototype)",
        "run to cursor (prototype)",
        "toggle breakpoint (prototype)",
    ]


def test_breakpoint_toggle_prefers_source_cursor_then_selected_frame(tmp_path: Path) -> None:
    manager = RecordingManager()
    ctx = _registered_context(manager=manager)
    store = ctx.services.get(SESSION_STORE)
    source = tmp_path / "app.py"
    source.write_text("print('x')\n", encoding="utf-8")

    async def run() -> None:
        store.update(source_path=str(source), source_line=1)
        await ctx.commands.get("breakpoint.toggle").run()

        store.update(
            source_path=None,
            source_line=None,
            frames=(FrameInfo(id=7, name="main", path=str(source), line=1),),
            selected_frame_id=7,
        )
        await ctx.commands.get("breakpoint.toggle").run()

    asyncio.run(run())

    assert manager.calls == [
        ("toggle_breakpoint", (str(source), 1)),
        ("toggle_breakpoint", (str(source), 1)),
    ]


def test_run_to_cursor_guardrails_and_success_path(tmp_path: Path) -> None:
    manager = RecordingManager()
    host = RecordingHost()
    ctx = _registered_context(manager=manager, host=host)
    store = ctx.services.get(SESSION_STORE)
    source = tmp_path / "worker.py"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")

    async def run() -> None:
        await ctx.commands.get("debug.run_to_cursor").run()
        store.update(state=SessionState.PAUSED)
        await ctx.commands.get("debug.run_to_cursor").run()
        store.update(
            source_path=str(source),
            source_line=2,
            frames=(FrameInfo(id=1, name="main", path=str(source), line=1),),
            selected_frame_id=1,
        )
        await ctx.commands.get("debug.run_to_cursor").run()

    asyncio.run(run())

    assert [n[0] for n in host.notifications[:2]] == [
        "Run to cursor requires PAUSED state.",
        "No source location selected.",
    ]
    assert manager.calls[-1] == ("run_to_cursor", (str(source), 2))


def test_run_to_cursor_reports_same_line_unsupported_backend_and_failures(
    tmp_path: Path,
) -> None:
    source = tmp_path / "worker.py"
    source.write_text("one\ntwo\n", encoding="utf-8")

    same_line_host = RecordingHost()
    same_line_manager = RecordingManager()
    same_line_ctx = _registered_context(manager=same_line_manager, host=same_line_host)
    same_line_ctx.services.get(SESSION_STORE).update(
        state=SessionState.PAUSED,
        source_path=str(source),
        source_line=1,
        frames=(FrameInfo(id=1, name="main", path=str(source), line=1),),
        selected_frame_id=1,
    )
    asyncio.run(same_line_ctx.commands.get("debug.run_to_cursor").run())
    assert same_line_host.notifications[-1][0].startswith("Move the Source cursor")
    assert same_line_manager.calls == []

    unsupported_host = RecordingHost()
    unsupported_ctx = _registered_context(manager=object(), host=unsupported_host)
    unsupported_ctx.services.get(SESSION_STORE).update(
        state=SessionState.PAUSED,
        source_path=str(source),
        source_line=2,
    )
    asyncio.run(unsupported_ctx.commands.get("debug.run_to_cursor").run())
    assert (
        unsupported_host.notifications[-1][0] == "Run to cursor is not supported by this backend."
    )

    failure_host = RecordingHost()
    failure_manager = RecordingManager(fail={"run_to_cursor": RuntimeError("adapter rejected")})
    failure_ctx = _registered_context(manager=failure_manager, host=failure_host)
    failure_ctx.services.get(SESSION_STORE).update(
        state=SessionState.PAUSED,
        source_path=str(source),
        source_line=2,
    )
    asyncio.run(failure_ctx.commands.get("debug.run_to_cursor").run())
    assert failure_host.notifications[-1][0] == "adapter rejected"


def test_jump_to_execution_updates_source_only_when_paused(tmp_path: Path) -> None:
    host = RecordingHost()
    ctx = _registered_context(host=host)
    store = ctx.services.get(SESSION_STORE)
    source = tmp_path / "main.py"
    source.write_text("print('ok')\n", encoding="utf-8")

    store.update(frames=(FrameInfo(id=9, name="main", path=str(source), line=1),))
    asyncio.run(ctx.commands.get("source.jump_to_exec").run())
    assert host.notifications[-1][0] == "Jump to execution requires PAUSED state."

    store.update(state=SessionState.PAUSED, selected_frame_id=9)
    asyncio.run(ctx.commands.get("source.jump_to_exec").run())
    snap = store.snapshot()
    assert (snap.source_path, snap.source_line, snap.source_col) == (str(source), 1, 1)


def test_jump_to_execution_reports_missing_paused_frame() -> None:
    host = RecordingHost()
    ctx = _registered_context(host=host)
    ctx.services.get(SESSION_STORE).update(
        state=SessionState.PAUSED,
        frames=(FrameInfo(id=9, name="main", path=None, line=None),),
        selected_frame_id=9,
    )

    asyncio.run(ctx.commands.get("source.jump_to_exec").run())

    assert host.notifications[-1][0] == "No execution frame."


def test_task_commands_refresh_and_toggle_mode() -> None:
    manager = RecordingManager()
    ctx = _registered_context(manager=manager)
    store = ctx.services.get(SESSION_STORE)

    async def run() -> None:
        await ctx.commands.get("tasks.refresh").run()
        await ctx.commands.get("tasks.toggle_mode").run()
        await ctx.commands.get("tasks.toggle_mode").run()

    asyncio.run(run())

    assert manager.calls == [("refresh_tasks", ())]
    assert store.snapshot().task_view_mode is TaskViewMode.FLAT


def test_task_refresh_without_capable_manager_notifies() -> None:
    host = RecordingHost()
    ctx = _registered_context(host=host)

    asyncio.run(ctx.commands.get("tasks.refresh").run())

    assert host.notifications[-1][0] == "Task capture unavailable on this backend."


def test_task_refresh_reports_backend_failures() -> None:
    host = RecordingHost()
    manager = RecordingManager(fail={"refresh_tasks": RuntimeError("task capture failed")})
    ctx = _registered_context(manager=manager, host=host)

    asyncio.run(ctx.commands.get("tasks.refresh").run())

    assert manager.calls == [("refresh_tasks", ())]
    assert host.notifications[-1][0] == "task capture failed"


def test_quit_shuts_down_session_before_exiting() -> None:
    manager = RecordingManager()
    host = RecordingHost()
    ctx = _registered_context(manager=manager, host=host)

    asyncio.run(ctx.commands.get("app.quit").run())

    assert manager.calls == [("shutdown", ())]
    assert host.exited is True


def test_quit_reports_shutdown_failure_but_still_exits() -> None:
    manager = RecordingManager(fail={"shutdown": RuntimeError("shutdown failed")})
    host = RecordingHost()
    ctx = _registered_context(manager=manager, host=host)

    asyncio.run(ctx.commands.get("app.quit").run())

    assert manager.calls == [("shutdown", ())]
    assert host.notifications[-1][0] == "shutdown failed"
    assert host.exited is True


def test_source_and_dialog_commands_delegate_to_host() -> None:
    host = RecordingHost()
    ctx = _registered_context(host=host)

    asyncio.run(ctx.commands.get("source.find").run())
    asyncio.run(ctx.commands.get("source.goto").run())
    asyncio.run(ctx.commands.get("watch.add").run())
    asyncio.run(ctx.commands.get("breakpoint.add").run())
    asyncio.run(ctx.commands.get("view.zoom").run())
    asyncio.run(ctx.commands.get("view.locals").run())
    asyncio.run(ctx.commands.get("view.locals.filter").run())
    asyncio.run(ctx.commands.get("view.locals.expand").run())
    asyncio.run(ctx.commands.get("view.locals.edit").run())

    assert host.source_find_opens == 1
    assert len(host.screens) == 3
    assert host.zooms == 1
    assert host.locals_focuses == 1
    assert host.locals_filter_focuses == 1
    assert host.local_expands == 1
    assert host.local_edits == 1


def test_breakpoint_toggle_reports_missing_location() -> None:
    host = RecordingHost()
    manager = RecordingManager()
    ctx = _registered_context(manager=manager, host=host)
    store = ctx.services.get(SESSION_STORE)
    store.update(
        frames=(FrameInfo(id=1, name="main", path=None, line=None),),
        breakpoints=(BreakpointInfo(path="/tmp/a.py", line=3),),
        threads=(ThreadInfo(id=1, name="MainThread"),),
    )

    asyncio.run(ctx.commands.get("breakpoint.toggle").run())

    assert host.notifications[-1][0] == "No source location for breakpoint."
    assert manager.calls == []
