from __future__ import annotations

import asyncio
import socket
import subprocess

import pytest

from yathaavat.app import server_discovery
from yathaavat.app.server_discovery import probe_server


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_probe_open_port() -> None:
    """Probing a port with a real TCP listener returns True."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        result = asyncio.run(probe_server("127.0.0.1", port))
        assert result is True
    finally:
        srv.close()


def test_probe_closed_port() -> None:
    """Probing a port with no listener returns False."""
    port = _pick_free_port()
    result = asyncio.run(probe_server("127.0.0.1", port, timeout=0.1))
    assert result is False


def test_probe_timeout() -> None:
    """Probing with a very short timeout doesn't hang."""
    port = _pick_free_port()
    result = asyncio.run(probe_server("127.0.0.1", port, timeout=0.01))
    assert result is False


def test_discover_debugpy_servers_resolves_only_live_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_probe(host: str, port: int) -> bool:
        assert host == "127.0.0.1"
        return port in {5680, 5682}

    async def fake_resolve(host: str, port: int) -> tuple[int | None, str]:
        return port + 1000, f"service-{port}.py"

    monkeypatch.setattr(server_discovery, "probe_server", fake_probe)
    monkeypatch.setattr(server_discovery, "_resolve_pid", fake_resolve)

    servers = asyncio.run(server_discovery.discover_debugpy_servers(ports=range(5678, 5683)))
    assert [(srv.port, srv.pid, srv.process_name, srv.alive) for srv in servers] == [
        (5680, 6680, "service-5680.py", True),
        (5682, 6682, "service-5682.py", True),
    ]


def test_probe_history_entries_preserves_endpoint_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_probe(_host: str, port: int) -> bool:
        return port == 7001

    monkeypatch.setattr(server_discovery, "probe_server", fake_probe)
    entries = [("localhost", 7000), ("127.0.0.1", 7001)]
    assert asyncio.run(server_discovery.probe_history_entries(entries)) == {
        ("localhost", 7000): False,
        ("127.0.0.1", 7001): True,
    }


def test_resolve_pid_returns_remote_without_local_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0, stdout="123\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert asyncio.run(server_discovery._resolve_pid("10.0.0.2", 5678)) == (None, "remote")
    assert called is False


def test_resolve_pid_and_process_name_parse_lsof_and_ps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_name(pid: int) -> str:
        assert pid == 4321
        return "worker.py"

    def fake_lsof(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert cmd[:2] == ["lsof", "-i"]
        return subprocess.CompletedProcess(cmd, 0, stdout="4321\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_lsof)
    monkeypatch.setattr(server_discovery, "_resolve_process_name", fake_name)
    assert asyncio.run(server_discovery._resolve_pid("localhost", 5678)) == (4321, "worker.py")


def test_resolve_process_name_prefers_python_script_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="/usr/bin/python -m debugpy --listen 5678 /repo/api/server.py\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert asyncio.run(server_discovery._resolve_process_name(4321)) == "server.py"


def test_resolve_process_name_falls_back_to_last_arg_or_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="/usr/bin/python -m debugpy\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert asyncio.run(server_discovery._resolve_process_name(4321)) == "debugpy"

    def failing_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="missing")

    monkeypatch.setattr(subprocess, "run", failing_run)
    assert asyncio.run(server_discovery._resolve_process_name(4321)) == "unknown"
