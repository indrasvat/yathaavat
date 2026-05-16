from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from textual.widgets import DataTable, ListView, RichLog, Static, TextArea, Tree

from tests.support import RecordingHost, RecordingManager, SingleWidgetApp, make_context
from yathaavat.app.exception import ExceptionPanel, _frame_label, _node_label
from yathaavat.app.panels import (
    BreakpointsPanel,
    BreakpointsTable,
    LocalsPanel,
    SourcePanel,
    StackPanel,
    TranscriptPanel,
    _format_breakpoint_details,
    _frame_rows,
    _language_for_path,
)
from yathaavat.app.tasks import TasksPanel, _name_cell, _state_cell, _status_message
from yathaavat.app.threads import ThreadsPanel, _thread_rows
from yathaavat.app.watches import WatchesPanel, WatchesTable
from yathaavat.core import (
    SESSION_STORE,
    BreakMode,
    BreakpointInfo,
    ExceptionInfo,
    ExceptionNode,
    ExceptionRelation,
    FrameInfo,
    SessionState,
    TaskCaptureStatus,
    TaskGraphInfo,
    TaskInfo,
    TaskNode,
    TaskStackFrame,
    TaskState,
    TaskViewMode,
    ThreadInfo,
    TracebackFrame,
    VariableInfo,
    WatchInfo,
)


def test_stack_and_thread_row_formatters_fill_missing_names() -> None:
    assert _frame_rows((FrameInfo(id=1, name="main", path="/tmp/app.py", line=7),))[0].label == (
        "main  app.py:7"
    )
    assert _thread_rows((ThreadInfo(id=99, name=""),))[0].label == "Thread 99"


def test_exception_and_breakpoint_labels_are_user_facing() -> None:
    frame = TracebackFrame(path="/repo/app.py", line=42, name="handler", text="raise err")
    assert _frame_label(frame) == "app.py:42  handler  # raise err"
    assert (
        _node_label(
            ExceptionNode(
                type_name="ValueError",
                message="bad",
                relation=ExceptionRelation.CAUSE,
            )
        )
        == "↳ caused by: ValueError: bad"
    )
    assert (
        _format_breakpoint_details(
            BreakpointInfo(
                path="/repo/app.py",
                line=42,
                condition="x > 1",
                hit_condition="3",
                log_message="x={x}",
                message="verified",
            )
        )
        == "log x={x}  •  if x > 1  •  hit 3  •  verified"
    )


def test_source_language_detection_is_extension_based() -> None:
    assert _language_for_path(Path("pyproject.toml")) == "toml"
    assert _language_for_path(Path("workflow.yaml")) == "yaml"
    assert _language_for_path(Path("notes.md")) == "markdown"
    assert _language_for_path(Path("script.py")) == "python"
    assert _language_for_path(Path("binary.bin")) is None


def test_transcript_panel_appends_incrementally_and_handles_reset() -> None:
    async def run() -> None:
        ctx = make_context()
        store = ctx.services.get(SESSION_STORE)
        panel = TranscriptPanel(ctx=ctx)
        async with SingleWidgetApp(panel).run_test() as pilot:
            await pilot.pause()
            store.update(transcript=("one", "two"))
            await pilot.pause()
            log = panel.query_one("#transcript_log", RichLog)
            assert len(log.lines) == 2

            store.update(transcript=("fresh",))
            await pilot.pause()
            assert len(log.lines) == 1

    asyncio.run(run())


def test_stack_and_threads_panels_select_via_manager(tmp_path: Path) -> None:
    async def run() -> None:
        manager = RecordingManager()
        ctx = make_context(manager=manager)
        store = ctx.services.get(SESSION_STORE)
        source = tmp_path / "service.py"
        source.write_text("print('hi')\n", encoding="utf-8")

        stack = StackPanel(ctx=ctx)
        async with SingleWidgetApp(stack).run_test() as pilot:
            await pilot.pause()
            store.update(
                frames=(FrameInfo(id=11, name="handler", path=str(source), line=1),),
                selected_frame_id=11,
            )
            await pilot.pause()
            lv = stack.query_one("#stack_list", ListView)
            assert len(lv.children) == 1
            stack._on_selected(ListView.Selected(lv, lv.children[0], 0))  # type: ignore[arg-type]
            await pilot.pause()

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

        assert ("select_frame", (11,)) in manager.calls
        assert ("select_thread", (5,)) in manager.calls

    asyncio.run(run())


def test_source_panel_loads_file_searches_and_handles_unreadable_source(tmp_path: Path) -> None:
    async def run() -> None:
        host = RecordingHost()
        ctx = make_context(host=host)
        store = ctx.services.get(SESSION_STORE)
        source = tmp_path / "sample.py"
        source.write_text("alpha = 1\nbeta = alpha + 1\n", encoding="utf-8")
        missing = tmp_path / "missing.py"

        panel = SourcePanel(ctx=ctx)
        async with SingleWidgetApp(panel).run_test() as pilot:
            await pilot.pause()
            store.update(
                frames=(FrameInfo(id=1, name="main", path=str(source), line=2),),
                selected_frame_id=1,
                source_path=str(source),
                source_line=2,
                source_col=1,
            )
            await pilot.pause()
            header = panel.query_one("#source_header", Static)
            editor = panel.query_one("#source_view", TextArea)
            assert str(source) in str(header.content)
            assert "beta = alpha" in editor.text

            panel.open_find()
            panel._find_in_source("alpha", direction="next", include_current=True)
            await pilot.pause()
            assert "/2" in str(panel.query_one("#find_status", Static).content)

            panel._find_in_source("missing", direction="next", include_current=True)
            assert str(panel.query_one("#find_status", Static).content) == "0"

            panel._close_find()
            assert panel.query_one("#find_root").styles.display == "none"

            store.update(source_path=str(missing), source_line=1)
            await pilot.pause()
            assert panel.query_one("#source_view", TextArea).text == "(unreadable source)"

    asyncio.run(run())


def test_locals_panel_expands_variables_and_reports_unsupported() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variables={7: (VariableInfo(name="child", value="2", type="int"),)}
        )
        ctx = make_context(manager=manager)
        store = ctx.services.get(SESSION_STORE)
        app = SingleWidgetApp(lambda: LocalsPanel(ctx=ctx))
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = cast(LocalsPanel, app.widget)
            store.update(
                locals=(
                    VariableInfo(name="root", value="{...}", type="dict", variables_reference=7),
                )
            )
            await pilot.pause()
            table = panel.query_one(DataTable)
            table.move_cursor(row=0)
            await panel._table.action_toggle_expand()
            await pilot.pause()
            assert table.row_count == 2
            assert ("get_variables", (7,)) in manager.calls

    asyncio.run(run())


def test_breakpoints_panel_renders_jump_and_delete_actions(tmp_path: Path) -> None:
    async def run() -> None:
        manager = RecordingManager()
        ctx = make_context(manager=manager)
        store = ctx.services.get(SESSION_STORE)
        source = tmp_path / "worker.py"
        source.write_text("print('x')\n", encoding="utf-8")

        app = SingleWidgetApp(lambda: BreakpointsPanel(ctx=ctx))
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = cast(BreakpointsPanel, app.widget)
            store.update(
                breakpoints=(BreakpointInfo(path=str(source), line=1, verified=True, message="ok"),)
            )
            await pilot.pause()
            table = panel.query_one(BreakpointsTable)
            assert table.row_count == 1
            table.move_cursor(row=0)
            table.action_jump()
            await table.action_delete_breakpoint()
            snap = store.snapshot()
            assert (snap.source_path, snap.source_line, snap.source_col) == (str(source), 1, 1)
            assert manager.calls[-1] == ("toggle_breakpoint", (str(source), 1))

    asyncio.run(run())


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


def test_exception_panel_builds_tree_and_frame_jump_falls_back_to_source(tmp_path: Path) -> None:
    async def run() -> None:
        ctx = make_context()
        store = ctx.services.get(SESSION_STORE)
        source = tmp_path / "boom.py"
        source.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        frame = TracebackFrame(path=str(source), line=1, name="main", text="raise")
        info = ExceptionInfo(
            exception_id="RuntimeError",
            break_mode=BreakMode.UNHANDLED,
            stack_trace="traceback",
            tree=ExceptionNode(type_name="RuntimeError", message="boom", frames=(frame,)),
        )

        panel = ExceptionPanel(ctx=ctx)
        async with SingleWidgetApp(panel).run_test() as pilot:
            await pilot.pause()
            store.update(exception_info=info)
            await pilot.pause()
            assert "RuntimeError" in str(panel.query_one("#exc_header", Static).content)
            tree = panel.query_one(Tree)
            branch = tree.root.children[0]
            selected_frame = branch.children[0].data
            assert isinstance(selected_frame, TracebackFrame)
            panel._tree._jump_to_frame(selected_frame)
            snap = store.snapshot()
            assert (snap.source_path, snap.source_line, snap.source_col) == (str(source), 1, 1)

    asyncio.run(run())


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
