from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from yathaavat.core import SESSION_MANAGER, SESSION_STORE, AppContext, SessionManager


@dataclass(frozen=True, slots=True)
class BreakpointSpec:
    path: str
    line: int


def parse_breakpoint_spec(
    value: str, *, default_path: str | None = None, cwd: Path | None = None
) -> BreakpointSpec | None:
    s = value.strip()
    if not s:
        return None

    line_num: int | None = None
    if s.isdigit():
        if default_path is None:
            return None
        line_num = int(s)
        if line_num <= 0:
            return None
        path = str(Path(default_path).expanduser().resolve())
        return BreakpointSpec(path=path, line=line_num)

    cwd = cwd or Path.cwd()
    path_part = s

    if "#L" in s:
        left, right = s.rsplit("#L", 1)
        if right.strip().isdigit():
            path_part = left
            line_num = int(right.strip())
    elif ":" in s:
        left, right = s.rsplit(":", 1)
        if right.strip().isdigit():
            path_part = left
            line_num = int(right.strip())

    if line_num is None or line_num <= 0:
        return None

    path_s = path_part.strip()
    if not path_s:
        return None

    p = Path(path_s).expanduser()
    if not p.is_absolute():
        p = cwd / p
    path = str(p.resolve())
    return BreakpointSpec(path=path, line=line_num)


class BreakpointDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Add breakpoint", id="bp_title"),
            Input(placeholder="path:line  (e.g. app/service.py:42)", id="bp_input"),
            Static("Enter to toggle • Esc to close", id="bp_hint"),
            id="bp_root",
        )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted, "#bp_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        store = self._ctx.services.get(SESSION_STORE)
        default_path = store.snapshot().source_path
        spec = parse_breakpoint_spec(event.value, default_path=default_path)
        if spec is None:
            hint = "Invalid breakpoint. Use: path:line (e.g. app/service.py:42)."
            self.query_one("#bp_hint", Static).update(hint)
            return

        manager: SessionManager | None
        try:
            manager = self._ctx.services.get(SESSION_MANAGER)
        except KeyError:
            manager = None

        if manager is None:
            self._ctx.host.notify("No session backend available.", timeout=2.0)
            self.app.pop_screen()
            return

        self._ctx.host.notify(
            f"Toggling breakpoint: {Path(spec.path).name}:{spec.line}", timeout=2.0
        )

        async def _toggle() -> None:
            try:
                await manager.toggle_breakpoint(spec.path, spec.line)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        self._task = asyncio.create_task(_toggle())
        self.app.pop_screen()
