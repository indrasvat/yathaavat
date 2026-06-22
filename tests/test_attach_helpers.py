from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from tests.support import RecordingHost, RecordingManager, make_context
from yathaavat.app import attach
from yathaavat.core.processes import ProcessInfo


def test_attach_endpoint_parsers_and_safe_attach_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    assert attach._truncate("abcdef", 4) == "abc…"
    assert attach._debugpy_dap_endpoint("python -m debugpy --listen 5678 app.py") == (
        "127.0.0.1",
        5678,
    )
    assert attach._debugpy_dap_endpoint("debugpy --listen localhost:9000 app.py") == (
        "localhost",
        9000,
    )
    assert attach._debugpy_dap_endpoint("debugpy --listen bad") is None
    assert attach._debugpy_adapter_endpoint("python -m debugpy.adapter --host ::1 --port 4711") == (
        "::1",
        4711,
    )
    assert attach._debugpy_adapter_endpoint("python app.py") is None
    assert attach._is_loopback("[::1]") is True
    assert attach._is_loopback("10.0.0.2") is False

    monkeypatch.delattr(sys, "remote_exec", raising=False)
    assert attach._safe_attach_unavailable_reason() == "unsupported locally"
    monkeypatch.setattr(sys, "remote_exec", object(), raising=False)
    monkeypatch.setenv("PYTHON_DISABLE_REMOTE_DEBUG", "1")
    assert attach._safe_attach_unavailable_reason() == "disabled locally"


def test_attach_lsof_parsers_ignore_bad_process_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "-sTCP:LISTEN" in cmd and "-t" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="101\nbad\n202\n", stderr="")
        if "-sTCP:LISTEN" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                    "python 1 me 3u IPv4 TCP *:5678 (LISTEN)\n"
                    "python 1 me 4u IPv6 TCP [::1]:9000 (LISTEN)\n"
                    "python 1 me 5u IPv4 TCP bad:port (LISTEN)\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "python 1 me 3u IPv4 TCP 127.0.0.1:5000->127.0.0.1:6000 (ESTABLISHED)\n"
                "python 1 me 4u IPv4 TCP 127.0.0.1:5001->10.0.0.2:6001 (ESTABLISHED)\n"
                "python 1 me 5u IPv4 TCP bad\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert attach._list_listening_tcp_endpoints(123) == [("127.0.0.1", 5678), ("::1", 9000)]
    assert attach._list_established_remote_ports(123) == [6000]
    assert attach._listener_pids_for_port(6000) == [101, 202]


def test_attach_process_probes_degrade_on_lsof_and_ps_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_os_error(_cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("missing tool")

    monkeypatch.setattr(subprocess, "run", raise_os_error)
    assert attach._list_listening_tcp_endpoints(123) == []
    assert attach._list_established_remote_ports(123) == []
    assert attach._listener_pids_for_port(6000) == []
    assert attach._ps_args(101) is None

    def nonzero(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="ignored", stderr="denied")

    monkeypatch.setattr(subprocess, "run", nonzero)
    assert attach._list_listening_tcp_endpoints(123) == []
    assert attach._list_established_remote_ports(123) == []
    assert attach._listener_pids_for_port(6000) == []
    assert attach._ps_args(101) is None

    def ps_success(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="  python -m debugpy.adapter  \n")

    monkeypatch.setattr(subprocess, "run", ps_success)
    assert attach._ps_args(101) == "python -m debugpy.adapter"


def test_infer_debugpy_endpoint_uses_adapter_connected_to_debuggee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attach, "_list_established_remote_ports", lambda pid: [6000])
    monkeypatch.setattr(attach, "_listener_pids_for_port", lambda port: [100, 101, 202])

    def ps_args(pid: int) -> str | None:
        if pid == 100:
            return None
        if pid == 101:
            return ""
        return "python -m debugpy.adapter --host 127.0.0.1 --port 51578 --for-server 6000"

    monkeypatch.setattr(attach, "_ps_args", ps_args)
    monkeypatch.setattr(attach, "_list_listening_tcp_endpoints", lambda pid: [])

    assert asyncio.run(attach._infer_debugpy_dap_endpoint(123)) == ("127.0.0.1", 51578)


def test_infer_debugpy_endpoint_probes_listeners_with_loopback_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[tuple[str, int]] = []
    monkeypatch.setattr(attach, "_list_established_remote_ports", lambda pid: [])
    monkeypatch.setattr(attach, "_list_listening_tcp_endpoints", lambda pid: [("127.0.0.1", 5678)])

    async def probe(host: str, port: int) -> bool:
        probes.append((host, port))
        return host == "::1"

    monkeypatch.setattr(attach, "_probe_dap_endpoint", probe)

    assert asyncio.run(attach._infer_debugpy_dap_endpoint(123)) == ("::1", 5678)
    assert probes == [("127.0.0.1", 5678), ("::1", 5678)]


def test_infer_debugpy_endpoint_accepts_direct_dap_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[tuple[str, int]] = []
    monkeypatch.setattr(attach, "_list_established_remote_ports", lambda pid: [])
    monkeypatch.setattr(attach, "_list_listening_tcp_endpoints", lambda pid: [("127.0.0.1", 5678)])

    async def probe(host: str, port: int) -> bool:
        probes.append((host, port))
        return True

    monkeypatch.setattr(attach, "_probe_dap_endpoint", probe)

    assert asyncio.run(attach._infer_debugpy_dap_endpoint(123)) == ("127.0.0.1", 5678)
    assert probes == [("127.0.0.1", 5678)]


def test_infer_debugpy_endpoint_falls_back_from_ipv6_to_ipv4_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[tuple[str, int]] = []
    monkeypatch.setattr(attach, "_list_established_remote_ports", lambda pid: [])
    monkeypatch.setattr(attach, "_list_listening_tcp_endpoints", lambda pid: [("::1", 5678)])

    async def probe(host: str, port: int) -> bool:
        probes.append((host, port))
        return host == "127.0.0.1"

    monkeypatch.setattr(attach, "_probe_dap_endpoint", probe)

    assert asyncio.run(attach._infer_debugpy_dap_endpoint(123)) == ("127.0.0.1", 5678)
    assert probes == [("::1", 5678), ("127.0.0.1", 5678)]


def test_infer_debugpy_endpoint_returns_none_when_candidates_do_not_speak_dap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attach, "_list_established_remote_ports", lambda pid: [6000])
    monkeypatch.setattr(attach, "_listener_pids_for_port", lambda port: [101])
    monkeypatch.setattr(attach, "_ps_args", lambda pid: "python worker.py")
    monkeypatch.setattr(attach, "_list_listening_tcp_endpoints", lambda pid: [("::1", 5678)])

    async def probe(_host: str, _port: int) -> bool:
        return False

    monkeypatch.setattr(attach, "_probe_dap_endpoint", probe)

    assert asyncio.run(attach._infer_debugpy_dap_endpoint(123)) is None


def test_attach_picker_rows_mark_debugpy_and_safe_attach_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attach, "_safe_attach_unavailable_reason", lambda: None)
    ctx = make_context(manager=RecordingManager(), host=RecordingHost())
    picker = attach.AttachPicker(ctx=ctx)
    picker._processes = [
        ProcessInfo(
            pid=2, command="python", args="python -m debugpy --listen 5678 app.py", is_python=True
        ),
        ProcessInfo(
            pid=3,
            command="python3.14",
            args="python3.14 worker.py",
            is_python=True,
            python_version_hint="3.14",
        ),
        ProcessInfo(pid=4, command="node", args="node server.js", is_python=False),
    ]

    rows = picker._rows()
    assert [(row.pid, row.dap_endpoint, row.safe_attach_enabled) for row in rows] == [
        (2, ("127.0.0.1", 5678), False),
        (3, None, True),
    ]

    picker.show_non_python = True
    picker.query_text = "node"
    assert [row.pid for row in picker._rows()] == [4]
