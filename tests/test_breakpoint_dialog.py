from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, Static

from tests.support import RecordingHost, RecordingManager, SingleScreenApp, make_context
from yathaavat.app.breakpoint import BreakpointDialog, BreakpointEditDialog
from yathaavat.core import SESSION_STORE, BreakpointInfo


def test_breakpoint_dialog_configures_conditional_breakpoint(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "svc.py"
        source.write_text("print('ok')\n", encoding="utf-8")
        manager = RecordingManager()
        host = RecordingHost()
        ctx = make_context(host=host, manager=manager)
        ctx.services.get(SESSION_STORE).update(source_path=str(source))
        dialog = BreakpointDialog(ctx=ctx)

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            input_widget = dialog.query_one("#bp_input", Input)
            dialog._on_submit(Input.Submitted(input_widget, '12 if "x > 1" hit 3 log seen'))
            if dialog._task is not None:
                await dialog._task

        assert manager.calls == [
            ("set_breakpoint_config", (str(source.resolve()), 12, "x > 1", "3", "seen"))
        ]
        assert host.notifications == [("Configuring breakpoint: svc.py:12", 2.0)]

    asyncio.run(run())


def test_breakpoint_dialog_toggles_plain_breakpoint_and_reports_invalid(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "svc.py"
        source.write_text("print('ok')\n", encoding="utf-8")
        manager = RecordingManager()
        ctx = make_context(manager=manager)
        ctx.services.get(SESSION_STORE).update(source_path=str(source))
        dialog = BreakpointDialog(ctx=ctx)

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            input_widget = dialog.query_one("#bp_input", Input)
            dialog._on_submit(Input.Submitted(input_widget, "not-a-location"))
            assert str(dialog.query_one("#bp_hint", Static).content) == (
                "Invalid breakpoint. Use: path:line  [if EXPR]  [hit N]  [log MSG] "
                "(quote args with spaces)."
            )
            dialog._on_submit(Input.Submitted(input_widget, "7"))
            if dialog._task is not None:
                await dialog._task

        assert manager.calls == [("toggle_breakpoint", (str(source.resolve()), 7))]

    asyncio.run(run())


def test_breakpoint_dialog_without_backend_notifies_and_closes(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "svc.py"
        source.write_text("print('ok')\n", encoding="utf-8")
        host = RecordingHost()
        ctx = make_context(host=host)
        ctx.services.get(SESSION_STORE).update(source_path=str(source))
        dialog = BreakpointDialog(ctx=ctx)

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            input_widget = dialog.query_one("#bp_input", Input)
            dialog._on_submit(Input.Submitted(input_widget, "3"))
            await pilot.pause()
            assert dialog.is_attached is False

        assert host.notifications == [("No session backend available.", 2.0)]

    asyncio.run(run())


def test_breakpoint_edit_dialog_applies_and_clears_optional_config(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "svc.py"
        source.write_text("print('ok')\n", encoding="utf-8")
        manager = RecordingManager()
        host = RecordingHost()
        dialog = BreakpointEditDialog(
            ctx=make_context(host=host, manager=manager),
            breakpoint=BreakpointInfo(
                path=str(source),
                line=5,
                condition="old",
                hit_condition="2",
                log_message="old log",
            ),
        )

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            dialog.query_one("#bpedit_condition", Input).value = "value > 10"
            dialog.query_one("#bpedit_hit", Input).value = ""
            dialog.query_one("#bpedit_log", Input).value = "value={value}"
            dialog._on_submit(Input.Submitted(dialog.query_one("#bpedit_condition", Input), ""))
            if dialog._task is not None:
                await dialog._task

        assert manager.calls == [
            ("set_breakpoint_config", (str(source), 5, "value > 10", None, "value={value}"))
        ]
        assert host.notifications == [("Updated breakpoint svc.py:5 if value > 10  •  log", 2.0)]

    asyncio.run(run())


def test_breakpoint_edit_dialog_reports_unsupported_backend(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / "svc.py"
        source.write_text("print('ok')\n", encoding="utf-8")
        host = RecordingHost()
        dialog = BreakpointEditDialog(
            ctx=make_context(host=host),
            breakpoint=BreakpointInfo(path=str(source), line=5),
        )

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            dialog._on_submit(Input.Submitted(dialog.query_one("#bpedit_condition", Input), ""))
            await pilot.pause()

        assert host.notifications == [("Breakpoint configuration is not supported.", 2.5)]

    asyncio.run(run())
