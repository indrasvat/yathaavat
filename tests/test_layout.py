from __future__ import annotations

import asyncio

from textual.widgets import Static

from tests.support import SingleWidgetApp, make_context
from yathaavat.app.layout import SlotDescriptor, SlotTabs, _safe_dom_id
from yathaavat.core import WidgetContribution
from yathaavat.core.widgets import Slot


def test_safe_dom_id_replaces_non_alphanumeric_chars() -> None:
    contribution = WidgetContribution(
        id="plugin.source/find",
        title="Find",
        slot=Slot.CENTER,
        factory=lambda _ctx: Static("x"),
    )
    assert _safe_dom_id(contribution) == "pane_plugin_source_find"


def test_slot_tabs_renders_empty_state_without_registered_panels() -> None:
    async def run() -> None:
        widget = SlotTabs(
            ctx=make_context(),
            slot=SlotDescriptor(Slot.LEFT, "Left"),
            id="left_slot",
        )
        async with SingleWidgetApp(widget).run_test() as pilot:
            await pilot.pause()
            assert "(no panels registered)" in str(widget.query_one(Static).content)

    asyncio.run(run())


def test_slot_tabs_renders_registered_contributions_in_order() -> None:
    async def run() -> None:
        ctx = make_context()
        ctx.widgets.register(
            WidgetContribution(
                id="z-panel",
                title="Zed",
                slot=Slot.RIGHT,
                factory=lambda _ctx: Static("second", id="second"),
                order=20,
            )
        )
        ctx.widgets.register(
            WidgetContribution(
                id="a.panel",
                title="Alpha",
                slot=Slot.RIGHT,
                factory=lambda _ctx: Static("first", id="first"),
                order=10,
            )
        )
        widget = SlotTabs(
            ctx=ctx,
            slot=SlotDescriptor(Slot.RIGHT, "Right"),
            id="right_slot",
        )
        async with SingleWidgetApp(widget).run_test() as pilot:
            await pilot.pause()
            assert str(widget.query_one("#first", Static).content) == "first"
            assert str(widget.query_one("#second", Static).content) == "second"

    asyncio.run(run())
