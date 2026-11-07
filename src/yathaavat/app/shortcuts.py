from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from yathaavat.app.keys import format_keys
from yathaavat.core import AppContext, CommandRegistry


@dataclass(frozen=True, slots=True)
class ShortcutItem:
    id: str
    title: str
    keys: str


@dataclass(frozen=True, slots=True)
class ShortcutGroup:
    title: str
    items: tuple[ShortcutItem, ...]


def shortcut_groups(commands: CommandRegistry) -> tuple[ShortcutGroup, ...]:
    titles = {"app": "Application", "breakpoint": "Breakpoints", "watch": "Watches"}
    groups: dict[str, list[ShortcutItem]] = {}
    for command in commands.all():
        spec = command.spec
        if not spec.default_keys:
            continue
        area = spec.id.split(".", 1)[0]
        title = titles.get(area, area.replace("_", " ").title())
        groups.setdefault(title, []).append(
            ShortcutItem(id=spec.id, title=spec.title, keys=format_keys(spec.default_keys))
        )
    return tuple(
        ShortcutGroup(
            title=title, items=tuple(sorted(items, key=lambda item: item.title.casefold()))
        )
        for title, items in sorted(groups.items())
    )


class KeyboardShortcuts(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss", "Close"),
        ("?", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    KeyboardShortcuts { align: center middle; background: #000000 45%; }
    KeyboardShortcuts #shortcuts_root {
        width: 78;
        max-width: 94%;
        height: 90%;
        max-height: 48;
        border: round #2a3b52;
        background: #0f1520;
        color: #d6e2ff;
        padding: 1 2;
    }
    KeyboardShortcuts #shortcuts_title { height: 1; color: #8bd5ff; text-style: bold; }
    KeyboardShortcuts #shortcuts_subtitle { height: auto; color: #93a4c7; margin-bottom: 1; }
    KeyboardShortcuts #shortcuts_list { height: 1fr; }
    KeyboardShortcuts .shortcut_group {
        height: 1;
        margin-top: 1;
        color: #8bd5ff;
        text-style: bold;
    }
    KeyboardShortcuts .shortcut_row { height: auto; }
    KeyboardShortcuts .shortcut_key { width: 26; height: auto; color: #d6e2ff; }
    KeyboardShortcuts .shortcut_title { width: 1fr; height: auto; color: #93a4c7; }
    KeyboardShortcuts #shortcuts_footer {
        height: auto;
        margin-top: 1;
        color: #93a4c7;
    }
    """

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        with Container(id="shortcuts_root"):
            yield Static("Keyboard shortcuts", id="shortcuts_title")
            yield Static(
                "Default keys · availability depends on focus and session", id="shortcuts_subtitle"
            )
            with VerticalScroll(id="shortcuts_list"):
                for group in shortcut_groups(self._ctx.commands):
                    yield Static(group.title, classes="shortcut_group", markup=False)
                    for item in group.items:
                        yield Horizontal(
                            Static(item.keys, classes="shortcut_key", markup=False),
                            Static(item.title, classes="shortcut_title", markup=False),
                            classes="shortcut_row",
                        )
            yield Static("↑ ↓ / PgUp PgDn scroll    Esc / ? close", id="shortcuts_footer")

    def on_mount(self) -> None:
        self.query_one("#shortcuts_list", VerticalScroll).focus()
