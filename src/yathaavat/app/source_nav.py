from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal
from textual.document._document import Document, Selection
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea

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


class FindDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        yield Container(
            Horizontal(
                Static("Find", id="find_title"),
                Input(placeholder="type to search…", id="find_input"),
                Static("", id="find_status"),
                id="find_row",
            ),
            Static("Enter next  •  Esc close", id="find_hint"),
            id="find_root",
        )

    def on_mount(self) -> None:
        self.styles.background = "transparent"
        self.query_one(Input).focus()

    @on(Input.Submitted, "#find_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        query = event.value
        if not query:
            return

        try:
            editor = self.app.query_one("#source_view", TextArea)
        except Exception:
            self._ctx.host.notify("Source view not available.", timeout=2.0)
            return

        path = getattr(editor, "path", None)
        if not isinstance(path, str) or not path:
            self._ctx.host.notify("No source file loaded.", timeout=2.0)
            return

        text = editor.text or ""
        if not text:
            self._ctx.host.notify("No source text loaded.", timeout=2.0)
            return

        doc = cast(Document, editor.document)
        start_index = doc.get_index_from_location(editor.cursor_location)
        found = text.find(query, start_index + 1)
        if found < 0:
            found = text.find(query, 0)
        if found < 0:
            self.query_one("#find_hint", Static).update("No matches.  •  Esc close")
            self.query_one("#find_status", Static).update("0")
            return

        start_loc = doc.get_location_from_index(found)
        end_loc = doc.get_location_from_index(found + len(query))
        editor.selection = Selection(start_loc, end_loc)
        editor.cursor_location = start_loc

        store = self._ctx.services.get(SESSION_STORE)
        store.update(
            source_path=path,
            source_line=start_loc[0] + editor.line_number_start,
            source_col=start_loc[1] + 1,
        )
        self.query_one("#find_hint", Static).update("Enter next  •  Esc close")
        self.query_one("#find_status", Static).update(
            f"{start_loc[0] + editor.line_number_start}:{start_loc[1] + 1}"
        )


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
