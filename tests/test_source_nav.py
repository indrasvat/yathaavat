from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, Static

from tests.support import RecordingHost, SingleScreenApp, make_context
from yathaavat.app.source_nav import GotoDialog, parse_goto_spec
from yathaavat.core import SESSION_STORE


def test_parse_goto_spec_line_only() -> None:
    spec = parse_goto_spec("12")
    assert spec is not None
    assert spec.line == 12
    assert spec.col == 1


def test_parse_goto_spec_line_col() -> None:
    spec = parse_goto_spec("12:5")
    assert spec is not None
    assert spec.line == 12
    assert spec.col == 5


def test_parse_goto_spec_rejects_invalid() -> None:
    assert parse_goto_spec("") is None
    assert parse_goto_spec("a") is None
    assert parse_goto_spec("0") is None
    assert parse_goto_spec("12:0") is None
    assert parse_goto_spec("12:x") is None


def test_goto_dialog_updates_source_position_when_file_is_loaded(tmp_path: Path) -> None:
    async def run() -> None:
        ctx = make_context()
        store = ctx.services.get(SESSION_STORE)
        source = tmp_path / "app.py"
        source.write_text("print('ok')\n", encoding="utf-8")
        store.update(source_path=str(source), source_line=1, source_col=1)
        dialog = GotoDialog(ctx=ctx)

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            input_widget = dialog.query_one("#goto_input", Input)
            dialog._on_submit(Input.Submitted(input_widget, "14:5"))
            await pilot.pause()

        snap = store.snapshot()
        assert (snap.source_line, snap.source_col) == (14, 5)

    asyncio.run(run())


def test_goto_dialog_reports_invalid_or_missing_source() -> None:
    async def run() -> None:
        host = RecordingHost()
        ctx = make_context(host=host)
        dialog = GotoDialog(ctx=ctx)

        async with SingleScreenApp(dialog).run_test() as pilot:
            await pilot.pause()
            input_widget = dialog.query_one("#goto_input", Input)
            dialog._on_submit(Input.Submitted(input_widget, "bad"))
            assert str(dialog.query_one("#goto_hint", Static).content) == (
                "Invalid location. Use: line[:col]."
            )
            dialog._on_submit(Input.Submitted(input_widget, "10"))
            await pilot.pause()

        assert host.notifications == [("No source file loaded.", 2.0)]

    asyncio.run(run())
