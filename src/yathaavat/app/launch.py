from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from yathaavat.core import SESSION_MANAGER, AppContext, SessionManager


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    argv: list[str]


def parse_launch_spec(value: str) -> LaunchSpec | None:
    s = value.strip()
    if not s:
        return None
    try:
        argv = shlex.split(s)
    except ValueError:
        return None
    if not argv:
        return None
    return LaunchSpec(argv=argv)


class LaunchDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._launch_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Launch under debugpy", id="launch_title"),
            Input(
                placeholder="script.py [args…]  |  -m pkg.module [args…]  |  -c 'code'",
                id="launch_input",
            ),
            Static("Enter to launch • Esc to close", id="launch_hint"),
            id="launch_root",
        )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted, "#launch_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        spec = parse_launch_spec(event.value)
        if spec is None:
            self.query_one("#launch_hint", Static).update("Invalid command.")
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

        self._ctx.host.notify("Launching…", timeout=2.0)

        async def _launch() -> None:
            try:
                await manager.launch(spec.argv)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        self._launch_task = asyncio.create_task(_launch())
        self.app.pop_screen()

    def on_unmount(self) -> None:
        # Do not cancel the launch task on unmount; the screen is closed immediately
        # after starting it, and canceling would abort the launch.
        pass
