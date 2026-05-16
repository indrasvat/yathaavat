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
