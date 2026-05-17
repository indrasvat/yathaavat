from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Static, Tree

from tests.support import SingleWidgetApp, make_context
from yathaavat.app.exception import ExceptionPanel, _frame_label, _node_label
from yathaavat.core import (
    SESSION_STORE,
    BreakMode,
    ExceptionInfo,
    ExceptionNode,
    ExceptionRelation,
    FrameInfo,
    TracebackFrame,
)


def test_exception_labels_are_user_facing() -> None:
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


def test_exception_tree_actions_copy_and_toggle_breakpoint(tmp_path: Path) -> None:
    async def run() -> None:
        from tests.support import RecordingHost, RecordingManager

        host = RecordingHost()
        manager = RecordingManager()
        ctx = make_context(host=host, manager=manager)
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
            panel._tree.action_copy_traceback()
            assert host.notifications[-1][0] == "No traceback to copy."

            store.update(exception_info=info)
            await pilot.pause()
            panel._tree.action_copy_traceback()
            assert host.notifications[-1][0] == "Copied traceback."

            tree = panel.query_one(Tree)
            branch = tree.root.children[0]
            frame_node = branch.children[0]
            tree.cursor_line = frame_node.line
            panel._tree.action_add_breakpoint()
            await pilot.pause()

        assert ("toggle_breakpoint", (str(source), 1)) in manager.calls

    asyncio.run(run())


def test_exception_tree_selects_matching_stack_frame_or_reports_failure(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        from tests.support import RecordingHost, RecordingManager

        source = tmp_path / "boom.py"
        source.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        frame = TracebackFrame(path=str(source), line=3, name="main", text="raise")
        manager = RecordingManager(fail={"select_frame": RuntimeError("stopped")})
        host = RecordingHost()
        ctx = make_context(host=host, manager=manager)
        store = ctx.services.get(SESSION_STORE)
        store.update(frames=(FrameInfo(id=9, name="main", path=str(source), line=3),))

        panel = ExceptionPanel(ctx=ctx)
        async with SingleWidgetApp(panel).run_test() as pilot:
            await pilot.pause()
            panel._tree._jump_to_frame(frame)
            await pilot.pause()

        assert ("select_frame", (9,)) in manager.calls
        assert host.notifications == [("stopped", 2.5)]

    asyncio.run(run())
