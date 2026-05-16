from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from textual.widgets import DataTable, ListView, RichLog, Static, TextArea

from tests.support import RecordingHost, RecordingManager, SingleWidgetApp, make_context
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
from yathaavat.core import (
    SESSION_STORE,
    BreakpointInfo,
    FrameInfo,
    VariableInfo,
)


def test_frame_rows_and_breakpoint_labels_are_user_facing() -> None:
    assert _frame_rows((FrameInfo(id=1, name="main", path="/tmp/app.py", line=7),))[0].label == (
        "main  app.py:7"
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


def test_stack_panel_selects_frame_via_manager(tmp_path: Path) -> None:
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

        assert ("select_frame", (11,)) in manager.calls

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
