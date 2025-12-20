from __future__ import annotations

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
class HostPort:
    host: str
    port: int


def parse_host_port(value: str) -> HostPort | None:
    s = value.strip()
    if not s:
        return None
    if ":" not in s:
        try:
            return HostPort(host="127.0.0.1", port=int(s))
        except ValueError:
            return None
    host, port_s = s.rsplit(":", 1)
    host = host.strip() or "127.0.0.1"
    try:
        port = int(port_s.strip())
    except ValueError:
        return None
    if not (0 < port < 65536):
        return None
    return HostPort(host=host, port=port)


class ConnectDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._connect_task: object | None = None

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Connect to debugpy", id="connect_title"),
            Input(placeholder="host:port  (e.g. 127.0.0.1:5678)", id="connect_input"),
            Static("Enter to connect • Esc to close", id="connect_hint"),
            id="connect_root",
        )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted, "#connect_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        hp = parse_host_port(event.value)
        if hp is None:
            self.query_one("#connect_hint", Static).update("Invalid host:port.")
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

        self._ctx.host.notify(f"Connecting to {hp.host}:{hp.port}…", timeout=2.0)

        async def _connect() -> None:
            try:
                await manager.connect(hp.host, hp.port)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        import asyncio

        self._connect_task = asyncio.create_task(_connect())
        self.app.pop_screen()
