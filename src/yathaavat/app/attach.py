from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from yathaavat.core import SESSION_MANAGER, AppContext, SafeAttachManager, SessionManager
from yathaavat.core.processes import PROCESS_DISCOVERY, ProcessInfo


@dataclass(frozen=True, slots=True)
class _Row:
    pid: int
    label: str
    detail: str
    dap_endpoint: tuple[str, int] | None = None
    supports_safe_attach: bool = False


class AttachPicker(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "app.pop_screen", "Close"),
        ("r", "refresh", "Refresh"),
        ("t", "toggle_all", "Toggle All"),
    ]

    query_text = reactive("")
    show_non_python = reactive(False)

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._processes: list[ProcessInfo] = []
        self._loading = False
        self._attach_task: asyncio.Task[None] | None = None
        self._load_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Attach to Process", id="attach_title"),
            Input(placeholder="Search PID / command…", id="attach_input"),
            ListView(id="attach_list"),
            id="attach_root",
        )

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self.action_refresh()

    @on(Input.Changed, "#attach_input")
    def _on_query(self, event: Input.Changed) -> None:
        self.query_text = event.value
        self._refresh_results()

    @on(ListView.Selected, "#attach_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        item = event.item
        pid = getattr(item, "pid", None)
        if not isinstance(pid, int):
            return
        dap_endpoint = getattr(item, "dap_endpoint", None)
        manager: SessionManager | None
        try:
            manager = self._ctx.services.get(SESSION_MANAGER)
        except KeyError:
            manager = None

        if manager is None:
            if isinstance(dap_endpoint, tuple) and len(dap_endpoint) == 2:
                self._ctx.host.notify(f"connect to {dap_endpoint[0]}:{dap_endpoint[1]} (prototype)")
            else:
                self._ctx.host.notify(f"attach to pid {pid} (prototype)")
            self.app.pop_screen()
            return

        safe_manager = manager if isinstance(manager, SafeAttachManager) else None

        async def _attach() -> None:
            try:
                if isinstance(dap_endpoint, tuple) and len(dap_endpoint) == 2:
                    host, port = dap_endpoint
                    if not isinstance(host, str) or not isinstance(port, int):
                        raise TypeError("Invalid DAP endpoint")
                    self._ctx.host.notify(f"Connecting to {host}:{port}…", timeout=2.0)
                    await manager.connect(host, port)
                elif safe_manager is not None and getattr(item, "supports_safe_attach", False):
                    self._ctx.host.notify(f"Safe-attaching to PID {pid}…", timeout=2.0)
                    await safe_manager.safe_attach(pid)
                else:
                    self._ctx.host.notify(f"Attaching to PID {pid}…", timeout=2.0)
                    await manager.attach(pid)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        self._attach_task = asyncio.create_task(_attach())
        self.app.pop_screen()

    def action_refresh(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._set_title("Attach to Process — scanning…")
        self._load_task = asyncio.create_task(self._load_processes())

    def action_toggle_all(self) -> None:
        self.show_non_python = not self.show_non_python
        self._refresh_results()

    def on_unmount(self) -> None:
        if self._load_task is not None:
            self._load_task.cancel()

    async def _load_processes(self) -> None:
        try:
            discovery = self._ctx.services.get(PROCESS_DISCOVERY)
        except KeyError:
            self._processes = []
            self._loading = False
            self._set_title("Attach to Process — no discovery service")
            self._refresh_results()
            return

        self._processes = await asyncio.to_thread(discovery.list_processes)
        self._loading = False
        self._set_title(f"Attach to Process — {len(self._processes)} found")
        self._refresh_results()

    def _set_title(self, text: str) -> None:
        self.query_one("#attach_title", Static).update(text)

    def _rows(self) -> list[_Row]:
        q = self.query_text.strip().lower()
        out: list[_Row] = []
        for proc in self._processes:
            if not self.show_non_python and not proc.is_python:
                continue
            dap_endpoint = _debugpy_dap_endpoint(proc.args)
            supports_safe_attach = proc.python_version_hint == "3.14"
            py = f"  py{proc.python_version_hint or ''}".rstrip() if proc.is_python else ""
            label = f"{proc.pid:>6}  {proc.command}{py}"
            if dap_endpoint is not None:
                host, port = dap_endpoint
                label = f"{label}  dap {host}:{port}"
            elif supports_safe_attach:
                label = f"{label}  safe"
            detail = proc.args
            if q and q not in label.lower() and q not in detail.lower():
                continue
            out.append(
                _Row(
                    pid=proc.pid,
                    label=label,
                    detail=_truncate(detail, 110),
                    dap_endpoint=dap_endpoint,
                    supports_safe_attach=supports_safe_attach,
                )
            )
        out.sort(key=lambda r: r.pid)
        return out

    def _refresh_results(self) -> None:
        lv = self.query_one(ListView)
        lv.clear()
        if self._loading:
            lv.append(ListItem(Static("Scanning…")))
            return
        if not self._processes:
            lv.append(ListItem(Static("No processes found.")))
            return
        rows = self._rows()
        if not rows:
            hint = "Press [b]t[/b] to include non-Python processes."
            lv.append(ListItem(Static(f"No matches.\n{hint}")))
            return
        for row in rows:
            li = ListItem(
                Static(f"{row.label}\n{row.detail}", classes="attach_row"),
            )
            li.pid = row.pid  # type: ignore[attr-defined]
            li.dap_endpoint = row.dap_endpoint  # type: ignore[attr-defined]
            li.supports_safe_attach = row.supports_safe_attach  # type: ignore[attr-defined]
            lv.append(li)


def _truncate(text: str, max_len: int) -> str:
    s = text.strip()
    if len(s) <= max_len:
        return s
    return f"{s[: max_len - 1]}…"


_DEBUGPY_LISTEN_RE = re.compile(r"(?:^|\s)--listen(?:\s|$)")


def _debugpy_dap_endpoint(args: str) -> tuple[str, int] | None:
    if not _DEBUGPY_LISTEN_RE.search(args):
        return None
    try:
        tokens = shlex.split(args, posix=True)
    except ValueError:
        tokens = args.split()

    host = "127.0.0.1"
    port: int | None = None
    for idx, token in enumerate(tokens):
        if token == "--listen" and idx + 1 < len(tokens):
            value = tokens[idx + 1]
            if ":" in value:
                maybe_host, maybe_port = value.rsplit(":", 1)
                maybe_host = maybe_host.strip() or "127.0.0.1"
                try:
                    port = int(maybe_port.strip())
                    host = maybe_host
                except ValueError:
                    port = None
            else:
                try:
                    port = int(value.strip())
                except ValueError:
                    port = None
        elif token == "--host" and idx + 1 < len(tokens):
            # Some debugpy invocations use split host/port flags.
            host = tokens[idx + 1]
        elif token == "--port" and idx + 1 < len(tokens):
            try:
                port = int(tokens[idx + 1])
            except ValueError:
                port = None
    if port is None:
        return None
    return host, port
