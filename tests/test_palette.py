from __future__ import annotations

import asyncio
from typing import cast

from textual.widgets import ListItem, ListView

from tests.support import RecordingHost, SingleScreenApp, make_context
from yathaavat.app.palette import CommandPalette
from yathaavat.core import Command, CommandSpec


def test_command_palette_items_sort_and_fuzzy_filter() -> None:
    ctx = make_context()
    ctx.commands.register(
        Command(
            CommandSpec(
                id="debug.continue",
                title="Continue",
                summary="resume target",
                default_keys=("f5", "c"),
            ),
            handler=lambda: None,
        )
    )
    ctx.commands.register(
        Command(
            CommandSpec(id="source.find", title="Find", summary="search source"),
            handler=lambda: None,
        )
    )
    palette = CommandPalette(ctx=ctx)

    assert [item.title for item in palette._items()] == ["Continue", "Find"]
    palette.query_text = "src find"
    filtered = palette._items()
    assert [item.id for item in filtered] == ["source.find"]


def test_command_palette_refresh_and_selection_runs_command() -> None:
    async def run() -> None:
        ran: list[str] = []
        ctx = make_context()
        ctx.commands.register(
            Command(
                CommandSpec(id="debug.pause", title="Pause", summary="pause execution"),
                handler=lambda: ran.append("pause"),
            )
        )
        palette = CommandPalette(ctx=ctx)

        async with SingleScreenApp(palette).run_test() as pilot:
            await pilot.pause()
            lv = palette.query_one(ListView)
            assert lv.index == 0
            assert len(lv.children) == 1
            palette._on_selected(ListView.Selected(lv, cast(ListItem, lv.children[0]), 0))
            await pilot.pause()

        assert ran == ["pause"]

    asyncio.run(run())


def test_command_palette_selection_reports_command_failure() -> None:
    async def run() -> None:
        host = RecordingHost()
        ctx = make_context(host=host)

        def fail() -> None:
            raise RuntimeError("no target")

        ctx.commands.register(
            Command(CommandSpec(id="debug.fail", title="Fail", summary="boom"), handler=fail)
        )
        palette = CommandPalette(ctx=ctx)

        async with SingleScreenApp(palette).run_test() as pilot:
            await pilot.pause()
            lv = palette.query_one(ListView)
            palette._on_selected(ListView.Selected(lv, cast(ListItem, lv.children[0]), 0))
            await pilot.pause()

        assert host.notifications == [("no target", 3.0)]

    asyncio.run(run())
