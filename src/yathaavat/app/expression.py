from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.message import Message
from textual.widgets import ListItem, ListView, Static, TextArea

from yathaavat.app.input_history import InputHistory
from yathaavat.core import SESSION_MANAGER, AppContext, CompletionItem, CompletionsManager


def _is_typing_key(event: events.Key) -> bool:
    if event.key in {"backspace", "delete"}:
        return True
    if len(event.key) == 1:
        return True
    return False


def _render_completion(item: CompletionItem) -> Text:
    text = Text()
    text.append(item.label, style="bold")
    if item.type:
        text.append(f"  {item.type}", style="dim")
    return text


def apply_completion(text: str, item: CompletionItem) -> tuple[str, int]:
    start = max(0, min(item.replace_start, len(text)))
    end = max(start, min(start + item.replace_length, len(text)))
    next_text = f"{text[:start]}{item.insert_text}{text[end:]}"
    return next_text, start + len(item.insert_text)


class _CompletionRow(ListItem):
    def __init__(self, item: CompletionItem) -> None:
        super().__init__(Static(_render_completion(item), classes="expr_completion_row"))
        self.item = item


class ExpressionInput(Container):
    """A single-line Python expression editor with optional DAP completions."""

    class Submitted(Message):
        def __init__(self, control: ExpressionInput, text: str) -> None:
            super().__init__()
            self._control = control
            self.text = text

        @property
        def control(self) -> ExpressionInput:
            return self._control

    def __init__(
        self,
        *,
        ctx: AppContext,
        placeholder: str = "",
        history: InputHistory | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._ctx = ctx
        self._placeholder = placeholder
        self._history = history
        self._completion_task: asyncio.Task[None] | None = None
        self._completion_items: tuple[CompletionItem, ...] = ()
        self._completion_index: int = 0

        self._area = _ExpressionArea(owner=self, placeholder=self._placeholder)
        self._completions = ListView(classes="expr_completions")

    def compose(self) -> ComposeResult:
        yield self._completions
        yield self._area

    def on_mount(self) -> None:
        self._hide_completions()
        self._area.focus()

    def on_unmount(self) -> None:
        if self._completion_task is not None:
            self._completion_task.cancel()

    @property
    def value(self) -> str:
        return self._area.text

    @value.setter
    def value(self, value: str) -> None:
        self._area.text = value
        self._set_cursor(len(value))

    def clear(self) -> None:
        self._area.text = ""
        self._set_cursor(0)
        self._hide_completions()

    def focus_input(self) -> None:
        self._area.focus()

    def history_prev(self) -> None:
        if self._history is None:
            return
        value = self._history.prev(self._area.text)
        if value is None:
            return
        self._area.text = value
        self._set_cursor(len(value))

    def history_next(self) -> None:
        if self._history is None:
            return
        value = self._history.next()
        if value is None:
            return
        self._area.text = value
        self._set_cursor(len(value))

    def _cursor(self) -> int:
        row, col = self._area.cursor_location
        _ = row
        return int(col)

    def _set_cursor(self, col: int) -> None:
        self._area.cursor_location = (0, max(0, int(col)))

    def _hide_completions(self) -> None:
        self._completions.styles.display = "none"
        self._completion_items = ()
        self._completion_index = 0
        self._completions.clear()

    def close_completions(self) -> bool:
        if self._completion_items:
            self._hide_completions()
            return True
        return False

    def _manager(self) -> CompletionsManager | None:
        try:
            manager = self._ctx.services.get(SESSION_MANAGER)
        except KeyError:
            return None
        return manager if isinstance(manager, CompletionsManager) else None

    def submit(self) -> None:
        text = self._area.text.strip()
        if self._history is not None:
            self._history.push(text)
        self.post_message(self.Submitted(self, text=text))

    def completion_prev(self) -> None:
        if not self._completion_items:
            self.history_prev()
            return
        self._completion_index = max(0, self._completion_index - 1)
        self._completions.index = self._completion_index

    def completion_next(self) -> None:
        if not self._completion_items:
            self.history_next()
            return
        self._completion_index = min(len(self._completion_items) - 1, self._completion_index + 1)
        self._completions.index = self._completion_index

    def accept_completion(self) -> bool:
        if not self._completion_items:
            return False
        item = self._completion_items[self._completion_index]
        next_text, next_cursor = apply_completion(self._area.text, item)
        self._area.text = next_text
        self._set_cursor(next_cursor)
        self._hide_completions()
        return True

    def request_completions(self) -> None:
        manager = self._manager()
        if manager is None:
            self._hide_completions()
            return

        text = self._area.text
        cursor = self._cursor()
        if self._completion_task is not None:
            self._completion_task.cancel()

        async def _run() -> None:
            items = await manager.complete(text, cursor=cursor)
            self._show_completions(items)

        self._completion_task = asyncio.create_task(_run())

    def _show_completions(self, items: Iterable[CompletionItem]) -> None:
        self._completion_items = tuple(items)
        self._completion_index = 0
        self._completions.clear()
        if not self._completion_items:
            self._hide_completions()
            return
        for it in self._completion_items[:12]:
            self._completions.append(_CompletionRow(it))
        self._completions.index = 0
        self._completions.styles.display = "block"


class _ExpressionArea(TextArea):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+p", "app.open_palette", "Palette"),
        ("ctrl+f", "app.command('source.find')", "Find"),
    ]

    def __init__(self, *, owner: ExpressionInput, placeholder: str) -> None:
        super().__init__(
            "",
            language="python",
            theme="monokai",
            read_only=False,
            soft_wrap=False,
            tab_behavior="indent",
            show_line_numbers=False,
            highlight_cursor_line=False,
            show_cursor=True,
            placeholder=placeholder,
            classes="expr_area",
        )
        self._owner = owner

    async def on_key(self, event: events.Key) -> None:
        match event.key:
            case "tab":
                if self._owner.accept_completion():
                    event.stop()
                    event.prevent_default()
                    return
                self._owner.request_completions()
                event.stop()
                event.prevent_default()
                return
            case "enter":
                if self._owner.accept_completion():
                    event.stop()
                    event.prevent_default()
                    return
                self._owner.submit()
                event.stop()
                event.prevent_default()
                return
            case "escape":
                if self._owner.close_completions():
                    event.stop()
                    event.prevent_default()
                    return
            case "up":
                self._owner.completion_prev()
                event.stop()
                event.prevent_default()
                return
            case "down":
                self._owner.completion_next()
                event.stop()
                event.prevent_default()
                return
            case _ if _is_typing_key(event):
                self._owner.close_completions()

        await self.handle_key(event)
