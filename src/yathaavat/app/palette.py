from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from yathaavat.app.keys import format_keys
from yathaavat.core import AppContext


@dataclass(frozen=True, slots=True)
class PaletteItem:
    id: str
    title: str
    summary: str
    key_hint: str


class CommandPalette(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    query_text = reactive("")

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Command Palette", id="pal_title"),
            Input(placeholder="Type to search…", id="pal_input"),
            ListView(id="pal_list"),
            id="pal_root",
        )

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._refresh_results()

    @on(Input.Changed, "#pal_input")
    def _on_query(self, event: Input.Changed) -> None:
        self.query_text = event.value
        self._refresh_results()

    @on(Input.Submitted, "#pal_input")
    def _on_submit(self, _event: Input.Submitted) -> None:
        lv = self.query_one("#pal_list", ListView)
        lv.action_select_cursor()

    @on(ListView.Selected, "#pal_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        item = event.item
        cmd_id = getattr(item, "cmd_id", None)
        if not isinstance(cmd_id, str):
            return
        self.app.pop_screen()

        async def _run() -> None:
            try:
                await self._ctx.commands.get(cmd_id).run()
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        task = asyncio.create_task(_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _items(self) -> list[PaletteItem]:
        out: list[PaletteItem] = []
        for cmd in sorted(self._ctx.commands.all(), key=lambda c: c.spec.title.lower()):
            out.append(
                PaletteItem(
                    id=cmd.spec.id,
                    title=cmd.spec.title,
                    summary=cmd.spec.summary,
                    key_hint=format_keys(cmd.spec.default_keys),
                )
            )
        q = self.query_text.strip().lower()
        if not q:
            return out
        return [
            i for i in out if q in i.title.lower() or q in i.id.lower() or q in i.summary.lower()
        ]

    def _refresh_results(self) -> None:
        lv = self.query_one(ListView)
        lv.clear()
        items = self._items()
        for it in items:
            li = ListItem(Static(f"{it.title}  [{it.id}]  {it.key_hint}", classes="pal_row"))
            li.cmd_id = it.id  # type: ignore[attr-defined]
            lv.append(li)
        lv.index = 0 if items else None
