from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from time import monotonic
from typing import override

from platformdirs import user_cache_path

from yathaavat.app.connect import ConnectDialog
from yathaavat.app.launch import LaunchDialog
from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    BreakpointInfo,
    Command,
    CommandSpec,
    FrameInfo,
    Plugin,
    SessionState,
    SessionStore,
    ThreadInfo,
    UiHost,
    VariableInfo,
)
from yathaavat.core.dap import DapClient, DapRequestError
from yathaavat.core.services import ServiceRegistrationError
from yathaavat.core.session import SessionManager


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        _host, port = s.getsockname()
        return int(port)


def _body(response: dict[str, object]) -> dict[str, object]:
    body = response.get("body")
    return body if isinstance(body, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _parse_variables(items: list[object]) -> list[VariableInfo]:
    variables: list[VariableInfo] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        vtype = item.get("type")
        variables.append(
            VariableInfo(
                name=name,
                value=value,
                type=vtype if isinstance(vtype, str) else None,
                variables_reference=int(item.get("variablesReference") or 0),
            )
        )
    return variables


@dataclass(frozen=True, slots=True)
class _BreakpointConfig:
    condition: str | None = None
    hit_condition: str | None = None
    log_message: str | None = None


@dataclass(slots=True)
class DebugpySessionManager(SessionManager):
    store: SessionStore
    host: UiHost
    _dap: DapClient | None = None
    _initialized: asyncio.Event = field(default_factory=asyncio.Event)
    _breakpoints: dict[str, dict[int, _BreakpointConfig]] = field(default_factory=dict)
    _run_to_cursor_target: tuple[str, int] | None = None
    _run_to_cursor_added: bool = False
    _launched: asyncio.subprocess.Process | None = None
    _launch_output_task: asyncio.Task[None] | None = None
    _capture_launch_output: bool = False
    _auto_resume_pending: bool = False

    async def connect(self, host: str, port: int) -> None:
        await self.disconnect()
        self.store.update(
            backend="debugpy", python=f"{sys.version_info.major}.{sys.version_info.minor}"
        )
        self.store.append_transcript(f"Connecting to debugpy server {host}:{port}…")
        await self._connect_with_timeout(host, port, timeout_s=6.0)

    async def _connect_with_timeout(self, host: str, port: int, *, timeout_s: float) -> None:
        reader, writer = await self._open_connection_retry(host, port, timeout_s=timeout_s)
        self._dap = DapClient(reader=reader, writer=writer)
        self._dap.on_event(self._on_event)
        self._dap.on_disconnect(self._on_disconnect)
        self._dap.start()

        try:
            await self._dap.request(
                "initialize",
                {
                    "clientID": "yathaavat",
                    "adapterID": "python",
                    "pathFormat": "path",
                    "linesStartAt1": True,
                    "columnsStartAt1": True,
                    "supportsVariableType": True,
                    "supportsVariablePaging": True,
                },
            )
            attach_task = asyncio.create_task(
                self._dap.request(
                    "attach",
                    {
                        "name": "yathaavat",
                        "type": "python",
                        "request": "attach",
                        "justMyCode": False,
                        "redirectOutput": True,
                    },
                    timeout_s=20.0,
                )
            )
            await asyncio.wait_for(self._initialized.wait(), timeout=10.0)
            await self._sync_all_breakpoints()
            config_task = asyncio.create_task(self._dap.request("configurationDone", {}))
            await attach_task
            await config_task
        except (ConnectionError, DapRequestError, TimeoutError) as exc:
            self.store.append_transcript(f"Attach failed: {exc}")
            await self._hard_disconnect()
            raise

        if self.store.snapshot().state != SessionState.PAUSED:
            self.store.update(state=SessionState.RUNNING)
        await self._refresh_threads()
        self.store.append_transcript("Connected.")
        self._capture_launch_output = False

    async def attach(self, pid: int) -> None:
        port = _pick_free_port()
        self.store.update(pid=pid)
        self.store.append_transcript(f"Injecting debugpy into PID {pid} (listen 127.0.0.1:{port})…")

        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [
                    sys.executable,
                    "-m",
                    "debugpy",
                    "--listen",
                    f"127.0.0.1:{port}",
                    "--pid",
                    str(pid),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10.0,
            )
        except subprocess.TimeoutExpired as exc:
            msg = (
                "PID attach timed out. On macOS this often requires elevated privileges, "
                "or it may be unsupported by the OS debugger security policy."
            )
            raw_detail = exc.stderr or exc.stdout or ""
            match raw_detail:
                case bytes() | bytearray():
                    detail = raw_detail.decode(errors="replace").strip()
                case str():
                    detail = raw_detail.strip()
                case _:
                    detail = str(raw_detail).strip()
            if detail:
                msg = f"{msg}\n{detail}".rstrip()
            self.store.append_transcript(msg)
            raise TimeoutError(msg) from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"exit {completed.returncode}"
            self.store.append_transcript(f"PID attach failed: {detail}")
            raise RuntimeError(detail)

        await self.connect("127.0.0.1", port)
        await self.pause()

    async def safe_attach(self, pid: int) -> None:
        """Attach using Python 3.14's `sys.remote_exec` (PEP 768) to bootstrap debugpy."""

        await self.disconnect()
        self.store.update(
            backend="debugpy", python=f"{sys.version_info.major}.{sys.version_info.minor}", pid=pid
        )

        host = "127.0.0.1"
        port = _pick_free_port()
        token = token_hex(8)
        remote_dir = _remote_exec_dir()
        script_path = remote_dir / f"attach_{pid}_{token}.py"
        status_path = remote_dir / f"attach_{pid}_{token}.json"

        script_path.write_text(
            _remote_exec_script(status_path=status_path, host=host, port=port),
            encoding="utf-8",
        )

        self.store.append_transcript(f"Safe attach via sys.remote_exec to PID {pid}…")
        self.store.append_transcript(f"Starting debugpy server on {host}:{port}…")

        try:
            await asyncio.to_thread(sys.remote_exec, pid, str(script_path))
        except Exception as exc:
            self.store.append_transcript(f"sys.remote_exec failed: {exc}")
            raise

        try:
            await self._await_remote_exec_status(status_path, timeout_s=20.0)
            self.store.append_transcript("Remote exec started debugpy.")
            await self._connect_with_timeout(host, port, timeout_s=25.0)
            await self.pause()
        finally:
            # Ensure the remote process has executed the script before removing it.
            if status_path.exists():
                script_path.unlink(missing_ok=True)

    async def launch(self, target_argv: list[str]) -> None:
        if not target_argv:
            raise ValueError("Launch requires a target (e.g. script.py or -m module)")

        await self.disconnect()
        await self._terminate_launched()

        port = _pick_free_port()
        self.store.append_transcript(f"Launching under debugpy on 127.0.0.1:{port}…")
        self._capture_launch_output = True
        self._launched = await asyncio.create_subprocess_exec(
            sys.executable,
            "-Xfrozen_modules=off",
            "-m",
            "debugpy",
            "--listen",
            f"127.0.0.1:{port}",
            "--wait-for-client",
            *target_argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        if self._launched.stdout is not None:
            self._launch_output_task = asyncio.create_task(
                self._drain_launch_output(self._launched)
            )

        self._auto_resume_pending = True
        self.store.update(
            backend="debugpy", python=f"{sys.version_info.major}.{sys.version_info.minor}"
        )
        self.store.append_transcript(f"Connecting to debugpy server 127.0.0.1:{port}…")
        await self._connect_with_timeout("127.0.0.1", port, timeout_s=6.0)

    async def disconnect(self) -> None:
        if self._dap is not None:
            try:
                await self._dap.request("disconnect", {"terminateDebuggee": False}, timeout_s=2.0)
            except Exception:
                pass
        await self._hard_disconnect()

    async def terminate(self) -> None:
        if self._dap is not None:
            try:
                await self._dap.request("disconnect", {"terminateDebuggee": True}, timeout_s=2.0)
            except Exception:
                pass
        await self._hard_disconnect()
        await self._terminate_launched()

    async def shutdown(self) -> None:
        await self.disconnect()
        await self._terminate_launched()

    async def resume(self) -> None:
        dap = self._require_dap()
        thread_id = self._require_thread()
        await dap.request("continue", {"threadId": thread_id})
        self.store.update(
            state=SessionState.RUNNING,
            frames=(),
            locals=(),
            selected_frame_id=None,
            source_path=None,
            source_line=None,
            source_col=None,
        )

    async def pause(self) -> None:
        dap = self._require_dap()
        thread_id = self._require_thread()
        await dap.request("pause", {"threadId": thread_id})

    async def step_over(self) -> None:
        dap = self._require_dap()
        thread_id = self._require_thread()
        await dap.request("next", {"threadId": thread_id})

    async def step_in(self) -> None:
        dap = self._require_dap()
        thread_id = self._require_thread()
        await dap.request("stepIn", {"threadId": thread_id})

    async def step_out(self) -> None:
        dap = self._require_dap()
        thread_id = self._require_thread()
        await dap.request("stepOut", {"threadId": thread_id})

    async def select_frame(self, frame_id: int) -> None:
        frame = next((f for f in self.store.snapshot().frames if f.id == frame_id), None)
        self.store.update(
            selected_frame_id=frame_id,
            source_path=frame.path if frame is not None else None,
            source_line=frame.line if frame is not None else None,
            source_col=None,
        )
        await self._refresh_locals(frame_id)

    async def select_thread(self, thread_id: int) -> None:
        snap = self.store.snapshot()
        if snap.state != SessionState.PAUSED:
            raise RuntimeError("Thread selection requires PAUSED state")
        if not any(t.id == thread_id for t in snap.threads):
            raise ValueError(f"Unknown thread: {thread_id}")

        name = next((t.name for t in snap.threads if t.id == thread_id), "")
        label = f"{thread_id}" if not name else f"{thread_id} ({name})"
        self.store.append_transcript(f"Selecting thread {label}…")
        self.store.update(selected_thread_id=thread_id)
        await self._refresh_frames(thread_id)

    async def evaluate(self, expression: str) -> str:
        dap = self._require_dap()
        frame_id = self.store.snapshot().selected_frame_id
        args: dict[str, object] = {"expression": expression, "context": "repl"}
        if isinstance(frame_id, int):
            args["frameId"] = frame_id
        resp = await dap.request("evaluate", args)
        result = str(_body(resp).get("result") or "")
        self.store.append_transcript(f">>> {expression}\n{result}")
        return result

    async def evaluate_silent(self, expression: str) -> str:
        dap = self._require_dap()
        frame_id = self.store.snapshot().selected_frame_id
        args: dict[str, object] = {"expression": expression, "context": "watch"}
        if isinstance(frame_id, int):
            args["frameId"] = frame_id
        resp = await dap.request("evaluate", args)
        return str(_body(resp).get("result") or "")

    async def get_variables(self, variables_reference: int) -> tuple[VariableInfo, ...]:
        if variables_reference <= 0:
            return ()
        dap = self._require_dap()
        resp = await dap.request("variables", {"variablesReference": variables_reference})
        return tuple(_parse_variables(_as_list(_body(resp).get("variables"))))

    async def toggle_breakpoint(self, path: str, line: int) -> None:
        path = str(Path(path).expanduser().resolve())
        if line <= 0:
            raise ValueError("Invalid line number")

        configs = self._breakpoints.setdefault(path, {})
        removed = line in configs
        if removed:
            configs.pop(line, None)
        else:
            configs[line] = _BreakpointConfig()

        if not configs:
            self._breakpoints.pop(path, None)

        if self._dap is None:
            self._set_breakpoints_offline(path, sorted(configs))
            file = Path(path).name
            action = "removed" if removed else "queued"
            self.store.append_transcript(f"Breakpoint {action}: {file}:{line}")
            return

        await self._set_breakpoints(path, sorted(configs))

    async def run_to_cursor(self, path: str, line: int) -> None:
        if self._dap is None:
            raise RuntimeError("No active debug session")

        path = str(Path(path).expanduser().resolve())
        if line <= 0:
            raise ValueError("Invalid line number")

        configs = self._breakpoints.setdefault(path, {})
        already = line in configs
        if not already:
            configs[line] = _BreakpointConfig()
            await self._set_breakpoints(path, sorted(configs))

        self._run_to_cursor_target = (path, line)
        self._run_to_cursor_added = not already
        note = " (existing breakpoint)" if already else " (temporary breakpoint armed)"
        self.store.append_transcript(f"Run to cursor: {Path(path).name}:{line}{note}")
        await self.resume()

    async def set_breakpoint_config(
        self,
        path: str,
        line: int,
        *,
        condition: str | None = None,
        hit_condition: str | None = None,
        log_message: str | None = None,
    ) -> None:
        path = str(Path(path).expanduser().resolve())
        if line <= 0:
            raise ValueError("Invalid line number")

        configs = self._breakpoints.setdefault(path, {})
        configs[line] = _BreakpointConfig(
            condition=condition or None,
            hit_condition=hit_condition or None,
            log_message=log_message or None,
        )

        # Keep the map tidy.
        if not configs:
            self._breakpoints.pop(path, None)

        if self._dap is None:
            self._set_breakpoints_offline(path, sorted(configs))
            file = Path(path).name
            parts = []
            if condition:
                parts.append("if")
            if hit_condition:
                parts.append("hit")
            if log_message:
                parts.append("log")
            suffix = f" ({', '.join(parts)})" if parts else ""
            self.store.append_transcript(f"Breakpoint queued: {file}:{line}{suffix}")
            return

        # Apply to adapter.
        await self._set_breakpoints(path, sorted(configs))

    def _set_breakpoints_offline(self, path: str, lines: list[int]) -> None:
        # When disconnected, we still track and display breakpoints so they can be queued
        # and applied on the next connect/launch.
        cfgs = self._breakpoints.get(path) or {}
        updated = tuple(
            BreakpointInfo(
                path=path,
                line=line,
                condition=(cfgs.get(line) or _BreakpointConfig()).condition,
                hit_condition=(cfgs.get(line) or _BreakpointConfig()).hit_condition,
                log_message=(cfgs.get(line) or _BreakpointConfig()).log_message,
                verified=None,
                message="queued",
            )
            for line in lines
        )
        existing = tuple(bp for bp in self.store.snapshot().breakpoints if bp.path != path)
        self.store.update(
            breakpoints=tuple(sorted((*existing, *updated), key=lambda b: (b.path, b.line)))
        )

    def _require_dap(self) -> DapClient:
        if self._dap is None:
            raise RuntimeError("No active debug session")
        return self._dap

    def _require_thread(self) -> int:
        snapshot = self.store.snapshot()
        if isinstance(snapshot.selected_thread_id, int):
            return snapshot.selected_thread_id
        if snapshot.threads:
            return snapshot.threads[0].id
        raise RuntimeError("No threads available")

    async def _hard_disconnect(self) -> None:
        dap = self._dap
        if dap is not None:
            await dap.close()
        self._dap = None
        self._initialized = asyncio.Event()
        self._auto_resume_pending = False
        self._run_to_cursor_target = None
        self._run_to_cursor_added = False
        self.store.update(
            state=SessionState.DISCONNECTED,
            threads=(),
            selected_thread_id=None,
            frames=(),
            selected_frame_id=None,
            source_path=None,
            source_line=None,
            source_col=None,
            stop_reason=None,
            stop_description=None,
            locals=(),
        )

    async def _on_disconnect(self, exc: BaseException) -> None:
        detail = str(exc).strip() or exc.__class__.__name__
        self.store.append_transcript(f"Disconnected ({detail})")
        await self._hard_disconnect()

    async def _on_event(self, event: dict[str, object]) -> None:
        name = event.get("event")
        body = _body(event)
        match name:
            case "initialized":
                self._initialized.set()
            case "process":
                pid = body.get("systemProcessId")
                if isinstance(pid, int):
                    self.store.update(pid=pid)
            case "continued":
                self.store.update(
                    state=SessionState.RUNNING,
                    frames=(),
                    locals=(),
                    selected_frame_id=None,
                    source_path=None,
                    source_line=None,
                    source_col=None,
                    stop_reason=None,
                    stop_description=None,
                )
            case "stopped":
                reason = body.get("reason")
                description = body.get("description")
                thread_id = body.get("threadId")
                if isinstance(thread_id, int):
                    self.store.update(
                        state=SessionState.PAUSED,
                        selected_thread_id=thread_id,
                        stop_reason=reason if isinstance(reason, str) else None,
                        stop_description=description if isinstance(description, str) else None,
                    )
                else:
                    self.store.update(
                        state=SessionState.PAUSED,
                        stop_reason=reason if isinstance(reason, str) else None,
                        stop_description=description if isinstance(description, str) else None,
                    )
                if isinstance(reason, str):
                    self.store.append_transcript(f"Stopped ({reason})")
                await self._refresh_threads()
                thread_to_refresh = (
                    thread_id
                    if isinstance(thread_id, int)
                    else self.store.snapshot().selected_thread_id
                )
                if isinstance(thread_to_refresh, int):
                    await self._refresh_frames(thread_to_refresh)
                    await self._run_to_cursor_maybe_complete()

                if self._auto_resume_pending:
                    self._auto_resume_pending = False
                    snap = self.store.snapshot()
                    has_user_frame = any(
                        isinstance(f.path, str) and _is_user_path(f.path) for f in snap.frames
                    )
                    if not has_user_frame:
                        self.store.append_transcript("Auto-resuming (launch)…")
                        try:
                            await self.resume()
                        except Exception:
                            pass
            case "output":
                text = body.get("output")
                category = body.get("category")
                if isinstance(category, str) and category.lower() == "telemetry":
                    return
                if isinstance(text, str) and text.strip():
                    self.store.append_transcript(text.rstrip())
            case "terminated" | "exited":
                self.store.append_transcript("Session ended.")
                await self.disconnect()
            case _:
                return

    async def _run_to_cursor_maybe_complete(self) -> None:
        target = self._run_to_cursor_target
        if target is None:
            return
        target_path, target_line = target
        snap = self.store.snapshot()
        if (
            snap.state != SessionState.PAUSED
            or snap.source_path != target_path
            or snap.source_line != target_line
        ):
            return

        self._run_to_cursor_target = None
        added = self._run_to_cursor_added
        self._run_to_cursor_added = False
        if added:
            await self._clear_breakpoint_line(target_path, target_line)
        self.store.append_transcript(
            f"Run to cursor reached: {Path(target_path).name}:{target_line}"
        )

    async def _clear_breakpoint_line(self, path: str, line: int) -> None:
        configs = self._breakpoints.get(path)
        if not configs or line not in configs:
            return
        configs.pop(line, None)
        remaining = sorted(configs)
        if not remaining:
            self._breakpoints.pop(path, None)
        await self._set_breakpoints(path, remaining)

    async def _refresh_threads(self) -> None:
        dap = self._require_dap()
        resp = await dap.request("threads", {})
        threads: list[ThreadInfo] = []
        for item in _as_list(_body(resp).get("threads")):
            if not isinstance(item, dict):
                continue
            tid = item.get("id")
            name = item.get("name")
            if isinstance(tid, int) and isinstance(name, str):
                threads.append(ThreadInfo(id=tid, name=name))
        threads.sort(key=lambda t: t.id)
        selected = self.store.snapshot().selected_thread_id
        if selected is None and threads:
            selected = threads[0].id
        self.store.update(threads=tuple(threads), selected_thread_id=selected)

    async def _refresh_frames(self, thread_id: int) -> None:
        dap = self._require_dap()
        resp = await dap.request("stackTrace", {"threadId": thread_id})
        frames: list[FrameInfo] = []
        for item in _as_list(_body(resp).get("stackFrames")):
            if not isinstance(item, dict):
                continue
            fid = item.get("id")
            name = item.get("name")
            line = item.get("line")
            source = item.get("source")
            path: str | None = None
            if isinstance(source, dict):
                p = source.get("path")
                if isinstance(p, str):
                    path = p
            frames.append(
                FrameInfo(
                    id=int(fid) if isinstance(fid, int) else -1,
                    name=str(name) if isinstance(name, str) else "?",
                    path=path,
                    line=int(line) if isinstance(line, int) else None,
                )
            )
        frames = [f for f in frames if f.id >= 0]
        selected = next(
            (f for f in frames if isinstance(f.path, str) and _is_user_path(f.path)),
            frames[0] if frames else None,
        )
        selected_frame = selected.id if selected is not None else None
        self.store.update(
            frames=tuple(frames),
            selected_frame_id=selected_frame,
            source_path=selected.path if selected is not None else None,
            source_line=selected.line if selected is not None else None,
            source_col=None,
        )
        if isinstance(selected_frame, int):
            await self._refresh_locals(selected_frame)

    async def _refresh_locals(self, frame_id: int) -> None:
        dap = self._require_dap()
        scopes_resp = await dap.request("scopes", {"frameId": frame_id})
        scopes = _as_list(_body(scopes_resp).get("scopes"))
        locals_ref: int | None = None
        for scope in scopes:
            if not isinstance(scope, dict):
                continue
            name = scope.get("name")
            ref = scope.get("variablesReference")
            if isinstance(name, str) and name.lower() == "locals" and isinstance(ref, int):
                locals_ref = ref
                break
        if locals_ref is None:
            self.store.update(locals=())
            return

        vars_resp = await dap.request("variables", {"variablesReference": locals_ref})
        self.store.update(
            locals=tuple(_parse_variables(_as_list(_body(vars_resp).get("variables"))))
        )

    async def _sync_all_breakpoints(self) -> None:
        if not self._breakpoints:
            return
        for path, lines in sorted(self._breakpoints.items()):
            await self._set_breakpoints(path, sorted(lines))

    async def _set_breakpoints(self, path: str, lines: list[int]) -> None:
        dap = self._require_dap()
        cfgs = self._breakpoints.get(path) or {}
        requested: list[dict[str, object]] = []
        for line in lines:
            cfg = cfgs.get(line) or _BreakpointConfig()
            bp: dict[str, object] = {"line": line}
            if cfg.condition:
                bp["condition"] = cfg.condition
            if cfg.hit_condition:
                bp["hitCondition"] = cfg.hit_condition
            if cfg.log_message:
                bp["logMessage"] = cfg.log_message
            requested.append(bp)
        resp = await dap.request(
            "setBreakpoints",
            {
                "source": {"path": path},
                "breakpoints": requested,
                "sourceModified": False,
            },
        )
        updated: list[BreakpointInfo] = []
        for item in _as_list(_body(resp).get("breakpoints")):
            if not isinstance(item, dict):
                continue
            raw_line = item.get("line")
            if not isinstance(raw_line, int):
                continue
            line = raw_line
            verified = item.get("verified")
            message = item.get("message")
            cfg = cfgs.get(line) or _BreakpointConfig()
            updated.append(
                BreakpointInfo(
                    path=path,
                    line=line,
                    condition=cfg.condition,
                    hit_condition=cfg.hit_condition,
                    log_message=cfg.log_message,
                    verified=verified if isinstance(verified, bool) else None,
                    message=message if isinstance(message, str) else None,
                )
            )
        existing = tuple(bp for bp in self.store.snapshot().breakpoints if bp.path != path)
        self.store.update(
            breakpoints=tuple(sorted((*existing, *updated), key=lambda b: (b.path, b.line)))
        )
        if lines:
            self.store.append_transcript(f"Breakpoints set: {Path(path).name} ({len(lines)})")
        else:
            self.store.append_transcript(f"Breakpoints cleared: {Path(path).name}")

    async def _await_remote_exec_status(self, status_path: Path, *, timeout_s: float) -> None:
        deadline = monotonic() + timeout_s
        while monotonic() < deadline:
            if status_path.exists():
                try:
                    payload = json.loads(status_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    state = payload.get("state")
                    if state == "listening":
                        return
                    if state == "error":
                        error = str(payload.get("error") or "remote exec failed")
                        tb = payload.get("traceback")
                        detail = f"{error}\n{tb}".rstrip() if isinstance(tb, str) and tb else error
                        raise RuntimeError(detail)
            await asyncio.sleep(0.15)
        raise TimeoutError("Timed out waiting for sys.remote_exec script to run")

    async def _open_connection_retry(
        self, host: str, port: int, *, timeout_s: float
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        deadline = monotonic() + timeout_s
        last_exc: OSError | None = None
        while monotonic() < deadline:
            try:
                return await asyncio.open_connection(host, port)
            except OSError as exc:
                last_exc = exc
                await asyncio.sleep(0.15)
        raise TimeoutError(f"Timed out connecting to {host}:{port}") from last_exc

    async def _terminate_launched(self) -> None:
        if self._launch_output_task is not None:
            self._launch_output_task.cancel()
        self._launch_output_task = None

        proc = self._launched
        self._launched = None
        if proc is None:
            return
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.2)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    async def _drain_launch_output(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            s = line.decode("utf-8", errors="replace").rstrip()
            if s and self._capture_launch_output:
                self.store.append_transcript(s)
        rc = proc.returncode
        if rc is not None:
            self.store.append_transcript(f"Debuggee exited ({rc})")


@dataclass(frozen=True, slots=True)
class DebugpyPlugin(Plugin):
    @property
    @override
    def id(self) -> str:
        return "debugpy"

    @override
    def register(self, ctx: AppContext) -> None:
        try:
            store = ctx.services.get(SESSION_STORE)
        except KeyError:
            store = SessionStore()
            ctx.services.register(SESSION_STORE, store)

        manager = DebugpySessionManager(store=store, host=ctx.host)
        try:
            ctx.services.register(SESSION_MANAGER, manager)
        except ServiceRegistrationError:
            pass

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="session.connect",
                    title="Connect…",
                    summary="Connect to a debugpy server on host:port.",
                    default_keys=("ctrl+k",),
                ),
                handler=lambda: ctx.host.push_screen(ConnectDialog(ctx=ctx)),
            )
        )
        ctx.commands.register(
            Command(
                CommandSpec(
                    id="session.launch",
                    title="Launch…",
                    summary="Launch a Python target under debugpy.",
                    default_keys=("ctrl+r",),
                ),
                handler=lambda: ctx.host.push_screen(LaunchDialog(ctx=ctx)),
            )
        )
        ctx.commands.register(
            Command(
                CommandSpec(
                    id="session.disconnect",
                    title="Disconnect",
                    summary="Disconnect from the current debug session.",
                    default_keys=("ctrl+\\",),
                ),
                handler=manager.disconnect,
            )
        )
        ctx.commands.register(
            Command(
                CommandSpec(
                    id="session.terminate",
                    title="Terminate Debuggee",
                    summary="Terminate the debuggee process (if supported).",
                    default_keys=("ctrl+shift+\\",),
                ),
                handler=manager.terminate,
            )
        )


def plugin() -> Plugin:
    return DebugpyPlugin()


def _remote_exec_dir() -> Path:
    d = user_cache_path("yathaavat") / "remote_exec"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _remote_exec_script(*, status_path: Path, host: str, port: int) -> str:
    # This file is read by the remote process at execution time; keep it stable and self-contained.
    cfg = {"status_path": str(status_path), "host": host, "port": int(port)}
    return (
        "import json, os, traceback\n"
        f"_CFG = {cfg!r}\n"
        "def _write(state, **extra):\n"
        "    data = {'state': state, **extra}\n"
        "    try:\n"
        "        with open(_CFG['status_path'], 'w', encoding='utf-8') as f:\n"
        "            json.dump(data, f)\n"
        "    except Exception:\n"
        "        pass\n"
        "_write('starting', pid=os.getpid())\n"
        "try:\n"
        "    import debugpy\n"
        "    debugpy.listen((_CFG['host'], int(_CFG['port'])))\n"
        "    _write('listening', host=_CFG['host'], port=int(_CFG['port']))\n"
        "except Exception as exc:\n"
        "    _write('error', error=str(exc), traceback=traceback.format_exc())\n"
    )


def _is_user_path(path: str) -> bool:
    if path.startswith("<") and path.endswith(">"):
        return False
    try:
        p = Path(path).expanduser().resolve()
    except OSError:
        return False
    cwd = Path.cwd().resolve()
    return p.is_relative_to(cwd)
