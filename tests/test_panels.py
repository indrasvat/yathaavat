from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from textual.widgets import DataTable, Input, ListView, RichLog, Static, TextArea

from tests.support import RecordingHost, RecordingManager, SingleWidgetApp, make_context
from yathaavat.app.expression import ExpressionInput
from yathaavat.app.panels import (
    BreakpointsPanel,
    BreakpointsTable,
    CodeView,
    ConsolePanel,
    LocalsPanel,
    LocalsTable,
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
    VariablePage,
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


def test_code_view_copy_selection_and_line_mapping() -> None:
    async def run() -> None:
        view = CodeView()
        async with SingleWidgetApp(view).run_test() as pilot:
            await pilot.pause()
            view.text = "alpha\nbeta\n"
            view.show_line_numbers = True
            view.cursor_location = (0, 0)
            assert view.line_number_at_viewport_y(0) == 1

            view.action_copy_selection()
            await pilot.pause()

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
            assert ("get_variables_page", (7, 0, 50, None)) in manager.calls

    asyncio.run(run())


def test_locals_table_reports_unsupported_expansion_and_copies_value() -> None:
    async def run() -> None:
        host = RecordingHost()
        ctx = make_context(host=host)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (
                    VariableInfo(
                        name="root",
                        value="{...}",
                        type="dict",
                        variables_reference=9,
                    ),
                )
            )
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            table.action_copy_value()
            await pilot.pause()

        assert host.notifications == [
            ("Variable expansion is not supported by this session.", 2.5),
            ("Copied value.", 1.2),
        ]

    asyncio.run(run())


def test_locals_table_pages_large_variable_children() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="[0]", value="zero", type="str"),
                        VariableInfo(name="[1]", value="one", type="str"),
                    ),
                    start=0,
                    count=2,
                    indexed_variables=5,
                ),
                (9, 2, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="[2]", value="two", type="str"),
                        VariableInfo(name="[3]", value="three", type="str"),
                    ),
                    start=2,
                    count=2,
                    indexed_variables=5,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (
                    VariableInfo(
                        name="items",
                        value="list[5]",
                        type="list",
                        variables_reference=9,
                    ),
                )
            )
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            await pilot.pause()

            assert table.row_count == 4
            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "Load more...",
            ]
            assert ("get_variables_page", (9, 0, 2, None)) in manager.calls

            table.move_cursor(row=3)
            await table.action_toggle_expand()
            await pilot.pause()

            assert table.row_count == 6
            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "[2]",
                "[3]",
                "Load more...",
            ]
            assert ("get_variables_page", (9, 2, 2, None)) in manager.calls

    asyncio.run(run())


def test_locals_table_chunks_full_variable_responses_locally() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="[0]", value="zero", type="str"),
                        VariableInfo(name="[1]", value="one", type="str"),
                        VariableInfo(name="[2]", value="two", type="str"),
                        VariableInfo(name="[3]", value="three", type="str"),
                        VariableInfo(name="[4]", value="four", type="str"),
                    ),
                    start=0,
                    count=None,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (
                    VariableInfo(
                        name="items",
                        value="list[5]",
                        type="list",
                        variables_reference=9,
                    ),
                )
            )
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "Load more...",
            ]

            table.move_cursor(row=3)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "[2]",
                "[3]",
                "Load more...",
            ]
            assert manager.calls.count(("get_variables_page", (9, 0, 2, None))) == 1

            table.move_cursor(row=5)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "[2]",
                "[3]",
                "[4]",
            ]
            assert manager.calls.count(("get_variables_page", (9, 0, 2, None))) == 1

    asyncio.run(run())


def test_locals_table_does_not_append_duplicate_full_response_pages() -> None:
    async def run() -> None:
        full_response = VariablePage(
            variables=(
                VariableInfo(name="[0]", value="zero", type="str"),
                VariableInfo(name="[1]", value="one", type="str"),
            ),
            start=0,
            count=2,
        )
        manager = RecordingManager(
            variable_pages={
                (9, 0, 2, None): full_response,
                (9, 2, 2, None): full_response,
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root((VariableInfo(name="items", value="list[2]", variables_reference=9),))
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "Load more...",
            ]

            table.move_cursor(row=3)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == ["items", "[0]", "[1]"]
            assert manager.calls.count(("get_variables_page", (9, 2, 2, None))) == 1

    asyncio.run(run())


def test_locals_table_keeps_new_variables_from_partially_overlapping_pages() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="[0]", value="zero", type="str"),
                        VariableInfo(name="[1]", value="one", type="str"),
                    ),
                    start=0,
                    count=2,
                ),
                (9, 2, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="[1]", value="one", type="str"),
                        VariableInfo(name="[2]", value="two", type="str"),
                    ),
                    start=2,
                    count=2,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root((VariableInfo(name="items", value="list[3]", variables_reference=9),))
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            await pilot.pause()

            table.move_cursor(row=3)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "[2]",
            ]

    asyncio.run(run())


def test_locals_table_falls_back_to_get_variables_for_legacy_backends() -> None:
    class LegacyManager(RecordingManager):
        def __getattribute__(self, name: str) -> object:
            if name == "get_variables_page":
                raise AttributeError(name)
            return super().__getattribute__(name)

    async def run() -> None:
        manager = LegacyManager(
            variables={
                9: (
                    VariableInfo(name="[0]", value="zero", type="str"),
                    VariableInfo(name="[1]", value="one", type="str"),
                    VariableInfo(name="[2]", value="two", type="str"),
                )
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root((VariableInfo(name="items", value="list[3]", variables_reference=9),))
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            await pilot.pause()

            assert ("get_variables", (9,)) in manager.calls
            assert [node.name for node in table.visible_nodes()] == [
                "items",
                "[0]",
                "[1]",
                "Load more...",
            ]

    asyncio.run(run())


def test_locals_table_keeps_load_more_visible_while_filtered() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="[0]", value="zero", type="str"),
                        VariableInfo(name="[1]", value="one", type="str"),
                        VariableInfo(name="[2]", value="two", type="str"),
                    ),
                    start=0,
                    count=None,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root((VariableInfo(name="items", value="list[3]", variables_reference=9),))
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            table.set_filter("not-present")
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == ["Load more..."]

    asyncio.run(run())


def test_locals_table_ignores_obsolete_variable_fetches() -> None:
    class SlowManager(RecordingManager):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def get_variables_page(
            self,
            variables_reference: int,
            *,
            start: int | None = None,
            count: int | None = None,
            filter: str | None = None,
        ) -> VariablePage:
            self._record("get_variables_page", variables_reference, start, count, filter)
            self.started.set()
            await self.release.wait()
            return VariablePage(
                variables=(VariableInfo(name="stale", value="old", type="str"),),
                start=start,
                count=count,
                indexed_variables=1,
            )

    async def run() -> None:
        manager = SlowManager()
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root((VariableInfo(name="old", value="{}", variables_reference=9),))
            table.move_cursor(row=0)
            task = asyncio.create_task(table.action_toggle_expand())
            await manager.started.wait()

            table.set_root((VariableInfo(name="new", value="{}", variables_reference=10),))
            manager.release.set()
            await task
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == ["new"]

    asyncio.run(run())


def test_locals_table_pages_nested_variable_children() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="nested", value="list[3]", variables_reference=11),
                    ),
                    start=0,
                    count=2,
                    named_variables=1,
                ),
                (11, 0, 2, None): VariablePage(
                    variables=(
                        VariableInfo(name="[0]", value="zero", type="str"),
                        VariableInfo(name="[1]", value="one", type="str"),
                    ),
                    start=0,
                    count=2,
                    indexed_variables=3,
                ),
                (11, 2, 2, None): VariablePage(
                    variables=(VariableInfo(name="[2]", value="two", type="str"),),
                    start=2,
                    count=2,
                    indexed_variables=3,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (
                    VariableInfo(
                        name="outer",
                        value="{...}",
                        type="dict",
                        variables_reference=9,
                    ),
                )
            )
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            table.move_cursor(row=1)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == [
                "outer",
                "nested",
                "[0]",
                "[1]",
                "Load more...",
            ]

            table.move_cursor(row=4)
            await table.action_toggle_expand()
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == [
                "outer",
                "nested",
                "[0]",
                "[1]",
                "[2]",
            ]

    asyncio.run(run())


def test_locals_table_filters_visible_variables_without_resetting_expansion() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 3, None): VariablePage(
                    variables=(
                        VariableInfo(name="alpha", value="1", type="int"),
                        VariableInfo(name="beta", value="2", type="int"),
                        VariableInfo(name="gamma", value="3", type="int"),
                    ),
                    start=0,
                    count=3,
                    named_variables=3,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=3))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (
                    VariableInfo(
                        name="payload",
                        value="{...}",
                        type="dict",
                        variables_reference=9,
                    ),
                )
            )
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            table.set_filter("gam")
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == ["gamma"]

            table.set_filter("")
            await pilot.pause()
            assert [node.name for node in table.visible_nodes()] == [
                "payload",
                "alpha",
                "beta",
                "gamma",
            ]

    asyncio.run(run())


def test_locals_table_filter_prefers_first_editable_match() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 3, None): VariablePage(
                    variables=(
                        VariableInfo(name="012", value="'item-012'", type="str"),
                        VariableInfo(
                            name="013",
                            value="{'label': 'item-013'}",
                            type="dict",
                            variables_reference=11,
                        ),
                    ),
                    start=0,
                    count=3,
                    indexed_variables=2,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=3))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (
                    VariableInfo(
                        name="items",
                        value="['item-012', 'item-013']",
                        type="list",
                        variables_reference=9,
                    ),
                ),
                parent_reference=99,
            )
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            table.move_cursor(row=2)
            table.set_filter("013")
            await pilot.pause()

            assert [node.name for node in table.visible_nodes()] == ["items", "013"]
            assert table.cursor_row == 1

            await table.edit_selected_value("'changed'")
            assert ("set_variable", (9, "013", "'changed'")) in manager.calls

    asyncio.run(run())


def test_locals_table_edits_selected_variable() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 2, None): VariablePage(
                    variables=(VariableInfo(name="answer", value="42", type="int"),),
                    start=0,
                    count=2,
                    named_variables=1,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (
                    VariableInfo(
                        name="scope",
                        value="{...}",
                        type="dict",
                        variables_reference=9,
                    ),
                )
            )
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            table.move_cursor(row=1)
            await table.edit_selected_value("43")
            await pilot.pause()

            assert ("set_variable", (9, "answer", "43")) in manager.calls
            assert [node.value for node in table.visible_nodes() if node.name == "answer"] == ["43"]
            assert table.cursor_row == 1

    asyncio.run(run())


def test_locals_table_edit_failure_returns_false_and_preserves_value() -> None:
    async def run() -> None:
        host = RecordingHost()
        manager = RecordingManager(fail={"set_variable": RuntimeError("read only")})
        ctx = make_context(host=host, manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (VariableInfo(name="answer", value="42", type="int"),),
                parent_reference=99,
            )
            table.move_cursor(row=0)
            updated = await table.edit_selected_value("43")
            await pilot.pause()

            assert updated is False
            assert [node.value for node in table.visible_nodes()] == ["42"]
            assert host.notifications[-1][0] == "read only"

    asyncio.run(run())


def test_locals_table_edit_uses_original_dialog_node() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variable_pages={
                (9, 0, 5, None): VariablePage(
                    variables=(
                        VariableInfo(name="first", value="1", type="int"),
                        VariableInfo(name="second", value="2", type="int"),
                    ),
                    start=0,
                    count=5,
                    named_variables=2,
                ),
            }
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=5))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root((VariableInfo(name="scope", value="{...}", variables_reference=9),))
            table.move_cursor(row=0)
            await table.action_toggle_expand()
            original_node = table.visible_nodes()[1]
            table.move_cursor(row=2)
            updated = await table.edit_selected_value("10", node=original_node)
            await pilot.pause()

            assert updated is True
            assert ("set_variable", (9, "first", "10")) in manager.calls

    asyncio.run(run())


def test_locals_table_edits_root_variable_with_scope_reference() -> None:
    async def run() -> None:
        manager = RecordingManager()
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx, page_size=2))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (VariableInfo(name="answer", value="42", type="int"),),
                parent_reference=99,
            )
            table.move_cursor(row=0)
            await table.edit_selected_value("43")
            await pilot.pause()

            assert manager.calls == [("set_variable", (99, "answer", "43"))]
            assert [node.value for node in table.visible_nodes()] == ["43"]

    asyncio.run(run())


def test_locals_filter_escape_clears_query_and_focuses_table() -> None:
    async def run() -> None:
        ctx = make_context()
        store = ctx.services.get(SESSION_STORE)
        app = SingleWidgetApp(lambda: LocalsPanel(ctx=ctx))

        async with app.run_test() as pilot:
            await pilot.pause()
            panel = cast(LocalsPanel, app.widget)
            store.update(locals=(VariableInfo(name="answer", value="42"),))
            await pilot.pause()
            filter_input = cast(Any, panel.query_one("#locals_filter", Input))
            table = panel.query_one(LocalsTable)

            filter_input.value = "answer"
            filter_input.focus()
            filter_input.action_clear_filter()
            await pilot.pause()

            assert filter_input.value == ""
            assert table.has_focus

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


@dataclass(frozen=True, slots=True)
class _RowHighlighted:
    cursor_row: int


def test_breakpoints_table_copy_edit_highlight_and_missing_manager(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "worker.py"
        source.write_text("print('x')\n", encoding="utf-8")
        host = RecordingHost()
        ctx = make_context(host=host)
        store = ctx.services.get(SESSION_STORE)
        app = SingleWidgetApp(lambda: BreakpointsTable(ctx=ctx, store=store))

        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(BreakpointsTable, app.widget)
            table.set_breakpoints(
                (
                    BreakpointInfo(
                        path=str(source),
                        line=3,
                        verified=False,
                        condition="x > 1",
                    ),
                )
            )
            table.focus()
            table.move_cursor(row=0)
            table._on_row_highlighted(cast(DataTable.RowHighlighted, _RowHighlighted(0)))
            table.action_copy_location()
            table.action_edit_breakpoint()
            await table.action_delete_breakpoint()
            await pilot.pause()

        assert (store.snapshot().source_path, store.snapshot().source_line) == (str(source), 3)
        assert [type(screen).__name__ for screen in host.screens] == ["BreakpointEditDialog"]
        assert host.notifications == [("Copied location.", 1.2), ("No session.", 2.0)]

    asyncio.run(run())


def test_console_panel_evaluates_or_reports_no_session() -> None:
    async def run() -> None:
        no_session = ConsolePanel(ctx=make_context())
        async with SingleWidgetApp(no_session).run_test() as pilot:
            await pilot.pause()
            control = no_session.query_one("#console_input", ExpressionInput)
            no_session._on_submit(ExpressionInput.Submitted(control, "x + 1"))
            await pilot.pause()
            assert len(no_session.query_one("#console_log", RichLog).lines) == 2

        manager = RecordingManager(evaluate_result="42")
        ok = ConsolePanel(ctx=make_context(manager=manager))
        async with SingleWidgetApp(ok).run_test() as pilot:
            await pilot.pause()
            control = ok.query_one("#console_input", ExpressionInput)
            ok._on_submit(ExpressionInput.Submitted(control, "6 * 7"))
            await pilot.pause()
            assert manager.calls == [("evaluate", ("6 * 7",))]

        failing_manager = RecordingManager(fail={"evaluate": RuntimeError("boom")})
        failing = ConsolePanel(ctx=make_context(manager=failing_manager))
        async with SingleWidgetApp(failing).run_test() as pilot:
            await pilot.pause()
            control = failing.query_one("#console_input", ExpressionInput)
            failing._on_submit(ExpressionInput.Submitted(control, "explode()"))
            await pilot.pause()
            assert failing_manager.calls == [("evaluate", ("explode()",))]

    asyncio.run(run())


def test_locals_table_enter_key_press_toggles_expand() -> None:
    async def run() -> None:
        manager = RecordingManager(
            variables={7: (VariableInfo(name="child", value="2", type="int"),)}
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: LocalsTable(ctx=ctx))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = cast(LocalsTable, app.widget)
            table.set_root(
                (VariableInfo(name="root", value="{...}", type="dict", variables_reference=7),)
            )
            table.move_cursor(row=0)
            table.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert table.row_count == 2

            await pilot.press("enter")
            await pilot.pause()
            assert table.row_count == 1

    asyncio.run(run())
