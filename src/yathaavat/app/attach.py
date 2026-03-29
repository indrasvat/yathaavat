from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
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
    safe_attach_candidate: bool = False
    safe_attach_enabled: bool = False


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

    @on(Input.Submitted, "#attach_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        rows = self._rows()
        if not rows:
            return
        q = event.value.strip()
        chosen = rows[0]
        if q.isdigit():
            pid = int(q)
            chosen = next((r for r in rows if r.pid == pid), chosen)
        self._start_attach(
            pid=chosen.pid,
            dap_endpoint=chosen.dap_endpoint,
            safe_attach_candidate=chosen.safe_attach_candidate,
            safe_attach_enabled=chosen.safe_attach_enabled,
        )

    @on(ListView.Selected, "#attach_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        item = event.item
        pid = getattr(item, "pid", None)
        if not isinstance(pid, int):
            return
        dap_endpoint = getattr(item, "dap_endpoint", None)
        safe_attach_candidate = bool(getattr(item, "safe_attach_candidate", False))
        safe_attach_enabled = bool(getattr(item, "safe_attach_enabled", False))
        self._start_attach(
            pid=pid,
            dap_endpoint=dap_endpoint if isinstance(dap_endpoint, tuple) else None,
            safe_attach_candidate=safe_attach_candidate,
            safe_attach_enabled=safe_attach_enabled,
        )

    def _start_attach(
        self,
        *,
        pid: int,
        dap_endpoint: tuple[str, int] | None,
        safe_attach_candidate: bool,
        safe_attach_enabled: bool,
    ) -> None:
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
                inferred: tuple[str, int] | None = None
                if dap_endpoint is None:
                    inferred = await _infer_debugpy_dap_endpoint(pid)
                if inferred is not None:
                    host, port = inferred
                    self._ctx.host.notify(
                        f"Found debugpy on {host}:{port}. Connecting…", timeout=2.0
                    )
                    await manager.connect(host, port)
                elif isinstance(dap_endpoint, tuple) and len(dap_endpoint) == 2:
                    host, port = dap_endpoint
                    if not isinstance(host, str) or not isinstance(port, int):
                        raise TypeError("Invalid DAP endpoint")
                    self._ctx.host.notify(f"Connecting to {host}:{port}…", timeout=2.0)
                    await manager.connect(host, port)
                elif safe_manager is not None and safe_attach_enabled:
                    self._ctx.host.notify(f"Safe-attaching to PID {pid}…", timeout=2.0)
                    await safe_manager.safe_attach(pid)
                else:
                    if safe_manager is not None and safe_attach_candidate:
                        self._ctx.host.notify(
                            "Safe attach requires elevated privileges on this platform; "
                            "falling back to debugpy --pid.",
                            timeout=3.0,
                        )
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
            adapter_endpoint = _debugpy_adapter_endpoint(proc.args)
            is_adapter = adapter_endpoint is not None
            dap_endpoint = _debugpy_dap_endpoint(proc.args) or adapter_endpoint
            safe_attach_candidate = proc.python_version_hint == "3.14" and not is_adapter
            safe_attach_enabled = safe_attach_candidate and _safe_attach_enabled()
            py = f"  py{proc.python_version_hint or ''}".rstrip() if proc.is_python else ""
            name = "debugpy.adapter" if is_adapter else proc.command
            label = f"{proc.pid:>6}  {name}{py}"
            if dap_endpoint is not None:
                host, port = dap_endpoint
                label = f"{label}  dap {host}:{port}"
            elif safe_attach_candidate:
                label = f"{label}  safe" if safe_attach_enabled else f"{label}  safe (sudo)"
            detail = proc.args
            if q and q not in label.lower() and q not in detail.lower():
                continue
            out.append(
                _Row(
                    pid=proc.pid,
                    label=label,
                    detail=_truncate(detail, 110),
                    dap_endpoint=dap_endpoint,
                    safe_attach_candidate=safe_attach_candidate,
                    safe_attach_enabled=safe_attach_enabled,
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
            li.safe_attach_candidate = row.safe_attach_candidate  # type: ignore[attr-defined]
            li.safe_attach_enabled = row.safe_attach_enabled  # type: ignore[attr-defined]
            lv.append(li)


def _truncate(text: str, max_len: int) -> str:
    s = text.strip()
    if len(s) <= max_len:
        return s
    return f"{s[: max_len - 1]}…"


def _safe_attach_enabled() -> bool:
    # On macOS, `sys.remote_exec` currently requires task port privileges (root or entitlement).
    if sys.platform == "darwin":
        geteuid = getattr(os, "geteuid", None)
        return callable(geteuid) and geteuid() == 0
    return True


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


_LSOF_LISTEN_RE = re.compile(r"TCP\s+(?P<addr>\S+?):(?P<port>\d+)\s+\(LISTEN\)")
_LSOF_ESTABLISHED_RE = re.compile(
    r"TCP\s+(?P<laddr>\S+?):(?P<lport>\d+)->(?P<raddr>\S+?):(?P<rport>\d+)\s+\(ESTABLISHED\)"
)


def _is_debugpy_adapter_args(args: str) -> bool:
    return "debugpy/adapter" in args or "debugpy.adapter" in args


def _is_loopback(addr: str) -> bool:
    if addr.startswith("[") and addr.endswith("]"):
        addr = addr[1:-1]
    return addr in {"127.0.0.1", "::1", "localhost"}


def _debugpy_adapter_endpoint(args: str) -> tuple[str, int] | None:
    if not _is_debugpy_adapter_args(args):
        return None
    try:
        tokens = shlex.split(args, posix=True)
    except ValueError:
        tokens = args.split()
    host = "127.0.0.1"
    port: int | None = None
    for idx, token in enumerate(tokens):
        if token == "--host" and idx + 1 < len(tokens):
            host = tokens[idx + 1]
        elif token == "--port" and idx + 1 < len(tokens):
            try:
                port = int(tokens[idx + 1])
            except ValueError:
                port = None
    if port is None:
        return None
    return host, port


def _list_listening_tcp_endpoints(pid: int) -> list[tuple[str, int]]:
    """Best-effort `lsof` probe for LISTEN sockets owned by a PID.

    Returns (host, port) tuples suitable for a quick localhost DAP probe.
    """
    try:
        completed = subprocess.run(
            ["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []

    endpoints: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for line in (completed.stdout or "").splitlines():
        match = _LSOF_LISTEN_RE.search(line)
        if not match:
            continue
        addr = match.group("addr")
        port_s = match.group("port")
        try:
            port = int(port_s)
        except ValueError:
            continue
        host: str
        if addr in {"*", "0.0.0.0"}:
            host = "127.0.0.1"
        elif addr.startswith("[") and addr.endswith("]"):
            host = addr[1:-1]
        else:
            host = addr
        ep = (host, port)
        if ep in seen:
            continue
        seen.add(ep)
        endpoints.append(ep)
    return endpoints


def _list_established_remote_ports(pid: int) -> list[int]:
    """Best-effort `lsof` probe for remote ports on ESTABLISHED TCP sockets owned by PID."""
    try:
        completed = subprocess.run(
            ["lsof", "-nP", "-a", "-p", str(pid), "-iTCP"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []

    ports: list[int] = []
    seen: set[int] = set()
    for line in (completed.stdout or "").splitlines():
        match = _LSOF_ESTABLISHED_RE.search(line)
        if not match:
            continue
        if not _is_loopback(match.group("raddr")):
            continue
        try:
            rport = int(match.group("rport"))
        except ValueError:
            continue
        if rport in seen:
            continue
        seen.add(rport)
        ports.append(rport)
    return ports


def _listener_pids_for_port(port: int) -> list[int]:
    try:
        completed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    out: list[int] = []
    for line in (completed.stdout or "").splitlines():
        try:
            out.append(int(line.strip()))
        except ValueError:
            continue
    return out


def _ps_args(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "args="],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip()


async def _probe_dap_endpoint(host: str, port: int, *, timeout_s: float = 0.25) -> bool:
    """Return True if (host, port) speaks the DAP framing protocol."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout_s
        )
    except (OSError, TimeoutError):
        return False

    try:
        payload = json.dumps(
            {
                "seq": 1,
                "type": "request",
                "command": "initialize",
                "arguments": {
                    "clientID": "yathaavat-probe",
                    "adapterID": "python",
                    "pathFormat": "path",
                    "linesStartAt1": True,
                    "columnsStartAt1": True,
                },
            }
        )
        raw = payload.encode("utf-8")
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        writer.write(header + raw)
        await writer.drain()
        data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout_s)
        return data.startswith(b"Content-Length:")
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        return False
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


async def _infer_debugpy_dap_endpoint(pid: int) -> tuple[str, int] | None:
    """Best-effort discovery of an already-listening debugpy DAP endpoint for PID."""
    # `debugpy.listen()` starts a detached adapter process on macOS. The debuggee won't own the
    # DAP LISTEN socket. Instead, it holds an established connection to an adapter-owned internal
    # port. Use that connection to find the adapter PID, then extract the DAP port from its args.
    remote_ports = await asyncio.to_thread(_list_established_remote_ports, pid)
    for rport in remote_ports[:15]:
        for adapter_pid in _listener_pids_for_port(rport):
            args = _ps_args(adapter_pid)
            if not isinstance(args, str) or not args:
                continue
            endpoint = _debugpy_adapter_endpoint(args)
            if endpoint is not None:
                return endpoint

    endpoints = await asyncio.to_thread(_list_listening_tcp_endpoints, pid)
    # Common case: services listen on localhost; probe in-order and stop early.
    for host, port in endpoints[:25]:
        if await _probe_dap_endpoint(host, port):
            return host, port
        # If we got an IPv6 listen socket, also try loopback v4 (and vice versa) for * binds.
        if host == "127.0.0.1" and await _probe_dap_endpoint("::1", port):
            return "::1", port
        if host == "::1" and await _probe_dap_endpoint("127.0.0.1", port):
            return "127.0.0.1", port
    return None
