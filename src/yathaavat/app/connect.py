from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from yathaavat.app.fuzzy import fuzzy_match
from yathaavat.app.picker_history import HistoryEntry, PickerHistory
from yathaavat.app.server_discovery import (
    DiscoveredServer,
    discover_debugpy_servers,
    probe_history_entries,
)
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
            port = int(s)
        except ValueError:
            return None
        if not (0 < port < 65536):
            return None
        return HostPort(host="127.0.0.1", port=port)
    host, port_s = s.rsplit(":", 1)
    host = host.strip() or "127.0.0.1"
    try:
        port = int(port_s.strip())
    except ValueError:
        return None
    if not (0 < port < 65536):
        return None
    return HostPort(host=host, port=port)


def _relative_time(timestamp: float) -> str:
    delta = time.time() - timestamp
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


class ConnectPicker(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "app.pop_screen", "Close"),
        ("r", "refresh", "Refresh"),
    ]

    query_text: reactive[str] = reactive("")

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._history = PickerHistory("connect")
        self._entries: list[HistoryEntry] = []
        self._servers: list[DiscoveredServer] = []
        self._liveness: dict[tuple[str, int], bool] = {}
        self._discover_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._loading = True

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Connect to debugpy", id="connect_title"),
            Input(
                placeholder="Type to search, or enter host:port…",
                id="connect_input",
            ),
            ListView(id="connect_list"),
            id="connect_root",
        )

    def on_mount(self) -> None:
        self.query_one("#connect_input", Input).focus()
        self._entries = self._history.load()
        self._discover_task = asyncio.create_task(self._discover())
        self._refresh_results()

    def on_unmount(self) -> None:
        if self._discover_task is not None:
            self._discover_task.cancel()

    async def _discover(self) -> None:
        try:
            servers, liveness = await asyncio.gather(
                discover_debugpy_servers(),
                self._probe_history(),
            )
            self._servers = servers
            self._liveness = liveness
        except Exception:
            self._servers = []
            self._liveness = {}
        self._loading = False
        self._refresh_results()

    async def _probe_history(self) -> dict[tuple[str, int], bool]:
        pairs: list[tuple[str, int]] = []
        for entry in self._entries:
            hp = parse_host_port(entry.command)
            if hp is not None:
                pairs.append((hp.host, hp.port))
        if not pairs:
            return {}
        return await probe_history_entries(pairs)

    def action_refresh(self) -> None:
        if self._discover_task is not None:
            self._discover_task.cancel()
        self._loading = True
        self._refresh_results()
        self._discover_task = asyncio.create_task(self._discover())

    @on(Input.Changed, "#connect_input")
    def _on_query(self, event: Input.Changed) -> None:
        self.query_text = event.value

    def watch_query_text(self) -> None:
        self._refresh_results()

    def _refresh_results(self) -> None:
        lv = self.query_one("#connect_list", ListView)
        lv.clear()

        q = self.query_text.strip()
        rows = self._build_rows(q)

        if not rows and self._loading:
            li = ListItem(Static("[dim]Scanning for servers…[/]", classes="connect_row"))
            lv.append(li)
            return

        if not rows and q:
            li = ListItem(
                Static(
                    "[dim]No matches. Press Enter to connect manually.[/]", classes="connect_row"
                )
            )
            lv.append(li)
            return

        for row in rows[:20]:
            li = ListItem(Static(row.label, classes="connect_row"))
            li.connect_host = row.host  # type: ignore[attr-defined]
            li.connect_port = row.port  # type: ignore[attr-defined]
            lv.append(li)

    @dataclass(frozen=True, slots=True)
    class _Row:
        label: str
        host: str
        port: int
        kind: str  # "discovered" | "history"
        score: int

    def _build_rows(self, query: str) -> list[_Row]:
        rows: list[ConnectPicker._Row] = []

        # Discovered servers
        for srv in self._servers:
            haystack = f"{srv.host}:{srv.port} {srv.process_name}"
            if query:
                m = fuzzy_match(query, haystack)
                if m is None:
                    continue
                score = m.score
            else:
                score = 0
            pid_str = f"PID {srv.pid}" if srv.pid else ""
            label = (
                f"  [green]●[/] {srv.host}:{srv.port}"
                f"  [bold]{srv.process_name}[/]  [dim]{pid_str}[/]"
            )
            rows.append(
                self._Row(
                    label=label,
                    host=srv.host,
                    port=srv.port,
                    kind="discovered",
                    score=score,
                )
            )

        # History entries
        for entry in self._entries:
            hp = parse_host_port(entry.command)
            if hp is None:
                continue
            alive = self._liveness.get((hp.host, hp.port), False)
            indicator = "[green]●[/]" if alive else "[dim]○[/]"
            age = _relative_time(entry.timestamp)
            haystack = f"{hp.host}:{hp.port} {entry.label}"
            if query:
                m = fuzzy_match(query, haystack)
                if m is None:
                    continue
                score = m.score
            else:
                score = 100
            # Skip history entries that duplicate a discovered server
            if any(s.host == hp.host and s.port == hp.port for s in self._servers):
                continue
            label = f"  {indicator} {hp.host}:{hp.port}  [dim]{age}[/]"
            rows.append(
                self._Row(
                    label=label,
                    host=hp.host,
                    port=hp.port,
                    kind="history",
                    score=score,
                )
            )

        if query:
            rows.sort(key=lambda r: (r.score, f"{r.host}:{r.port}"))
        else:
            discovered = [r for r in rows if r.kind == "discovered"]
            history = [r for r in rows if r.kind == "history"]
            rows = discovered + history

        return rows

    @on(Input.Submitted, "#connect_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        lv = self.query_one("#connect_list", ListView)
        if lv.index is not None and lv.index >= 0:
            items = list(lv.children)
            if lv.index < len(items):
                item = items[lv.index]
                host = getattr(item, "connect_host", None)
                port = getattr(item, "connect_port", None)
                if isinstance(host, str) and isinstance(port, int):
                    self._do_connect(host, port, event.value)
                    return

        # Fall back to raw input
        hp = parse_host_port(event.value)
        if hp is None:
            self._ctx.host.notify("Invalid host:port.", timeout=2.0)
            return
        self._do_connect(hp.host, hp.port, event.value)

    @on(ListView.Selected, "#connect_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        host = getattr(event.item, "connect_host", None)
        port = getattr(event.item, "connect_port", None)
        if isinstance(host, str) and isinstance(port, int):
            self._do_connect(host, port, f"{host}:{port}")

    def _do_connect(self, host: str, port: int, raw: str) -> None:
        manager: SessionManager | None
        try:
            manager = self._ctx.services.get(SESSION_MANAGER)
        except KeyError:
            manager = None

        if manager is None:
            self._ctx.host.notify("No session backend available.", timeout=2.0)
            self.app.pop_screen()
            return

        # Save to history
        self._history.push(
            HistoryEntry(
                command=f"{host}:{port}",
                label=raw.strip(),
                timestamp=PickerHistory.now(),
            )
        )

        self._ctx.host.notify(f"Connecting to {host}:{port}…", timeout=2.0)

        async def _connect() -> None:
            try:
                await manager.connect(host, port)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        task = asyncio.create_task(_connect())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self.app.pop_screen()
