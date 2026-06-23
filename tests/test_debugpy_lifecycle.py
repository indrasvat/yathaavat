from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from tests.test_debugpy_manager_behavior import _set_dap, _TestDap
from yathaavat.core import NullUiHost, SessionState, SessionStore
from yathaavat.plugins import debugpy
from yathaavat.plugins.debugpy import DebugpySessionManager


class _LifecycleManager(DebugpySessionManager):
    def __init__(self, store: SessionStore) -> None:
        super().__init__(store=store, host=NullUiHost())
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def connect(self, host: str, port: int) -> None:
        self.calls.append(("connect", (host, port)))

    async def pause(self) -> None:
        self.calls.append(("pause", ()))

    async def _connect_with_timeout(self, host: str, port: int, *, timeout_s: float) -> None:
        self.calls.append(("_connect_with_timeout", (host, port, timeout_s)))
        self.store.update(state=SessionState.RUNNING)

    async def _await_remote_exec_status(self, status_path: Path, *, timeout_s: float) -> None:
        self.calls.append(("_await_remote_exec_status", (status_path.name, timeout_s)))

    async def disconnect(self) -> None:
        self.calls.append(("disconnect", ()))
        await self._hard_disconnect()

    async def _terminate_launched(self) -> None:
        self.calls.append(("_terminate_launched", ()))
        await super()._terminate_launched()


@dataclass(slots=True)
class _FakeCompleted:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def test_pid_attach_success_runs_debugpy_injection_then_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _LifecycleManager(store)
        monkeypatch.setattr(debugpy, "_pick_free_port", lambda: 6123)

        def fake_run(cmd: list[str], **_kwargs: object) -> _FakeCompleted:
            assert cmd == [
                sys.executable,
                "-m",
                "debugpy",
                "--listen",
                "127.0.0.1:6123",
                "--pid",
                "4321",
            ]
            return _FakeCompleted(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        await manager.attach(4321)

        assert store.snapshot().pid == 4321
        assert manager.calls == [("connect", ("127.0.0.1", 6123)), ("pause", ())]
        assert "Injecting debugpy into PID 4321" in store.snapshot().transcript[0]

    asyncio.run(run())


def test_pid_attach_nonzero_exit_reports_best_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _LifecycleManager(store)
        monkeypatch.setattr(debugpy, "_pick_free_port", lambda: 6123)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_args, **_kwargs: _FakeCompleted(returncode=2, stdout="out", stderr="err"),
        )

        with pytest.raises(RuntimeError, match="err"):
            await manager.attach(111)

        assert store.snapshot().transcript[-1] == "PID attach failed: err"

    asyncio.run(run())


def test_safe_attach_success_runs_remote_exec_and_cleans_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _LifecycleManager(store)
        remote_dir = tmp_path / "handoff"
        remote_dir.mkdir()
        script_path = remote_dir / "attach.py"
        status_path = remote_dir / "status.json"
        script_path.write_text("print('attach')\n", encoding="utf-8")
        monkeypatch.setattr(debugpy, "_pick_free_port", lambda: 7001)
        monkeypatch.setattr(
            debugpy,
            "_prepare_remote_exec_handoff",
            lambda *, pid, token, host, port: (remote_dir, script_path, status_path),
        )
        remote_calls: list[tuple[int, str]] = []
        monkeypatch.setattr(
            sys,
            "remote_exec",
            lambda pid, path: remote_calls.append((pid, path)),
            raising=False,
        )

        await manager.safe_attach(222)

        assert remote_calls == [(222, str(script_path))]
        assert not remote_dir.exists()
        assert manager.calls[:2] == [
            ("disconnect", ()),
            ("_await_remote_exec_status", ("status.json", 20.0)),
        ]
        assert ("_connect_with_timeout", ("127.0.0.1", 7001, 25.0)) in manager.calls
        assert ("pause", ()) in manager.calls

    asyncio.run(run())


def test_safe_attach_remote_exec_failure_includes_actionable_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _LifecycleManager(store)
        remote_dir = tmp_path / "handoff"
        remote_dir.mkdir()
        script_path = remote_dir / "attach.py"
        status_path = remote_dir / "status.json"
        script_path.write_text("print('attach')\n", encoding="utf-8")
        monkeypatch.setattr(debugpy, "_pick_free_port", lambda: 7001)
        monkeypatch.setattr(
            debugpy,
            "_prepare_remote_exec_handoff",
            lambda *, pid, token, host, port: (remote_dir, script_path, status_path),
        )

        def fail_remote_exec(_pid: int, _path: str) -> None:
            raise RuntimeError("remote denied")

        monkeypatch.setattr(sys, "remote_exec", fail_remote_exec, raising=False)

        with pytest.raises(RuntimeError, match="remote denied"):
            await manager.safe_attach(222)

        assert not remote_dir.exists()
        assert "sys.remote_exec failed: remote denied" in store.snapshot().transcript

    asyncio.run(run())


@dataclass(slots=True)
class _FakeStdout:
    lines: list[bytes]

    async def readline(self) -> bytes:
        if self.lines:
            return self.lines.pop(0)
        return b""


@dataclass(slots=True)
class _FakeProcess:
    stdout: _FakeStdout | None = None
    returncode: int | None = None
    terminated: bool = False
    killed: bool = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


def test_launch_starts_debugpy_subprocess_and_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _LifecycleManager(store)
        proc = _FakeProcess(stdout=_FakeStdout([]), returncode=0)
        monkeypatch.setattr(debugpy, "_pick_free_port", lambda: 7111)
        create_calls: list[tuple[object, ...]] = []

        async def fake_create_subprocess_exec(*argv: object, **_kwargs: object) -> _FakeProcess:
            create_calls.append(argv)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        await manager.launch(["demo.py", "--flag"])

        assert create_calls == [
            (
                sys.executable,
                "-Xfrozen_modules=off",
                "-m",
                "debugpy",
                "--listen",
                "127.0.0.1:7111",
                "--wait-for-client",
                "demo.py",
                "--flag",
            )
        ]
        assert manager.calls == [
            ("disconnect", ()),
            ("_terminate_launched", ()),
            ("_connect_with_timeout", ("127.0.0.1", 7111, 6.0)),
        ]
        assert store.snapshot().backend == "debugpy"
        assert manager._auto_resume_pending is True

    asyncio.run(run())


def test_launch_uses_custom_debugpy_prefix_and_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = _LifecycleManager(store)
        proc = _FakeProcess(stdout=_FakeStdout([]), returncode=0)
        monkeypatch.setenv("VIRTUAL_ENV", "/repo/.venv")
        monkeypatch.setattr(debugpy, "_pick_free_port", lambda: 7112)
        create_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def fake_create_subprocess_exec(*argv: object, **kwargs: object) -> _FakeProcess:
            create_calls.append((argv, kwargs))
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        await manager.launch(
            ["/svc/.venv/bin/traffic-ledger", "--port", "8077"],
            debugpy_prefix=["uv", "--directory", "/svc", "run", "--with", "debugpy", "python"],
            cwd="/svc",
        )

        argv, kwargs = create_calls[0]
        assert argv[:6] == (
            "uv",
            "--directory",
            "/svc",
            "run",
            "--with",
            "debugpy",
        )
        assert "-m" in argv
        assert "/svc/.venv/bin/traffic-ledger" in argv
        assert kwargs["cwd"] == "/svc"
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert "VIRTUAL_ENV" not in env

    asyncio.run(run())


def test_launch_rejects_empty_target() -> None:
    async def run() -> None:
        manager = _LifecycleManager(SessionStore())
        with pytest.raises(ValueError, match="Launch requires a target"):
            await manager.launch([])

    asyncio.run(run())


def test_disconnect_terminate_shutdown_and_launch_output_paths() -> None:
    async def run() -> None:
        store = SessionStore()
        manager = DebugpySessionManager(store=store, host=NullUiHost())
        dap = _TestDap()
        _set_dap(manager, dap)

        await manager.disconnect()
        assert dap.requests == [("disconnect", {"terminateDebuggee": False}, 2.0)]

        dap2 = _TestDap()
        _set_dap(manager, dap2)
        launched = _FakeProcess(stdout=None)
        cast(Any, manager)._launched = launched
        await manager.terminate()
        assert dap2.requests == [("disconnect", {"terminateDebuggee": True}, 2.0)]
        assert launched.terminated is True

        proc = _FakeProcess(stdout=_FakeStdout([b"line one\n", b"\xffbad\n"]), returncode=7)
        cast(Any, manager)._capture_launch_output = True
        await manager._drain_launch_output(cast(Any, proc))
        assert store.snapshot().transcript[-3:] == ("line one", "�bad", "Debuggee exited (7)")

    asyncio.run(run())


def test_connect_with_timeout_initializes_attaches_and_configures_breakpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = DebugpySessionManager(store=store, host=NullUiHost())
        manager._initialized.set()
        requests: list[tuple[str, dict[str, object], float | None]] = []

        class FakeDapClient:
            def __init__(self, *, reader: object, writer: object) -> None:
                self.reader = reader
                self.writer = writer

            def on_event(self, _handler: object) -> None:
                requests.append(("on_event", {}, None))

            def on_disconnect(self, _handler: object) -> None:
                requests.append(("on_disconnect", {}, None))

            def start(self) -> None:
                requests.append(("start", {}, None))

            async def request(
                self,
                command: str,
                arguments: dict[str, object],
                timeout_s: float | None = None,
            ) -> dict[str, object]:
                requests.append((command, arguments, timeout_s))
                if command == "setBreakpoints":
                    return {"body": {"breakpoints": [{"line": 4, "verified": True}]}}
                return {"body": {}}

            async def close(self) -> None:
                requests.append(("close", {}, None))

        async def fake_open_connection_retry(
            host: str, port: int, *, timeout_s: float
        ) -> tuple[object, object]:
            assert (host, port, timeout_s) == ("127.0.0.1", 9123, 6.0)
            return object(), object()

        source = Path("connected.py").resolve()
        manager._breakpoints[str(source)] = {4: debugpy._BreakpointConfig(condition="ready")}
        monkeypatch.setattr(debugpy, "DapClient", FakeDapClient)
        monkeypatch.setattr(manager, "_open_connection_retry", fake_open_connection_retry)

        await manager._connect_with_timeout("127.0.0.1", 9123, timeout_s=6.0)

        commands = [entry[0] for entry in requests]
        assert commands == [
            "on_event",
            "on_disconnect",
            "start",
            "initialize",
            "setBreakpoints",
            "setExceptionBreakpoints",
            "attach",
            "configurationDone",
            "threads",
        ]
        assert store.snapshot().state is SessionState.RUNNING
        assert store.snapshot().breakpoints[0].condition == "ready"
        assert store.snapshot().transcript[-1] == "Connected."

    asyncio.run(run())


def test_connect_with_timeout_hard_disconnects_on_initialize_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        store = SessionStore()
        manager = DebugpySessionManager(store=store, host=NullUiHost())

        class FailingDapClient:
            def __init__(self, *, reader: object, writer: object) -> None:
                self.closed = False

            def on_event(self, _handler: object) -> None:
                return None

            def on_disconnect(self, _handler: object) -> None:
                return None

            def start(self) -> None:
                return None

            async def request(
                self,
                command: str,
                arguments: dict[str, object],
                timeout_s: float | None = None,
            ) -> dict[str, object]:
                raise TimeoutError("no initialize")

            async def close(self) -> None:
                self.closed = True

        async def fake_open_connection_retry(
            _host: str, _port: int, *, timeout_s: float
        ) -> tuple[object, object]:
            return object(), object()

        monkeypatch.setattr(debugpy, "DapClient", FailingDapClient)
        monkeypatch.setattr(manager, "_open_connection_retry", fake_open_connection_retry)

        with pytest.raises(TimeoutError, match="no initialize"):
            await manager._connect_with_timeout("127.0.0.1", 9123, timeout_s=0.1)

        snap = store.snapshot()
        assert snap.state is SessionState.DISCONNECTED
        assert snap.transcript == ("Attach failed: no initialize",)

    asyncio.run(run())
