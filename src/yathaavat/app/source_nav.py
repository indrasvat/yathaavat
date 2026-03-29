from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from yathaavat.core import SESSION_STORE, AppContext


@dataclass(frozen=True, slots=True)
class GotoSpec:
    line: int
    col: int = 1


def parse_goto_spec(value: str) -> GotoSpec | None:
    s = value.strip()
    if not s:
        return None

    if ":" in s:
        left, right = s.rsplit(":", 1)
        left = left.strip()
        right = right.strip()
        if not left.isdigit() or not right.isdigit():
            return None
        line = int(left)
        col = int(right)
    else:
        if not s.isdigit():
            return None
        line = int(s)
        col = 1

    if line <= 0 or col <= 0:
        return None
    return GotoSpec(line=line, col=col)


class GotoDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Go to line", id="goto_title"),
            Input(placeholder="line[:col]  (e.g. 120 or 120:5)", id="goto_input"),
            Static("Enter to jump • Esc to close", id="goto_hint"),
            id="goto_root",
        )

    def on_mount(self) -> None:
        self.styles.background = "transparent"
        self.query_one(Input).focus()

    @on(Input.Submitted, "#goto_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        spec = parse_goto_spec(event.value)
        if spec is None:
            self.query_one("#goto_hint", Static).update("Invalid location. Use: line[:col].")
            return

        store = self._ctx.services.get(SESSION_STORE)
        snap = store.snapshot()
        if not snap.source_path:
            self._ctx.host.notify("No source file loaded.", timeout=2.0)
            self.app.pop_screen()
            return

        store.update(source_line=spec.line, source_col=spec.col)
        self.app.pop_screen()
