from __future__ import annotations

import asyncio

from textual.containers import VerticalScroll
from textual.widgets import Static

from tests.support import RecordingHost, SingleScreenApp, make_context
from yathaavat.app.keys import format_keys
from yathaavat.app.shortcuts import KeyboardShortcuts, shortcut_groups
from yathaavat.app.tui import YathaavatApp
from yathaavat.core import Command, CommandRegistry, CommandSpec
from yathaavat.plugins.builtin import plugin
from yathaavat.plugins.debugpy import plugin as debugpy_plugin


class _TestShortcutsApp(SingleScreenApp):
    CSS = YathaavatApp.CSS


def test_shortcut_groups_include_every_registered_key_and_omit_unbound_commands() -> None:
    ctx = make_context()
    plugin().register(ctx)
    debugpy_plugin().register(ctx)
    groups = shortcut_groups(ctx.commands)
    items = [item for group in groups for item in group.items]

    assert {item.id: (item.title, item.keys) for item in items} == {
        cmd.spec.id: (cmd.spec.title, format_keys(cmd.spec.default_keys))
        for cmd in ctx.commands.all()
        if cmd.spec.default_keys
    }
    assert len(items) == len({item.id for item in items})
    assert {group.title for group in groups} == {
        "Application",
        "Breakpoints",
        "Debug",
        "Help",
        "Session",
        "Source",
        "View",
        "Watches",
    }


def test_shortcut_groups_handle_empty_registry_and_new_plugin_commands() -> None:
    commands = CommandRegistry()
    assert shortcut_groups(commands) == ()
    for command_id, title, keys in (
        ("custom.zebra", "Zebra", ("ctrl+z", "f4")),
        ("custom.alpha", "Alpha [literal]", ("alt+a",)),
        ("custom.hidden", "Hidden", ()),
    ):
        commands.register(Command(CommandSpec(command_id, title, "", keys), lambda: None))

    groups = shortcut_groups(commands)
    assert [group.title for group in groups] == ["Custom"]
    assert [(item.id, item.title, item.keys) for item in groups[0].items] == [
        ("custom.alpha", "Alpha [literal]", "Alt+A"),
        ("custom.zebra", "Zebra", "Ctrl+Z / F4"),
    ]


def test_shortcuts_command_opens_modal_with_all_bound_commands() -> None:
    async def run() -> None:
        host = RecordingHost()
        ctx = make_context(host=host)
        plugin().register(ctx)
        debugpy_plugin().register(ctx)
        command = ctx.commands.get("help.shortcuts")
        assert command.spec.title == "Help: keyboard shortcuts"
        assert command.spec.default_keys == ("?",)
        await command.run()
        screen = host.screens[-1]
        assert isinstance(screen, KeyboardShortcuts)

        async with SingleScreenApp(screen).run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            rendered = "\n".join(str(widget.content) for widget in screen.query(Static))
            for cmd in ctx.commands.all():
                if cmd.spec.default_keys:
                    assert cmd.spec.title in rendered
                    assert format_keys(cmd.spec.default_keys) in rendered

    asyncio.run(run())


def test_shortcuts_fit_scroll_and_dismiss_with_app_styles() -> None:
    async def run() -> None:
        ctx = make_context()
        plugin().register(ctx)
        debugpy_plugin().register(ctx)
        screen = KeyboardShortcuts(ctx=ctx)
        async with _TestShortcutsApp(screen).run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert screen.styles.background.a == 0.45
            root = screen.query_one("#shortcuts_root")
            assert 0 <= root.region.x < root.region.right <= 80
            assert 0 <= root.region.y < root.region.bottom <= 24
            scroller = screen.query_one(VerticalScroll)
            assert screen.focused is scroller
            await pilot.press("pagedown")
            await pilot.pause()
            assert scroller.scroll_y > 0
            await pilot.press("escape")
            assert len(pilot.app.screen_stack) == 1
            await pilot.app.push_screen(KeyboardShortcuts(ctx=ctx))
            await pilot.press("?")
            assert len(pilot.app.screen_stack) == 1

    asyncio.run(run())
