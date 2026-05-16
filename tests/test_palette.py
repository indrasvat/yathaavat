from __future__ import annotations

from tests.support import make_context
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
